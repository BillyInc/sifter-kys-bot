"""Telegram integration routes."""
from flask import Blueprint, request, jsonify
import os

from auth import require_auth
from services.telegram_notifier import TelegramNotifier

telegram_bp = Blueprint('telegram', __name__, url_prefix='/api/telegram')

# Initialize Telegram notifier
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
telegram_notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None


def _get_user_id() -> str | None:
    """Get user ID from auth or request."""
    return getattr(request, 'user_id', None)


@telegram_bp.route('/status', methods=['GET'])
@require_auth
def get_telegram_status():
    """Check if user has Telegram connected."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503
    
    user_id = _get_user_id() or request.args.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    
    is_connected = telegram_notifier.is_user_connected(user_id)
    chat_id = telegram_notifier.get_user_chat_id(user_id) if is_connected else None
    
    return jsonify({
        'success': True,
        'connected': is_connected,
        'chat_id': chat_id
    }), 200


@telegram_bp.route('/connect/code', methods=['POST'])
@require_auth
def generate_connection_code():
    """Generate connection code for linking Telegram account."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503
    
    data = request.json or {}
    user_id = _get_user_id() or data.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    
    # Generate code
    code = telegram_notifier.generate_connection_code(user_id)
    
    return jsonify({
        'success': True,
        'code': code,
        'expires_in': 600,  # 10 minutes
        'instructions': [
            'Open Telegram',
            'Search for @YourBotName',  # TODO: Update with actual bot name
            'Send /start',
            'Send this code'
        ]
    }), 200


@telegram_bp.route('/disconnect', methods=['POST'])
@require_auth
def disconnect_telegram():
    """Disconnect Telegram account."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503
    
    data = request.json or {}
    user_id = _get_user_id() or data.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    
    success = telegram_notifier.disconnect_user(user_id)
    
    if success:
        return jsonify({
            'success': True,
            'message': 'Telegram disconnected'
        }), 200
    else:
        return jsonify({
            'success': False,
            'error': 'No Telegram connection found'
        }), 404


@telegram_bp.route('/alerts/toggle', methods=['POST'])
@require_auth
def toggle_telegram_alerts():
    """Enable/disable Telegram alerts."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503
    
    data = request.json or {}
    user_id = _get_user_id() or data.get('user_id')
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


@telegram_bp.route('/test', methods=['POST'])
@require_auth
def send_test_alert():
    """Send test alert to user's Telegram."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503
    
    data = request.json or {}
    user_id = _get_user_id() or data.get('user_id')
    
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
    
    import time
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
    Webhook endpoint for Telegram bot updates.
    Configure this URL in BotFather as your webhook.
    """
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503
    
    update = request.json
    
    if not update:
        return jsonify({'error': 'No update data'}), 400
    
    try:
        # Process single update
        telegram_notifier.process_bot_updates([update])
        return jsonify({'ok': True}), 200
    except Exception as e:
        print(f"[TELEGRAM WEBHOOK] Error: {e}")
        return jsonify({'error': str(e)}), 500


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