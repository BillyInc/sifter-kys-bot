"""Cluster co-entry assembler — the new front door for tracked-wallet buys.

Replaces the single-wallet ``elite15`` framing with **cluster co-entry**: a signal
fires when ``>= min_members_to_fire`` members of a ``copy_clusters`` row buy the same
fresh token within ``co_entry_window_s`` (default 120s), triggering on the *2nd*
confirming buy (PAPER_TRADER_INSTRUCTIONS §0/§3).

Two responsibilities, kept separate (record-once-score-many, §1):

1. **Record once.** Every per-wallet buy of a tracked wallet is appended to
   ``paper_raw_cobuys`` (immutable substrate) and seeds a ``paper_price_paths`` point.
   Nothing here is exit- or variant-specific; the offline scorer reads this stream.

2. **Emit live cluster signals.** Buffered per token in Redis (shared across Celery
   workers). When a *bot* cluster's co-entry threshold is met, a ``source="cluster"``
   signal is emitted to ``PaperTrader.process_signal`` — the active, deployable
   hypothesis. Manual clusters and single wallets are NOT auto-emitted live; they are
   covered offline by the variant scorer over the same recorded stream.

Wire-in point: ``tasks.ingest_helius_signal`` calls :meth:`ingest_buy` right before the
legacy ``signal_aggregator.receive`` so both paths run side-by-side (backward compatible).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from services.copytrade_config import (
    STRENGTH_RANK,
    TIER_WEIGHT,
    Cluster,
    get_copytrade_config,
)

_REDIS_PREFIX = "sifter:cobuy:"        # token buffer:  <prefix><token> -> JSON {buys:[...]}
_FIRED_PREFIX = "sifter:cobuy:fired:"  # dedup:         <prefix><cluster>:<token> -> "1"
_PRICE_CACHE_PREFIX = "sifter:cobuy:px:"
_BUFFER_TTL_S = 600                     # hold buys ~3x the widest window for late co-buys
_FIRED_TTL_S = 6 * 3600                 # don't re-fire the same cluster+token for 6h
_PRICE_CACHE_TTL_S = 30


def compute_signal_strength(cluster: Cluster, member_addresses: List[str]) -> int:
    """Rank score for a cluster co-entry (higher = stronger). Used to take top-N up to caps.

    Combines: cluster strength band, number of distinct co-buyers, tier weight of the
    triggering members, and an ELITE-present bonus (ELITE confluence ≈ 2x runner rate).
    """
    members = [cluster.member(a) for a in member_addresses]
    members = [m for m in members if m is not None]
    tier_sum = sum(TIER_WEIGHT.get((m.tier or "").upper(), 1) for m in members)
    elite_present = any((m.tier or "").upper() == "ELITE" for m in members)
    base = STRENGTH_RANK.get((cluster.strength or "FAIR").upper(), 1) * 1000
    return base + len(members) * 100 + tier_sum * 10 + (50 if elite_present else 0)


class CoBuyAssembler:
    """Records the raw co-buy stream and emits bot-cluster co-entry signals."""

    def __init__(self, *, redis_client=None, supabase=None, runtime=None) -> None:
        self._redis = redis_client
        self._supabase = supabase
        self._schema = None
        self._runtime = runtime

    # ── lazy deps (so the module imports cleanly in tests / pre-migration) ───
    def _r(self):
        if self._redis is None:
            from services.redis_pool import get_redis_client
            self._redis = get_redis_client()
        return self._redis

    def _sb(self):
        if self._supabase is None:
            from services.supabase_client import SCHEMA_NAME, get_supabase_client
            self._supabase = get_supabase_client()
            self._schema = SCHEMA_NAME
        return self._supabase

    def _table(self, name: str):
        sb = self._sb()
        return sb.schema(self._schema).table(name)

    def _rt(self):
        if self._runtime is None:
            from services.paper_trade_runtime import get_paper_trade_runtime
            self._runtime = get_paper_trade_runtime()
        return self._runtime

    # ── public API ───────────────────────────────────────────────────────────
    def ingest_buy(
        self,
        wallet: str,
        token_address: str,
        *,
        trigger_price: Optional[float] = None,
        usd_value: float = 0.0,
        token_ticker: Optional[str] = None,
        ts: Optional[float] = None,
        security_pass: Optional[bool] = None,
        paper_trader=None,
        emit: bool = True,
    ) -> Dict:
        """Record one tracked-wallet buy and emit any bot-cluster co-entry it completes.

        Returns a summary dict (recorded flag, raw_event_id, list of fired cluster_ids).
        Best-effort and exception-safe: a recording/emit failure never raises to the caller.
        """
        out: Dict = {"recorded": False, "raw_event_id": None, "fired": []}
        if not wallet or not token_address:
            return out

        cfg = get_copytrade_config()
        clusters = cfg.clusters_for_wallet(wallet)
        if not clusters and not cfg.is_tracked_wallet(wallet):
            # Untracked wallet — not part of any cluster/roster; ignore for the cobuy substrate.
            return out

        ts = ts or time.time()
        price = trigger_price if trigger_price is not None else self._token_price(token_address)
        wmeta = cfg.wallet(wallet)
        # Prefer the per-cluster member tier/style; fall back to the roster wallet record.
        tier = wmeta.tier if wmeta else None
        entry_style = wmeta.entry_style if wmeta else None
        for c in clusters:
            m = c.member(wallet)
            if m is not None:
                tier = m.tier or tier
                entry_style = m.entry_style or entry_style
                break

        # 1) record-once substrate
        raw_id = self._record_raw_cobuy(
            ts=ts, wallet=wallet, wallet_tier=tier, entry_style=entry_style,
            token_address=token_address, trigger_price=price, security_pass=security_pass,
        )
        out["recorded"] = raw_id is not None
        out["raw_event_id"] = raw_id
        self._record_price_point(token_address, ts, price)

        # 2) buffer this buy per token and check each cluster's co-entry threshold
        self._append_to_buffer(token_address, wallet, ts, price, usd_value, tier, entry_style)

        if emit:
            for c in clusters:
                if not c.is_bot_cluster:
                    continue  # live emit is bot-clusters only; manual/singles are offline-scored
                fired = self._check_and_emit(
                    cluster=c, token_address=token_address, token_ticker=token_ticker,
                    raw_event_id=raw_id, paper_trader=paper_trader,
                )
                if fired:
                    out["fired"].append(c.cluster_id)

            # Opt-in single-wallet copy (default OFF; STEP 7). Only attempt when this is a
            # selectable List-A wallet AND confluence already exists (≥2 distinct tracked
            # co-buyers) — so there is no DB/opt-in lookup on the common no-confluence path.
            if wmeta and wmeta.selectable:
                distinct = self._distinct_tracked_cobuyers(token_address, 120, ts)
                if distinct >= 2:
                    try:
                        from services.bot_single_copy import route_single_buy
                        route_single_buy(
                            wallet, token_address, distinct_cobuyers=distinct,
                            signal={
                                "token_address": token_address, "token_ticker": token_ticker,
                                "side": "buy", "trigger_price": price, "timestamp": int(ts),
                            },
                        )
                    except Exception as exc:
                        logger.debug("[COBUY] single-copy route failed: %s", exc)
        return out

    # ── record-once writers ──────────────────────────────────────────────────
    def _record_raw_cobuy(
        self, *, ts: float, wallet: str, wallet_tier: Optional[str], entry_style: Optional[str],
        token_address: str, trigger_price: Optional[float], security_pass: Optional[bool],
    ) -> Optional[int]:
        try:
            row = {
                "ts": _iso(ts),
                "wallet": wallet,
                "wallet_tier": wallet_tier,
                "entry_style": entry_style,
                "token_address": token_address,
                "trigger_price": float(trigger_price or 0.0),
                "security_pass": security_pass,
            }
            res = self._table("paper_raw_cobuys").insert(row).execute()
            if res.data and res.data[0].get("id") is not None:
                return int(res.data[0]["id"])
        except Exception as exc:
            logger.debug("[COBUY] raw_cobuy insert failed: %s", exc)
        return None

    def _record_price_point(self, token_address: str, ts: float, price: Optional[float]) -> None:
        if not price or price <= 0:
            return
        try:
            # PK (token_address, ts) — ignore duplicates on the same second.
            self._table("paper_price_paths").upsert(
                {"token_address": token_address, "ts": _iso(ts), "price": float(price)},
                ignore_duplicates=True,
            ).execute()
        except Exception as exc:
            logger.debug("[COBUY] price_point upsert failed: %s", exc)

    # ── co-entry buffer + emit ───────────────────────────────────────────────
    def _append_to_buffer(
        self, token_address: str, wallet: str, ts: float, price: Optional[float],
        usd_value: float, tier: Optional[str], entry_style: Optional[str],
    ) -> None:
        try:
            r = self._r()
            key = f"{_REDIS_PREFIX}{token_address}"
            raw = r.get(key)
            buf = json.loads(raw) if raw else {"buys": []}
            buf["buys"].append({
                "wallet": wallet, "ts": ts, "price": price,
                "usd": usd_value, "tier": tier, "style": entry_style,
            })
            # prune to widest window we care about
            cutoff = ts - _BUFFER_TTL_S
            buf["buys"] = [b for b in buf["buys"] if float(b.get("ts") or 0) >= cutoff]
            r.setex(key, _BUFFER_TTL_S, json.dumps(buf, default=str))
        except Exception as exc:
            logger.debug("[COBUY] buffer append failed: %s", exc)

    def _recent_member_buys(self, cluster: Cluster, token_address: str, now: float) -> List[Dict]:
        """Distinct cluster-member buys for this token within the cluster's window."""
        try:
            r = self._r()
            raw = r.get(f"{_REDIS_PREFIX}{token_address}")
            buys = json.loads(raw)["buys"] if raw else []
        except Exception:
            buys = []
        member_set = set(cluster.member_addresses)
        window = cluster.co_entry_window_s
        seen: Dict[str, Dict] = {}
        for b in buys:
            w = b.get("wallet")
            if w not in member_set:
                continue
            if now - float(b.get("ts") or 0) > window:
                continue
            # keep the earliest buy per wallet (the trigger price we'd have copied)
            if w not in seen or float(b["ts"]) < float(seen[w]["ts"]):
                seen[w] = b
        return list(seen.values())

    def _check_and_emit(
        self, *, cluster: Cluster, token_address: str, token_ticker: Optional[str],
        raw_event_id: Optional[int], paper_trader=None,
    ) -> bool:
        now = time.time()
        member_buys = self._recent_member_buys(cluster, token_address, now)
        if len(member_buys) < cluster.min_members_to_fire:
            return False

        # dedup: fire a given (cluster, token) once per window
        fired_key = f"{_FIRED_PREFIX}{cluster.cluster_id}:{token_address}"
        try:
            r = self._r()
            if not r.set(fired_key, "1", nx=True, ex=_FIRED_TTL_S):
                return False  # already fired
        except Exception:
            pass  # if Redis dedup unavailable, still emit (process_signal dedups by token too)

        signal = self._build_cluster_signal(cluster, token_address, token_ticker, member_buys, raw_event_id)
        self._log_fired(cluster, signal)
        self._emit(signal, paper_trader)
        self._route_live(signal)
        logger.info(
            "[COBUY] action=fire cluster=%s token=%s members=%d strength=%d",
            cluster.cluster_id, token_address[:8], len(member_buys), signal["signal_strength"],
        )
        return True

    def _log_fired(self, cluster: Cluster, signal: Dict) -> None:
        """Self-describing fire log (§5): which variant/cluster/wallets, the trigger, the outcome.

        ``variant_id`` is the live/active selection (``<cluster>|live``). fill_price/chase_ratio/
        is_runner/edge_kept are filled by the paper-trader entry log and the offline scorer rows;
        every line traces back to a ``paper_raw_cobuys`` id via ``raw_event_id``.
        """
        try:
            self._rt().log(
                severity="info",
                component="cobuy_assembler",
                event_type="signal_fired",
                status="fired",
                message=f"Cluster co-entry fired: {cluster.cluster_id}",
                signal_key=signal["signal_key"],
                token_address=signal["token_address"],
                payload={
                    "variant_id": f"{cluster.cluster_id}|live",
                    "cluster_id": cluster.cluster_id,
                    "trigger_wallets": signal["trigger_wallets"],
                    "wallet_tiers": signal["wallet_tiers"],
                    "entry_style": signal.get("entry_style"),
                    "entry_styles": signal.get("entry_styles"),
                    "trigger_price": signal.get("trigger_price"),
                    "first_buy_price": signal.get("first_buy_price"),
                    "signal_strength": signal["signal_strength"],
                    "min_members": cluster.min_members_to_fire,
                    "window_s": cluster.co_entry_window_s,
                    "raw_event_id": signal.get("raw_event_id"),
                },
            )
        except Exception as exc:
            logger.debug("[COBUY] signal_fired log failed: %s", exc)

    def _build_cluster_signal(
        self, cluster: Cluster, token_address: str, token_ticker: Optional[str],
        member_buys: List[Dict], raw_event_id: Optional[int],
    ) -> Dict:
        member_buys = sorted(member_buys, key=lambda b: float(b.get("ts") or 0))
        addrs = [b["wallet"] for b in member_buys]
        tiers = [b.get("tier") for b in member_buys]
        styles = [b.get("style") for b in member_buys]
        # 2nd-buy trigger: the confirming (2nd) member's price is the realistic entry.
        trigger_price = member_buys[1].get("price") if len(member_buys) >= 2 else member_buys[0].get("price")
        first_price = member_buys[0].get("price")
        total_usd = round(sum(float(b.get("usd") or 0) for b in member_buys), 2)

        # Confluence facts (drive size-up): distinct tracked co-buyers on this token, and
        # whether an ELITE / List-A wallet is among them (ELITE present ≈ 2x runner rate).
        cfg = get_copytrade_config()
        distinct_cobuyers = self._distinct_tracked_cobuyers(token_address, cluster.co_entry_window_s, time.time())
        list_a = {w.address for w in cfg.list_a_singles()}
        elite_present = any((t or "").upper() == "ELITE" for t in tiers)
        list_a_present = any(a in list_a for a in addrs)

        size_pct = None
        try:
            from services.copytrade_sizing import confluence_size_pct
            size_pct = confluence_size_pct(
                cfg.confluence_sizing(),
                elite_or_list_a_present=(elite_present or list_a_present),
                distinct_cobuyers=distinct_cobuyers,
            )
        except Exception:
            size_pct = None

        return {
            "source": "cluster",
            "side": "buy",
            "token_address": token_address,
            "token_ticker": token_ticker,
            "signal_key": f"{cluster.cluster_id}:{token_address}",
            "cluster_id": cluster.cluster_id,
            "is_bot_cluster": cluster.is_bot_cluster,
            "wallet_count": len(member_buys),
            "trigger_wallets": addrs,
            "wallet_tiers": tiers,
            "entry_styles": styles,
            "entry_style": styles[0] if styles else None,
            "trigger_price": trigger_price,
            "first_buy_price": first_price,
            "trades": [{"usd_value": float(b.get("usd") or 0)} for b in member_buys],
            "wallets": [{"wallet": a, "tier": t} for a, t in zip(addrs, tiers)],
            "total_usd": total_usd,
            "signal_strength": compute_signal_strength(cluster, addrs),
            "distinct_cobuyers": distinct_cobuyers,
            "elite_present": elite_present,
            "list_a_present": list_a_present,
            "size_pct": size_pct,
            "sl_tp": cfg.sl_tp(cluster.cluster_id),
            "raw_event_id": raw_event_id,
            "timestamp": int(time.time()),
        }

    def _distinct_tracked_cobuyers(self, token_address: str, window_s: float, now: float) -> int:
        """Count distinct tracked wallets (any cluster/roster) that bought this token in-window."""
        try:
            raw = self._r().get(f"{_REDIS_PREFIX}{token_address}")
            buys = json.loads(raw)["buys"] if raw else []
        except Exception:
            return 0
        cfg = get_copytrade_config()
        wallets = {
            b.get("wallet") for b in buys
            if now - float(b.get("ts") or 0) <= window_s and cfg.is_tracked_wallet(b.get("wallet"))
        }
        return len(wallets)

    def _emit(self, signal: Dict, paper_trader=None) -> None:
        try:
            if paper_trader is None:
                from services.paper_trader import PaperTrader
                paper_trader = PaperTrader()
            paper_trader.process_signal(signal)
        except Exception as exc:
            logger.error("[COBUY] emit to paper_trader failed: %s", exc)

    def _route_live(self, signal: Dict) -> None:
        """Run the live cluster selection (chase-guard + caps + fan-out). Best-effort.

        Selection/caps/chase-guard always run and log; real per-user routing only happens
        when COPYTRADE_LIVE_CLUSTER_ROUTING is enabled, and execution still obeys the
        BotExecutionRouter safe gate. A failure here never affects paper recording.
        """
        try:
            from services.bot_cluster_autotrade import route_cluster_signal
            route_cluster_signal(signal)
        except Exception as exc:
            logger.error("[COBUY] live cluster route failed: %s", exc)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _token_price(self, token_address: str) -> float:
        """Best-effort current price with a short Redis cache (avoids per-buy API spam)."""
        try:
            r = self._r()
            cached = r.get(f"{_PRICE_CACHE_PREFIX}{token_address}")
            if cached is not None:
                return float(cached)
        except Exception:
            r = None
        price = 0.0
        try:
            from services.solana_tracker_client import get_st_client
            data = get_st_client().get_token_info(token_address)
            pools = (data or {}).get("pools") or []
            if pools:
                pool = max(pools, key=lambda p: p.get("liquidity", {}).get("usd", 0))
                price = float(pool.get("price", {}).get("usd") or 0)
        except Exception:
            price = 0.0
        try:
            if r is not None and price > 0:
                r.setex(f"{_PRICE_CACHE_PREFIX}{token_address}", _PRICE_CACHE_TTL_S, str(price))
        except Exception:
            pass
        return price


def _iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


_assembler: Optional[CoBuyAssembler] = None


def get_cobuy_assembler() -> CoBuyAssembler:
    global _assembler
    if _assembler is None:
        _assembler = CoBuyAssembler()
    return _assembler


def ingest_buy_from_signal(signal: Dict, *, paper_trader=None) -> Dict:
    """Adapter: pull the fields the assembler needs out of a raw Helius/monitor signal."""
    return get_cobuy_assembler().ingest_buy(
        wallet=signal.get("wallet_address") or signal.get("wallet") or "",
        token_address=signal.get("token_address") or "",
        trigger_price=_num(signal.get("price")),
        usd_value=float(signal.get("usd_value") or 0),
        token_ticker=signal.get("token_ticker"),
        security_pass=signal.get("token_qualified"),
        paper_trader=paper_trader,
    )


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
