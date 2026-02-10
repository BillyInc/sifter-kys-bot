"""
telegram_notifier.py - Telegram Alert Service

Sends wallet activity alerts to users via Telegram bot.
Handles bot commands, user linking, and message formatting.
"""

import requests
import time
import secrets
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from services.supabase_client import get_supabase_client, SCHEMA_NAME


class TelegramNotifier:
    """
    Service for sending wallet alerts via Telegram bot.
    Handles user linking and alert delivery.
    """
    
    def __init__(self, bot_token: str):
        """
        Initialize Telegram notifier.
        
        Args:
            bot_token: Telegram Bot API token
        """
        self.bot_token = bot_token
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        print(f"[TELEGRAM] Notifier initialized")
    
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
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        
        # Delete old codes for this user
        self._table('telegram_users').delete().eq(
            'user_id', user_id
        ).is_('telegram_chat_id', 'null').execute()
        
        # Insert new code
        self._table('telegram_users').insert({
            'user_id': user_id,
            'connection_code': code,
            'code_expires_at': expires_at.isoformat()
        }).execute()
        
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
        # Find valid code
        result = self._table('telegram_users').select('*').eq(
            'connection_code', code
        ).is_('telegram_chat_id', 'null').execute()
        
        if not result.data:
            return None
        
        user_data = result.data[0]
        user_id = user_data['user_id']
        expires_at = datetime.fromisoformat(user_data['code_expires_at'].replace('Z', '+00:00'))
        
        # Check if expired
        if expires_at < datetime.utcnow().replace(tzinfo=expires_at.tzinfo):
            self._table('telegram_users').delete().eq('connection_code', code).execute()
            return None
        
        # Link account
        self._table('telegram_users').update({
            'telegram_chat_id': telegram_chat_id,
            'telegram_username': telegram_username,
            'telegram_first_name': telegram_first_name,
            'telegram_last_name': telegram_last_name,
            'connection_code': None,
            'code_expires_at': None,
            'connected_at': datetime.utcnow().isoformat()
        }).eq('user_id', user_id).execute()
        
        print(f"[TELEGRAM] Linked user {user_id} to chat {telegram_chat_id}")
        return user_id
    
    def get_user_chat_id(self, user_id: str) -> Optional[str]:
        """Get Telegram chat ID for a user"""
        result = self._table('telegram_users').select(
            'telegram_chat_id'
        ).eq('user_id', user_id).eq('alerts_enabled', True).execute()
        
        return result.data[0]['telegram_chat_id'] if result.data else None
    
    def is_user_connected(self, user_id: str) -> bool:
        """Check if user has Telegram connected"""
        return self.get_user_chat_id(user_id) is not None
    
    def disconnect_user(self, user_id: str) -> bool:
        """Disconnect user's Telegram"""
        result = self._table('telegram_users').delete().eq('user_id', user_id).execute()
        
        deleted = len(result.data) > 0
        if deleted:
            print(f"[TELEGRAM] Disconnected user {user_id}")
        
        return deleted
    
    def toggle_alerts(self, user_id: str, enabled: bool) -> bool:
        """Enable/disable alerts for user"""
        result = self._table('telegram_users').update({
            'alerts_enabled': enabled
        }).eq('user_id', user_id).execute()
        
        return len(result.data) > 0
    
    # =========================================================================
    # WATCHLIST-SPECIFIC ALERT METHODS
    # =========================================================================
    
    def send_trade_alert(self, user_id: str, alert_data: Dict) -> bool:
        """Send wallet trade alert"""
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False
        
        wallet = alert_data['wallet']
        action = alert_data['action']
        token = alert_data['token']
        trade = alert_data['trade']
        
        emoji = "🟢" if action == 'buy' else "🔴"
        
        message = f"""
{emoji} <b>WALLET ALERT - Position #{wallet.get('position', '?')}</b>

<b>Wallet:</b> <code>{wallet['address'][:8]}...{wallet['address'][-6:]}</code>
<b>Tier:</b> {wallet.get('tier', 'C')} | Score: {wallet.get('professional_score', 0)}

<b>ACTION: {action.upper()} ${token['symbol']}</b>
<b>Amount:</b> ${trade['amount_usd']:,.2f}
<b>Price:</b> ${trade['price']:.8f}

📊 This wallet has {wallet.get('roi_30d', 0)}% avg ROI ({wallet.get('runners_30d', 0)} runners this month)
""".strip()
        
        buttons = {
            'inline_keyboard': [
                [
                    {'text': '📋 Copy to Photon', 'callback_data': f'copy_photon:{token["address"]}'},
                    {'text': '📋 Copy to Bonkbot', 'callback_data': f'copy_bonkbot:{token["address"]}'}
                ],
                [
                    {'text': '📊 View Chart', 'url': alert_data.get('chart_url', '')},
                    {'text': '❌ Dismiss', 'callback_data': 'dismiss'}
                ]
            ]
        }
        
        return self.send_message(chat_id, message, buttons)
    
    def send_position_change_alert(self, user_id: str, wallet_data: Dict) -> bool:
        """Alert when wallet moves in Premier League table"""
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False
        
        old_pos = wallet_data['old_position']
        new_pos = wallet_data['new_position']
        movement = old_pos - new_pos  # Positive = moved up
        
        if movement > 0:
            emoji = "📈"
            text = f"climbed from #{old_pos} → #{new_pos}"
        else:
            emoji = "📉"
            text = f"dropped from #{old_pos} → #{new_pos}"
        
        message = f"""
{emoji} <b>WATCHLIST UPDATE</b>

Position Change!

Wallet {wallet_data['wallet_address'][:8]}... {text}

Reason:
- {wallet_data.get('reason', 'Performance change')}
- Current ROI: {wallet_data.get('roi_30d', 0)}%
- Runners: {wallet_data.get('runners_30d', 0)}

Your watchlist avg ROI: {wallet_data.get('watchlist_avg_roi', 0)}%
""".strip()
        
        buttons = {
            'inline_keyboard': [[
                {'text': 'View Watchlist', 'callback_data': 'view_watchlist'}
            ]]
        }
        
        return self.send_message(chat_id, message, buttons)
    
    def send_degradation_warning(self, user_id: str, wallet_data: Dict) -> bool:
        """Warning when wallet enters monitoring/relegation zone"""
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False
        
        severity = wallet_data.get('severity', 'warning')
        
        if severity == 'critical':
            emoji = "🔴"
            title = "CRITICAL WATCHLIST ALERT"
        else:
            emoji = "⚠️"
            title = "WATCHLIST WARNING"
        
        issues = wallet_data.get('issues', [])
        issues_text = '\n'.join([f'• {issue}' for issue in issues])
        
        message = f"""
{emoji} <b>{title}</b>

Wallet Performance Declining

<b>Wallet:</b> {wallet_data['wallet_address'][:8]}...
<b>Was:</b> Position #{wallet_data['old_position']} ({wallet_data['old_tier']}-Tier)
<b>Now:</b> Position #{wallet_data['new_position']} ({wallet_data['tier']}-Tier)

<b>Issues:</b>
{issues_text}

<b>Status:</b> {wallet_data['zone'].upper()} ZONE

We found {wallet_data.get('replacement_count', 0)} replacement wallets performing better.
""".strip()
        
        buttons = {
            'inline_keyboard': [
                [
                    {'text': 'View Replacements', 'callback_data': f'replacements:{wallet_data["wallet_address"]}'},
                    {'text': 'Keep & Monitor', 'callback_data': 'keep'}
                ]
            ]
        }
        
        return self.send_message(chat_id, message, buttons)
    
    def send_replacement_complete_alert(self, user_id: str, replacement_data: Dict) -> bool:
        """Confirmation when wallet is replaced"""
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False
        
        message = f"""
✅ <b>WATCHLIST AUTO-UPDATED</b>

Replacement Complete

<b>REMOVED:</b> {replacement_data['old_wallet'][:8]}... ({replacement_data['old_tier']}-Tier, {replacement_data['old_roi']}% ROI)
<b>ADDED:</b> {replacement_data['new_wallet'][:8]}... ({replacement_data['new_tier']}-Tier, {replacement_data['new_roi']}% ROI)

<b>Your watchlist health improved:</b>
- Position #{replacement_data['position']}: {replacement_data['old_roi']}% → {replacement_data['new_roi']}%
- Avg watchlist ROI: {replacement_data['old_avg']}% → {replacement_data['new_avg']}%
- You're now +{replacement_data['vs_platform']}% above platform avg 🚀

New wallet is already being tracked.
First alert should arrive within hours.
""".strip()
        
        buttons = {
            'inline_keyboard': [[
                {'text': 'View New Wallet', 'callback_data': f'view_wallet:{replacement_data["new_wallet"]}'},
                {'text': 'See Updated Table', 'callback_data': 'view_watchlist'}
            ]]
        }
        
        return self.send_message(chat_id, message, buttons)
    
    def send_weekly_digest(self, user_id: str, digest_data: Dict) -> bool:
        """Weekly performance summary"""
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False
        
        message = f"""
🏆 <b>WEEKLY WATCHLIST REPORT</b>

Week {digest_data['week_number']} Summary

📊 <b>LEAGUE TABLE STANDINGS:</b>

<b>Top Performer:</b>
🥇 #{digest_data['top_performer']['position']}: {digest_data['top_performer']['wallet'][:8]}... ({digest_data['top_performer']['roi']}% ROI, {digest_data['top_performer']['runners']} runners)

<b>Biggest Riser:</b>
📈 #{digest_data['biggest_riser']['position']}: {digest_data['biggest_riser']['wallet'][:8]}... (↑ {digest_data['biggest_riser']['moved']} positions)

━━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 <b>YOUR PERFORMANCE:</b>

Watchlist Avg ROI: {digest_data['avg_roi']}% (+{digest_data['roi_change']}% vs last week)
Platform Avg: {digest_data['platform_avg']}%
You're beating {digest_data['percentile']}% of users 🎯

Runners Hit This Week: {digest_data['runners_hit']}
Total Alerts Sent: {digest_data['alerts_sent']}
Best Trade: +{digest_data['best_trade']['roi']}% (${digest_data['best_trade']['token']})

━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ <b>ACTION ITEMS:</b>

- {digest_data['monitoring_count']} wallet(s) in monitoring zone
- {digest_data['relegation_count']} wallet(s) in relegation zone
- {digest_data['replacement_count']} replacement suggestions ready

Next update: {digest_data['next_update']}
""".strip()
        
        buttons = {
            'inline_keyboard': [[
                {'text': 'View Full Watchlist', 'callback_data': 'view_watchlist'},
                {'text': 'Make Changes', 'callback_data': 'manage_watchlist'}
            ]]
        }
        
        return self.send_message(chat_id, message, buttons)
    
    def send_multi_wallet_signal_alert(self, user_id: str, signal: Dict) -> bool:
        """Send alert when multiple watchlist wallets buy same token"""
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False
        
        wallet_count = signal['wallet_count']
        token_address = signal['token_address']
        signal_strength = signal['signal_strength']
        wallets = signal['wallets']
        
        # Calculate signal emoji based on strength
        if signal_strength >= 10:
            signal_emoji = "🔥🔥🔥"
            signal_label = "EXTREME"
        elif signal_strength >= 7:
            signal_emoji = "🔥🔥"
            signal_label = "STRONG"
        else:
            signal_emoji = "🔥"
            signal_label = "MODERATE"
        
        # Build wallet list
        wallet_list = "\n".join([
            f"{'🥇' if w['tier'] == 'S' else '🥈' if w['tier'] == 'A' else '🥉'} "
            f"{w['tier']}-Tier: {w['wallet'][:8]}... (${w['usd_value']:,.0f})"
            for w in wallets[:5]
        ])
        
        message = f"""
{signal_emoji} <b>MULTI-WALLET SIGNAL - {signal_label}</b>

<b>{wallet_count} of your watchlist wallets just bought the SAME token!</b>

🎯 Token: <code>{token_address[:12]}...</code>
💪 Signal Strength: {signal_strength}/10

<b>Wallets Buying:</b>
{wallet_list}

⏰ {wallet_count} wallets bought within the same time window 

<b>What to do:</b>
1️⃣ Check the token chart immediately
2️⃣ Review if it's a fresh launch or existing runner
3️⃣ Set alerts to track if more wallets join
""".strip()
        
        buttons = {
            'inline_keyboard': [
                [
                    {'text': '📊 View on DexScreener', 'url': f'https://dexscreener.com/solana/{token_address}'},
                    {'text': '🔍 View on Birdeye', 'url': f'https://birdeye.so/token/{token_address}'}
                ],
                [
                    {'text': '📋 Copy Address', 'callback_data': f'copy_token:{token_address}'}
                ]
            ]
        }
        
        return self.send_message(chat_id, message, buttons)
    
    def handle_callback_query(self, callback_query: dict) -> bool:
        """Handle inline button callbacks"""
        callback_id = callback_query['id']
        data = callback_query['data']
        chat_id = callback_query['from']['id']
        message_id = callback_query['message']['message_id']
        
        if data.startswith('copy_photon:'):
            token_address = data.split(':')[1]
            command = f"/buy {token_address} 1000"
            
            self.send_message(
                str(chat_id),
                f"📋 <b>Photon Command:</b>\n\n<code>{command}</code>\n\nCopy and paste in @PhotonSol_Bot"
            )
            
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
        """Process incoming bot updates"""
        for update in updates:
            if 'message' in update:
                self._handle_message(update['message'])
            elif 'callback_query' in update:
                self.handle_callback_query(update['callback_query'])
    
    def _handle_message(self, message: dict):
        """Handle incoming message with proper linking flow"""
        chat_id = str(message['chat']['id'])
        text = message.get('text', '').strip()
        username = message['from'].get('username')
        first_name = message['from'].get('first_name')
        last_name = message['from'].get('last_name')
        
        if text == '/start':
            self.send_message(
                chat_id,
                "👋 <b>Welcome to Sifter KYS!</b>\n\n"
                "🔗 <b>To connect your dashboard:</b>\n"
                "1. Go to your Sifter dashboard → Settings → Telegram\n"
                "2. Click 'Generate Connection Code'\n"
                "3. Send that 6-character code here\n\n"
                "<b>Example code:</b> <code>AB123C</code>\n\n"
                "💡 Your Chat ID: <code>{}</code>".format(chat_id)
            )
        
        # Check if it's a 6-character alphanumeric code
        elif len(text) == 6 and text.isalnum():
            user_id = self.verify_connection_code(
                text.upper(),  # Convert to uppercase for consistency
                chat_id,
                username,
                first_name,
                last_name
            )
            
            if user_id:
                self.send_message(
                    chat_id,
                    "✅ <b>Account Connected Successfully!</b>\n\n"
                    "You will now receive:\n"
                    "• 🔔 Wallet trade alerts\n"
                    "• 📊 Watchlist updates\n"
                    "• 📈 Performance notifications\n\n"
                    "Manage your alert settings in your dashboard.\n\n"
                    "Chat ID: <code>{}</code>".format(chat_id)
                )
            else:
                self.send_message(
                    chat_id,
                    "❌ <b>Invalid or Expired Code</b>\n\n"
                    "The connection code is either invalid or has expired (10 min limit).\n\n"
                    "Please generate a new code in your dashboard:\n"
                    "Settings → Telegram → Generate Connection Code"
                )
        
        elif text.startswith('/'):
            # Unknown command
            self.send_message(
                chat_id,
                "❓ <b>Unknown Command</b>\n\n"
                "<b>Available Commands:</b>\n"
                "• <code>/start</code> - Get setup instructions\n\n"
                "To connect, generate a code in your dashboard and send it here."
            )
        
        else:
            # Not a command or valid code
            self.send_message(
                chat_id,
                "❓ I didn't understand that.\n\n"
                "Send <code>/start</code> for setup instructions."
            )