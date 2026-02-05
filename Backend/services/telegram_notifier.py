"""
telegram_notifier.py - Telegram Alert Service

Sends wallet activity alerts to users via Telegram bot.
Handles bot commands, user linking, and message formatting.
"""

import requests
import sqlite3
import time
import secrets
from typing import Dict, List, Optional
from datetime import datetime, timedelta


class TelegramNotifier:
    """
    Service for sending wallet alerts via Telegram bot.
    Handles user linking and alert delivery.
    """
    
    def __init__(self, bot_token: str, db_path: str = 'watchlists.db'):
        """
        Initialize Telegram notifier.
        
        Args:
            bot_token: Telegram Bot API token
            db_path: Path to SQLite database
        """
        self.bot_token = bot_token
        self.db_path = db_path
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        print(f"[TELEGRAM] Notifier initialized")
    
    def _make_request(self, method: str, data: dict = None) -> dict:
        """Make request to Telegram Bot API"""
        url = f"{self.base_url}/{method}"
        try:
            response = requests.post(url, json=data, timeout=10)
            return response.json()
        except Exception as e:
            print(f"[TELEGRAM] API error: {e}")
            return {'ok': False, 'error': str(e)}
    
    def send_message(self, chat_id: str, text: str, reply_markup: dict = None) -> bool:
        """
        Send message to Telegram chat.
        
        Args:
            chat_id: Telegram chat ID
            text: Message text
            reply_markup: Optional inline keyboard
            
        Returns:
            True if sent successfully
        """
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        
        if reply_markup:
            data['reply_markup'] = reply_markup
        
        result = self._make_request('sendMessage', data)
        
        if result.get('ok'):
            return True
        else:
            print(f"[TELEGRAM] Failed to send message: {result.get('description')}")
            return False
    
    def generate_connection_code(self, user_id: str) -> str:
        """
        Generate unique connection code for user linking.
        
        Args:
            user_id: User ID from your system
            
        Returns:
            6-character connection code
        """
        code = secrets.token_hex(3).upper()  # 6 chars
        expires_at = int(time.time()) + 600  # 10 minutes
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Delete old codes for this user
        cursor.execute('DELETE FROM telegram_users WHERE user_id = ? AND telegram_chat_id IS NULL', (user_id,))
        
        # Insert new code
        cursor.execute('''
            INSERT INTO telegram_users (user_id, connection_code, code_expires_at)
            VALUES (?, ?, ?)
        ''', (user_id, code, expires_at))
        
        conn.commit()
        conn.close()
        
        print(f"[TELEGRAM] Generated code {code} for user {user_id}")
        return code
    
    def verify_connection_code(self, code: str, telegram_chat_id: str, 
                               telegram_username: str = None,
                               telegram_first_name: str = None,
                               telegram_last_name: str = None) -> Optional[str]:
        """
        Verify connection code and link Telegram account.
        
        Args:
            code: Connection code from user
            telegram_chat_id: Telegram chat ID
            telegram_username: Telegram username
            telegram_first_name: First name
            telegram_last_name: Last name
            
        Returns:
            user_id if successful, None if failed
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Find valid code
        cursor.execute('''
            SELECT user_id, code_expires_at 
            FROM telegram_users 
            WHERE connection_code = ? AND telegram_chat_id IS NULL
        ''', (code,))
        
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return None
        
        user_id, expires_at = result
        
        # Check if expired
        if expires_at < int(time.time()):
            cursor.execute('DELETE FROM telegram_users WHERE connection_code = ?', (code,))
            conn.commit()
            conn.close()
            return None
        
        # Link account
        cursor.execute('''
            UPDATE telegram_users
            SET telegram_chat_id = ?,
                telegram_username = ?,
                telegram_first_name = ?,
                telegram_last_name = ?,
                connection_code = NULL,
                code_expires_at = NULL,
                connected_at = ?
            WHERE user_id = ?
        ''', (telegram_chat_id, telegram_username, telegram_first_name, 
              telegram_last_name, int(time.time()), user_id))
        
        conn.commit()
        conn.close()
        
        print(f"[TELEGRAM] Linked user {user_id} to chat {telegram_chat_id}")
        return user_id
    
    def get_user_chat_id(self, user_id: str) -> Optional[str]:
        """Get Telegram chat ID for a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT telegram_chat_id 
            FROM telegram_users 
            WHERE user_id = ? AND alerts_enabled = TRUE
        ''', (user_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else None
    
    def is_user_connected(self, user_id: str) -> bool:
        """Check if user has Telegram connected"""
        return self.get_user_chat_id(user_id) is not None
    
    def disconnect_user(self, user_id: str) -> bool:
        """Disconnect user's Telegram"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM telegram_users WHERE user_id = ?', (user_id,))
        
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        
        if deleted:
            print(f"[TELEGRAM] Disconnected user {user_id}")
        
        return deleted
    
    def toggle_alerts(self, user_id: str, enabled: bool) -> bool:
        """Enable/disable alerts for user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE telegram_users 
            SET alerts_enabled = ?
            WHERE user_id = ?
        ''', (enabled, user_id))
        
        conn.commit()
        updated = cursor.rowcount > 0
        conn.close()
        
        return updated
    
    def format_alert_message(self, alert_data: Dict) -> str:
        """
        Format wallet activity into Telegram message.
        
        Args:
            alert_data: Wallet activity data
            
        Returns:
            Formatted HTML message
        """
        wallet = alert_data['wallet']
        action = alert_data['action']
        token = alert_data['token']
        trade = alert_data['trade']
        links = alert_data.get('links', {})
        
        # Emoji based on action
        emoji = "🟢" if action == 'buy' else "🔴"
        action_text = action.upper()
        
        # Format message
        message = f"""
{emoji} <b>WALLET ALERT</b>

<b>Wallet:</b> <code>{wallet['address'][:8]}...{wallet['address'][-6:]}</code>
<b>Tier:</b> {wallet.get('tier', 'C')} | Score: {wallet.get('consistency_score', 0):.1f}

<b>Action:</b> {action_text}
<b>Token:</b> ${token['symbol']}
<b>Name:</b> {token.get('name', 'Unknown')}

<b>💰 Value:</b> ${trade['amount_usd']:,.2f}
<b>📊 Price:</b> ${trade['price']:.8f}
<b>🕐 Time:</b> {datetime.fromtimestamp(trade['timestamp']).strftime('%H:%M:%S')}

<b>📎 Links:</b>
• <a href="{links.get('solscan', '')}">Solscan</a>
• <a href="{links.get('birdeye', '')}">Birdeye</a>
• <a href="{links.get('dexscreener', '')}">DexScreener</a>
""".strip()
        
        return message
    
    def create_trade_buttons(self, alert_data: Dict) -> dict:
        """
        Create inline keyboard with copy-trade buttons.
        
        Args:
            alert_data: Alert data
            
        Returns:
            Telegram inline keyboard markup
        """
        token_address = alert_data['token']['address']
        amount_usd = alert_data['trade']['amount_usd']
        
        # Format commands for different bots
        photon_cmd = f"/buy {token_address} {int(amount_usd)}"
        bonkbot_cmd = f".buy {token_address} {amount_usd / 100:.2f}sol"  # Rough conversion
        
        return {
            'inline_keyboard': [
                [
                    {'text': '📋 Copy Photon', 'callback_data': f'copy_photon:{token_address}'},
                    {'text': '📋 Copy Bonkbot', 'callback_data': f'copy_bonkbot:{token_address}'}
                ],
                [
                    {'text': '📊 View Chart', 'url': alert_data['links'].get('dexscreener', '')},
                    {'text': '❌ Dismiss', 'callback_data': 'dismiss'}
                ]
            ]
        }
    
    def send_wallet_alert(self, user_id: str, alert_data: Dict, activity_id: int) -> bool:
        """
        Send wallet activity alert to user.
        
        Args:
            user_id: User ID
            alert_data: Alert data dictionary
            activity_id: Wallet activity ID
            
        Returns:
            True if sent successfully
        """
        chat_id = self.get_user_chat_id(user_id)
        
        if not chat_id:
            print(f"[TELEGRAM] User {user_id} not connected")
            return False
        
        # Format message
        message = self.format_alert_message(alert_data)
        buttons = self.create_trade_buttons(alert_data)
        
        # Send message
        success = self.send_message(chat_id, message, buttons)
        
        # Log notification
        self._log_notification(user_id, chat_id, activity_id, success)
        
        return success
    
    def _log_notification(self, user_id: str, chat_id: str, activity_id: int, success: bool):
        """Log notification to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO telegram_notification_log 
            (user_id, telegram_chat_id, activity_id, success)
            VALUES (?, ?, ?, ?)
        ''', (user_id, chat_id, activity_id, success))
        
        conn.commit()
        conn.close()
    
    def handle_callback_query(self, callback_query: dict) -> bool:
        """
        Handle inline button callbacks.
        
        Args:
            callback_query: Telegram callback query data
            
        Returns:
            True if handled successfully
        """
        callback_id = callback_query['id']
        data = callback_query['data']
        chat_id = callback_query['from']['id']
        message_id = callback_query['message']['message_id']
        
        if data.startswith('copy_photon:'):
            token_address = data.split(':')[1]
            command = f"/buy {token_address} 1000"
            
            # Send command as new message
            self.send_message(
                str(chat_id),
                f"📋 <b>Photon Command:</b>\n\n<code>{command}</code>\n\nCopy and paste in @PhotonSol_Bot"
            )
            
            # Answer callback
            self._make_request('answerCallbackQuery', {
                'callback_query_id': callback_id,
                'text': '✅ Command copied!'
            })
            return True
        
        elif data.startswith('copy_bonkbot:'):
            token_address = data.split(':')[1]
            command = f".buy {token_address} 1sol"
            
            self.send_message(
                str(chat_id),
                f"📋 <b>Bonkbot Command:</b>\n\n<code>{command}</code>\n\nCopy and paste in @bonkbot_bot"
            )
            
            self._make_request('answerCallbackQuery', {
                'callback_query_id': callback_id,
                'text': '✅ Command copied!'
            })
            return True
        
        elif data == 'dismiss':
            # Delete message
            self._make_request('deleteMessage', {
                'chat_id': chat_id,
                'message_id': message_id
            })
            
            self._make_request('answerCallbackQuery', {
                'callback_query_id': callback_id,
                'text': '✅ Alert dismissed'
            })
            return True
        
        return False
    
    def process_bot_updates(self, updates: List[dict]):
        """
        Process incoming bot updates (messages, callbacks).
        
        Args:
            updates: List of Telegram updates
        """
        for update in updates:
            if 'message' in update:
                self._handle_message(update['message'])
            elif 'callback_query' in update:
                self.handle_callback_query(update['callback_query'])
    
    def _handle_message(self, message: dict):
        """Handle incoming message"""
        chat_id = str(message['chat']['id'])
        text = message.get('text', '')
        username = message['from'].get('username')
        first_name = message['from'].get('first_name')
        last_name = message['from'].get('last_name')
        
        if text == '/start':
            # Welcome message
            self.send_message(
                chat_id,
                "👋 <b>Welcome to Sifter KYS Alerts!</b>\n\n"
                "To connect your account:\n"
                "1. Go to your dashboard settings\n"
                "2. Click 'Connect Telegram'\n"
                "3. Enter the code shown here"
            )
        
        elif len(text) == 6 and text.isalnum():
            # Possibly a connection code
            user_id = self.verify_connection_code(
                text.upper(),
                chat_id,
                username,
                first_name,
                last_name
            )
            
            if user_id:
                self.send_message(
                    chat_id,
                    "✅ <b>Account Connected!</b>\n\n"
                    "You'll now receive wallet alerts here.\n\n"
                    "Manage settings in your dashboard."
                )
            else:
                self.send_message(
                    chat_id,
                    "❌ <b>Invalid or expired code</b>\n\n"
                    "Generate a new code in your dashboard."
                )