"""
Helius webhook receiver — push notifications for Elite wallet activity.
Replaces SolanaTracker polling as the primary wallet monitoring signal source.
"""
from __future__ import annotations
import hmac, logging, os
from typing import Any, Dict, List, Optional
from flask import Blueprint, current_app, jsonify, request

from services.supabase_client import get_supabase_client, SCHEMA_NAME

try:
    from services.alert_router import alert, P0, P1
except ImportError:
    def alert(*a, **kw): pass
    P0 = P1 = "P3"

logger = logging.getLogger(__name__)
helius_bp = Blueprint("helius", __name__)


def _verify_secret(auth_header: str) -> bool:
    """Verify the Authorization header matches our webhook secret."""
    secret = os.environ.get("HELIUS_WEBHOOK_SECRET", "")
    if not secret:
        logger.error("[HELIUS] HELIUS_WEBHOOK_SECRET not set — rejecting request")
        return False
    return hmac.compare_digest(auth_header, secret)


def _extract_swap_signal(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract a buy signal from a Helius enhanced transaction event."""
    if event.get("type") != "SWAP":
        return None

    wallet_address = event.get("feePayer") or ""
    signature = event.get("signature") or ""
    token_transfers = event.get("tokenTransfers") or []
    native_transfers = event.get("nativeTransfers") or []

    if not signature or not wallet_address:
        return None

    # Find the token the wallet received (buy side)
    token_in = None
    for transfer in token_transfers:
        if transfer.get("toUserAccount") == wallet_address:
            token_in = transfer
            break

    if not token_in:
        return None

    # Calculate SOL spent
    sol_sent = 0.0
    for nt in native_transfers:
        if nt.get("fromUserAccount") == wallet_address:
            sol_sent += float(nt.get("amount") or 0) / 1e9

    signal = {
        "source": "elite15",
        "side": "buy",
        "wallet_address": wallet_address,
        "token_address": token_in.get("mint", ""),
        "token_ticker": token_in.get("symbol") or "UNKNOWN",
        "tx_hash": signature,
        "signal_key": signature,
        "usd_value": sol_sent * 150,  # rough SOL->USD estimate
        "sol_amount": sol_sent,
        "wallet_tier": "S",
        "wallet_count": 1,
    }

    if not signal["token_address"]:
        return None

    return signal


def _process_signal(signal: Dict[str, Any]) -> None:
    """
    Process a validated swap signal:
    1. Create notifications for all users watching this wallet
    2. Send Telegram alerts
    3. Record paper trades for auto-trading users
    """
    wallet_address = signal["wallet_address"]
    supabase = get_supabase_client()

    # Find all users watching this wallet with alerts enabled
    try:
        result = supabase.schema(SCHEMA_NAME).table("wallet_watchlist").select(
            "user_id, alert_enabled, alert_threshold_usd, min_trade_usd, alert_on_buy, alert_on_sell"
        ).eq("wallet_address", wallet_address).eq("alert_enabled", True).execute()
        watchers = result.data or []
    except Exception as e:
        logger.error("[HELIUS] action=query_watchers status=failed wallet=%s error=%s", wallet_address[:8], str(e)[:200])
        watchers = []

    if not watchers:
        logger.debug("[HELIUS] action=process status=no_watchers wallet=%s", wallet_address[:8])
        return

    # Create notifications and send Telegram alerts
    telegram_notifier = current_app.config.get("TELEGRAM_NOTIFIER")
    notifications_created = 0

    for watcher in watchers:
        user_id = watcher["user_id"]
        usd_value = signal.get("usd_value", 0)

        # Check threshold filters
        min_trade = float(watcher.get("min_trade_usd") or 0)
        if min_trade > 0 and usd_value < min_trade:
            continue

        alert_on_buy = watcher.get("alert_on_buy", True)
        if not alert_on_buy:
            continue

        # Insert notification
        try:
            supabase.schema(SCHEMA_NAME).table("wallet_notifications").insert({
                "user_id": user_id,
                "wallet_address": wallet_address,
                "notification_type": "buy",
                "title": f"BUY: {signal['token_ticker']}",
                "message": f"${usd_value:.2f} buy via Helius webhook",
                "metadata": {
                    "token_address": signal["token_address"],
                    "tx_hash": signal["tx_hash"],
                    "usd_value": usd_value,
                    "source": "helius_webhook",
                    "sol_amount": signal.get("sol_amount", 0),
                },
            }).execute()
            notifications_created += 1
        except Exception as e:
            logger.error("[HELIUS] action=create_notification status=failed user=%s error=%s", user_id[:8], str(e)[:200])

        # Send Telegram alert
        if telegram_notifier:
            try:
                telegram_notifier.send_wallet_alert(
                    user_id=user_id,
                    alert_type="trade",
                    data={
                        "wallet_address": wallet_address,
                        "side": "buy",
                        "token_ticker": signal["token_ticker"],
                        "token_address": signal["token_address"],
                        "usd_value": usd_value,
                        "tx_hash": signal["tx_hash"],
                    },
                )
            except Exception as e:
                logger.error("[HELIUS] action=telegram_alert status=failed user=%s error=%s", user_id[:8], str(e)[:200])

    if notifications_created > 0:
        logger.info("[HELIUS] action=notify wallet=%s notifications=%d", wallet_address[:8], notifications_created)
    elif watchers:
        alert(P1, "HELIUS", f"Signal received but 0 notifications created for {len(watchers)} watchers",
              details={"wallet": wallet_address, "token": signal.get("token_ticker")})

    # Record paper trades for eligible users
    _maybe_record_paper_trades(signal, watchers)


def _maybe_record_paper_trades(signal: Dict[str, Any], watchers: List[Dict]) -> None:
    """Record paper trades for users with auto-trading enabled."""
    try:
        from services.paper_trading_manager import get_paper_trading_manager
        ptm = get_paper_trading_manager()

        if ptm.is_kill_switch_active():
            return

        usd_value = float(signal.get("usd_value", 0))
        if usd_value < 50:
            return

        token_address = signal["token_address"]
        token_symbol = signal["token_ticker"]
        wallet_address = signal["wallet_address"]
        # Estimate price per token (rough: use sol_amount as proxy)
        sol_amount = signal.get("sol_amount", 0)
        price = (usd_value / sol_amount) if sol_amount > 0 else 0

        for watcher in watchers:
            user_id = watcher["user_id"]
            # Only record paper trades for users with auto-trade enabled
            if not watcher.get("auto_trade_enabled"):
                continue
            try:
                ptm.record_trade(
                    user_id=user_id,
                    token_address=token_address,
                    token_symbol=token_symbol,
                    side="buy",
                    amount_usd=usd_value,
                    price_per_token=price,
                    trigger_wallet=wallet_address,
                    trigger_type="auto_elite",
                )
            except Exception as e:
                logger.error("[HELIUS] action=paper_trade status=failed user=%s error=%s", user_id[:8], str(e)[:200])

    except Exception as e:
        logger.error("[HELIUS] action=paper_trade_module status=failed error=%s", str(e)[:200])


@helius_bp.route("/api/webhooks/helius", methods=["POST"])
def helius_wallet_alert():
    """
    Helius webhook endpoint for enhanced transaction events.
    Always returns 200 to prevent Helius from retrying.
    """
    auth_header = request.headers.get("Authorization", "")
    if not _verify_secret(auth_header):
        logger.warning("[HELIUS] Invalid webhook secret")
        alert(P0, "HELIUS", "Unauthorized webhook request received",
              details={"ip": request.remote_addr, "auth_header_present": bool(auth_header)})
        return jsonify({"status": "unauthorized"}), 200  # Still 200 to avoid retries

    try:
        payload = request.get_json(silent=True) or []
        # Helius sends an array of enhanced transaction objects
        events = payload if isinstance(payload, list) else [payload]

        signals_processed = 0
        for event in events:
            signal = _extract_swap_signal(event)
            if signal:
                _process_signal(signal)
                signals_processed += 1

        logger.info("[HELIUS] action=process signals=%d events=%d", signals_processed, len(events))

    except Exception as e:
        logger.error("[HELIUS] action=process status=failed error=%s", str(e)[:200])

    return jsonify({"status": "ok"}), 200
