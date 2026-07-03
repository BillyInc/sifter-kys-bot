"""Live cluster co-entry router — selects bot-cluster co-entries and fans them out.

Sits between the co-entry assembler and the per-user autonomous pipeline:

    bot-cluster co-entry  ->  [chase-guard + bot caps + rank]  ->  queue_autonomous_trade (per user)

It deliberately reuses ``bot_autotrade.queue_autonomous_trade`` so the **existing safe
execution gate** (security screen, blacklist, BotExecutionRouter mode) is untouched — this
module only adds the cluster-level selection on top.

Selection rules (bot_defaults):
- **Chase-guard** (§3): abort if the live fill has run > guard× past the trigger price.
- **Bot caps**: daily 4 / hourly 2 / weekly 28, enforced bot-globally in Redis. Candidates
  carry ``signal_strength`` so callers can rank top-N; within the streaming caps we admit by
  arrival and log cap exhaustion (a batch flush can pre-rank via ``copytrade_sizing.rank_candidates``).
- Source is bot clusters only; manual clusters / singles never auto-route here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Live cluster fan-out is opt-in per deployment. Selection/caps/chase-guard always run
# (and log), but real per-user routing only happens when enabled. Execution itself still
# obeys the BotExecutionRouter mode (safe_noop/paper) regardless.
_LIVE_ROUTING_ENABLED = os.environ.get("COPYTRADE_LIVE_CLUSTER_ROUTING", "false").lower() in {"1", "true", "yes"}
_CAP_PREFIX = "sifter:clustercap:"


def route_cluster_signal(signal: Dict[str, Any], *, supabase=None, redis_client=None) -> Dict[str, Any]:
    """Apply chase-guard + bot caps, then fan a bot-cluster co-entry out to opted-in users."""
    from services.copytrade_config import get_copytrade_config

    if signal.get("source") != "cluster":
        return {"status": "skipped", "reason": "not_cluster"}
    cluster_id = signal.get("cluster_id")
    cfg = get_copytrade_config()
    cluster = cfg.get_cluster(cluster_id) if cluster_id else None
    if cluster is None or not cluster.is_bot_cluster:
        return {"status": "skipped", "reason": "not_bot_cluster"}

    rt = _runtime()

    # ── chase-guard: abort if the live fill has chased too far past the trigger ──
    fill_price = _fresh_price(signal.get("token_address"))
    trigger_price = signal.get("trigger_price")
    from services.copytrade_sizing import chase_ratio, is_chase_abort
    if is_chase_abort(fill_price, trigger_price):
        _log(rt, "warning", "signal_aborted_chase", cluster, signal,
             extra={"fill_price": fill_price, "chase_ratio": chase_ratio(fill_price, trigger_price)})
        return {"status": "aborted", "reason": "chase_guard", "chase_ratio": chase_ratio(fill_price, trigger_price)}

    # ── bot caps (daily/hourly/weekly), bot-global ──────────────────────────────
    limits = cfg.trade_limits()
    admit = _admit_under_caps(limits, redis_client=redis_client)
    if not admit["ok"]:
        _log(rt, "info", "signal_ignored", cluster, signal,
             extra={"reason": f"cap_{admit['which']}", "strength": signal.get("signal_strength")})
        return {"status": "skipped", "reason": f"cap_{admit['which']}"}

    if not _LIVE_ROUTING_ENABLED:
        _log(rt, "info", "cluster_selected", cluster, signal,
             extra={"routing": "disabled", "size_pct": signal.get("size_pct")})
        return {"status": "selected", "routed_users": 0, "note": "live routing disabled"}

    # ── fan out to opted-in users via the existing safe pipeline ────────────────
    routed = _fan_out_to_users(signal, supabase=supabase)
    _log(rt, "info", "cluster_routed", cluster, signal, extra={"routed_users": routed})
    return {"status": "routed", "routed_users": routed}


def _admit_under_caps(limits: Dict[str, Any], *, redis_client=None) -> Dict[str, Any]:
    """Increment bot-global daily/hourly/weekly counters; refuse once any cap is hit."""
    try:
        r = redis_client or _redis()
    except Exception:
        return {"ok": True, "which": None}  # Redis down → don't block (safe gate still applies)

    now = datetime.now(timezone.utc)
    windows = [
        ("hourly", int(limits.get("hourly_max") or 0), now.strftime("%Y%m%d%H"), 3600),
        ("daily", int(limits.get("daily_max") or 0), now.strftime("%Y%m%d"), 86400),
        ("weekly", int(limits.get("weekly_max") or 0), now.strftime("%Y%W"), 7 * 86400),
    ]
    # check first (no increment) so a later cap doesn't consume an earlier budget
    for which, cap, bucket, _ttl in windows:
        if cap <= 0:
            continue
        try:
            used = int(r.get(f"{_CAP_PREFIX}{which}:{bucket}") or 0)
        except Exception:
            used = 0
        if used >= cap:
            return {"ok": False, "which": which}
    for which, cap, bucket, ttl in windows:
        if cap <= 0:
            continue
        try:
            key = f"{_CAP_PREFIX}{which}:{bucket}"
            new = r.incr(key)
            if new == 1:
                r.expire(key, ttl)
        except Exception:
            pass
    return {"ok": True, "which": None}


def _fan_out_to_users(signal: Dict[str, Any], *, supabase=None) -> int:
    from services.bot_autotrade import queue_autonomous_trade
    if supabase is None:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
    from services.supabase_client import SCHEMA_NAME

    try:
        users = (
            supabase.schema(SCHEMA_NAME).table("telegram_users")
            .select("user_id, auto_trade_enabled, auto_trade_source")
            .eq("auto_trade_enabled", True)
            .execute().data or []
        )
    except Exception as exc:
        logger.error("[CLUSTER ROUTE] user load failed: %s", exc)
        return 0

    routed = 0
    for user in users:
        if (user.get("auto_trade_source") or "elite15") not in ("cluster", "all"):
            continue
        user_id = user.get("user_id")
        if not user_id:
            continue
        try:
            queued = queue_autonomous_trade(user_id=user_id, signal=signal, supabase=supabase)
            queue_id = queued.get("queue_id")
            if queue_id and queued.get("status") == "pending":
                from services.tasks import execute_bot_auto_trade
                execute_bot_auto_trade.delay(queue_id)
                routed += 1
        except Exception as exc:
            logger.warning("[CLUSTER ROUTE] queue failed for %s: %s", str(user_id)[:8], exc)
    return routed


# ── helpers ──────────────────────────────────────────────────────────────────

def _fresh_price(token_address: Optional[str]) -> Optional[float]:
    if not token_address:
        return None
    try:
        from services.solana_tracker_client import get_st_client
        data = get_st_client().get_token_info(token_address)
        pools = (data or {}).get("pools") or []
        if not pools:
            return None
        pool = max(pools, key=lambda p: p.get("liquidity", {}).get("usd", 0))
        return float(pool.get("price", {}).get("usd") or 0) or None
    except Exception:
        return None


def _redis():
    from services.redis_pool import get_redis_client
    return get_redis_client()


def _runtime():
    try:
        from services.paper_trade_runtime import get_paper_trade_runtime
        return get_paper_trade_runtime()
    except Exception:
        return None


def _log(rt, severity: str, event_type: str, cluster, signal: Dict[str, Any], extra: Dict[str, Any]):
    if rt is None:
        return
    try:
        rt.log(
            severity=severity, component="cluster_autotrade", event_type=event_type,
            status=event_type, message=f"{event_type}: {cluster.cluster_id}",
            signal_key=signal.get("signal_key"), token_address=signal.get("token_address"),
            payload={
                "variant_id": f"{cluster.cluster_id}|live",
                "cluster_id": cluster.cluster_id,
                "trigger_wallets": signal.get("trigger_wallets"),
                "wallet_tiers": signal.get("wallet_tiers"),
                "signal_strength": signal.get("signal_strength"),
                **extra,
            },
        )
    except Exception:
        pass


def route_manual_cluster_signal(signal: Dict[str, Any], *, supabase=None) -> int:
    """Advisory fan-out for a MANUAL cluster co-entry: notify opted-in manual
    traders on Telegram. No auto-trade — the trader acts by hand.

    Recipients: telegram_users with alerts_enabled and the notif_signal toggle
    on (the "Cluster Buy Signals" opt-in). Returns the number notified.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    supabase = supabase or get_supabase_client()
    try:
        users = (
            supabase.schema(SCHEMA_NAME).table("telegram_users")
            .select("user_id, alerts_enabled, notif_signal")
            .eq("alerts_enabled", True)
            .execute().data or []
        )
    except Exception as exc:
        logger.error("[MANUAL ROUTE] user load failed: %s", exc)
        return 0

    recipients = [u.get("user_id") for u in users if u.get("notif_signal", True) and u.get("user_id")]
    if not recipients:
        return 0

    try:
        from config import Config
        from services.telegram_notifier import TelegramNotifier
        notifier = TelegramNotifier(Config.TELEGRAM_BOT_TOKEN)
    except Exception as exc:
        logger.error("[MANUAL ROUTE] notifier init failed: %s", exc)
        return 0

    sent = 0
    for user_id in recipients:
        try:
            if notifier.send_manual_cluster_signal(user_id, signal):
                sent += 1
        except Exception as exc:
            logger.error("[MANUAL ROUTE] send failed user=%s err=%s", str(user_id)[:8], str(exc)[:120])
    logger.info(
        "[MANUAL ROUTE] cluster=%s token=%s notified=%d",
        signal.get("cluster_id"), str(signal.get("token_address"))[:8], sent,
    )
    return sent
