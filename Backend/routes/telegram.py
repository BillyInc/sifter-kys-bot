"""Telegram integration routes."""
import logging
from flask import Blueprint, request, jsonify
import os
import threading
import time
import requests
import secrets
from datetime import datetime, timedelta, timezone
from routes import anon_user_id

logger = logging.getLogger(__name__)

from auth import require_auth, optional_auth
from services.supabase_client import is_supabase_available
from services.telegram_notifier import TelegramNotifier
from repositories.registry import get_telegram_repo

telegram_bp = Blueprint('telegram', __name__)

# Initialize Telegram notifier
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
telegram_notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None


def _get_user_id() -> str | None:
    """Get user ID from auth or request."""
    return getattr(request, 'user_id', None)


def _operator_error():
    user_id = _get_user_id()
    if not is_supabase_available() and not user_id:
        return None
    from services.paper_trade_runtime import is_operator_user

    if is_operator_user(user_id):
        return None
    return jsonify({'error': 'Operator access required'}), 403


def _get_paper_trader():
    try:
        from flask import current_app
        trader = current_app.config.get('PAPER_TRADER')
        if trader:
            return trader
    except Exception:
        pass
    from services.paper_trader import PaperTrader
    return PaperTrader()


@telegram_bp.route('/status', methods=['GET', 'OPTIONS'])
@optional_auth
def get_telegram_status():
    """Check if user has Telegram connected."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503

    user_id = _get_user_id() or anon_user_id()

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    is_connected = telegram_notifier.is_user_connected(user_id)
    chat_id = telegram_notifier.get_user_chat_id(user_id) if is_connected else None

    return jsonify({
        'success': True,
        'connected': is_connected,
        'chat_id': chat_id
    }), 200


@telegram_bp.route('/connect/link', methods=['POST', 'OPTIONS'])
@optional_auth
def generate_connection_link():
    """Generate Telegram deep link for one-click connection."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503

    data = request.json or {}
    user_id = _get_user_id() or anon_user_id()

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    try:
        # Generate unique connection token
        connection_token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

        repo = get_telegram_repo()

        # Clean up old unused tokens for this user
        repo.delete_unused_tokens(user_id)

        # Insert new token
        repo.create_connection_token(user_id, connection_token, expires_at)

        # Get bot username from environment or config
        bot_username = os.environ.get('TELEGRAM_BOT_USERNAME', 'SifterDueDiligenceBot')

        # Create Telegram deep link
        telegram_link = f"https://t.me/{bot_username}?start={connection_token}"

        print(f"[TELEGRAM] Generated connection link for user {user_id[:8]}...")

        return jsonify({
            'success': True,
            'telegram_link': telegram_link,
            'connection_token': connection_token,
            'expires_in': 900  # 15 minutes in seconds
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


@telegram_bp.route('/disconnect', methods=['POST', 'OPTIONS'])
@optional_auth
def disconnect_telegram():
    """Disconnect Telegram account."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503

    data = request.json or {}
    user_id = _get_user_id() or anon_user_id()

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    success = telegram_notifier.disconnect_user(user_id)

    if success:
        print(f"[TELEGRAM] Disconnected user {user_id[:8]}...")
        return jsonify({
            'success': True,
            'message': 'Telegram disconnected'
        }), 200
    else:
        return jsonify({
            'success': False,
            'error': 'No Telegram connection found'
        }), 404


@telegram_bp.route('/alerts/toggle', methods=['POST', 'OPTIONS'])
@optional_auth
def toggle_telegram_alerts():
    """Enable/disable Telegram alerts."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503

    data = request.json or {}
    user_id = _get_user_id() or anon_user_id()
    enabled = data.get('enabled', True)

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    success = telegram_notifier.toggle_alerts(user_id, enabled)

    if success:
        return jsonify({
            'success': True,
            'alerts_enabled': enabled
        }), 200
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to update settings'
        }), 500


@telegram_bp.route('/test', methods=['POST', 'OPTIONS'])
@optional_auth
def send_test_alert():
    """Send test alert to user's Telegram."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503

    data = request.json or {}
    user_id = _get_user_id() or anon_user_id()

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    # Check if connected
    if not telegram_notifier.is_user_connected(user_id):
        return jsonify({
            'success': False,
            'error': 'Telegram not connected'
        }), 400

    # Create test alert
    test_alert = {
        'wallet': {
            'address': 'TEST123456789ABCDEFGHIJK',
            'tier': 'S',
            'consistency_score': 8.5
        },
        'action': 'buy',
        'token': {
            'address': 'So11111111111111111111111111111111111111112',
            'symbol': 'SOL',
            'name': 'Solana (TEST)'
        },
        'trade': {
            'amount_usd': 1000,
            'price': 100.50,
            'timestamp': int(time.time())
        },
        'links': {
            'solscan': 'https://solscan.io',
            'birdeye': 'https://birdeye.so',
            'dexscreener': 'https://dexscreener.com'
        }
    }

    success = telegram_notifier.send_wallet_alert(user_id, test_alert, 0)

    if success:
        return jsonify({
            'success': True,
            'message': 'Test alert sent'
        }), 200
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to send test alert'
        }), 500


@telegram_bp.route('/webhook', methods=['POST'])
def telegram_webhook():
    """
    Ultra-fast webhook handler - queues processing immediately
    Responds to Telegram in <50ms
    """
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503

    update = request.json

    if not update:
        return jsonify({'error': 'No update data'}), 400

    # Verify secret token (timing-safe, fail closed if not configured)
    import hmac
    secret_token = os.environ.get('TELEGRAM_SECRET_TOKEN')
    if not secret_token:
        logger.error("[TELEGRAM WEBHOOK] TELEGRAM_SECRET_TOKEN not set — rejecting")
        return jsonify({'error': 'Unauthorized'}), 401
    header_token = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if not hmac.compare_digest(header_token, secret_token):
        logger.warning("[TELEGRAM WEBHOOK] Invalid secret token")
        return jsonify({'error': 'Unauthorized'}), 401

    # Handle callback queries (button clicks)
    if 'callback_query' in update:
        threading.Thread(
            target=telegram_notifier._handle_callback,
            args=(update['callback_query'],),
            daemon=True
        ).start()
        return jsonify({'ok': True}), 200

    # Handle messages
    if 'message' in update:
        # Process in background thread
        threading.Thread(
            target=telegram_notifier.process_bot_updates,
            args=([update],),
            daemon=True
        ).start()
        print(f"[TELEGRAM WEBHOOK] ✓ Update queued")

    # Respond immediately (Telegram requires <1s response)
    return jsonify({'ok': True}), 200


@telegram_bp.route('/bot/info', methods=['GET'])
def get_bot_info():
    """Get information about the Telegram bot."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503

    # Get bot info from Telegram API
    result = telegram_notifier._make_request('getMe')

    if result.get('ok'):
        bot_info = result['result']
        return jsonify({
            'success': True,
            'bot': {
                'username': bot_info.get('username'),
                'first_name': bot_info.get('first_name'),
                'can_join_groups': bot_info.get('can_join_groups'),
                'supports_inline_queries': bot_info.get('supports_inline_queries')
            }
        }), 200
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to fetch bot info'
        }), 500

@telegram_bp.route('/ping', methods=['GET'])
def ping():
    """Simple test endpoint"""
    return jsonify({"pong": True, "message": "Telegram blueprint is alive!"})


@telegram_bp.route('/operator/status', methods=['GET', 'OPTIONS'])
@require_auth
def operator_status():
    error = _operator_error()
    if error:
        return error

    from services.paper_trade_runtime import get_paper_trade_runtime

    trader = _get_paper_trader()
    runtime = get_paper_trade_runtime()
    return jsonify({
        'success': True,
        'status': runtime.get_status(),
        'summary': trader.get_summary(),
        'failure_report': trader.get_failure_report(),
    }), 200


@telegram_bp.route('/operator/paper-trader/start', methods=['POST', 'OPTIONS'])
@require_auth
def operator_start_paper_trader():
    error = _operator_error()
    if error:
        return error

    from services.paper_trade_runtime import get_paper_trade_runtime

    runtime = get_paper_trade_runtime()
    run = runtime.start_run(started_by=_get_user_id(), source='web')
    return jsonify({'success': True, 'run': run, 'status': runtime.get_status()}), 200


@telegram_bp.route('/operator/paper-trader/stop', methods=['POST', 'OPTIONS'])
@require_auth
def operator_stop_paper_trader():
    error = _operator_error()
    if error:
        return error

    from services.paper_trade_runtime import get_paper_trade_runtime

    data = request.json or {}
    runtime = get_paper_trade_runtime()
    run = runtime.stop_run(stopped_by=_get_user_id(), reason=data.get('reason') or 'web')
    return jsonify({'success': True, 'run': run, 'status': runtime.get_status()}), 200


@telegram_bp.route('/operator/paper-trader/test-signal', methods=['POST', 'OPTIONS'])
@require_auth
def operator_test_paper_signal():
    error = _operator_error()
    if error:
        return error

    data = request.json or {}
    token_address = data.get('token_address') or 'So11111111111111111111111111111111111111112'
    now = int(time.time())
    signal = {
        'source': 'elite15',
        'side': 'buy',
        'token_address': token_address,
        'token_ticker': data.get('token_ticker') or 'TEST',
        'signal_key': data.get('signal_key') or f'test:{token_address}:{now}',
        'wallet_count': int(data.get('wallet_count') or 1),
        'total_usd': float(data.get('total_usd') or 250),
        'trades': data.get('trades') or [{'usd_value': float(data.get('total_usd') or 250)}],
        'wallets': data.get('wallets') or [{'wallet': 'operator-test', 'tier': 'S'}],
    }
    trader = _get_paper_trader()
    trader.process_signal(signal)
    return jsonify({
        'success': True,
        'signal': signal,
        'summary': trader.get_summary(),
        'failure_report': trader.get_failure_report(),
    }), 200


@telegram_bp.route('/operator/logs', methods=['GET', 'OPTIONS'])
@require_auth
def operator_logs():
    error = _operator_error()
    if error:
        return error

    from services.paper_trade_runtime import get_paper_trade_runtime

    limit = min(int(request.args.get('limit', 50)), 200)
    severity = request.args.get('severity')
    logs = get_paper_trade_runtime().recent_logs(limit=limit, severity=severity)
    return jsonify({'success': True, 'logs': logs, 'count': len(logs)}), 200


@telegram_bp.route('/operator/failure-report', methods=['GET', 'OPTIONS'])
@require_auth
def operator_failure_report():
    error = _operator_error()
    if error:
        return error

    trader = _get_paper_trader()
    return jsonify({'success': True, 'report': trader.get_failure_report()}), 200


@telegram_bp.route('/operator/settings', methods=['PATCH', 'OPTIONS'])
@require_auth
def operator_patch_settings():
    error = _operator_error()
    if error:
        return error

    from services.paper_trade_runtime import get_paper_trade_runtime

    allowed = {
        'paper_trader_enabled',
        'execution_mode',
        'quote_ttl_seconds',
        'min_liquidity_usd',
        'max_price_impact_bps',
        'default_slippage_bps',
        'default_priority_fee_lamports',
        'max_retry_count',
        'latency_ms',
        'partial_fill_probability',
        'route_failure_probability',
        'no_route_probability',
        'email_digest_enabled',
        'immediate_failure_alerts',
    }
    data = request.json or {}
    patch = {key: data[key] for key in allowed if key in data}
    runtime = get_paper_trade_runtime()
    settings = runtime.patch_settings(patch, updated_by=_get_user_id())
    runtime.log(
        severity='info',
        component='operator',
        event_type='settings_updated',
        status='ok',
        message='Paper trader settings updated',
        payload={'keys': sorted(patch.keys())},
    )
    return jsonify({'success': True, 'settings': settings}), 200


@telegram_bp.route('/operator/email-recipients', methods=['GET', 'PATCH', 'OPTIONS'])
@require_auth
def operator_email_recipients():
    error = _operator_error()
    if error:
        return error

    from services.paper_trade_runtime import get_paper_trade_runtime

    runtime = get_paper_trade_runtime()
    if request.method == 'GET':
        return jsonify({'success': True, 'recipients': runtime.get_email_recipients()}), 200

    data = request.json or {}
    recipients = runtime.replace_email_recipients(data.get('recipients') or [])
    runtime.log(
        severity='info',
        component='operator',
        event_type='email_recipients_updated',
        status='ok',
        message='Paper trader email recipients updated',
        payload={'count': len(recipients)},
    )
    return jsonify({'success': True, 'recipients': recipients}), 200
