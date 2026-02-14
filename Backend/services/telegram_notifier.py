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

# Setup logging
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
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        
        print(f"[TELEGRAM] ✅ Notifier ready (polling disabled for now)")
    
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
    # USER LINKING & CONNECTION (TOKEN-BASED)
    # =========================================================================

    def verify_connection_token(self, token: str, telegram_chat_id: str, 
                                telegram_username: str = None,
                                telegram_first_name: str = None,
                                telegram_last_name: str = None) -> Optional[str]:
        """Verify connection token and link Telegram account."""
        try:
            # Find the token
            result = self._table('telegram_connection_tokens').select('*').eq(
                'token', token
            ).eq('used', False).execute()
            
            if not result.data:
                print(f"[TELEGRAM] ❌ Token not found or already used: {token[:8]}...")
                return None
            
            token_data = result.data[0]
            user_id = token_data['user_id']
            
            # Check if expired
            expires_at = datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
            if expires_at < datetime.now(timezone.utc):
                print(f"[TELEGRAM] ❌ Token expired: {token[:8]}...")
                self._table('telegram_connection_tokens').delete().eq('token', token).execute()
                return None
            
            # Mark token as used
            self._table('telegram_connection_tokens').update({
                'used': True,
                'telegram_id': int(telegram_chat_id)
            }).eq('token', token).execute()
            
            # Check if user already has Telegram linked
            existing = self._table('telegram_users').select('*').eq(
                'user_id', user_id
            ).execute()
            
            if existing.data:
                # Update existing connection
                self._table('telegram_users').update({
                    'telegram_chat_id': str(telegram_chat_id),
                    'telegram_username': telegram_username,
                    'telegram_first_name': telegram_first_name,
                    'telegram_last_name': telegram_last_name,
                    'connected_at': datetime.now(timezone.utc).isoformat(),
                    'alerts_enabled': True
                }).eq('user_id', user_id).execute()
            else:
                # Create new connection
                self._table('telegram_users').insert({
                    'user_id': user_id,
                    'telegram_chat_id': str(telegram_chat_id),
                    'telegram_username': telegram_username,
                    'telegram_first_name': telegram_first_name,
                    'telegram_last_name': telegram_last_name,
                    'connected_at': datetime.now(timezone.utc).isoformat(),
                    'alerts_enabled': True
                }).execute()
            
            print(f"[TELEGRAM] ✅ User {user_id[:8]}... linked to chat {telegram_chat_id}")
            return user_id
            
        except Exception as e:
            logger.error(f"[TELEGRAM] Error verifying token: {e}")
            import traceback
            traceback.print_exc()
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
        """Check if user has active Telegram connection."""
        return self.get_user_chat_id(user_id) is not None

    def disconnect_user(self, user_id: str) -> bool:
        """Disconnect user's Telegram account."""
        try:
            result = self._table('telegram_users').delete().eq('user_id', user_id).execute()
            return len(result.data) > 0
        except:
            return False

    def toggle_alerts(self, user_id: str, enabled: bool) -> bool:
        """Enable/disable alerts for user."""
        try:
            result = self._table('telegram_users').update({
                'alerts_enabled': enabled
            }).eq('user_id', user_id).execute()
            return len(result.data) > 0
        except:
            return False

    # =========================================================================
    # ALERT FORMATTING & DELIVERY
    # =========================================================================

    def send_trade_alert(self, user_id: str, trades: List[Dict]) -> bool:
        """Sends a single or multi-wallet formatted trade alert."""
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False
        
        is_multi = len(trades) > 1
        t = trades[0]['trade']
        ca = t.get('token_address')
        total_usd = sum(item['trade']['amount_usd'] for item in trades)
        
        # UI Layout with Single Wallet Fallback
        header = "🚨 <b>MULTI-WALLET SIGNAL</b>" if is_multi else "🔥 <b>Tier S Wallet Activity</b>"
        
        msg = (
            f"{header}\n\n"
            f"<b>Token:</b> ${t.get('symbol')}\n"
            f"<b>Total Buy:</b> ${total_usd:,.2f}\n"
            f"<b>CA:</b> <code>{ca}</code>\n\n"
        )
        
        if is_multi:
            msg += "<b>Wallets:</b>\n" + "\n".join([
                f"• {x['wallet']['address'][:6]}... (Tier {x['wallet']['tier']})" 
                for x in trades
            ])
        else:
            msg += f"<b>Wallet:</b> <code>{trades[0]['wallet']['address']}</code>"
        
        buttons = {
            'inline_keyboard': [
                [
                    {'text': '🤖 Photon', 'callback_data': f'cp_p:{ca}'},
                    {'text': '🤖 Bonkbot', 'callback_data': f'cp_b:{ca}'}
                ],
                [{'text': '📊 View Chart', 'url': f'https://dexscreener.com/solana/{ca}'}]
            ]
        }
        
        return self._make_request('sendMessage', {
            'chat_id': chat_id,
            'text': msg,
            'parse_mode': 'HTML',
            'reply_markup': buttons
        }).get('ok', False)

    def send_wallet_alert(self, user_id: str, alert_data: Dict, activity_id: int = None) -> bool:
        """Legacy method for backward compatibility."""
        trades = [{
            'wallet': alert_data.get('wallet', {}),
            'trade': alert_data.get('trade', {})
        }]
        return self.send_trade_alert(user_id, trades)

    # =========================================================================
    # BOT UPDATE HANDLERS
    # =========================================================================

    def process_bot_updates(self, updates: List[dict]):
        """Entry point for Webhook or Polling updates."""
        for update in updates:
            if 'message' in update:
                self._handle_message(update['message'])
            elif 'callback_query' in update:
                self._handle_callback(update['callback_query'])

    def _handle_message(self, message: dict):
        """Handle incoming messages from users."""
        chat_id = str(message['chat']['id'])
        text = message.get('text', '').strip()
        
        # Handle /start with connection token (deep link)
        if text.startswith('/start '):
            connection_token = text.split(' ', 1)[1]
            
            user_id = self.verify_connection_token(
                connection_token, 
                chat_id,
                message['from'].get('username'),
                message['from'].get('first_name'),
                message['from'].get('last_name')
            )
            
            if user_id:
                self.send_message(chat_id, (
                    "✅ <b>Connection Successful!</b>\n\n"
                    "Your Sifter account is now linked.\n"
                    "You'll receive alerts for:\n"
                    "• Smart money wallet activity\n"
                    "• Multi-wallet signals\n"
                    "• Trending runners\n\n"
                    "Use /settings to configure your preferences."
                ))
            else:
                self.send_message(chat_id, (
                    "❌ <b>Verification Failed</b>\n\n"
                    "The connection link may have expired (valid for 15 minutes).\n"
                    "Please generate a new link from your Sifter dashboard."
                ))
            return
        
        # Handle /start without token
        if text == '/start':
            self.send_message(chat_id, (
                "👋 <b>Welcome to Sifter KYS Bot!</b>\n\n"
                "To connect your account:\n"
                "1. Go to your Sifter dashboard\n"
                "2. Navigate to Settings → Telegram\n"
                "3. Click 'Connect Telegram'\n"
                "4. You'll be redirected here automatically\n\n"
                "<b>Commands:</b>\n"
                "/settings - Configure alert preferences\n"
                "/help - Show help message"
            ))
            return
        
        # Handle /help
        if text == '/help':
            self.send_message(chat_id, (
                "📚 <b>Sifter KYS Bot Help</b>\n\n"
                "<b>Commands:</b>\n"
                "/start - Start the bot\n"
                "/settings - Configure alerts\n"
                "/help - Show this message\n\n"
                "<b>Features:</b>\n"
                "• Real-time wallet activity alerts\n"
                "• Multi-wallet signal detection\n"
                "• One-click trading bot integration\n"
                "• Customizable alert thresholds\n\n"
                "Connect your account from the Sifter dashboard to get started!"
            ))
            return
        
        # Handle /settings
        if text == '/settings':
            # Get user_id from telegram_chat_id
            try:
                result = self._table('telegram_users').select('user_id').eq(
                    'telegram_chat_id', chat_id
                ).limit(1).execute()
                
                if result.data:
                    user_id = result.data[0]['user_id']
                    self.show_settings(chat_id, user_id)
                else:
                    self.send_message(chat_id, (
                        "❌ <b>Not Connected</b>\n\n"
                        "Please link your Sifter account first.\n"
                        "Go to Settings → Telegram in your dashboard."
                    ))
            except Exception as e:
                logger.error(f"[TELEGRAM] Error in /settings: {e}")
                self.send_message(chat_id, "❌ <b>Error loading settings.</b>")

    def _handle_callback(self, query: dict):
        """Handle button clicks from inline keyboards."""
        query_id = query['id']
        chat_id = str(query['from']['id'])
        data = query['data']
        
        # Handle trade copy buttons (Photon/Bonkbot)
        if data.startswith('cp_p:') or data.startswith('cp_b:'):
            ca = data.split(':', 1)[1]
            bot_type = "Photon" if "cp_p:" in data else "Bonkbot"
            cmd = f"/buy {ca}" if bot_type == "Photon" else f"{ca}"
            
            # Show toast notification
            self._make_request('answerCallbackQuery', {
                'callback_query_id': query_id,
                'text': f"✅ {bot_type} command ready!",
                'show_alert': False
            })
            
            # Send copyable command
            self._make_request('sendMessage', {
                'chat_id': chat_id,
                'text': f"<code>{cmd}</code>",
                'parse_mode': 'HTML'
            })
        else:
            # Acknowledge callback
            self._make_request('answerCallbackQuery', {'callback_query_id': query_id})

    def show_settings(self, chat_id: str, user_id: str) -> bool:
        """Show settings menu (placeholder for future expansion)."""
        msg = (
            "⚙️ <b>Settings</b>\n\n"
            "Alert status: <b>Enabled</b>\n"
            "Minimum trade: <b>$10 USD</b>\n\n"
            "More settings coming soon!"
        )
        
        return self.send_message(chat_id, msg)

    # Legacy methods for backward compatibility
    def generate_connection_code(self, user_id: str) -> str:
        """Legacy method - now handled by routes."""
        return secrets.token_hex(3).upper()

    def send_raw_message(self, chat_id: str, text: str, reply_markup: dict = None) -> bool:
        """Alias for send_message."""
        return self.send_message(chat_id, text, reply_markup)