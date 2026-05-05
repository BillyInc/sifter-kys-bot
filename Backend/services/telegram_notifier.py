"""
telegram_notifier.py - Telegram Alert Service.

Handles user linking, wallet alerts, Elite 15 signal alerts, and the
Telegram-side configuration for autonomous trading.
"""

import hashlib
import html
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from services.supabase_client import SCHEMA_NAME, get_supabase_client

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Service for sending alerts to Telegram-linked users."""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        print("[TELEGRAM] Notifier ready")

    def _table(self, name: str):
        return self.supabase.schema(self.schema).table(name)

    def _make_request(self, method: str, data: dict = None) -> dict:
        try:
            response = requests.post(f"{self.base_url}/{method}", json=data, timeout=10)
            return response.json()
        except Exception as e:
            logger.error(f"[TELEGRAM] API error: {e}")
            return {"ok": False, "error": str(e)}

    def send_message(self, chat_id: str, text: str, reply_markup: dict = None) -> bool:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._make_request("sendMessage", payload).get("ok", False)

    def verify_connection_token(
        self,
        token: str,
        telegram_chat_id: str,
        telegram_username: str = None,
        telegram_first_name: str = None,
        telegram_last_name: str = None,
    ) -> Optional[str]:
        try:
            result = self._table("telegram_connection_tokens").select("*").eq(
                "token", token
            ).eq("used", False).execute()
            if not result.data:
                return None

            token_data = result.data[0]
            user_id = token_data["user_id"]
            expires_at = datetime.fromisoformat(token_data["expires_at"].replace("Z", "+00:00"))
            if expires_at < datetime.now(timezone.utc):
                self._table("telegram_connection_tokens").delete().eq("token", token).execute()
                return None

            self._table("telegram_connection_tokens").update(
                {"used": True, "telegram_id": int(telegram_chat_id)}
            ).eq("token", token).execute()

            existing = self._table("telegram_users").select("*").eq("user_id", user_id).execute()
            payload = {
                "telegram_chat_id": str(telegram_chat_id),
                "telegram_username": telegram_username,
                "telegram_first_name": telegram_first_name,
                "telegram_last_name": telegram_last_name,
                "connected_at": datetime.now(timezone.utc).isoformat(),
                "alerts_enabled": True,
            }
            if existing.data:
                self._table("telegram_users").update(payload).eq("user_id", user_id).execute()
            else:
                self._table("telegram_users").insert({"user_id": user_id, **payload}).execute()

            return user_id
        except Exception as e:
            logger.error(f"[TELEGRAM] Error verifying token: {e}")
            return None

    def get_user_chat_id(self, user_id: str) -> Optional[str]:
        try:
            result = self._table("telegram_users").select("telegram_chat_id").eq(
                "user_id", user_id
            ).eq("alerts_enabled", True).limit(1).execute()
            return result.data[0]["telegram_chat_id"] if result.data else None
        except Exception:
            return None

    def is_user_connected(self, user_id: str) -> bool:
        return self.get_user_chat_id(user_id) is not None

    def disconnect_user(self, user_id: str) -> bool:
        try:
            result = self._table("telegram_users").delete().eq("user_id", user_id).execute()
            return len(result.data) > 0
        except Exception:
            return False

    def toggle_alerts(self, user_id: str, enabled: bool) -> bool:
        try:
            result = self._table("telegram_users").update({"alerts_enabled": enabled}).eq(
                "user_id", user_id
            ).execute()
            return len(result.data) > 0
        except Exception:
            return False

    def send_trade_alert(self, user_id: str, trades: List[Dict]) -> bool:
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id or not trades:
            return False

        is_multi = len(trades) > 1
        t = trades[0]["trade"]
        token_symbol = html.escape(t.get("symbol") or t.get("token_ticker") or "UNKNOWN")
        token_address = html.escape(t.get("token_address") or "")
        total_usd = sum(float(item["trade"].get("amount_usd", 0) or 0) for item in trades)
        header = "MULTI-WALLET SIGNAL" if is_multi else "Wallet Activity"

        lines = [
            f"<b>{header}</b>",
            "",
            f"<b>Token:</b> ${token_symbol}",
            f"<b>Total Buy:</b> ${total_usd:,.2f}",
            f"<b>CA:</b> <code>{token_address}</code>",
            "",
        ]
        if is_multi:
            lines.append("<b>Wallets:</b>")
            for item in trades:
                wallet = item["wallet"]
                lines.append(
                    f"- {html.escape(wallet.get('address', '')[:6])}... "
                    f"(Tier {html.escape(str(wallet.get('tier', 'C')))})"
                )
        else:
            lines.append(f"<b>Wallet:</b> <code>{html.escape(trades[0]['wallet'].get('address', ''))}</code>")

        buttons = {
            "inline_keyboard": [[
                {"text": "View Chart", "url": f"https://dexscreener.com/solana/{token_address}"},
            ]]
        }
        return self.send_message(chat_id, "\n".join(lines), buttons)

    def send_wallet_alert(self, user_id: str, alert_data: Dict, activity_id: int = None) -> bool:
        trades = [{"wallet": alert_data.get("wallet", {}), "trade": alert_data.get("trade", {})}]
        return self.send_trade_alert(user_id, trades)

    def send_watchlist_alert(self, user_id: str, payload: dict) -> bool:
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False

        action = payload.get("action", "buy").upper()
        token = payload.get("token", {})
        trade = payload.get("trade", {})
        wallet = payload.get("wallet", {})
        links = payload.get("links", {})
        icon = "BUY" if action == "BUY" else "SELL"
        text = (
            f"<b>Wallet Alert</b>\n\n"
            f"{icon} <b>${html.escape(token.get('symbol', 'UNKNOWN'))}</b>\n"
            f"Amount: <b>${float(trade.get('amount_usd', 0) or 0):,.2f}</b>\n"
            f"Wallet: <code>{html.escape(wallet.get('address', '')[:8])}...</code> "
            f"(Tier {html.escape(str(wallet.get('tier', 'C')))})\n"
            f"CA: <code>{html.escape(token.get('address', ''))}</code>"
        )
        buttons = {
            "inline_keyboard": [[
                {"text": "Chart", "url": links.get("dexscreener", "#")},
                {"text": "Solscan", "url": links.get("solscan", "#")},
            ]]
        }
        return self.send_message(chat_id, text, buttons)

    def send_elite15_alert(self, user_id: str, payload: dict) -> bool:
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False

        action = payload.get("action", "buy").upper()
        token = payload.get("token", {})
        trade = payload.get("trade", {})
        wallet = payload.get("wallet", {})
        links = payload.get("links", {})
        text = (
            f"<b>ELITE 15 SIGNAL</b>\n\n"
            f"{action} <b>${html.escape(token.get('symbol', 'UNKNOWN'))}</b>\n"
            f"Amount: <b>${float(trade.get('amount_usd', 0) or 0):,.2f}</b>\n"
            f"Wallet: <code>{html.escape(wallet.get('address', '')[:8])}...</code> "
            f"(Tier {html.escape(str(wallet.get('tier', 'S')))})\n"
            f"CA: <code>{html.escape(token.get('address', ''))}</code>\n\n"
            f"<i>Auto-trader processing this signal...</i>"
        )
        buttons = {
            "inline_keyboard": [[
                {"text": "Chart", "url": links.get("dexscreener", "#")},
                {"text": "Solscan", "url": links.get("solscan", "#")},
            ]]
        }
        return self.send_message(chat_id, text, buttons)

    def send_multi_wallet_signal_alert(self, user_id: str, signal: Dict) -> bool:
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False

        wallets = signal.get("wallets", [])
        lines = [
            "<b>MULTI-WALLET SIGNAL</b>",
            "",
            f"Token: <code>{html.escape(signal.get('token_address', ''))}</code>",
            f"Wallet Count: <b>{len(wallets)}</b>",
            f"Signal Strength: <b>{signal.get('signal_strength', 0)}</b>",
            "",
            "<b>Wallets:</b>",
        ]
        for wallet in wallets[:8]:
            lines.append(
                f"- <code>{html.escape(wallet.get('wallet', '')[:8])}...</code> "
                f"Tier {html.escape(str(wallet.get('tier', 'C')))} "
                f"${float(wallet.get('usd_value', 0) or 0):,.2f}"
            )
        return self.send_message(chat_id, "\n".join(lines))

    def send_auto_trade_confirmation(self, user_id: str, trade: dict, txid: str) -> bool:
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False
        text = (
            f"<b>Auto-Trade Executed</b>\n\n"
            f"{trade.get('side', 'buy').upper()} <b>${html.escape(trade.get('token_ticker', 'UNKNOWN'))}</b>\n"
            f"Amount: <b>${float(trade.get('usd_amount', 0) or 0):,.2f}</b>\n"
            f"<a href='https://solscan.io/tx/{txid}'>View transaction</a>"
        )
        return self.send_message(chat_id, text)

    def send_auto_trade_failed(self, user_id: str, trade: dict, error: str) -> bool:
        chat_id = self.get_user_chat_id(user_id)
        if not chat_id:
            return False
        text = (
            f"<b>Auto-Trade Failed</b>\n\n"
            f"Token: <b>${html.escape(trade.get('token_ticker', 'UNKNOWN'))}</b>\n"
            f"Reason: <code>{html.escape(str(error)[:200])}</code>"
        )
        return self.send_message(chat_id, text)

    def execute_auto_trade_for_user(
        self,
        user_id: str,
        token_address: str,
        side: str,
        usd_amount: float,
    ) -> str | None:
        try:
            result = self._table("bot_wallets").select(
                "public_key, encrypted_key, key_iv, key_tag"
            ).eq("user_id", user_id).limit(1).execute()
            if not result.data:
                logger.warning(f"[BOT TRADE] No bot wallet registered for {user_id[:8]}...")
                return None

            encryption_secret = os.environ.get("WALLET_ENCRYPTION_SECRET")
            if not encryption_secret:
                raise RuntimeError("WALLET_ENCRYPTION_SECRET env var not set")

            private_key_bytes = self._decrypt_wallet_key(
                encrypted_hex=result.data[0]["encrypted_key"],
                iv_hex=result.data[0]["key_iv"],
                tag_hex=result.data[0]["key_tag"],
                secret=encryption_secret,
                user_id=user_id,
            )

            try:
                mock_txid = "BOT" + hashlib.sha256(
                    f"{user_id}{token_address}{side}{usd_amount}".encode()
                ).hexdigest()[:60]
                return mock_txid
            finally:
                for i in range(len(private_key_bytes)):
                    private_key_bytes[i] = 0
        except Exception as e:
            logger.error(f"[BOT TRADE] execute_auto_trade_for_user error: {e}")
            return None

    def _decrypt_wallet_key(
        self,
        encrypted_hex: str,
        iv_hex: str,
        tag_hex: str,
        secret: str,
        user_id: str,
    ) -> bytearray:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        raw_key = hashlib.pbkdf2_hmac(
            "sha256",
            (secret + user_id).encode(),
            user_id.encode(),
            200_000,
        )
        aes_gcm = AESGCM(raw_key)
        plaintext = aes_gcm.decrypt(
            bytes.fromhex(iv_hex),
            bytes.fromhex(encrypted_hex) + bytes.fromhex(tag_hex),
            None,
        )
        return bytearray(plaintext)

    def process_bot_updates(self, updates: List[dict]):
        for update in updates:
            if "message" in update:
                self._handle_message(update["message"])
            elif "callback_query" in update:
                self._handle_callback(update["callback_query"])

    def _handle_message(self, message: dict):
        chat_id = str(message["chat"]["id"])
        text = message.get("text", "").strip()
        username = message["from"].get("username")
        first_name = message["from"].get("first_name", "")
        last_name = message["from"].get("last_name")

        if text.startswith("/start "):
            token = text.split(" ", 1)[1]
            user_id = self.verify_connection_token(token, chat_id, username, first_name, last_name)
            if user_id:
                self.send_message(
                    chat_id,
                    "✅ <b>Connected!</b>\n\n"
                    "Your Sifter account is now linked.\n\n"
                    "<b>Auto-trading:</b>\n"
                    "/autotrade on\n"
                    "/autotrade off\n"
                    "/autotrade status\n"
                    "/setamount 200",
                )
            else:
                self.send_message(chat_id, "❌ <b>Link failed.</b> Generate a new link from the dashboard.")
            return

        if text == "/start":
            self.send_message(chat_id, "👋 <b>Sifter KYS Bot</b>\n\nConnect from the dashboard to get started.")
            return

        if text.startswith("/autotrade"):
            parts = text.split()
            action = parts[1].lower() if len(parts) > 1 else "status"
            result = self._table("telegram_users").select(
                "user_id, auto_trade_enabled, auto_trade_max_usd"
            ).eq("telegram_chat_id", chat_id).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "❌ Not connected. Use /start first.")
                return

            row = result.data[0]
            user_id = row["user_id"]

            if action == "on":
                has_wallet = self._table("bot_wallets").select("id").eq("user_id", user_id).limit(1).execute()
                if not has_wallet.data:
                    self.send_message(chat_id, "⚠️ No bot wallet registered in the dashboard yet.")
                    return
                self._table("telegram_users").update({"auto_trade_enabled": True}).eq("user_id", user_id).execute()
                self.send_message(
                    chat_id,
                    f"✅ <b>Auto-trading enabled</b>\nMax per trade: <b>${float(row.get('auto_trade_max_usd', 100)):.0f}</b>",
                )
            elif action == "off":
                self._table("telegram_users").update({"auto_trade_enabled": False}).eq("user_id", user_id).execute()
                self.send_message(chat_id, "🛑 <b>Auto-trading disabled</b>")
            else:
                enabled = row.get("auto_trade_enabled", False)
                self.send_message(
                    chat_id,
                    f"⚙️ <b>Auto-trade status</b>\n\n"
                    f"Status: {'ON' if enabled else 'OFF'}\n"
                    f"Max per trade: <b>${float(row.get('auto_trade_max_usd', 100)):.0f}</b>",
                )
            return

        if text.startswith("/setamount"):
            parts = text.split()
            try:
                amount = float(parts[1])
                if amount <= 0:
                    raise ValueError
            except (IndexError, ValueError):
                self.send_message(chat_id, "Usage: /setamount 200")
                return

            result = self._table("telegram_users").select("user_id").eq(
                "telegram_chat_id", chat_id
            ).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "❌ Not connected. Use /start first.")
                return

            self._table("telegram_users").update({"auto_trade_max_usd": amount}).eq(
                "user_id", result.data[0]["user_id"]
            ).execute()
            self.send_message(chat_id, f"✅ Max trade amount set to <b>${amount:,.0f}</b>")
            return

        if text == "/settings":
            result = self._table("telegram_users").select(
                "user_id, auto_trade_enabled, auto_trade_max_usd"
            ).eq("telegram_chat_id", chat_id).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "❌ Not connected.")
                return
            row = result.data[0]
            self.send_message(
                chat_id,
                f"⚙️ <b>Settings</b>\n\n"
                f"Auto-trade: {'ON' if row.get('auto_trade_enabled') else 'OFF'}\n"
                f"Max per trade: ${float(row.get('auto_trade_max_usd', 100)):.0f}\n\n"
                f"/autotrade on|off|status\n"
                f"/setamount 200",
            )
            return

        if text == "/help":
            self.send_message(
                chat_id,
                "<b>Sifter KYS Bot Commands</b>\n\n"
                "/settings\n"
                "/autotrade on|off|status\n"
                "/setamount 200\n"
                "/help",
            )
            return

    def _handle_callback(self, query: dict):
        query_id = query["id"]
        chat_id = str(query["from"]["id"])
        data = query["data"]

        if data.startswith("cp_p:") or data.startswith("cp_b:"):
            ca = data.split(":", 1)[1]
            bot_type = "Photon" if data.startswith("cp_p:") else "Bonkbot"
            cmd = f"/buy {ca}" if bot_type == "Photon" else ca
            self._make_request(
                "answerCallbackQuery",
                {"callback_query_id": query_id, "text": f"{bot_type} command ready!", "show_alert": False},
            )
            self._make_request(
                "sendMessage",
                {"chat_id": chat_id, "text": f"<code>{cmd}</code>", "parse_mode": "HTML"},
            )
        else:
            self._make_request("answerCallbackQuery", {"callback_query_id": query_id})

    def show_settings(self, chat_id: str, user_id: str) -> bool:
        try:
            result = self._table("telegram_users").select(
                "auto_trade_enabled, auto_trade_max_usd, alerts_enabled"
            ).eq("user_id", user_id).limit(1).execute()
            if result.data:
                row = result.data[0]
                text = (
                    f"⚙️ <b>Settings</b>\n\n"
                    f"Alerts: {'ON' if row.get('alerts_enabled', True) else 'OFF'}\n"
                    f"Auto-trade: {'ON' if row.get('auto_trade_enabled', False) else 'OFF'}\n"
                    f"Max per trade: ${float(row.get('auto_trade_max_usd', 100)):.0f}"
                )
            else:
                text = "⚙️ <b>Settings</b>\n\nNo Telegram settings found yet."
            return self.send_message(chat_id, text)
        except Exception:
            return self.send_message(chat_id, "⚙️ <b>Settings</b>\n\nUnable to load settings.")

    def generate_connection_code(self, user_id: str) -> str:
        return secrets.token_hex(3).upper()

    def send_raw_message(self, chat_id: str, text: str, reply_markup: dict = None) -> bool:
        return self.send_message(chat_id, text, reply_markup)
