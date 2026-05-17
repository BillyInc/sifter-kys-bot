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

from services.execution_adapters import LiveJupiterExecutionAdapter
from services.supabase_client import SCHEMA_NAME, get_supabase_client
from services.paper_trade_runtime import get_paper_trade_runtime, is_operator_chat_id

logger = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────────────

_wallet_import_pending: dict = {}  # chat_id -> "awaiting_private_key"


# ── Module-level helpers ──────────────────────────────────────────────────────

def _fmt_mcap(usd):
    """Format a market cap value into human-readable string."""
    if usd is None:
        return "?"
    usd = float(usd)
    if usd >= 1_000_000_000:
        return f"${usd / 1_000_000_000:.1f}B"
    if usd >= 1_000_000:
        return f"${usd / 1_000_000:.1f}M"
    if usd >= 1_000:
        return f"${usd / 1_000:.1f}K"
    return f"${usd:.0f}"


def _fmt_age(seconds):
    """Format age in seconds to human-readable duration."""
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _pnl_dot(pnl_pct):
    """Return a colored dot based on PnL percentage."""
    if pnl_pct is None:
        return "⚪"
    pnl_pct = float(pnl_pct)
    if pnl_pct >= 100:
        return "🟢"
    if pnl_pct >= 0:
        return "🟡"
    if pnl_pct >= -50:
        return "🟠"
    return "🔴"


def _build_position_card(pos):
    """Build a formatted text card for a single position."""
    symbol = html.escape(pos.get("token_symbol") or "???")
    token_address = pos.get("token_address", "")
    invested = float(pos.get("total_invested_usd") or 0)
    current_value = float(pos.get("current_value_usd") or invested)
    pnl = float(pos.get("unrealized_pnl_usd") or 0)
    pnl_pct = ((current_value / invested) - 1) * 100 if invested > 0 else 0.0
    dot = _pnl_dot(pnl_pct)

    lines = [
        f"{dot} <b>${symbol}</b>",
        f"   Invested: ${invested:,.2f}",
        f"   Value: ${current_value:,.2f}",
        f"   PnL: ${pnl:+,.2f} ({pnl_pct:+.1f}%)",
        f"   CA: <code>{token_address[:12]}...</code>",
    ]
    return "\n".join(lines)


def _build_sell_keyboard(token_address, user_id, chat_id):
    """Build inline keyboard with sell percentage buttons."""
    return {
        "inline_keyboard": [
            [
                {"text": "Sell 25%", "callback_data": f"sell|{chat_id}|{token_address}|25"},
                {"text": "Sell 50%", "callback_data": f"sell|{chat_id}|{token_address}|50"},
            ],
            [
                {"text": "Sell 75%", "callback_data": f"sell|{chat_id}|{token_address}|75"},
                {"text": "Sell 100%", "callback_data": f"sell|{chat_id}|{token_address}|100"},
            ],
        ]
    }


def _encrypt_private_key(raw_key_bytes: bytes) -> str:
    """Encrypt a private key using Fernet with WALLET_ENCRYPTION_SECRET."""
    from cryptography.fernet import Fernet
    import base64

    secret = os.environ.get("WALLET_ENCRYPTION_SECRET", "")
    # Derive a Fernet-compatible key from the secret
    key_material = hashlib.sha256(secret.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_material)
    f = Fernet(fernet_key)
    return f.encrypt(raw_key_bytes).decode()


def _decode_solana_private_key(key_str: str) -> bytes:
    """Decode a Solana private key from base58 or hex string."""
    import base58

    key_str = key_str.strip()
    # Try base58 first (most common for Solana)
    try:
        decoded = base58.b58decode(key_str)
        if len(decoded) in (32, 64):
            return bytes(decoded)
    except Exception:
        pass
    # Try hex
    try:
        decoded = bytes.fromhex(key_str)
        if len(decoded) in (32, 64):
            return decoded
    except Exception:
        pass
    raise ValueError("Invalid key format. Expected base58 or hex encoded private key.")


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

    def _is_operator(self, chat_id: str) -> bool:
        """Check if a chat_id belongs to a configured operator."""
        from config import Config
        try:
            return int(chat_id) in Config.TELEGRAM_OPERATOR_CHAT_IDS
        except (ValueError, TypeError):
            return False

    def _get_redis(self):
        """Return a Redis connection."""
        from services.redis_pool import get_redis_client
        return get_redis_client()

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
                execution = LiveJupiterExecutionAdapter().execute(
                    user_id=user_id,
                    token_address=token_address,
                    side=side,
                    usd_amount=usd_amount,
                    wallet_public_key=result.data[0].get("public_key"),
                )
                if execution.status == "filled":
                    return execution.txid
                logger.warning(
                    "[BOT TRADE] Live execution rejected at %s: %s",
                    execution.stage,
                    execution.reason,
                )
                return None
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

        # Intercept wallet import flow
        if chat_id in _wallet_import_pending:
            if text.lower() == '/cancel':
                _wallet_import_pending.pop(chat_id, None)
                self.send_message(chat_id, "❌ Wallet import cancelled.")
                return
            self._handle_wallet_key_message(chat_id, text, message)
            return

        if text.startswith("/start "):
            token = text.split(" ", 1)[1]
            user_id = self.verify_connection_token(token, chat_id, username, first_name, last_name)
            if user_id:
                self.send_message(
                    chat_id,
                    "\u2705 <b>Connected!</b>\n\n"
                    "Your Sifter account is now linked.\n\n"
                    "<b>Auto-trading:</b>\n"
                    "/autotrade on\n"
                    "/autotrade off\n"
                    "/autotrade status\n"
                    "/setamount 200",
                )
            else:
                self.send_message(chat_id, "\u274c <b>Link failed.</b> Generate a new link from the dashboard.")
            return

        if text == "/start":
            self.send_message(chat_id, "\U0001f44b <b>Sifter KYS Bot</b>\n\nConnect from the dashboard to get started.")
            return

        if text.startswith("/autotrade"):
            parts = text.split()
            action = parts[1].lower() if len(parts) > 1 else "status"
            result = self._table("telegram_users").select(
                "user_id, auto_trade_enabled, auto_trade_max_usd"
            ).eq("telegram_chat_id", chat_id).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "\u274c Not connected. Use /start first.")
                return

            row = result.data[0]
            user_id = row["user_id"]

            if action == "on":
                has_wallet = self._table("bot_wallets").select("id").eq("user_id", user_id).limit(1).execute()
                if not has_wallet.data:
                    self.send_message(chat_id, "\u26a0\ufe0f No bot wallet registered in the dashboard yet.")
                    return
                self._table("telegram_users").update({"auto_trade_enabled": True}).eq("user_id", user_id).execute()
                self.send_message(
                    chat_id,
                    f"\u2705 <b>Auto-trading enabled</b>\nMax per trade: <b>${float(row.get('auto_trade_max_usd', 100)):.0f}</b>",
                )
            elif action == "off":
                self._table("telegram_users").update({"auto_trade_enabled": False}).eq("user_id", user_id).execute()
                self.send_message(chat_id, "\U0001f6d1 <b>Auto-trading disabled</b>")
            else:
                enabled = row.get("auto_trade_enabled", False)
                self.send_message(
                    chat_id,
                    f"\u2699\ufe0f <b>Auto-trade status</b>\n\n"
                    f"Status: {'ON' if enabled else 'OFF'}\n"
                    f"Max per trade: <b>${float(row.get('auto_trade_max_usd', 100)):.0f}</b>",
                )
            return

        if text in {"/paper_status", "/paper_logs", "/paper_failures", "/paper_start", "/paper_stop", "/paper_test"}:
            self._handle_operator_command(chat_id, text)
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
                self.send_message(chat_id, "\u274c Not connected. Use /start first.")
                return

            self._table("telegram_users").update({"auto_trade_max_usd": amount}).eq(
                "user_id", result.data[0]["user_id"]
            ).execute()
            self.send_message(chat_id, f"\u2705 Max trade amount set to <b>${amount:,.0f}</b>")
            return

        if text == "/settings":
            result = self._table("telegram_users").select(
                "user_id, auto_trade_enabled, auto_trade_max_usd"
            ).eq("telegram_chat_id", chat_id).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "\u274c Not connected.")
                return
            row = result.data[0]
            self.send_message(
                chat_id,
                f"\u2699\ufe0f <b>Settings</b>\n\n"
                f"Auto-trade: {'ON' if row.get('auto_trade_enabled') else 'OFF'}\n"
                f"Max per trade: ${float(row.get('auto_trade_max_usd', 100)):.0f}\n\n"
                f"/autotrade on|off|status\n"
                f"/setamount 200",
            )
            return

        # ── Operator commands ─────────────────────────────────────────────────
        if text == "/kill":
            if not self._is_operator(chat_id):
                return
            self._get_redis().set("sifter:kill_switch", "1")
            self.send_message(chat_id, "🛑 <b>Kill switch ACTIVATED.</b> All auto-trading halted.")
            return

        if text == "/resume":
            if not self._is_operator(chat_id):
                return
            self._get_redis().delete("sifter:kill_switch")
            self.send_message(chat_id, "✅ <b>Kill switch CLEARED.</b> Auto-trading resumed.")
            return

        if text == "/sys":
            if not self._is_operator(chat_id):
                return
            try:
                r = self._get_redis()
                redis_ok = r.ping()
                user_count = len(
                    self._table("telegram_users").select("id").execute().data or []
                )
                paper_count = len(
                    self._table("paper_portfolio").select("id").eq("status", "open").execute().data or []
                )
                kill_active = r.get("sifter:kill_switch") is not None
                self.send_message(
                    chat_id,
                    "<b>System Health</b>\n\n"
                    f"Redis: {'✅ OK' if redis_ok else '❌ DOWN'}\n"
                    f"Kill switch: {'🛑 ACTIVE' if kill_active else '✅ OFF'}\n"
                    f"Telegram users: <b>{user_count}</b>\n"
                    f"Open paper positions: <b>{paper_count}</b>",
                )
            except Exception as e:
                self.send_message(chat_id, f"❌ System check failed: <code>{html.escape(str(e)[:200])}</code>")
            return

        if text == "/openpositions":
            if not self._is_operator(chat_id):
                return
            try:
                result = self._table("paper_portfolio").select("*").eq("status", "open").execute()
                positions = result.data or []
                if not positions:
                    self.send_message(chat_id, "<b>No open paper positions.</b>")
                    return
                lines = [f"<b>Open Paper Positions ({len(positions)})</b>", ""]
                for pos in positions[:20]:
                    symbol = html.escape(pos.get("token_symbol") or "???")
                    invested = float(pos.get("total_invested_usd") or 0)
                    current = float(pos.get("current_value_usd") or 0)
                    pnl = current - invested
                    lines.append(f"• <b>${symbol}</b> — ${invested:.0f} → ${current:.0f} ({pnl:+.0f})")
                if len(positions) > 20:
                    lines.append(f"\n<i>...and {len(positions) - 20} more</i>")
                self.send_message(chat_id, "\n".join(lines))
            except Exception as e:
                self.send_message(chat_id, f"❌ Error: <code>{html.escape(str(e)[:200])}</code>")
            return

        if text == "/closeall":
            if not self._is_operator(chat_id):
                return
            r = self._get_redis()
            r.set("sifter:confirm_closeall", "1", ex=60)
            self.send_message(
                chat_id,
                "⚠️ <b>Confirm close ALL paper positions?</b>\n\n"
                "Send /confirmcloseall within 60 seconds to proceed.",
            )
            return

        if text == "/confirmcloseall":
            if not self._is_operator(chat_id):
                return
            r = self._get_redis()
            if not r.get("sifter:confirm_closeall"):
                self.send_message(chat_id, "❌ No pending /closeall. Send /closeall first.")
                return
            r.delete("sifter:confirm_closeall")
            from services.paper_trading_manager import get_paper_trading_manager
            ptm = get_paper_trading_manager()
            closed = ptm.close_all_positions("operator_force_close")
            self.send_message(chat_id, f"✅ <b>Closed {closed} positions.</b>")
            return

        if text == "/paperstats":
            if not self._is_operator(chat_id):
                return
            from services.paper_trading_manager import get_paper_trading_manager
            ptm = get_paper_trading_manager()
            report = ptm.generate_daily_report()
            if "error" in report:
                self.send_message(chat_id, f"❌ Report error: <code>{html.escape(str(report['error'])[:200])}</code>")
                return
            self.send_message(
                chat_id,
                "<b>Paper Trading Stats</b>\n\n"
                f"Open positions: <b>{report.get('open_positions', 0)}</b>\n"
                f"Trades today: <b>{report.get('total_trades', 0)}</b>\n"
                f"Winning: <b>{report.get('winning_trades', 0)}</b>\n"
                f"Total invested: <b>${report.get('total_invested_usd', 0):,.2f}</b>\n"
                f"Current value: <b>${report.get('current_value_usd', 0):,.2f}</b>\n"
                f"PnL: <b>${report.get('total_pnl_usd', 0):+,.2f}</b>",
            )
            return

        if text == "/users":
            if not self._is_operator(chat_id):
                return
            try:
                all_users = self._table("telegram_users").select("id, auto_trade_enabled").execute().data or []
                total = len(all_users)
                auto_on = sum(1 for u in all_users if u.get("auto_trade_enabled"))
                self.send_message(
                    chat_id,
                    f"<b>Telegram Users</b>\n\n"
                    f"Total connected: <b>{total}</b>\n"
                    f"Auto-trade enabled: <b>{auto_on}</b>",
                )
            except Exception as e:
                self.send_message(chat_id, f"❌ Error: <code>{html.escape(str(e)[:200])}</code>")
            return

        if text == "/digest":
            if not self._is_operator(chat_id):
                return
            try:
                from services.tasks import send_daily_digest
                send_daily_digest.delay()
                self.send_message(chat_id, "✅ <b>Daily digest task queued.</b>")
            except Exception as e:
                self.send_message(chat_id, f"❌ Failed to queue digest: <code>{html.escape(str(e)[:100])}</code>")
            return

        # ── User commands ─────────────────────────────────────────────────────
        if text == "/importwallet":
            # DM-only check
            if message["chat"].get("type") != "private":
                self.send_message(chat_id, "⚠️ For security, use this command in a <b>direct message</b> to the bot.")
                return
            _wallet_import_pending[chat_id] = "awaiting_private_key"
            self.send_message(
                chat_id,
                "🔐 <b>Wallet Import</b>\n\n"
                "Send your Solana private key (base58 or hex).\n\n"
                "⚠️ <b>Security notice:</b>\n"
                "• Your key will be encrypted at rest\n"
                "• The message containing your key will be deleted immediately\n"
                "• Use a dedicated trading wallet, not your main wallet\n\n"
                "Send /cancel to abort.",
            )
            return

        if text == "/cancel":
            _wallet_import_pending.pop(chat_id, None)
            self.send_message(chat_id, "Cancelled.")
            return

        if text == "/mywallet":
            result = self._table("telegram_users").select(
                "wallet_address, wallet_imported"
            ).eq("telegram_chat_id", chat_id).limit(1).execute()
            if not result.data or not result.data[0].get("wallet_address"):
                self.send_message(chat_id, "No wallet imported. Use /importwallet to link one.")
                return
            row = result.data[0]
            self.send_message(
                chat_id,
                f"💳 <b>Your Wallet</b>\n\n"
                f"Address: <code>{html.escape(row['wallet_address'])}</code>\n"
                f"Imported: {'✅' if row.get('wallet_imported') else '❌'}",
            )
            return

        if text == "/stop":
            result = self._table("telegram_users").select("user_id").eq(
                "telegram_chat_id", chat_id
            ).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "❌ Not connected. Use /start first.")
                return
            self._table("telegram_users").update({"auto_trade_enabled": False}).eq(
                "user_id", result.data[0]["user_id"]
            ).execute()
            self.send_message(chat_id, "🛑 <b>Auto-trading disabled.</b> Use /autotrade on to re-enable.")
            return

        if text.startswith("/setmax"):
            parts = text.split()
            try:
                amount = float(parts[1])
                if amount < 1 or amount > 10000:
                    raise ValueError("out of range")
            except (IndexError, ValueError):
                self.send_message(chat_id, "Usage: /setmax &lt;amount&gt; (1-10000)")
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

        if text == "/mypositions":
            result = self._table("telegram_users").select(
                "user_id, wallet_address"
            ).eq("telegram_chat_id", chat_id).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "❌ Not connected. Use /start first.")
                return
            user_id = result.data[0]["user_id"]
            wallet_addr = result.data[0].get("wallet_address") or "No wallet"

            from services.paper_trading_manager import get_paper_trading_manager
            ptm = get_paper_trading_manager()
            positions = ptm.get_portfolio(user_id)

            if not positions:
                self.send_message(chat_id, "📊 <b>No open positions.</b>\n\nYou'll see positions here when auto-trade enters a token.")
                return

            header = f"💼 <b>My Positions</b>\n🔑 <code>{html.escape(wallet_addr[:8])}...</code>\n"
            for pos in positions[:10]:
                card_text = _build_position_card(pos)
                keyboard = _build_sell_keyboard(pos["token_address"], user_id, chat_id)
                self.send_message(chat_id, header + "\n" + card_text, keyboard)
                header = ""  # Only show header on first card
            return

        if text == "/portfolio":
            result = self._table("telegram_users").select("user_id").eq(
                "telegram_chat_id", chat_id
            ).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "❌ Not connected. Use /start first.")
                return
            from services.paper_trading_manager import get_paper_trading_manager
            ptm = get_paper_trading_manager()
            positions = ptm.get_portfolio(result.data[0]["user_id"])
            if not positions:
                self.send_message(chat_id, "📊 No open positions.")
                return
            lines = ["<b>Portfolio</b>", ""]
            total_invested = 0.0
            total_value = 0.0
            for pos in positions[:15]:
                symbol = html.escape(pos.get("token_symbol") or "???")
                invested = float(pos.get("total_invested_usd") or 0)
                current = float(pos.get("current_value_usd") or invested)
                pnl_pct = ((current / invested) - 1) * 100 if invested > 0 else 0
                dot = _pnl_dot(pnl_pct)
                lines.append(f"{dot} <b>${symbol}</b> — ${current:,.0f} ({pnl_pct:+.0f}%)")
                total_invested += invested
                total_value += current
            total_pnl = total_value - total_invested
            lines.append(f"\n<b>Total:</b> ${total_value:,.0f} (PnL: ${total_pnl:+,.0f})")
            self.send_message(chat_id, "\n".join(lines))
            return

        if text == "/pnl":
            result = self._table("telegram_users").select("user_id").eq(
                "telegram_chat_id", chat_id
            ).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "❌ Not connected. Use /start first.")
                return
            from services.paper_trading_manager import get_paper_trading_manager
            ptm = get_paper_trading_manager()
            summary = ptm.get_pnl_summary(result.data[0]["user_id"])
            win_rate = summary.get("win_rate", 0)
            self.send_message(
                chat_id,
                "<b>PnL Summary</b>\n\n"
                f"Total invested: <b>${summary.get('total_invested', 0):,.2f}</b>\n"
                f"Current value: <b>${summary.get('current_total_value', 0):,.2f}</b>\n"
                f"Total PnL: <b>${summary.get('total_pnl', 0):+,.2f}</b>\n"
                f"Win/Loss: <b>{summary.get('win_count', 0)}W / {summary.get('loss_count', 0)}L</b>\n"
                f"Win rate: <b>{win_rate:.0f}%</b>",
            )
            return

        if text == "/history":
            result = self._table("telegram_users").select("user_id").eq(
                "telegram_chat_id", chat_id
            ).limit(1).execute()
            if not result.data:
                self.send_message(chat_id, "❌ Not connected. Use /start first.")
                return
            from services.paper_trading_manager import get_paper_trading_manager
            ptm = get_paper_trading_manager()
            trades = ptm.get_trade_history(result.data[0]["user_id"], limit=10)
            if not trades:
                self.send_message(chat_id, "📜 No trade history yet.")
                return
            lines = ["<b>Recent Trades</b>", ""]
            for t in trades:
                side = (t.get("side") or "buy").upper()
                symbol = html.escape(t.get("token_symbol") or "???")
                amount = float(t.get("usd_amount") or 0)
                created = t.get("created_at", "")[:10]
                lines.append(f"• {side} <b>${symbol}</b> — ${amount:,.0f} ({created})")
            self.send_message(chat_id, "\n".join(lines))
            return

        if text == "/help":
            self.send_message(
                chat_id,
                "<b>Sifter KYS Bot Commands</b>\n\n"
                "<b>Trading</b>\n"
                "/autotrade on|off|status\n"
                "/setamount 200\n"
                "/setmax 500\n"
                "/stop — disable auto-trade\n\n"
                "<b>Wallet</b>\n"
                "/importwallet — import trading wallet\n"
                "/mywallet — show linked wallet\n\n"
                "<b>Positions</b>\n"
                "/mypositions — positions with sell buttons\n"
                "/portfolio — portfolio overview\n"
                "/pnl — profit/loss summary\n"
                "/history — recent trades\n\n"
                "<b>Paper Trading</b>\n"
                "/paper_status\n"
                "/paper_start /paper_stop\n"
                "/paper_logs /paper_failures\n"
                "/paper_test\n\n"
                "<b>Settings</b>\n"
                "/settings\n"
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
        elif data.startswith("sell|"):
            parts = data.split("|")
            if len(parts) == 4:
                _, owner_chat_id, token_address, pct_str = parts
                if chat_id != owner_chat_id:
                    self._make_request(
                        "answerCallbackQuery",
                        {"callback_query_id": query_id, "text": "❌ Not your button.", "show_alert": True},
                    )
                    return
                try:
                    pct = int(pct_str)
                except ValueError:
                    self._make_request("answerCallbackQuery", {"callback_query_id": query_id})
                    return

                # Look up user_id
                user_result = self._table("telegram_users").select("user_id").eq(
                    "telegram_chat_id", chat_id
                ).limit(1).execute()
                if not user_result.data:
                    self._make_request(
                        "answerCallbackQuery",
                        {"callback_query_id": query_id, "text": "❌ User not found.", "show_alert": True},
                    )
                    return

                user_id = user_result.data[0]["user_id"]
                from services.paper_trading_manager import get_paper_trading_manager
                ptm = get_paper_trading_manager()

                if pct >= 100:
                    success = ptm.close_position(user_id, token_address)
                    result_text = "✅ Position closed." if success else "❌ Failed to close position."
                else:
                    result = ptm.partial_close_position(user_id, token_address, pct, reason="telegram_sell")
                    sold_value = result.get("sol_received", 0)
                    result_text = f"✅ Sold {pct}% — ${sold_value:,.2f}" if sold_value > 0 else f"❌ Failed to sell {pct}%."

                self._make_request(
                    "answerCallbackQuery",
                    {"callback_query_id": query_id, "text": result_text, "show_alert": True},
                )
                # Edit the message to show result
                message_id = query.get("message", {}).get("message_id")
                if message_id:
                    self._make_request("editMessageText", {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": f"{result_text}\n\nToken: <code>{token_address[:12]}...</code>",
                        "parse_mode": "HTML",
                    })
            else:
                self._make_request("answerCallbackQuery", {"callback_query_id": query_id})
        else:
            self._make_request("answerCallbackQuery", {"callback_query_id": query_id})

    def _handle_wallet_key_message(self, chat_id: str, raw_text: str, message: dict):
        """Process a private key message during wallet import flow."""
        # Remove pending state immediately
        _wallet_import_pending.pop(chat_id, None)

        # Delete the message containing the key for security
        message_id = message.get("message_id")
        if message_id:
            self._make_request("deleteMessage", {
                "chat_id": chat_id,
                "message_id": message_id,
            })

        # Decode the private key
        try:
            raw_bytes = _decode_solana_private_key(raw_text)
        except ValueError as e:
            self.send_message(chat_id, f"❌ <b>Invalid key:</b> {html.escape(str(e))}\n\nUse /importwallet to try again.")
            return

        # Encrypt the key
        try:
            encrypted = _encrypt_private_key(raw_bytes)
        except Exception as e:
            logger.error(f"[TELEGRAM] Encryption error: {e}")
            self.send_message(chat_id, "❌ Encryption failed. Contact support.")
            return

        # Derive public address from the key
        try:
            import base58
            # For Solana, if 64 bytes the first 32 are the secret key, last 32 are public key
            if len(raw_bytes) == 64:
                public_key_bytes = raw_bytes[32:]
            else:
                # 32-byte secret key — derive pubkey via ed25519
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
                private_key = Ed25519PrivateKey.from_private_bytes(raw_bytes[:32])
                public_key_bytes = private_key.public_key().public_bytes_raw()
            wallet_address = base58.b58encode(public_key_bytes).decode()
        except Exception as e:
            logger.error(f"[TELEGRAM] Pubkey derivation error: {e}")
            self.send_message(chat_id, "❌ Could not derive wallet address. Invalid key format.")
            return

        # Look up user_id from telegram_users
        result = self._table("telegram_users").select("user_id").eq(
            "telegram_chat_id", chat_id
        ).limit(1).execute()
        if not result.data:
            self.send_message(chat_id, "❌ Not connected. Use /start first, then try /importwallet again.")
            return

        user_id = result.data[0]["user_id"]

        # Upsert wallet info
        try:
            self._table("telegram_users").update({
                "encrypted_private_key": encrypted,
                "wallet_address": wallet_address,
                "wallet_imported": True,
            }).eq("user_id", user_id).execute()
        except Exception as e:
            logger.error(f"[TELEGRAM] Wallet upsert error: {e}")
            self.send_message(chat_id, "❌ Failed to save wallet. Please try again.")
            return

        self.send_message(
            chat_id,
            "✅ <b>Wallet imported successfully!</b>\n\n"
            f"Address: <code>{wallet_address}</code>\n\n"
            "Your private key has been encrypted and the original message deleted.",
        )

    def show_settings(self, chat_id: str, user_id: str) -> bool:
        try:
            result = self._table("telegram_users").select(
                "auto_trade_enabled, auto_trade_max_usd, alerts_enabled"
            ).eq("user_id", user_id).limit(1).execute()
            if result.data:
                row = result.data[0]
                text = (
                    f"\u2699\ufe0f <b>Settings</b>\n\n"
                    f"Alerts: {'ON' if row.get('alerts_enabled', True) else 'OFF'}\n"
                    f"Auto-trade: {'ON' if row.get('auto_trade_enabled', False) else 'OFF'}\n"
                    f"Max per trade: ${float(row.get('auto_trade_max_usd', 100)):.0f}"
                )
            else:
                text = "\u2699\ufe0f <b>Settings</b>\n\nNo Telegram settings found yet."
            return self.send_message(chat_id, text)
        except Exception:
            return self.send_message(chat_id, "\u2699\ufe0f <b>Settings</b>\n\nUnable to load settings.")

    def generate_connection_code(self, user_id: str) -> str:
        return secrets.token_hex(3).upper()

    def send_raw_message(self, chat_id: str, text: str, reply_markup: dict = None) -> bool:
        return self.send_message(chat_id, text, reply_markup)

    def _handle_operator_command(self, chat_id: str, command: str):
        if not is_operator_chat_id(chat_id):
            self.send_message(chat_id, "<b>Operator access required.</b>")
            return

        runtime = get_paper_trade_runtime()
        from services.paper_trader import PaperTrader

        trader = PaperTrader()

        if command == "/paper_start":
            runtime.start_run(source="telegram")
            self.send_message(chat_id, "<b>Paper trader started.</b>")
            return

        if command == "/paper_stop":
            runtime.stop_run(reason="telegram")
            self.send_message(chat_id, "<b>Paper trader stopped.</b>")
            return

        if command == "/paper_test":
            signal = {
                "source": "elite15",
                "side": "buy",
                "token_address": "So11111111111111111111111111111111111111112",
                "token_ticker": "TEST",
                "signal_key": f"telegram-test:{int(datetime.now(timezone.utc).timestamp())}",
                "wallet_count": 1,
                "total_usd": 250,
                "trades": [{"usd_value": 250}],
                "wallets": [{"wallet": "telegram-operator", "tier": "S"}],
            }
            trader.process_signal(signal)
            self.send_message(chat_id, "<b>Test paper signal submitted.</b>")
            return

        if command == "/paper_logs":
            logs = runtime.recent_logs(limit=8)
            if not logs:
                self.send_message(chat_id, "<b>Recent logs</b>\n\nNo logs yet.")
                return
            lines = ["<b>Recent paper logs</b>", ""]
            for row in logs:
                lines.append(
                    f"{html.escape(str(row.get('severity', 'info')).upper())} "
                    f"{html.escape(str(row.get('component', 'paper')))}: "
                    f"{html.escape(str(row.get('message', ''))[:120])}"
                )
            self.send_message(chat_id, "\n".join(lines))
            return

        if command == "/paper_failures":
            report = trader.get_failure_report()
            issues = report.get("issues") or []
            actions = report.get("actions") or []
            lines = [
                "<b>Paper trader failure report</b>",
                "",
                f"Issues found: <b>{int(report.get('issues_found') or 0)}</b>",
            ]
            if issues:
                lines.append("Issues: " + html.escape(", ".join(issues)))
            if actions:
                lines.append("Next: " + html.escape(actions[0]))
            self.send_message(chat_id, "\n".join(lines))
            return

        status = runtime.get_status()
        summary = trader.get_summary()
        settings = status.get("settings", {})
        signals = summary.get("signals", {})
        portfolio = summary.get("portfolio", {})
        lines = [
            "<b>Paper trader status</b>",
            "",
            f"Runtime: <b>{'ON' if settings.get('paper_trader_enabled') else 'OFF'}</b>",
            f"Open run: <b>{'yes' if status.get('active_run') else 'no'}</b>",
            f"Signals seen: <b>{signals.get('seen', 0)}</b>",
            f"Entries: <b>{signals.get('entered', 0)}</b>",
            f"Skipped: <b>{signals.get('skipped', 0)}</b>",
            f"Cash: <b>${float(portfolio.get('available_cash_usd', 0) or 0):,.2f}</b>",
            f"PnL: <b>${float(portfolio.get('realized_pnl_usd', 0) or 0):,.2f}</b>",
        ]
        self.send_message(chat_id, "\n".join(lines))
