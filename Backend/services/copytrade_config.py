"""Copy-trade roster + bot-defaults loader (clusters, wallets, SL/TP/sizing/limits).

Single source of truth for the cluster co-entry engine. Loads:
  - clusters  (12; 3 flagged ``is_bot_cluster``) — who is in which cluster, per-member
    role (``selectable`` vs ``co-confirmation``) and entry style, plus cluster stats.
  - wallets   (124) — per-wallet tier/RR/EV/style/strength for the manual List-A menu.
  - defaults  — SL/TP, trade limits, confluence sizing (``bot_defaults.json``).

Source-of-truth strategy (PAPER_TRADER_INSTRUCTIONS STEP 1):
  - ``bot_defaults`` is **DB-first** (``sifter_dev.bot_defaults`` config row), falling back
    to the shipped ``seeds/copytrade/bot_defaults.json`` so nothing hard-fails pre-migration.
  - clusters/wallets use the versioned JSON seeds (``clusters.json`` / ``wallets.json``) for
    full per-member detail — the DB ``copy_clusters.members`` column only stores addresses —
    and overlay authoritative cluster stats / ``is_bot_cluster`` from the DB when seeded.

Everything is cached in-process for ``_CACHE_TTL_S`` so hot paths (the co-entry assembler
runs on every tracked buy) don't hammer Supabase. Call :func:`get_copytrade_config`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_SEEDS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "seeds", "copytrade")
_CACHE_TTL_S = 60.0

# Strength ordering for ranking co-entries / single signals (high → low).
STRENGTH_RANK: Dict[str, int] = {"STRONG": 3, "MODERATE": 2, "FAIR": 1, "WEAK": 0}
# Tier weights — ELITE confluence roughly doubles runner rate (bot_defaults sizing data).
TIER_WEIGHT: Dict[str, int] = {"ELITE": 4, "HIGH-RISK": 2, "CONSERVATIVE": 2, "DROP": 1}


def _seed_path(name: str) -> str:
    return os.path.join(_SEEDS_DIR, name)


@dataclass(frozen=True)
class ClusterMember:
    address: str
    tier: str = "CONSERVATIVE"
    role: str = "selectable"            # 'selectable' | 'co-confirmation'
    entry_style: str = "accumulator"   # 'accumulator' | 'first-pump' | 'first-dip'

    @property
    def is_co_confirmation(self) -> bool:
        return (self.role or "").lower() == "co-confirmation"

    @property
    def tradable(self) -> bool:
        """Co-confirmation members sharpen a signal but are never bought solo."""
        return not self.is_co_confirmation


@dataclass(frozen=True)
class Cluster:
    cluster_id: str
    is_bot_cluster: bool
    members: List[ClusterMember]
    shrunk_runner_rate_pct: float = 0.0
    nonrunner_ev_pct: float = 0.0
    signals_per_day: float = 0.0
    strength: str = "FAIR"
    co_entry_window_s: int = 120
    min_members_to_fire: int = 2

    @property
    def member_addresses(self) -> List[str]:
        return [m.address for m in self.members]

    def member(self, address: str) -> Optional[ClusterMember]:
        for m in self.members:
            if m.address == address:
                return m
        return None

    @property
    def bleeds_unmonitored(self) -> bool:
        """Negative non-runner EV — high RR but loses while held unattended.

        These are surfaced to the manual trader with a warning; the auto-bot skips them.
        """
        return self.nonrunner_ev_pct < 5.0


@dataclass(frozen=True)
class Wallet:
    address: str
    tier: str = "CONSERVATIVE"
    role: str = "bench"
    runner_rate_pct: float = 0.0
    nonrunner_ev_pct: float = 0.0
    profit_factor: float = 0.0
    runner_to_ath_x: float = 0.0
    tokens_30d: int = 0
    entry_style: str = "accumulator"
    signal_strength: str = "WEAK"
    selectable: bool = False


@dataclass
class _Snapshot:
    clusters: Dict[str, Cluster]
    wallets: Dict[str, Wallet]
    defaults: Dict
    wallet_to_clusters: Dict[str, List[str]]
    loaded_at: float = field(default_factory=time.time)


class CopyTradeConfig:
    """Cached accessor over the copy-trade roster and bot defaults."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snap: Optional[_Snapshot] = None

    # ── public API ───────────────────────────────────────────────────────────
    def reload(self) -> None:
        with self._lock:
            self._snap = self._build_snapshot()

    def _get(self) -> _Snapshot:
        snap = self._snap
        if snap is None or (time.time() - snap.loaded_at) > _CACHE_TTL_S:
            with self._lock:
                if self._snap is None or (time.time() - self._snap.loaded_at) > _CACHE_TTL_S:
                    self._snap = self._build_snapshot()
            snap = self._snap
        return snap

    def clusters(self) -> List[Cluster]:
        return list(self._get().clusters.values())

    def bot_clusters(self) -> List[Cluster]:
        return [c for c in self._get().clusters.values() if c.is_bot_cluster]

    def manual_clusters(self) -> List[Cluster]:
        """All 12 clusters ranked by strength (manual feed)."""
        return sorted(
            self._get().clusters.values(),
            key=lambda c: (STRENGTH_RANK.get(c.strength, 0), c.shrunk_runner_rate_pct),
            reverse=True,
        )

    def get_cluster(self, cluster_id: str) -> Optional[Cluster]:
        return self._get().clusters.get(cluster_id)

    def clusters_for_wallet(self, address: str) -> List[Cluster]:
        snap = self._get()
        return [snap.clusters[cid] for cid in snap.wallet_to_clusters.get(address, [])]

    def bot_clusters_for_wallet(self, address: str) -> List[Cluster]:
        return [c for c in self.clusters_for_wallet(address) if c.is_bot_cluster]

    def is_tracked_wallet(self, address: str) -> bool:
        return address in self._get().wallet_to_clusters or address in self._get().wallets

    def wallet(self, address: str) -> Optional[Wallet]:
        return self._get().wallets.get(address)

    def list_a_singles(self, strengths=("STRONG", "MODERATE")) -> List[Wallet]:
        """Selectable single wallets for the manual menu, ranked by strength then RR."""
        wanted = set(strengths)
        rows = [
            w for w in self._get().wallets.values()
            if w.selectable and w.signal_strength in wanted
        ]
        return sorted(
            rows,
            key=lambda w: (STRENGTH_RANK.get(w.signal_strength, 0), w.runner_rate_pct),
            reverse=True,
        )

    # ── bot defaults (SL/TP, limits, sizing) ─────────────────────────────────
    def defaults(self) -> Dict:
        return self._get().defaults

    def trade_limits(self) -> Dict:
        return self._get().defaults.get("trade_limits", {})

    def confluence_sizing(self) -> Dict:
        return self._get().defaults.get("confluence_sizing", {})

    def sl_tp(self, cluster_id: Optional[str] = None) -> Dict:
        """SL/TP strategy with per-cluster stop-loss override applied."""
        strat = dict(self._get().defaults.get("sl_tp_strategy", {}))
        if cluster_id:
            override = (strat.get("per_cluster_overrides") or {}).get(cluster_id)
            if override and override.get("stop_loss_pct") is not None:
                strat["stop_loss_pct"] = override["stop_loss_pct"]
        return strat

    def single_copy_policy(self) -> Dict:
        return self._get().defaults.get("bot_can_copy_singles", {})

    # ── loading ──────────────────────────────────────────────────────────────
    def _build_snapshot(self) -> _Snapshot:
        wallets = self._load_wallets()
        clusters = self._load_clusters(wallets)
        defaults = self._load_defaults()

        wallet_to_clusters: Dict[str, List[str]] = {}
        for c in clusters.values():
            for m in c.members:
                wallet_to_clusters.setdefault(m.address, []).append(c.cluster_id)

        return _Snapshot(
            clusters=clusters,
            wallets=wallets,
            defaults=defaults,
            wallet_to_clusters=wallet_to_clusters,
        )

    def _load_wallets(self) -> Dict[str, Wallet]:
        rows: List[Dict] = []
        # DB first.
        try:
            from services.supabase_client import SCHEMA_NAME, get_supabase_client
            data = (
                get_supabase_client().schema(SCHEMA_NAME).table("copy_wallets").select("*").execute().data
                or []
            )
            rows = data
        except Exception as exc:
            logger.debug("[COPYTRADE] copy_wallets DB read failed, using seed: %s", exc)

        if not rows:
            rows = self._read_seed("wallets.json").get("wallets", [])

        out: Dict[str, Wallet] = {}
        for r in rows:
            addr = r.get("address")
            if not addr:
                continue
            out[addr] = Wallet(
                address=addr,
                tier=r.get("tier") or "CONSERVATIVE",
                role=r.get("role") or "bench",
                runner_rate_pct=float(r.get("runner_rate_pct") or 0),
                nonrunner_ev_pct=float(r.get("nonrunner_ev_pct") or 0),
                profit_factor=float(r.get("profit_factor") or 0),
                runner_to_ath_x=float(r.get("runner_to_ath_x") or 0),
                tokens_30d=int(r.get("tokens_30d") or 0),
                entry_style=r.get("entry_style") or "accumulator",
                signal_strength=r.get("signal_strength") or "WEAK",
                selectable=bool(r.get("selectable")),
            )
        return out

    def _load_clusters(self, wallets: Dict[str, Wallet]) -> Dict[str, Cluster]:
        # clusters.json carries full per-member role/entry_style (the DB members column
        # stores addresses only), so it is the structural source. DB stats overlay below.
        seed = self._read_seed("clusters.json").get("clusters", [])
        db_stats = self._load_cluster_stats_from_db()

        out: Dict[str, Cluster] = {}
        for c in seed:
            cid = c.get("cluster_id")
            if not cid:
                continue
            members = [
                ClusterMember(
                    address=m["address"],
                    tier=m.get("tier") or (wallets.get(m["address"]).tier if wallets.get(m["address"]) else "CONSERVATIVE"),
                    role=m.get("role") or "selectable",
                    entry_style=m.get("entry_style")
                    or (wallets.get(m["address"]).entry_style if wallets.get(m["address"]) else "accumulator"),
                )
                for m in c.get("members", [])
                if m.get("address")
            ]
            stats = db_stats.get(cid, {})
            out[cid] = Cluster(
                cluster_id=cid,
                is_bot_cluster=bool(stats.get("is_bot_cluster", c.get("is_bot_cluster", False))),
                members=members,
                shrunk_runner_rate_pct=float(stats.get("shrunk_runner_rate_pct", c.get("shrunk_runner_rate_pct", 0)) or 0),
                nonrunner_ev_pct=float(stats.get("nonrunner_ev_pct", c.get("nonrunner_ev_pct", 0)) or 0),
                signals_per_day=float(c.get("signals_per_day", 0) or 0),
                strength=stats.get("strength") or c.get("strength") or "FAIR",
                co_entry_window_s=int(stats.get("co_entry_window_s", c.get("co_entry_window_s", 120)) or 120),
                min_members_to_fire=int(stats.get("min_members_to_fire", c.get("min_members_to_fire", 2)) or 2),
            )
        return out

    def _load_cluster_stats_from_db(self) -> Dict[str, Dict]:
        try:
            from services.supabase_client import SCHEMA_NAME, get_supabase_client
            data = (
                get_supabase_client().schema(SCHEMA_NAME).table("copy_clusters").select("*").execute().data
                or []
            )
            return {r["cluster_id"]: r for r in data if r.get("cluster_id")}
        except Exception as exc:
            logger.debug("[COPYTRADE] copy_clusters DB read failed, using seed stats: %s", exc)
            return {}

    def _load_defaults(self) -> Dict:
        # DB-first: the bot must load SL/TP/sizing/limits from the DB once seeded.
        try:
            from services.supabase_client import SCHEMA_NAME, get_supabase_client
            data = (
                get_supabase_client().schema(SCHEMA_NAME).table("bot_defaults")
                .select("config").eq("id", True).limit(1).execute().data
                or []
            )
            if data and data[0].get("config"):
                cfg = data[0]["config"]
                return cfg if isinstance(cfg, dict) else json.loads(cfg)
        except Exception as exc:
            logger.debug("[COPYTRADE] bot_defaults DB read failed, using seed: %s", exc)
        return self._read_seed("bot_defaults.json")

    def _read_seed(self, name: str) -> Dict:
        try:
            with open(_seed_path(name), encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("[COPYTRADE] seed read failed for %s: %s", name, exc)
            return {}


_config: Optional[CopyTradeConfig] = None
_config_lock = threading.Lock()


def get_copytrade_config() -> CopyTradeConfig:
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = CopyTradeConfig()
    return _config
