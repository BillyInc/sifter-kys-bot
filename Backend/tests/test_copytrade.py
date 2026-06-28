"""Tests for the cluster co-entry copy-trade system (record-once-score-many).

Covers the STEP 8 acceptance criteria:
  - a simulated co-buy of 2 BOT-1 members within 120s produces a cluster signal that
    records to paper_raw_cobuys and traces back via raw_event_id;
  - the offline scorer scores variants against the recorded substrate with ZERO new live
    capture (add-a-variant-scores-offline);
  - the elite15 single-wallet path is still accepted (not broken);
  - confluence sizing, chase-guard, bot caps, and the gated single-copy behave per spec.

All DB/Redis access is faked — no network, no live calls.
"""

from __future__ import annotations

import time

import pytest

from services.copytrade_config import get_copytrade_config
from services import cobuy_assembler as ca
from services import copytrade_sizing as sizing
from services import variant_scorer as vs
from services import bot_cluster_autotrade as bca
from services import bot_single_copy as bsc
from services.paper_trader import PaperTrader


BOT1 = [
    "912iwi9rQV6mc6RxGa77QDjcQjLgoKvEVahBFeqdpSgN",  # CONSERVATIVE accumulator
    "C8TaRv2K5BSe854b74xSUS92Lqjyv9Kks5W4Fb6VY3fe",  # ELITE first-pump
    "4PrW4vBqZA6GHCGb9Am25DL8eHs7Sjzw8Xfq4GgyRLi5",  # CONSERVATIVE accumulator
]


# ── fakes ─────────────────────────────────────────────────────────────────────

class FakeRedis:
    def __init__(self):
        self.kv = {}

    def get(self, k):
        return self.kv.get(k)

    def setex(self, k, ttl, v):
        self.kv[k] = v

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True

    def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]

    def expire(self, k, t):
        pass


class _Resp:
    def __init__(self, data):
        self.data = data


class FakeTable:
    _seq = [0]

    def insert(self, row):
        self._row = row
        return self

    def upsert(self, row, ignore_duplicates=False):
        self._row = row
        return self

    def execute(self):
        FakeTable._seq[0] += 1
        return _Resp([{"id": FakeTable._seq[0]}])


class FakeSupabase:
    def schema(self, _n):
        return self

    def table(self, _n):
        return FakeTable()


class FakePaper:
    def __init__(self):
        self.signals = []

    def process_signal(self, signal):
        self.signals.append(signal)


@pytest.fixture(autouse=True)
def _fresh_config():
    # ensure the loader reads the JSON seeds fresh for each test
    get_copytrade_config().reload()
    yield


# ── config ──────────────────────────────────────────────────────────────────

def test_roster_has_3_bot_clusters_9_wallets():
    cfg = get_copytrade_config()
    bots = cfg.bot_clusters()
    assert {c.cluster_id for c in bots} == {"BOT-1", "BOT-2", "BOT-3"}
    distinct = {m.address for c in bots for m in c.members}
    assert len(distinct) == 9


def test_co_confirmation_member_not_tradable():
    cfg = get_copytrade_config()
    dq = cfg.get_cluster("BOT-3").member("DQmMnakiKr1YNE2gcpggLCzBrauBwFbQkAaao2FTbjgp")
    assert dq is not None and dq.is_co_confirmation and not dq.tradable


def test_per_cluster_stop_loss_override():
    cfg = get_copytrade_config()
    assert cfg.sl_tp("BOT-2")["stop_loss_pct"] == -30   # BOT-2 bleeds more → tighter
    assert cfg.sl_tp("BOT-1")["stop_loss_pct"] == -35


# ── co-entry assembler (record-once + emit) ───────────────────────────────────

def _assembler():
    return ca.CoBuyAssembler(redis_client=FakeRedis(), supabase=FakeSupabase())


def test_coentry_fires_on_second_member_and_records_raw():
    asm = _assembler()
    fp = FakePaper()
    t = time.time()
    r1 = asm.ingest_buy(BOT1[0], "TOKA", trigger_price=1.0, usd_value=300, ts=t,
                        paper_trader=fp, emit=True)
    assert r1["recorded"] and r1["raw_event_id"] is not None
    assert r1["fired"] == [] and not fp.signals               # one buy → no co-entry

    r2 = asm.ingest_buy(BOT1[1], "TOKA", trigger_price=1.3, usd_value=300, ts=t + 30,
                        paper_trader=fp, emit=True)
    assert r2["fired"] == ["BOT-1"] and len(fp.signals) == 1   # second member fires

    sig = fp.signals[0]
    assert sig["source"] == "cluster"
    assert sig["signal_key"] == "BOT-1:TOKA"
    assert sig["trigger_price"] == 1.3                         # 2nd-buy trigger
    assert sig["first_buy_price"] == 1.0
    assert sig["raw_event_id"] is not None                     # traces to paper_raw_cobuys


def test_coentry_dedups_and_isolates_tokens():
    asm = _assembler()
    fp = FakePaper()
    t = time.time()
    asm.ingest_buy(BOT1[0], "TOKB", trigger_price=1.0, ts=t, paper_trader=fp)
    asm.ingest_buy(BOT1[1], "TOKB", trigger_price=1.2, ts=t + 10, paper_trader=fp)
    asm.ingest_buy(BOT1[2], "TOKB", trigger_price=1.4, ts=t + 20, paper_trader=fp)  # 3rd member
    assert len(fp.signals) == 1                               # only one fire per (cluster, token)

    asm.ingest_buy(BOT1[0], "TOKC", trigger_price=2.0, ts=t + 5, paper_trader=fp)  # lone buy
    assert len(fp.signals) == 1                               # different token, no co-entry


def test_window_expiry_no_fire():
    asm = _assembler()
    fp = FakePaper()
    t = time.time()
    asm.ingest_buy(BOT1[0], "TOKD", trigger_price=1.0, ts=t, paper_trader=fp)
    asm.ingest_buy(BOT1[1], "TOKD", trigger_price=1.0, ts=t + 200, paper_trader=fp)  # >120s
    assert fp.signals == []


# ── paper_trader generalization (elite15 still accepted) ──────────────────────

def test_process_signal_accepts_cluster_and_keeps_elite15():
    assert "elite15" in PaperTrader.ACCEPTED_SOURCES   # legacy not dropped
    assert "cluster" in PaperTrader.ACCEPTED_SOURCES   # new path
    assert {"single", "manual"} <= PaperTrader.ACCEPTED_SOURCES
    assert "watchlist" not in PaperTrader.ACCEPTED_SOURCES


# ── offline variant scorer (score-many, zero live capture) ────────────────────

def test_find_cluster_fires_min_members():
    raw = [
        {"id": 1, "ts": 1000.0, "wallet": BOT1[0], "trigger_price": 1.0},
        {"id": 2, "ts": 1030.0, "wallet": BOT1[1], "trigger_price": 1.3},
        {"id": 3, "ts": 1050.0, "wallet": BOT1[2], "trigger_price": 1.4},
    ]
    members = set(BOT1)
    f2 = vs.find_cluster_fires(raw, members, 120, 2)
    assert len(f2) == 1 and f2[0]["raw_event_id"] == 2 and f2[0]["trigger_price"] == 1.3
    f3 = vs.find_cluster_fires(raw, members, 120, 3)
    assert len(f3) == 1 and f3[0]["raw_event_id"] == 3
    # tight window: only 2 of 3 land within 15s
    assert vs.find_cluster_fires(raw, members, 15, 3) == []


def test_replay_exit_runner_and_chaseguard():
    path = [(1100.0, 2.0), (1200.0, 4.0), (1300.0, 12.0), (1400.0, 7.0)]
    res = vs.replay_exit(
        1.0, path, stop_loss_pct=-35,
        tp_ladder=[{"at_multiple": 2, "sell_pct": 25}, {"at_multiple": 4, "sell_pct": 25}],
        trailing_stop_pct=-40,
    )
    assert res["is_runner"] is True and res["realized_roi"] > 0

    fire = {"fired_ts": 1000.0, "trigger_price": 1.0, "raw_event_id": 9}
    fwd = [(1045.0, 3.0), (1200.0, 6.0)]   # fill at +45s = 3.0 → chase 3x
    row = vs.score_one(fire, fwd, chase_x=2.0, latency_s=45.0,
                       exit_cfg={"stop_loss_pct": -35, "take_profit_ladder": [], "trailing_stop_pct": -40})
    assert row["aborted"] is True and row["realized_roi"] is None
    assert row["raw_event_id"] == 9        # traces to the raw co-buy


def test_score_one_links_back_to_raw_event():
    fire = {"fired_ts": 1000.0, "trigger_price": 1.0, "raw_event_id": 42}
    fwd = [(1045.0, 1.1), (1200.0, 2.5)]
    row = vs.score_one(fire, fwd, chase_x=None, latency_s=45.0,
                       exit_cfg={"stop_loss_pct": -35,
                                 "take_profit_ladder": [{"at_multiple": 2, "sell_pct": 25}],
                                 "trailing_stop_pct": -40})
    assert row["aborted"] is False and row["raw_event_id"] == 42
    assert row["entry_price"] is not None and row["edge_kept"] is not None


# ── sizing / chase-guard / caps ───────────────────────────────────────────────

def test_confluence_sizing_ladder():
    cfg = get_copytrade_config().confluence_sizing()
    assert sizing.confluence_size_pct(cfg, elite_or_list_a_present=False, distinct_cobuyers=2) == 10
    assert sizing.confluence_size_pct(cfg, elite_or_list_a_present=True, distinct_cobuyers=2) == 15
    assert sizing.confluence_size_pct(cfg, elite_or_list_a_present=True, distinct_cobuyers=6) == 20  # cap


def test_chase_guard_and_pyramid():
    assert sizing.is_chase_abort(2.3, 1.0) is True
    assert sizing.is_chase_abort(1.4, 1.0) is False
    assert sizing.can_pyramid(1.4, 1.0) is True
    assert sizing.can_pyramid(1.7, 1.0) is False


def test_bot_caps_admit_then_refuse():
    r = FakeRedis()
    limits = {"daily_max": 4, "hourly_max": 2, "weekly_max": 28}
    admits = [bca._admit_under_caps(limits, redis_client=r)["ok"] for _ in range(4)]
    assert admits == [True, True, False, False]   # hourly cap of 2 binds first


# ── gated single-wallet copy (default OFF) ────────────────────────────────────

def test_single_copy_requires_confluence():
    res = bsc.route_single_buy(
        BOT1[1], "TOK", distinct_cobuyers=1,
        signal={"token_address": "TOK", "side": "buy"}, supabase=FakeSupabase(), redis_client=FakeRedis(),
    )
    assert res["reason"] == "no_confluence"
