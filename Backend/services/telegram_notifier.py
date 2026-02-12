"""
telegram_notifier.py - Telegram Alert Service

Sends wallet activity alerts to users via Telegram bot.
Handles bot commands, user linking, and message formatting.
"""

import requests
import time
import secrets
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone

from services.supabase_client import get_supabase_client, SCHEMA_NAME

# Setup logging to see errors in console
logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    Service for sending wallet alerts via Telegram bot.
    Handles user linking and alert delivery.
    """
    
    def __init__(self, bot_token: str):
        """Initialize Telegram notifier."""
        self.bot_token = bot_token
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        print(f"[TELEGRAM] Notifier initialized on schema: {self.schema}")
    
    def _table(self, name: str):
        """Get table reference with schema."""
        return self.supabase.schema(self.schema).table(name)
    
    def _make_request(self, method: str, data: dict = None) -> dict:
        """Make request to Telegram Bot API"""
        url = f"{self.base_url}/{method}"
        try:
            response = requests.post(url, json=data, timeout=10)
            return response.json()
        except Exception as e:
            logger.error(f"[TELEGRAM] API error: {e}")
            return {'ok': False, 'error': str(e)}
    
    def send_message(self, chat_id: str, text: str, reply_markup: dict = None) -> bool:
        """Send formatted HTML message to Telegram chat."""
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        
        if reply_markup:
            data['reply_markup'] = reply_markup
        
        result = self._make_request('sendMessage', data)
        return result.get('ok', False)

    # =========================================================================
    # USER LINKING & CONNECTION
    # =========================================================================

    def generate_connection_code(self, user_id: str) -> str:
        """Generate unique 6-char code for user linking (valid for 10 min)."""
        try:
            code = secrets.token_hex(3).upper()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
            
            # 1. Cleanup: Remove any existing unlinked codes for this user
            self._table('telegram_users').delete().eq(
                'user_id', user_id
            ).is_('telegram_chat_id', 'null').execute()
            
            # 2. Insert new code
            self._table('telegram_users').insert({
                'user_id': user_id,
                'connection_code': code,
                'code_expires_at': expires_at.isoformat()
            }).execute()
            
            print(f"[TELEGRAM] Generated code {code} for user {user_id}")
            return code
        except Exception as e:
            logger.error(f"[TELEGRAM] Database Error in generate_connection_code: {e}")
            raise e # Raise to let Flask return the error instead of hanging

    def verify_connection_code(self, code: str, telegram_chat_id: str, 
                               telegram_username: str = None,
                               telegram_first_name: str = None,
                               telegram_last_name: str = None) -> Optional[str]:
        """Verify code and link the Telegram chat ID to the Sifter User."""
        try:
            result = self._table('telegram_users').select('*').eq(
                'connection_code', code
            ).is_('telegram_chat_id', 'null').execute()
            
            if not result.data:
                return None
            
            user_data = result.data[0]
            user_id = user_data['user_id']
            expires_at = datetime.fromisoformat(user_data['code_expires_at'].replace('Z', '+00:00'))
            
            if expires_at < datetime.now(timezone.utc):
                self._table('telegram_users').delete().eq('connection_code', code).execute()
                return None
            
            # Link account
            self._table('telegram_users').update({
                'telegram_chat_id': str(telegram_chat_id),
                'telegram_username': telegram_username,
                'telegram_first_name': telegram_first_name,
                'telegram_last_name': telegram_last_name,
                'connection_code': None,
                'code_expires_at': None,
                'connected_at': datetime.now(timezone.utc).isoformat(),
                'alerts_enabled': True
            }).eq('user_id', user_id).execute()
            
            return user_id
        except Exception as e:
            logger.error(f"[TELEGRAM] Error verifying code: {e}")
            return None

    def get_user_chat_id(self, user_id: str) -> Optional[str]:
        """Fetch active chat_id for a user if alerts are enabled."""
        try:
            result = self._table('telegram_users').select(
                'telegram_chat_id'
            ).eq('user_id', user_id).eq('alerts_enabled', True).execute()
            return result.data[0]['telegram_chat_id'] if result.data else None
        except:
            return None

    def is_user_connected(self, user_id: str) -> bool:
        return self.get_user_chat_id(user_id) is not None

    def disconnect_user(self, user_id: str) -> bool:
        result = self._table('telegram_users').delete().eq('user_id', user_id).execute()
        return len(result.data) > 0

    def toggle_alerts(self, user_id: str, enabled: bool) -> bool:
        result = self._table('telegram_users').update({
            'alerts_enabled': enabled
        }).eq('user_id', user_id).execute()
        return len(result.data) > 0

    # =========================================================================
    # ALERT FORMATTING & DELIVERY
    # =========================================================================

    def send_trade_alert(self, user_id: str, alert_data: Dict) -> bool:
        """Formatted alert for individual wallet trades."""
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id: return False
        
        w, a, t, tr = alert_data['wallet'], alert_data['action'], alert_data['token'], alert_data['trade']
        emoji = "🟢" if a == 'buy' else "🔴"
        
        msg = (
            f"{emoji} <b>WALLET ALERT - Pos #{w.get('position', '?')}</b>\n\n"
            f"<b>Wallet:</b> <code>{w['address'][:8]}...{w['address'][-6:]}</code>\n"
            f"<b>Tier:</b> {w.get('tier', 'C')} | Score: {w.get('professional_score', 0)}\n\n"
            f"<b>ACTION: {a.upper()} ${t['symbol']}</b>\n"
            f"<b>Amount:</b> ${tr['amount_usd']:,.2f}\n"
            f"<b>Price:</b> ${tr['price']:.8f}\n\n"
            f"📊 ROI (30d): {w.get('roi_30d', 0)}% | {w.get('runners_30d', 0)} runners"
        )
        
        buttons = {'inline_keyboard': [
            [{'text': '📋 Copy Photon', 'callback_data': f'copy_photon:{t["address"]}'},
             {'text': '📋 Copy Bonkbot', 'callback_data': f'copy_bonkbot:{t["address"]}'}],
            [{'text': '📊 View Chart', 'url': alert_data.get('chart_url', f'https://dexscreener.com/solana/{t["address"]}')},
             {'text': '❌ Dismiss', 'callback_data': 'dismiss'}]
        ]}
        return self.send_message(chat_id, msg, buttons)

    def send_multi_wallet_signal_alert(self, user_id: str, signal: Dict) -> bool:
        """Alert when multiple wallets in your watchlist buy the same token."""
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id: return False

        count = signal['wallet_count']
        addr = signal['token_address']
        strength = signal['signal_strength']
        
        emoji = "🔥🔥🔥" if strength >= 9 else "🔥🔥" if strength >= 6 else "🔥"
        
        wallets_text = "\n".join([f"• {w['tier']}-Tier ({w['wallet'][:6]}...)" for w in signal['wallets'][:5]])
        
        msg = (
            f"{emoji} <b>MULTI-WALLET SIGNAL ({strength}/10)</b>\n\n"
            f"<b>{count} wallets</b> just bought the same token!\n"
            f"🎯 Token: <code>{addr}</code>\n\n"
            f"<b>Wallets Involved:</b>\n{wallets_text}\n\n"
            f"⚠️ <i>Significant accumulation detected in a short window.</i>"
        )
        
        buttons = {'inline_keyboard': [[
            {'text': '📊 DexScreener', 'url': f'https://dexscreener.com/solana/{addr}'},
            {'text': '📋 Copy Address', 'callback_data': f'copy_token:{addr}'}
        ]]}
        return self.send_message(chat_id, msg, buttons)

    # =========================================================================
    # BOT UPDATE HANDLERS (MESSAGE & CALLBACK)
    # =========================================================================

    def process_bot_updates(self, updates: List[dict]):
        """Entry point for Webhook or Polling updates."""
        for update in updates:
            if 'message' in update:
                self._handle_message(update['message'])
            elif 'callback_query' in update:
                self._handle_callback(update['callback_query'])

    def _handle_message(self, message: dict):
        chat_id = str(message['chat']['id'])
        text = message.get('text', '').strip()
        
        if text == '/start':
            self.send_message(chat_id, (
                "👋 <b>Welcome to Sifter KYS!</b>\n\n"
                "To connect, click 'Generate Code' in your dashboard and paste it here."
            ))
        elif len(text) == 6 and text.isalnum():
            user_id = self.verify_connection_code(
                text.upper(), chat_id, 
                message['from'].get('username'),
                message['from'].get('first_name')
            )
            if user_id:
                self.send_message(chat_id, "✅ <b>Success!</b> Your account is now linked.")
            else:
                self.send_message(chat_id, "❌ <b>Invalid or Expired Code.</b>")

    def _handle_callback(self, query: dict):
        data = query['data']
        chat_id = str(query['from']['id'])
        
        if data.startswith('copy_photon:'):
            addr = data.split(':')[1]
            self.send_message(chat_id, f"📋 <b>Photon:</b>\n<code>/buy {addr}</code>")
        elif data == 'dismiss':
            self._make_request('deleteMessage', {
                'chat_id': chat_id, 
                'message_id': query['message']['message_id']
            })
        
        self._make_request('answerCallbackQuery', {'callback_query_id': query['id']})