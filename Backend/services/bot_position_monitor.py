"""Periodic position monitor — checks open positions for TP/SL/trailing-stop triggers.

Runs as a Celery task every 15 seconds. For each open position:
  1. Fetches the current price from Birdeye/Jupiter
  2. Checks TP: current >= avg_entry_price * take_profit_x
  3. Checks SL: current <= avg_entry_price * (1 + stop_loss_pct/100)
  4. Checks trailing stop: tracks peak, closes on drop below threshold
  5. On trigger: routes a SELL through BotExecutionRouter, updates position
  6. Fires Telegram + email notifications independently

We intentionally do NOT hold hundreds of concurrent API calls — positions
are checked in batches with a small delay between each to stay within rate
limits.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.bot_execution import BotTradeRequest, get_bot_executor
from services.email_service import get_email_service
from services.supabase_client import get_supabase_client, SCHEMA_NAME

logger = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

BATCH_SIZE = 5            # how many positions to check in one invocation
PAUSE_BETWEEN = 0.3       # seconds between individual position checks

# ── price fetching ────────────────────────────────────────────────────────────

import requests as _requests

def _oracle_price(token_address: str) -> Optional[float]:
    """Test/paper price override. The mock Elite 15 harness sets scripted prices
    in Redis (key sifter:mock_price:{token}) so TP/SL/trailing can be forced
    deterministically without real liquidity. Returns None when not set."""
    try:
        import os as _os
        # Only honor the oracle outside of true live execution.
        from config import Config
        if Config.BOT_EXECUTION_MODE == "live":
            return None
        import redis as _redis
        r = _redis.Redis.from_url(
            _os.environ.get("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True,
        )
        val = r.get(f"sifter:mock_price:{token_address}")
        return float(val) if val is not None else None
    except Exception:
        return None


def _fetch_current_price(token_address: str) -> Tuple[Optional[float], Optional[str]]:
    """Fetch current USD price for a Solana token.

    Checks the test price oracle first (set by the mock Elite 15 harness in
    paper/devnet mode), then falls back to a live Jupiter quote.

    Returns (price_usd, error_message). error_message is None on success.
    """
    # Scripted price override for testing (paper/devnet only)
    oracle = _oracle_price(token_address)
    if oracle is not None:
        return oracle, None
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint=So11111111111111111111111111111111111111112&outputMint={token_address}&amount=1000000000&slippageBps=50"
        resp = _requests.get(url, timeout=8)
        if resp.status_code != 200:
            return None, f"Jupiter API returned {resp.status_code}"
        data = resp.json()
        out_amount = int(data.get("outAmount") or 0)
        if out_amount <= 0:
            return None, "zero outAmount from Jupiter"
        # 1 SOL (1e9 lamports) → outAmount tokens → price = 1e9 / outAmount in SOL, then convert to USD
        price_in_sol = 1e9 / out_amount
        # Approximate SOL/USD — in production fetch this independently
        sol_usd = _fetch_sol_price()
        return round(price_in_sol * sol_usd, 10), None
    except Exception as exc:
        return None, str(exc)


_sol_price_cache: Dict[str, Any] = {"price": None, "ts": 0}

def _fetch_sol_price() -> float:
    """Cached SOL/USD price for 60 seconds via Jupiter API (free, no key)."""
    now = time.time()
    if _sol_price_cache["price"] is not None and (now - _sol_price_cache["ts"]) < 60:
        return float(_sol_price_cache["price"])
    try:
        # Jupiter quote: 1 USDC → SOL gives us the SOL price in USD
        # USDC mint: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
        # SOL mint: So11111111111111111111111111111111111111112
        resp = _requests.get(
            "https://quote-api.jup.ag/v6/quote?"
            "inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&"
            "outputMint=So11111111111111111111111111111111111111112&"
            "amount=1000000&slippageBps=5",  # 1 USDC = 1,000,000 micro-units
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            out_amount = int(data.get("outAmount") or 0)
            if out_amount > 0:
                # outAmount is in lamports (1 SOL = 1e9 lamports)
                price = 1e9 / out_amount  # USD per SOL
            else:
                price = 150.0
        else:
            price = 150.0  # fallback
    except Exception:
        price = 150.0
    _sol_price_cache["price"] = price
    _sol_price_cache["ts"] = now
    return price


# ── check logic ───────────────────────────────────────────────────────────────

def _check_position(position: dict, current_price: float) -> Optional[Dict[str, Any]]:
    """Evaluate a single position against TP / SL / trailing-stop rules.

    Returns a dict with trigger info if the position should be closed, or None.
    """
    entry = float(position.get("avg_entry_price") or 0)
    if entry <= 0 or current_price <= 0:
        return None

    tp_x = float(position.get("take_profit_x") or 0)
    sl_pct = int(position.get("stop_loss_pct") or 0)
    trailing_pct = position.get("trailing_stop_pct")
    peak = float(position.get("peak_multiple") or 1.0)

    current_mult = current_price / entry

    # Update peak for trailing stop tracking
    if current_mult > peak:
        peak = current_mult

    # Check TP
    if tp_x > 0 and current_mult >= tp_x:
        return {
            "reason": "tp",
            "close_reason": "closed_tp",
            "multiplier": round(current_mult, 2),
            "peak_multiple": peak,
            "pnl_est": round(current_mult - 1.0, 4),
        }

    # Check SL (sl_pct is negative, e.g. -50 means 50% below entry)
    if sl_pct < 0:
        sl_threshold = 1.0 + (sl_pct / 100.0)
        if current_mult <= sl_threshold:
            return {
                "reason": "sl",
                "close_reason": "closed_sl",
                "multiplier": round(current_mult, 2),
                "peak_multiple": peak,
                "pnl_est": round(current_mult - 1.0, 4),
                "sl_pct": sl_pct,
            }

    # Check trailing stop
    if trailing_pct is not None:
        try:
            trail = float(trailing_pct)
            if trail > 0:
                trail_threshold = peak * (1.0 - trail / 100.0)
                if current_mult <= trail_threshold:
                    return {
                        "reason": "trailing",
                        "close_reason": "closed_trailing",
                        "multiplier": round(current_mult, 2),
                        "peak_multiple": peak,
                        "pnl_est": round(current_mult - 1.0, 4),
                        "peak_price": round(entry * peak, 10),
                    }
        except (TypeError, ValueError):
            pass

    # No trigger, but peak may have changed
    if current_mult > float(position.get("peak_multiple") or 1.0):
        return {"reason": "peak_update", "peak_multiple": peak}
    return None


# ── execution settings ────────────────────────────────────────────────────────

# Default execution preferences mirror the telegram_users column defaults
# (slippage_bps DEFAULT 100, mev_protection DEFAULT TRUE).
DEFAULT_EXIT_SLIPPAGE_BPS = 100


def _load_user_exec_settings(supabase, user_id: str, cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Load a user's live-execution preferences (slippage + MEV) for exits.

    Exits previously sent only stop_loss_pct/take_profit_x, so every TP/SL sold
    at the hardcoded adapter default (100 bps) regardless of the user's choice.
    We now carry the user's configured slippage_bps + mev_protection into the
    sell request. Results are cached per monitor cycle to avoid a DB hit per
    position. Falls back to safe defaults on any error."""
    if not user_id:
        return {"slippage_bps": DEFAULT_EXIT_SLIPPAGE_BPS, "mev_protection": True}
    if user_id in cache:
        return cache[user_id]
    settings = {"slippage_bps": DEFAULT_EXIT_SLIPPAGE_BPS, "mev_protection": True}
    try:
        res = (
            supabase.schema(SCHEMA_NAME)
            .table("telegram_users")
            .select("slippage_bps, mev_protection")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if res.data:
            row = res.data[0]
            if row.get("slippage_bps") is not None:
                settings["slippage_bps"] = int(row["slippage_bps"])
            if row.get("mev_protection") is not None:
                settings["mev_protection"] = bool(row["mev_protection"])
    except Exception as exc:
        logger.warning("[POS_MONITOR] exec settings load failed for %s: %s", str(user_id)[:8], exc)
    cache[user_id] = settings
    return settings


# ── Celery task entry point ───────────────────────────────────────────────────

def monitor_positions() -> Dict[str, Any]:
    """Celery task: check a batch of open positions for TP/SL/trailing triggers.

    Designed to be called every 15s. Each invocation checks BATCH_SIZE positions
    so that within a cycle all open positions get checked.
    """
    supabase = get_supabase_client()
    closed_count = 0
    skipped_count = 0
    errors: List[str] = []
    # Per-cycle cache of user execution prefs (slippage/MEV) — one DB hit per user.
    exec_settings_cache: Dict[str, Dict[str, Any]] = {}

    try:
        res = (
            supabase.schema(SCHEMA_NAME)
            .table("bot_live_positions")
            .select("*")
            .eq("status", "open")
            .order("last_checked_at", desc=False)
            .limit(BATCH_SIZE)
            .execute()
        )
        positions = res.data or []
    except Exception as exc:
        logger.error("[POS_MONITOR] fetch open positions failed: %s", exc)
        return {"closed": 0, "skipped": 0, "errors": [str(exc)]}

    for pos in positions:
        token = pos.get("token_address") or ""
        pos_id = pos.get("id")
        if not token or not pos_id:
            skipped_count += 1
            continue

        # Fetch current price
        current_price, err = _fetch_current_price(token)
        if err:
            logger.info("[POS_MONITOR] price fetch failed for %s: %s", token, err)
            # Still update last_checked_at so we don't get stuck
            try:
                supabase.schema(SCHEMA_NAME).table("bot_live_positions").update({
                    "last_checked_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", pos_id).execute()
            except Exception:
                pass
            errors.append(f"{token}: {err}")
            skipped_count += 1
            continue

        # Evaluate triggers
        trigger = _check_position(pos, current_price)
        if trigger is None:
            # No trigger — just bump last_checked and maybe peak
            updates: Dict[str, Any] = {
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
            }
            # Also update current_value_usd for dashboard display
            remaining = float(pos.get("remaining_amount") or 0)
            if remaining > 0:
                updates["current_value_usd"] = round(remaining * current_price, 2)
            try:
                supabase.schema(SCHEMA_NAME).table("bot_live_positions").update(updates).eq("id", pos_id).execute()
            except Exception:
                pass
            skipped_count += 1
            continue

        if trigger["reason"] == "peak_update":
            # Just update the peak
            try:
                supabase.schema(SCHEMA_NAME).table("bot_live_positions").update({
                    "peak_multiple": trigger["peak_multiple"],
                    "last_checked_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", pos_id).execute()
            except Exception:
                pass
            skipped_count += 1
            continue

        # Trigger fired — close the position
        logger.info(
            "[POS_MONITOR] %s triggered for pos %s token %s: mult=%.2f",
            trigger["reason"], pos_id, token, trigger["multiplier"],
        )
        user_id = pos.get("user_id") or ""

        try:
            executor = get_bot_executor()
            # Carry the user's configured slippage + MEV into the exit so TP/SL
            # don't silently sell at the adapter's hardcoded default.
            exec_prefs = _load_user_exec_settings(supabase, user_id, exec_settings_cache)
            req = BotTradeRequest(
                user_id=user_id,
                token_address=token,
                side="sell",
                requested_usd=0,
                token_symbol=pos.get("token_symbol") or "",
                trigger_type="auto_elite",
                sell_pct=100,
                settings={
                    "stop_loss_pct": pos.get("stop_loss_pct"),
                    "take_profit_x": pos.get("take_profit_x"),
                    "slippage_bps": exec_prefs["slippage_bps"],
                    "mev_protection": exec_prefs["mev_protection"],
                },
                snapshot={"trigger": trigger},
            )
            result = executor.execute(req)
            if result.status == "filled":
                close_reason = trigger["close_reason"]
                # Update position with close details
                supabase.schema(SCHEMA_NAME).table("bot_live_positions").update({
                    "status": "closed",
                    "close_reason": close_reason,
                    "closed_at": datetime.now(timezone.utc).isoformat(),
                    "peak_multiple": trigger.get("peak_multiple", float(pos.get("peak_multiple") or 1)),
                    "last_checked_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", pos_id).execute()

                # ── Notifications ──────────────────────────────────────────
                _send_close_notifications(pos, trigger, user_id)

                # Auto-blacklist if SL hit and user has auto-blacklist on
                if trigger["reason"] == "sl":
                    _maybe_auto_blacklist(supabase, user_id, token, pos.get("token_symbol") or "")

                closed_count += 1
            else:
                errors.append(f"{token}: execution returned {result.status}")
                skipped_count += 1
        except Exception as exc:
            logger.exception("[POS_MONITOR] close execution failed for %s: %s", pos_id, exc)
            errors.append(f"{token}: {exc}")
            skipped_count += 1

        # Small pause between positions to avoid rate limiting
        time.sleep(PAUSE_BETWEEN)

    return {
        "closed": closed_count,
        "skipped": skipped_count,
        "checked": len(positions),
        "errors": errors,
    }


# ── notification & blacklist helpers ──────────────────────────────────────────

def _send_close_notifications(position: dict, trigger: dict, user_id: str) -> None:
    """Fire email notifications for a position close (Telegram handled by caller)."""
    token_symbol = position.get("token_symbol") or "UNKNOWN"
    token_address = position.get("token_address") or ""
    pnl = trigger.get("pnl_est", 0)
    reason = trigger["reason"]

    trade_data = {
        "token_ticker": token_symbol,
        "token_address": token_address,
        "close_reason": trigger["close_reason"],
        "realized_pnl_usd": pnl,
        "stop_loss_pct": trigger.get("sl_pct"),
        "take_profit_x": trigger.get("multiplier"),
        "peak_price_usd": trigger.get("peak_price"),
        "close_price_usd": position.get("avg_entry_price", 0) * trigger.get("multiplier", 1),
        "hold_time": "—",
    }

    try:
        email_svc = get_email_service()
        supabase = get_supabase_client()
        # Fetch user email via Supabase Admin API
        try:
            user = supabase.auth.admin.get_user_by_id(user_id)
            email = user.user.email if user and hasattr(user, 'user') and user.user else None
        except Exception:
            email = None

        if not email:
            logger.info("[POS_MONITOR] No email found for user %s, skipping email notification", user_id)
            return

        from config import Config
        dashboard_url = Config.DASHBOARD_URL or ""

        if reason == "tp":
            email_svc.send_bot_tp_hit(email, trade_data, dashboard_url, user_id=user_id)
        elif reason == "sl":
            trade_data["auto_blacklisted"] = True
            email_svc.send_bot_sl_hit(email, trade_data, dashboard_url, user_id=user_id)
        elif reason == "trailing":
            email_svc.send_bot_trailing_stop(email, trade_data, dashboard_url, user_id=user_id)
        else:
            email_svc.send_bot_trade_close(email, trade_data, dashboard_url, user_id=user_id)

        logger.info("[POS_MONITOR] Email sent for %s close: %s", token_symbol, reason)
    except Exception as exc:
        logger.error("[POS_MONITOR] Email notification failed for %s: %s", user_id, exc)

    logger.info(
        "[POS_MONITOR] Position closed: %s via %s, PnL=%.2f%%",
        token_symbol, reason, pnl * 100,
    )


def _maybe_auto_blacklist(supabase, user_id: str, token_address: str, token_symbol: str) -> None:
    """If the user has auto_blacklist enabled, add the token to their blacklist."""
    try:
        user = (
            supabase.schema(SCHEMA_NAME)
            .table("telegram_users")
            .select("auto_blacklist")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if user.data and user.data[0].get("auto_blacklist"):
            existing = (
                supabase.schema(SCHEMA_NAME)
                .table("bot_token_blacklist")
                .select("id")
                .eq("user_id", user_id)
                .eq("token_address", token_address)
                .limit(1)
                .execute()
            )
            if not existing.data:
                supabase.schema(SCHEMA_NAME).table("bot_token_blacklist").insert({
                    "user_id": user_id,
                    "token_address": token_address,
                    "token_symbol": token_symbol,
                    "reason": "auto_sl",
                }).execute()
                logger.info("[POS_MONITOR] Auto-blacklisted %s for user %s", token_address, user_id)
    except Exception as exc:
        logger.warning("[POS_MONITOR] auto-blacklist failed: %s", exc)
