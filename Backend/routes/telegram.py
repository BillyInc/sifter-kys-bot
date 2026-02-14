"""Telegram integration routes."""
from flask import Blueprint, request, jsonify
import os
import threading
import time
import requests
import secrets
from datetime import datetime, timedelta, timezone

from auth import require_auth, optional_auth
from services.telegram_notifier import TelegramNotifier
from services.supabase_client import get_supabase_client, SCHEMA_NAME

telegram_bp = Blueprint('telegram', __name__)

# Initialize Telegram notifier
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
telegram_notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None


def _get_user_id() -> str | None:
    """Get user ID from auth or request."""
    return getattr(request, 'user_id', None)


@telegram_bp.route('/status', methods=['GET', 'OPTIONS'])
@optional_auth
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


@telegram_bp.route('/connect/link', methods=['POST', 'OPTIONS'])
@optional_auth
def generate_connection_link():
    """Generate Telegram deep link for one-click connection."""
    if not telegram_notifier:
        return jsonify({'error': 'Telegram not configured'}), 503
    
    data = request.json or {}
    user_id = _get_user_id() or data.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    
    try:
        # Generate unique connection token
        connection_token = secrets.token_urlsafe(32)
        
        # Store token in database with 15-minute expiry
        supabase = get_supabase_client()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        
        # Clean up old unused tokens for this user
        supabase.schema(SCHEMA_NAME).table('telegram_connection_tokens').delete().eq(
            'user_id', user_id
        ).eq('used', False).execute()
        
        # Insert new token
        supabase.schema(SCHEMA_NAME).table('telegram_connection_tokens').insert({
            'user_id': user_id,
            'token': connection_token,
            'expires_at': expires_at,
            'used': False
        }).execute()
        
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
        return jsonify({'error': str(e)}), 500


@telegram_bp.route('/disconnect', methods=['POST', 'OPTIONS'])
@optional_auth
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


@telegram_bp.route('/test', methods=['POST', 'OPTIONS'])
@optional_auth
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
    
    # Verify secret token (if set)
    secret_token = os.environ.get('TELEGRAM_SECRET_TOKEN')
    if secret_token:
        header_token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if header_token != secret_token:
            print("[TELEGRAM WEBHOOK] ⚠️ Invalid secret token")
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