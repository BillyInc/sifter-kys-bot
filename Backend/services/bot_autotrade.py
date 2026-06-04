"""Autonomous Telegram bot signal queue and execution.

This module owns the auto-trading path:

    Elite signal -> per-user filters -> bot_signal_queue -> BotExecutionRouter

It deliberately does not ask the user to approve an auto-trade. Manual trades
use separate handlers with explicit confirmation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from services.bot_execution import BotTradeRequest, get_bot_executor
from services.bot_filters import load_blacklist_set, passes_auto_trade_filters
from services.supabase_client import SCHEMA_NAME

logger = logging.getLogger(__name__)


def _table(supabase, name: str):
    return supabase.schema(SCHEMA_NAME).table(name)


def _signal_key(signal: Dict[str, Any]) -> str:
    explicit = signal.get("signal_key")
    if explicit:
        return str(explicit)
    token = signal.get("token_address") or "unknown"
    first_seen = signal.get("aggregation_first_seen") or signal.get("block_time") or ""
    wallets = ",".join(sorted(signal.get("wallet_addresses") or []))
    return f"elite15:{token}:{first_seen}:{wallets}"


def _signal_type(wallet_count: int) -> str:
    if wallet_count >= 3:
        return "mega"
    if wallet_count == 2:
        return "double"
    return "single"


def _requested_usd(user_row: Dict[str, Any], signal: Dict[str, Any]) -> float:
    """Calculate requested auto-trade size from saved settings.

    The existing schema does not store live wallet balance, so max-trade USD is
    the hard safety cap. Tier percentages are still honored against the signal
    total as a stable proxy until a balance snapshot is available.
    """
    cap = float(user_row.get("auto_trade_max_usd") or 100)
    total = float(signal.get("total_usd") or signal.get("usd_value") or cap)
    wallet_count = int(signal.get("wallet_count") or 1)
    if wallet_count >= 3:
        pct = float(user_row.get("tier3_pct_of_total") or 40)
    elif wallet_count == 2:
        pct = float(user_row.get("tier2_pct_of_pool") or 70)
    else:
        pct = float(user_row.get("tier1_pct_of_pool") or 30)
    return round(max(0.0, min(cap, total * (pct / 100.0))), 2)


def _load_elite_selections_for_user(supabase, user_id: str) -> Set[str]:
    """Return the set of wallet addresses this user has explicitly selected for
    copy-trading. An empty set means 'copy ALL Elite 15 wallets' (default)."""
    try:
        res = (
            _table(supabase, "bot_elite_selections")
            .select("wallet_address")
            .eq("user_id", user_id)
            .eq("enabled", True)
            .execute()
        )
        return {r["wallet_address"] for r in (res.data or [])}
    except Exception:
        return set()  # don't block trading on a DB error


def _load_elite_set(supabase) -> Set[str]:
    """Return the canonical Elite 15 wallet allow-list (the system watchlist).

    This is the source of truth for the security screen's exact-match check.
    Cached briefly in Redis to avoid a DB hit per signal. Empty set means the
    Elite set is unknown — the security screen then SKIPS the wallet check
    (but still enforces dust/mint/provenance)."""
    import os
    system_user = os.environ.get("ELITE_SYSTEM_USER_ID", "")
    if not system_user:
        return set()
    # Try Redis cache first
    try:
        import redis as _redis
        r = _redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        cached = r.smembers("sifter:elite_set")
        if cached:
            return set(cached)
    except Exception:
        r = None
    try:
        res = (
            _table(supabase, "wallet_watchlist")
            .select("wallet_address")
            .eq("user_id", system_user)
            .execute()
        )
        elite = {row["wallet_address"] for row in (res.data or []) if row.get("wallet_address")}
        if elite and r is not None:
            try:
                r.sadd("sifter:elite_set", *elite)
                r.expire("sifter:elite_set", 300)  # 5 min
            except Exception:
                pass
        return elite
    except Exception as exc:
        logger.warning("[BOT_AUTOTRADE] could not load elite set: %s", exc)
        return set()


def queue_autonomous_trade(
    *,
    user_id: str,
    signal: Dict[str, Any],
    supabase,
) -> Dict[str, Any]:
    """Create or reuse a bot_signal_queue row for an autonomous entry.

    Returns a small status dict. Duplicate signals reuse the existing row and
    never create a second trade.
    """
    try:
        user_res = (
            _table(supabase, "telegram_users")
            .select(
                "user_id, auto_trade_enabled, auto_trade_max_usd, "
                "auto_trade_hourly_limit, auto_trade_daily_limit, "
                "consensus_threshold, tier1_pct_of_pool, tier2_pct_of_pool, "
                "tier3_pct_of_total, stop_loss_pct, take_profit_x, "
                "trailing_stop_pct, slippage_bps, mev_protection, access_tier"
            )
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not user_res.data:
            return {"status": "skipped", "reason": "no_telegram_user"}

        user_row = user_res.data[0]
        if not user_row.get("auto_trade_enabled"):
            return {"status": "skipped", "reason": "auto_trade_disabled"}
        if user_row.get("access_tier") not in (None, "autotrader"):
            return {"status": "skipped", "reason": "access_required"}

        token_address = signal.get("token_address") or ""
        if not token_address:
            return {"status": "skipped", "reason": "missing_token"}

        # ── Security screen (BEFORE filters) ───────────────────────────────────
        # Address poisoning, ticker/mint mimicry, dust bait, transfer-in fakes.
        # The Elite set is the canonical wallet allow-list; exact-match only.
        try:
            from services.bot_security import security_screen
            elite_set = _load_elite_set(supabase)
            sec_ok, sec_reason = security_screen(
                signal, elite_set,
                require_elite_wallet=bool(elite_set),
                check_liquidity=True,
            )
            if not sec_ok:
                _insert_signal_queue(
                    supabase, user_id=user_id, signal=signal,
                    requested_usd=0, status="skipped", skip_reason=sec_reason,
                )
                return {"status": "skipped", "reason": sec_reason}
        except Exception as _sec_exc:
            logger.warning("[BOT_AUTOTRADE] security screen error (failing closed): %s", _sec_exc)
            return {"status": "skipped", "reason": "security_error"}

        blacklist = load_blacklist_set(supabase, user_id)
        ok, reason = passes_auto_trade_filters(user_row, signal, blacklist)
        if not ok:
            _insert_signal_queue(
                supabase,
                user_id=user_id,
                signal=signal,
                requested_usd=0,
                status="blacklisted" if reason == "blacklisted" else "skipped",
                skip_reason=reason,
            )
            return {"status": "skipped", "reason": reason}

        # ── Elite 15 wallet selection ──────────────────────────────────────────
        # If the user has explicitly selected wallets to copy-trade, only fire
        # on signals from those wallets. If no selections exist, copy ALL Elite
        # 15 wallets (the default).
        signal_wallets = signal.get("wallet_addresses") or signal.get("wallets") or []
        if isinstance(signal_wallets, list) and signal_wallets:
            selected = _load_elite_selections_for_user(supabase, user_id)
            if selected:
                # Only proceed if at least one signaling wallet is selected
                if not any(w in selected for w in signal_wallets):
                    _insert_signal_queue(
                        supabase,
                        user_id=user_id,
                        signal=signal,
                        requested_usd=0,
                        status="skipped",
                        skip_reason="wallet_not_selected",
                    )
                    return {"status": "skipped", "reason": "wallet_not_selected"}
        # ── end Elite selection ──────────────────────────────────────────────

        # ── Rate limits ──────────────────────────────────────────────────────
        hourly_limit = int(user_row.get("auto_trade_hourly_limit") or 0)
        daily_limit = int(user_row.get("auto_trade_daily_limit") or 0)
        if hourly_limit > 0 or daily_limit > 0:
            now_ts = datetime.now(timezone.utc)
            try:
                import redis as _redis
                import os as _os
                _r = _redis.Redis.from_url(
                    _os.environ.get("REDIS_URL", "redis://localhost:6379"),
                    decode_responses=True,
                )
                if daily_limit > 0:
                    daily_key = f"sifter:rate:{user_id}:daily:{now_ts.strftime('%Y%m%d')}"
                    daily_used = int(_r.get(daily_key) or 0)
                    if daily_used >= daily_limit:
                        _insert_signal_queue(
                            supabase, user_id=user_id, signal=signal,
                            requested_usd=0, status="rate_limited",
                            skip_reason="daily_limit",
                        )
                        return {"status": "skipped", "reason": "daily_limit"}
                if hourly_limit > 0:
                    hourly_key = f"sifter:rate:{user_id}:hourly:{now_ts.strftime('%Y%m%d%H')}"
                    hourly_used = int(_r.get(hourly_key) or 0)
                    if hourly_used >= hourly_limit:
                        _insert_signal_queue(
                            supabase, user_id=user_id, signal=signal,
                            requested_usd=0, status="rate_limited",
                            skip_reason="hourly_limit",
                        )
                        return {"status": "skipped", "reason": "hourly_limit"}
            except Exception:
                pass  # Redis down → don't block trading
        # ── end rate limits ──────────────────────────────────────────────────

        # Avoid stacking entries into the same token for the same user.
        open_pos = (
            _table(supabase, "bot_live_positions")
            .select("id")
            .eq("user_id", user_id)
            .eq("token_address", token_address)
            .eq("status", "open")
            .limit(1)
            .execute()
        )
        if open_pos.data:
            row = _insert_signal_queue(
                supabase,
                user_id=user_id,
                signal=signal,
                requested_usd=0,
                status="skipped",
                skip_reason="duplicate_open_position",
            )
            return {"status": "skipped", "reason": "duplicate_open_position", "queue_id": row.get("id")}

        requested = _requested_usd(user_row, signal)
        if requested <= 0:
            return {"status": "skipped", "reason": "zero_size"}

        row = _insert_signal_queue(
            supabase,
            user_id=user_id,
            signal=signal,
            requested_usd=requested,
            status="pending",
            skip_reason=None,
        )
        return {"status": row.get("status", "pending"), "queue_id": row.get("id"), "requested_usd": requested}
    except Exception as exc:
        logger.error("[BOT_AUTOTRADE] queue failed for %s: %s", user_id, exc)
        return {"status": "error", "error": str(exc)}


def _insert_signal_queue(
    supabase,
    *,
    user_id: str,
    signal: Dict[str, Any],
    requested_usd: float,
    status: str,
    skip_reason: Optional[str],
) -> Dict[str, Any]:
    signal_key = _signal_key(signal)
    token_address = signal.get("token_address") or ""
    wallet_count = int(signal.get("wallet_count") or 1)
    row = {
        "user_id": user_id,
        "signal_key": signal_key,
        "token_address": token_address,
        "token_ticker": signal.get("token_ticker") or signal.get("token_symbol") or "UNKNOWN",
        "side": signal.get("side") or "buy",
        "wallet_count": wallet_count,
        "signal_type": signal.get("signal_type_resolved") or _signal_type(wallet_count),
        "total_usd": float(signal.get("total_usd") or signal.get("usd_value") or 0),
        "requested_usd": requested_usd,
        "status": status,
        "skip_reason": skip_reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    existing = (
        _table(supabase, "bot_signal_queue")
        .select("*")
        .eq("user_id", user_id)
        .eq("signal_key", signal_key)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]

    res = (
        _table(supabase, "bot_signal_queue")
        .insert(row)
        .execute()
    )
    return res.data[0] if res.data else row


def execute_queued_autonomous_trade(*, queue_id: int, supabase) -> Dict[str, Any]:
    """Execute one pending bot_signal_queue row through BotExecutionRouter."""
    try:
        try:
            from services.redis_pool import get_redis_client

            lock_key = f"sifter:bot_queue_lock:{queue_id}"
            locked = get_redis_client().set(lock_key, "1", nx=True, ex=300)
            if not locked:
                return {"status": "skipped", "reason": "already_processing"}
        except Exception:
            # If Redis is down, continue to the DB status gate below; live/devnet
            # execution still has the kill-switch fail-closed check in tasks.py.
            pass

        res = _table(supabase, "bot_signal_queue").select("*").eq("id", queue_id).limit(1).execute()
        if not res.data:
            return {"status": "not_found"}

        queue_row = res.data[0]
        if queue_row.get("status") != "pending":
            return {"status": "skipped", "reason": queue_row.get("status")}

        now = datetime.now(timezone.utc).isoformat()
        _table(supabase, "bot_signal_queue").update({
            "status": "executing",
            "updated_at": now,
        }).eq("id", queue_id).eq("status", "pending").execute()

        settings = _load_user_settings(supabase, queue_row["user_id"])
        request = BotTradeRequest(
            user_id=queue_row["user_id"],
            token_address=queue_row["token_address"],
            token_symbol=queue_row.get("token_ticker"),
            side=queue_row.get("side") or "buy",
            requested_usd=float(queue_row.get("requested_usd") or 0),
            signal_key=queue_row.get("signal_key"),
            wallet_count=int(queue_row.get("wallet_count") or 1),
            signal_type=queue_row.get("signal_type") or "single",
            trigger_type="auto_elite",
            snapshot={"price": 1.0},
            settings=settings,
        )
        result = get_bot_executor().execute(request)
        status = "executed" if result.status == "filled" else "error"
        update = {
            "status": status,
            "skip_reason": result.reason if status != "executed" else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _table(supabase, "bot_signal_queue").update(update).eq("id", queue_id).execute()
        return {"status": status, "result": result.to_dict()}
    except Exception as exc:
        logger.error("[BOT_AUTOTRADE] execute failed for queue %s: %s", queue_id, exc)
        try:
            _table(supabase, "bot_signal_queue").update({
                "status": "error",
                "skip_reason": str(exc)[:200],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", queue_id).execute()
        except Exception:
            pass
        return {"status": "error", "error": str(exc)}


def _load_user_settings(supabase, user_id: str) -> Dict[str, Any]:
    res = (
        _table(supabase, "telegram_users")
        .select("stop_loss_pct, take_profit_x, trailing_stop_pct, slippage_bps, mev_protection")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return dict(res.data[0]) if res.data else {}
