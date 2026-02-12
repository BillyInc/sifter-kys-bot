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
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        
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

    def send_raw_message(self, chat_id: str, text: str, reply_markup: dict = None) -> bool:
        """Alias for send_message - for backward compatibility."""
        return self.send_message(chat_id, text, reply_markup)

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

    def send_wallet_alert(self, user_id: str, alert_data: Dict, activity_id: int = None) -> bool:
        """Formatted alert for individual wallet trades (legacy method for backward compatibility)."""
        # Convert to new format and use send_trade_alert
        trades = [{
            'wallet': alert_data.get('wallet', {}),
            'trade': alert_data.get('trade', {})
        }]
        return self.send_trade_alert(user_id, trades)

    # =========================================================================
    # SETTINGS MANAGEMENT
    # =========================================================================

    def get_user_settings(self, user_id: str) -> Dict:
        """Fetch user settings from database."""
        try:
            result = self._table('user_settings').select(
                'min_buy_usd, preferred_bot'
            ).eq('user_id', user_id).limit(1).execute()
            
            if result.data:
                return result.data[0]
            return {'min_buy_usd': 50.0, 'preferred_bot': 'photon'}
        except Exception as e:
            logger.error(f"[TELEGRAM] Error fetching user settings: {e}")
            return {'min_buy_usd': 50.0, 'preferred_bot': 'photon'}

    def update_user_bot_pref(self, user_id: str, bot: str) -> bool:
        """Update user's preferred bot."""
        try:
            # Check if settings exist
            existing = self._table('user_settings').select('user_id').eq(
                'user_id', user_id
            ).limit(1).execute()
            
            if existing.data:
                # Update existing
                self._table('user_settings').update({
                    'preferred_bot': bot
                }).eq('user_id', user_id).execute()
            else:
                # Insert new
                self._table('user_settings').insert({
                    'user_id': user_id,
                    'preferred_bot': bot,
                    'min_buy_usd': 50.0
                }).execute()
            
            return True
        except Exception as e:
            logger.error(f"[TELEGRAM] Error updating bot preference: {e}")
            return False

    def update_min_buy(self, user_id: str, min_buy_usd: float) -> bool:
        """Update user's minimum buy threshold."""
        try:
            # Check if settings exist
            existing = self._table('user_settings').select('user_id').eq(
                'user_id', user_id
            ).limit(1).execute()
            
            if existing.data:
                # Update existing
                self._table('user_settings').update({
                    'min_buy_usd': min_buy_usd
                }).eq('user_id', user_id).execute()
            else:
                # Insert new
                self._table('user_settings').insert({
                    'user_id': user_id,
                    'min_buy_usd': min_buy_usd,
                    'preferred_bot': 'photon'
                }).execute()
            
            return True
        except Exception as e:
            logger.error(f"[TELEGRAM] Error updating min buy: {e}")
            return False

    def show_settings(self, chat_id: str, user_id: str) -> bool:
        """Interactive settings menu with toggle buttons."""
        settings = self.get_user_settings(user_id)
        pref = settings.get('preferred_bot', 'photon')
        
        # UI Toggles using Emojis
        p_tick = "✅ " if pref == 'photon' else ""
        b_tick = "✅ " if pref == 'bonkbot' else ""
        
        msg = (
            f"⚙️ <b>Settings</b>\n\n"
            f"Min Buy Alert: ${settings.get('min_buy_usd', 50)} USD\n"
            f"Default Bot: {pref.capitalize()}"
        )
        
        buttons = {
            'inline_keyboard': [
                [
                    {'text': f"{p_tick}Photon", 'callback_data': 'set_bot:photon'},
                    {'text': f"{b_tick}Bonkbot", 'callback_data': 'set_bot:bonkbot'}
                ],
                [{'text': "💰 Change Min Buy", 'callback_data': 'set_min_buy'}]
            ]
        }
        
        return self._make_request('sendMessage', {
            'chat_id': chat_id,
            'text': msg,
            'parse_mode': 'HTML',
            'reply_markup': buttons
        }).get('ok', False)

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
        
        # Handle replies to Min Buy prompt
        if 'reply_to_message' in message:
            replied_to_text = message['reply_to_message'].get('text', '')
            if "Enter new Min Buy" in replied_to_text:
                try:
                    # Get user_id from telegram_chat_id
                    result = self._table('telegram_users').select('user_id').eq(
                        'telegram_chat_id', chat_id
                    ).limit(1).execute()
                    
                    if result.data:
                        user_id = result.data[0]['user_id']
                        new_val = float(text.replace('$', '').replace(',', '').strip())
                        
                        if new_val < 0:
                            self.send_message(chat_id, "❌ <b>Amount must be positive.</b>")
                            return
                        
                        self.update_min_buy(user_id, new_val)
                        self.send_message(chat_id, f"✅ <b>Threshold set to ${new_val:,.2f}</b>")
                        self.show_settings(chat_id, user_id)
                    else:
                        self.send_message(chat_id, "❌ <b>Not connected.</b>")
                except ValueError:
                    self.send_message(chat_id, "❌ <b>Invalid number. Try again.</b>")
                return
        
        if text == '/start':
            self.send_message(chat_id, (
                "👋 <b>Welcome to Sifter KYS!</b>\n\n"
                "To connect, click 'Generate Code' in your dashboard and paste it here.\n\n"
                "Commands:\n"
                "/settings - Configure your alerts\n"
                "/help - Show this message"
            ))
        elif text == '/settings':
            # Get user_id from telegram_chat_id
            try:
                result = self._table('telegram_users').select('user_id').eq(
                    'telegram_chat_id', chat_id
                ).limit(1).execute()
                
                if result.data:
                    user_id = result.data[0]['user_id']
                    self.show_settings(chat_id, user_id)
                else:
                    self.send_message(chat_id, "❌ <b>Not connected.</b> Please link your account first.")
            except Exception as e:
                logger.error(f"[TELEGRAM] Error in /settings: {e}")
                self.send_message(chat_id, "❌ <b>Error loading settings.</b>")
        elif text == '/help':
            self.send_message(chat_id, (
                "👋 <b>Sifter KYS Bot</b>\n\n"
                "<b>Commands:</b>\n"
                "/start - Start the bot\n"
                "/settings - Configure alerts\n"
                "/help - Show this message\n\n"
                "To link your account, generate a code in the dashboard and send it here."
            ))
        elif len(text) == 6 and text.isalnum():
            user_id = self.verify_connection_code(
                text.upper(), chat_id, 
                message['from'].get('username'),
                message['from'].get('first_name')
            )
            if user_id:
                self.send_message(chat_id, "✅ <b>Success!</b> Your account is now linked.\n\nUse /settings to configure your alerts.")
            else:
                self.send_message(chat_id, "❌ <b>Invalid or Expired Code.</b>")

    def _handle_callback(self, query: dict):
        """The 'Toast' Feedback and Auto-Copy Command."""
        query_id = query['id']
        chat_id = str(query['from']['id'])
        data = query['data']
        
        # Get user_id for settings callbacks
        user_id = None
        try:
            result = self._table('telegram_users').select('user_id').eq(
                'telegram_chat_id', chat_id
            ).limit(1).execute()
            if result.data:
                user_id = result.data[0]['user_id']
        except:
            pass
        
        # 1. Handle Trade Copy Buttons
        if data.startswith('cp_p:') or data.startswith('cp_b:'):
            ca = data.split(':', 1)[1]
            bot_type = "Photon" if "cp_p:" in data else "Bonkbot"
            cmd = f"/buy {ca}" if bot_type == "Photon" else f"{ca}"
            
            # Trigger Top-Bar Toast
            self._make_request('answerCallbackQuery', {
                'callback_query_id': query_id,
                'text': f"✅ {bot_type} command ready! Tap below.",
                'show_alert': False
            })
            
            # Send Tappable Command
            self._make_request('sendMessage', {
                'chat_id': chat_id,
                'text': f"<code>{cmd}</code>",
                'parse_mode': 'HTML'
            })
        
        # 2. Handle Settings Toggles
        elif data.startswith('set_bot:'):
            new_bot = data.split(':')[1]
            if user_id:
                self.update_user_bot_pref(user_id, new_bot)
                self._make_request('answerCallbackQuery', {
                    'callback_query_id': query_id,
                    'text': f"✅ Default bot: {new_bot.capitalize()}",
                    'show_alert': False
                })
                # Refresh the settings menu to show the new checkmark
                self.show_settings(chat_id, user_id)
            else:
                self._make_request('answerCallbackQuery', {
                    'callback_query_id': query_id,
                    'text': "❌ Not connected",
                    'show_alert': True
                })
        
        elif data == 'set_min_buy' or data == 'prompt_min_buy':
            self._make_request('answerCallbackQuery', {'callback_query_id': query_id})
            # Send message with force reply to capture user's numeric input
            self._make_request('sendMessage', {
                'chat_id': chat_id,
                'text': "⌨️ <b>Enter new Min Buy USD amount</b>\n\nExample: 100",
                'parse_mode': 'HTML',
                'reply_markup': {'force_reply': True}
            })
        
        # Handle legacy callback formats
        elif data.startswith('copy_p:') or data.startswith('copy_b:'):
            bot_type = "Photon" if data.startswith('copy_p:') else "Bonkbot"
            ca = data.split(':', 1)[1]
            cmd = f"/buy {ca}" if bot_type == "Photon" else f"{ca}"
            
            self._make_request('answerCallbackQuery', {
                'callback_query_id': query_id,
                'text': f"✅ {bot_type} command ready! Tap below to copy.",
                'show_alert': False
            })
            
            self._make_request('sendMessage', {
                'chat_id': chat_id,
                'text': f"<code>{cmd}</code>",
                'parse_mode': 'HTML'
            })
        elif data.startswith('copy_photon:'):
            addr = data.split(':')[1]
            self._make_request('answerCallbackQuery', {
                'callback_query_id': query_id,
                'text': "✅ Photon command ready! Tap below to copy.",
                'show_alert': False
            })
            self.send_message(chat_id, f"📋 <b>Photon:</b>\n<code>/buy {addr}</code>")
        elif data.startswith('copy_token:'):
            addr = data.split(':')[1]
            self._make_request('answerCallbackQuery', {
                'callback_query_id': query_id,
                'text': "✅ Address copied!",
                'show_alert': False
            })
            self.send_message(chat_id, f"📋 <b>Token Address:</b>\n<code>{addr}</code>")
        elif data == 'dismiss':
            self._make_request('deleteMessage', {
                'chat_id': chat_id, 
                'message_id': query['message']['message_id']
            })
            self._make_request('answerCallbackQuery', {'callback_query_id': query_id})
        else:
            self._make_request('answerCallbackQuery', {'callback_query_id': query_id})

    def handle_callback(self, query: Dict):
        """Public method for handling callbacks (for backward compatibility)."""
        self._handle_callback(query)