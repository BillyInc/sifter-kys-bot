"""Opt-in, gated single-wallet copy (STEP 7) — default OFF.

The 3 clusters are the safe default. A user may *opt in* to auto-copy a List-A elite single
wallet, but blind single-wallet copy blows the budget (an elite does 100–400 tokens/30d) and
single RR (24–35%) < cluster RR (44–53%). So this path is hard-gated:

1. **Default OFF** — only fires for users with a ``bot_single_copy_optins`` row for that wallet.
2. **Confluence required** — execute the single's buy ONLY when it ALSO has ≥1 other tracked
   co-buyer on the same token in-window (fold the single into confluence, never solo).
3. **Per-wallet daily cap of 2** — separate from the cluster caps.

Execution still flows through ``queue_autonomous_trade`` (the safe BotExecutionRouter gate).
If the opt-in table is absent (pre-migration), there are simply no opt-ins → nothing fires.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

PER_WALLET_DAILY_CAP = 2
_CAP_PREFIX = "sifter:singlecap:"


def route_single_buy(
    wallet: str,
    token_address: str,
    *,
    distinct_cobuyers: int,
    signal: Dict[str, Any],
    supabase=None,
    redis_client=None,
) -> Dict[str, Any]:
    """Route an opted-in List-A single's buy, gated by confluence + per-wallet daily cap."""
    from services.copytrade_config import get_copytrade_config

    cfg = get_copytrade_config()
    wmeta = cfg.wallet(wallet)
    # Must be a selectable List-A single (the user opted into one of these).
    if not wmeta or not wmeta.selectable:
        return {"status": "skipped", "reason": "not_list_a"}

    # Confluence gate: never copy a lone single — needs ≥1 other tracked co-buyer in-window.
    if distinct_cobuyers < 2:
        return {"status": "skipped", "reason": "no_confluence"}

    optin_users = _load_optin_users(wallet, supabase=supabase)
    if not optin_users:
        return {"status": "skipped", "reason": "no_optins"}

    # Per-wallet daily cap (separate from cluster caps).
    if not _under_daily_cap(wallet, redis_client=redis_client):
        return {"status": "skipped", "reason": "per_wallet_daily_cap"}

    single_signal = {
        **signal,
        "source": "single",
        "signal_key": f"single:{wallet}:{token_address}",
        "single_wallet": wallet,
        "wallet_count": max(int(signal.get("wallet_count") or 1), distinct_cobuyers),
        "distinct_cobuyers": distinct_cobuyers,
    }

    routed = _fan_out(single_signal, optin_users, supabase=supabase)
    if routed:
        _incr_daily_cap(wallet, redis_client=redis_client)
    return {"status": "routed" if routed else "skipped", "routed_users": routed}


# ── opt-in storage ───────────────────────────────────────────────────────────

def _load_optin_users(wallet: str, *, supabase=None) -> List[str]:
    """Users who opted in to copy this single wallet (default OFF → empty if none/no table)."""
    try:
        if supabase is None:
            from services.supabase_client import get_supabase_client
            supabase = get_supabase_client()
        from services.supabase_client import SCHEMA_NAME
        rows = (
            supabase.schema(SCHEMA_NAME).table("bot_single_copy_optins")
            .select("user_id").eq("wallet_address", wallet).eq("enabled", True).execute().data or []
        )
        return [r["user_id"] for r in rows if r.get("user_id")]
    except Exception as exc:
        logger.debug("[SINGLE COPY] optin load failed (treat as none): %s", exc)
        return []


# ── per-wallet daily cap ─────────────────────────────────────────────────────

def _cap_key(wallet: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{_CAP_PREFIX}{wallet}:{day}"


def _under_daily_cap(wallet: str, *, redis_client=None) -> bool:
    try:
        r = redis_client or _redis()
        used = int(r.get(_cap_key(wallet)) or 0)
        return used < PER_WALLET_DAILY_CAP
    except Exception:
        return True  # Redis down → don't block (safe gate still applies downstream)


def _incr_daily_cap(wallet: str, *, redis_client=None) -> None:
    try:
        r = redis_client or _redis()
        key = _cap_key(wallet)
        new = r.incr(key)
        if new == 1:
            r.expire(key, 86400)
    except Exception:
        pass


def _redis():
    from services.redis_pool import get_redis_client
    return get_redis_client()


def _fan_out(signal: Dict[str, Any], user_ids: List[str], *, supabase=None) -> int:
    from services.bot_autotrade import queue_autonomous_trade
    if supabase is None:
        from services.supabase_client import get_supabase_client
        supabase = get_supabase_client()
    routed = 0
    for user_id in user_ids:
        try:
            queued = queue_autonomous_trade(user_id=user_id, signal=signal, supabase=supabase)
            queue_id = queued.get("queue_id")
            if queue_id and queued.get("status") == "pending":
                from services.tasks import execute_bot_auto_trade
                execute_bot_auto_trade.delay(queue_id)
                routed += 1
        except Exception as exc:
            logger.warning("[SINGLE COPY] queue failed for %s: %s", str(user_id)[:8], exc)
    return routed
