"""Offline variant scorer — score-many over the recorded co-buy stream (§1, §2).

A "variant" is a pure SELECTION scorer (cluster/window/chase-guard/min-members, or a
single wallet). It is evaluated **offline** against the immutable substrate
(``paper_raw_cobuys`` + ``paper_price_paths``) and writes one ``paper_variant_signals``
row per fire. Adding a variant = adding a scorer = **zero new live capture**.

Exits do not vary per-variant (no ``exit_rule`` in the grid): every variant replays the
same SL/TP/trailing model from ``bot_defaults.sl_tp_strategy`` on the stored price path.
The variant axes are entry selection only. Execution physics (latency) is modeled here so
first-pump copyability is measured (§3); changing it is the only thing that would require
re-capture — never a different selection or exit.

Idempotent: re-scoring a variant deletes its prior rows then re-inserts, so the table
always reflects the current substrate. Pure functions (``replay_exit``, ``find_cluster_fires``,
``find_single_fires``) are dependency-free and unit-tested directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Simulated execution latency by family (seconds) — §3: bot ≈ 30–60s, manual ≈ 60–300s.
LATENCY_S = {"bot": 45.0, "manual": 120.0}
RUNNER_MULTIPLE = 10.0  # is_runner = token hit >=10x on the path (§4C)


# ── pure scoring primitives ──────────────────────────────────────────────────

def _parse_ts(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def price_at(path: List[Tuple[float, float]], at_ts: float) -> Optional[float]:
    """First path price at-or-after ``at_ts``; falls back to the last point before it."""
    before = None
    for ts, px in path:
        if ts >= at_ts:
            return px
        before = px
    return before


def replay_exit(
    entry_price: float,
    forward_path: List[Tuple[float, float]],
    *,
    stop_loss_pct: float,
    tp_ladder: List[Dict],
    trailing_stop_pct: float,
) -> Dict:
    """Replay the bot_defaults SL/TP/trailing exit on a forward price path.

    Returns realized_roi (blended over partial exits), is_runner, peak multiple, and
    whether the position fully resolved on the available path. Unsold tail is marked to
    the last path price (paths are forward-captured and may be sparse — PENDING_OHLCV).
    """
    if entry_price <= 0 or not forward_path:
        return {"resolved": False, "realized_roi": None, "exit_price": None,
                "is_runner": None, "peak_mult": None}

    sl_level = entry_price * (1 + stop_loss_pct / 100.0)
    tps = sorted(tp_ladder or [], key=lambda t: float(t.get("at_multiple") or 0))
    tp_done = [False] * len(tps)
    remaining = 1.0
    realized = 0.0            # sum of fraction_sold * exit_multiple
    peak = entry_price

    for _ts, price in forward_path:
        if price <= 0:
            continue
        peak = max(peak, price)
        mult = price / entry_price

        # stop loss closes the whole remaining position
        if price <= sl_level and remaining > 0:
            realized += remaining * mult
            remaining = 0.0
            break

        # take-profit ladder (partial exits)
        for i, tp in enumerate(tps):
            if tp_done[i] or remaining <= 0:
                continue
            if mult >= float(tp["at_multiple"]):
                frac = min(remaining, float(tp["sell_pct"]) / 100.0)
                realized += frac * float(tp["at_multiple"])
                remaining -= frac
                tp_done[i] = True

        # wide trailing stop on the runner tail, only after the ladder is exhausted
        if remaining > 0 and tps and all(tp_done):
            trail_level = peak * (1 + trailing_stop_pct / 100.0)
            if price <= trail_level:
                realized += remaining * mult
                remaining = 0.0
                break

    resolved = remaining <= 0
    if remaining > 0:  # mark unsold tail to the last observed price
        realized += remaining * (forward_path[-1][1] / entry_price)

    return {
        "resolved": resolved,
        "realized_roi": round(realized - 1.0, 6),
        "exit_price": round(entry_price * realized, 12),
        "is_runner": (peak / entry_price) >= RUNNER_MULTIPLE,
        "peak_mult": round(peak / entry_price, 4),
    }


def find_cluster_fires(
    raw_rows: List[Dict], member_set: set, window_s: float, min_members: int,
) -> List[Dict]:
    """Find the first co-entry fire per token for a cluster variant.

    ``raw_rows`` are paper_raw_cobuys dicts (id, ts, wallet, token_address, trigger_price)
    for ONE token, sorted ascending by ts. Returns at most one fire dict with the confirming
    (Nth distinct member) row's id/ts/price and the triggering members.
    """
    window: List[Dict] = []
    seen: Dict[str, Dict] = {}
    for row in raw_rows:
        w = row.get("wallet")
        if w not in member_set:
            continue
        ts = _parse_ts(row.get("ts"))
        window.append({**row, "_ts": ts})
        # drop rows outside the window relative to the current row
        window = [r for r in window if ts - r["_ts"] <= window_s]
        seen = {}
        for r in window:
            rw = r.get("wallet")
            if rw not in seen or r["_ts"] < seen[rw]["_ts"]:
                seen[rw] = r
        if len(seen) >= min_members:
            members = sorted(seen.values(), key=lambda r: r["_ts"])
            confirming = members[min_members - 1]  # the Nth distinct member completes it
            return [{
                "fired_ts": confirming["_ts"],
                "trigger_price": float(confirming.get("trigger_price") or 0),
                "first_price": float(members[0].get("trigger_price") or 0),
                "raw_event_id": confirming.get("id"),
                "members": [m.get("wallet") for m in members],
            }]
    return []


def find_single_fires(raw_rows: List[Dict], wallet: str) -> List[Dict]:
    """One fire per token: the target wallet's first buy of that token."""
    for row in sorted(raw_rows, key=lambda r: _parse_ts(r.get("ts"))):
        if row.get("wallet") == wallet:
            ts = _parse_ts(row.get("ts"))
            price = float(row.get("trigger_price") or 0)
            return [{
                "fired_ts": ts, "trigger_price": price, "first_price": price,
                "raw_event_id": row.get("id"), "members": [wallet],
            }]
    return []


def score_one(
    fire: Dict,
    forward_path: List[Tuple[float, float]],
    *,
    chase_x: Optional[float],
    latency_s: float,
    exit_cfg: Dict,
) -> Dict:
    """Apply latency + chase-guard + exit replay to a single fire → a variant_signal row."""
    trigger_price = fire["trigger_price"]
    fill_ts = fire["fired_ts"] + latency_s
    fill_price = price_at(forward_path, fill_ts) or trigger_price
    chase_ratio = (fill_price / trigger_price) if trigger_price > 0 else None
    aborted = bool(chase_x is not None and chase_ratio is not None and chase_ratio > chase_x)
    # edge_kept = how much of the entry edge survived latency (≤1 means we paid up)
    edge_kept = round(trigger_price / fill_price, 6) if fill_price > 0 else None

    row = {
        "token_address": None,  # filled by caller
        "fired_ts": _iso(fire["fired_ts"]),
        "entry_price": round(fill_price, 12) if fill_price else None,
        "aborted": aborted,
        "exit_price": None,
        "is_runner": None,
        "realized_roi": None,
        "edge_kept": edge_kept,
        "raw_event_id": fire.get("raw_event_id"),
    }
    if aborted:
        return row  # skipping a chase is the correct outcome; no exit replayed

    fwd = [(ts, px) for ts, px in forward_path if ts >= fill_ts]
    exit_res = replay_exit(
        fill_price, fwd,
        stop_loss_pct=float(exit_cfg.get("stop_loss_pct", -35)),
        tp_ladder=exit_cfg.get("take_profit_ladder") or [],
        trailing_stop_pct=float(exit_cfg.get("trailing_stop_pct", -40)),
    )
    row["exit_price"] = exit_res["exit_price"]
    row["is_runner"] = exit_res["is_runner"]
    row["realized_roi"] = exit_res["realized_roi"]
    return row


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── orchestration (DB IO) ────────────────────────────────────────────────────

@dataclass
class _Substrate:
    raw_by_token: Dict[str, List[Dict]]
    paths_by_token: Dict[str, List[Tuple[float, float]]]


class VariantScorer:
    def __init__(self, *, supabase=None, runtime=None) -> None:
        self._supabase = supabase
        self._schema = None
        self._runtime = runtime

    def _sb(self):
        if self._supabase is None:
            from services.supabase_client import SCHEMA_NAME, get_supabase_client
            self._supabase = get_supabase_client()
            self._schema = SCHEMA_NAME
        return self._supabase

    def _table(self, name: str):
        return self._sb().schema(self._schema).table(name)

    def _log(self, **kw):
        try:
            if self._runtime is None:
                from services.paper_trade_runtime import get_paper_trade_runtime
                self._runtime = get_paper_trade_runtime()
            self._runtime.log(**kw)
        except Exception:
            pass

    # public entry point
    def score_all(self, variant_ids: Optional[List[str]] = None) -> Dict:
        from services.copytrade_config import get_copytrade_config
        cfg = get_copytrade_config()
        variants = self._load_variants(variant_ids)
        sub = self._load_substrate()

        total_rows = 0
        scored = 0
        for v in variants:
            try:
                rows = self._score_variant(v, sub, cfg)
                self._write_variant_rows(v["variant_id"], rows)
                total_rows += len(rows)
                scored += 1
            except Exception as exc:
                logger.error("[SCORER] variant=%s failed: %s", v.get("variant_id"), exc)
        self._log(
            severity="info", component="variant_scorer", event_type="score_complete",
            status="ok", message=f"Scored {scored} variants → {total_rows} signals",
            payload={"variants": scored, "signals": total_rows,
                     "top": self.compute_rollup(top=5)},
        )
        return {"variants_scored": scored, "signals_written": total_rows}

    def compute_rollup(self, top: int = 0) -> List[Dict]:
        """Per-variant self-describing rollup for the operator panel (§5).

        Live runner rate, signals/day, abort rate, and median edge_kept per variant — sorted so
        the operator sees which variants converge on the backtest (bot 44–53%) and which don't.
        """
        import statistics
        rows = self._fetch_all(
            "paper_variant_signals", "variant_id, fired_ts, aborted, is_runner, realized_roi, edge_kept"
        )
        by: Dict[str, List[Dict]] = {}
        for r in rows:
            by.setdefault(r.get("variant_id"), []).append(r)

        out: List[Dict] = []
        for vid, rs in by.items():
            total = len(rs)
            aborted = sum(1 for r in rs if r.get("aborted"))
            active = total - aborted
            runners = sum(1 for r in rs if not r.get("aborted") and r.get("is_runner"))
            edges = [float(r["edge_kept"]) for r in rs if r.get("edge_kept") is not None]
            rois = [float(r["realized_roi"]) for r in rs if r.get("realized_roi") is not None]
            ts = [_parse_ts(r.get("fired_ts")) for r in rs if r.get("fired_ts")]
            span_days = max((max(ts) - min(ts)) / 86400.0, 1e-9) if len(ts) >= 2 else 1.0
            out.append({
                "variant_id": vid,
                "signals": total,
                "active": active,
                "aborted": aborted,
                "runner_rate": round(runners / active, 4) if active else None,
                "abort_rate": round(aborted / total, 4) if total else None,
                "median_edge_kept": round(statistics.median(edges), 4) if edges else None,
                "avg_roi": round(statistics.mean(rois), 4) if rois else None,
                "signals_per_day": round(total / span_days, 3),
            })
        out.sort(key=lambda x: (x["runner_rate"] is not None, x["runner_rate"] or 0), reverse=True)
        return out[:top] if top else out

    def _score_variant(self, variant: Dict, sub: _Substrate, cfg) -> List[Dict]:
        config = variant.get("config") or {}
        family = variant.get("family") or "manual"
        latency = LATENCY_S.get(family, LATENCY_S["manual"])
        cluster_id = config.get("cluster_id")
        wallet = config.get("wallet")
        chase_x = config.get("chase_x")
        # cluster variants resolve the exit (and per-cluster SL override) from bot_defaults
        exit_cfg = cfg.sl_tp(cluster_id)

        rows: List[Dict] = []
        if cluster_id:
            cluster = cfg.get_cluster(cluster_id)
            if cluster is None:
                return rows
            member_set = set(cluster.member_addresses)
            window_s = float(config.get("window_s") or cluster.co_entry_window_s)
            min_members = int(config.get("min_members") or cluster.min_members_to_fire)
            for token, raw_rows in sub.raw_by_token.items():
                if not any(r.get("wallet") in member_set for r in raw_rows):
                    continue
                fires = find_cluster_fires(sorted(raw_rows, key=lambda r: _parse_ts(r.get("ts"))),
                                           member_set, window_s, min_members)
                for fire in fires:
                    row = score_one(fire, sub.paths_by_token.get(token, []),
                                    chase_x=chase_x, latency_s=latency, exit_cfg=exit_cfg)
                    row["token_address"] = token
                    rows.append(row)
        elif wallet:
            for token, raw_rows in sub.raw_by_token.items():
                fires = find_single_fires(raw_rows, wallet)
                for fire in fires:
                    row = score_one(fire, sub.paths_by_token.get(token, []),
                                    chase_x=chase_x, latency_s=latency, exit_cfg=exit_cfg)
                    row["token_address"] = token
                    rows.append(row)
        return rows

    # ── loaders / writers ────────────────────────────────────────────────────
    def _load_variants(self, variant_ids: Optional[List[str]]) -> List[Dict]:
        try:
            q = self._table("paper_variants").select("*")
            if variant_ids:
                q = q.in_("variant_id", variant_ids)
            data = q.execute().data or []
            if data:
                return data
        except Exception as exc:
            logger.debug("[SCORER] paper_variants DB read failed, using seed: %s", exc)
        # seed fallback
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "seeds", "copytrade", "paper_variants.json")
        with open(path, encoding="utf-8") as f:
            seed = json.load(f).get("variants", [])
        if variant_ids:
            wanted = set(variant_ids)
            seed = [v for v in seed if v.get("variant_id") in wanted]
        return seed

    def _load_substrate(self) -> _Substrate:
        raw = self._fetch_all("paper_raw_cobuys", "id, ts, wallet, wallet_tier, entry_style, token_address, trigger_price")
        paths = self._fetch_all("paper_price_paths", "token_address, ts, price")
        raw_by_token: Dict[str, List[Dict]] = {}
        for r in raw:
            raw_by_token.setdefault(r.get("token_address"), []).append(r)
        paths_by_token: Dict[str, List[Tuple[float, float]]] = {}
        for p in paths:
            paths_by_token.setdefault(p.get("token_address"), []).append(
                (_parse_ts(p.get("ts")), float(p.get("price") or 0))
            )
        for tok in paths_by_token:
            paths_by_token[tok].sort(key=lambda x: x[0])
        return _Substrate(raw_by_token=raw_by_token, paths_by_token=paths_by_token)

    def _fetch_all(self, table: str, columns: str, page: int = 1000) -> List[Dict]:
        out: List[Dict] = []
        start = 0
        while True:
            chunk = self._table(table).select(columns).range(start, start + page - 1).execute().data or []
            out.extend(chunk)
            if len(chunk) < page:
                break
            start += page
        return out

    def _write_variant_rows(self, variant_id: str, rows: List[Dict]) -> None:
        # idempotent: replace this variant's prior signals
        try:
            self._table("paper_variant_signals").delete().eq("variant_id", variant_id).execute()
        except Exception as exc:
            logger.debug("[SCORER] delete prior rows failed for %s: %s", variant_id, exc)
        if not rows:
            return
        payload = [{**r, "variant_id": variant_id} for r in rows]
        for i in range(0, len(payload), 500):
            try:
                self._table("paper_variant_signals").insert(payload[i:i + 500]).execute()
            except Exception as exc:
                logger.error("[SCORER] insert failed for %s: %s", variant_id, exc)


_scorer: Optional[VariantScorer] = None


def get_variant_scorer() -> VariantScorer:
    global _scorer
    if _scorer is None:
        _scorer = VariantScorer()
    return _scorer
