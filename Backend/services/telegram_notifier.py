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
from services.paper_trade_runtime import get_paper_trade_runtime, is_operator_chat_id

logger = logging.getLogger(__name__)

# ── Module-level helpers ──────────────────────────────────────────────────────
# Note: navigation/awaited-input state lives in Redis (services/bot_state.py).
# The wallet-import flow uses awaiting="wallet_private_key" there.

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

    def configure_bot_ui(self) -> None:
        """Register the bot's command list, description, and menu button with
        Telegram. Idempotent — safe to call on every startup. Best-effort: a
        failed call here must never block boot.
        """
        commands = [
            {"command": "menu", "description": "Open the main menu"},
            {"command": "help", "description": "How to use the bot"},
            {"command": "cancel", "description": "Cancel the current step"},
            {"command": "start", "description": "Connect or restart"},
        ]
        description = (
            "Solana copy-trading, powered by Elite 15 wallet intelligence.\n\n"
            "• Auto-trade smart money signals\n"
            "• Set your own SL, TP & consensus filters\n"
            "• Manual trade any token\n"
            "• Full portfolio & PnL tracking\n\n"
            "New? /start — Already a member? /menu"
        )
        short_description = (
            "Solana copy-trading bot. Track Elite smart money wallets, "
            "auto-trade signals & manage positions."
        )
        try:
            self._make_request("setMyCommands", {"commands": commands})
            # Native menu button stays the command list — a sensible fallback
            # alongside the in-chat persistent ☰ Menu / ❓ Help keyboard.
            self._make_request("setChatMenuButton", {"menu_button": {"type": "commands"}})
            self._make_request("setMyDescription", {"description": description})
            self._make_request("setMyShortDescription", {"short_description": short_description})
            print("[TELEGRAM] ✅ Bot UI configured (commands, description, menu button)")
        except Exception as e:
            logger.error("[TELEGRAM] configure_bot_ui failed: %s", e)

    def _table(self, name: str):
        return self.supabase.schema(self.schema).table(name)

    def _make_request(self, method: str, data: dict = None) -> dict:
        """Call Telegram Bot API with exponential-backoff retries."""
        import time as _time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(f"{self.base_url}/{method}", json=data, timeout=10)
                result = response.json()
                # If Telegram rate-limits us, wait and retry
                if not result.get("ok") and result.get("error_code") == 429:
                    retry_after = int(result.get("parameters", {}).get("retry_after", 2 ** attempt))
                    _time.sleep(retry_after)
                    continue
                return result
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt < max_retries - 1:
                    _time.sleep(2 ** attempt)
                    continue
                logger.error(f"[TELEGRAM] API error after {max_retries} retries: {e}")
                return {"ok": False, "error": str(e)}
            except Exception as e:
                logger.error(f"[TELEGRAM] API error: {e}")
                return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "max_retries_exceeded"}

    def _is_operator(self, chat_id: str) -> bool:
        """Check if chat_id belongs to an operator."""
        try:
            from config import Config
            cid = int(chat_id)
            return cid in (Config.TELEGRAM_OPERATOR_CHAT_IDS or []) or cid in (Config.TELEGRAM_OPERATOR_USER_IDS or [])
        except (ValueError, AttributeError):
            return False

    def _notify_paper_trade_event(self, user_id: str, event_type: str, details: dict) -> None:
        """Log paper trade events for operator review. Does NOT notify users.

        Paper trades are simulated for operator evaluation only. Real user
        notifications come from bot_position_monitor and bot_autotrade.
        """
        symbol = details.get("token_symbol", "???")
        logger.info(
            "[PAPER_TRADE] user=%s event=%s symbol=%s details=%s",
            user_id, event_type, symbol, details,
        )

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

    def send_document(self, chat_id: str, file_bytes: bytes, filename: str = "file.csv") -> bool:
        """Send a file via Telegram Bot API sendDocument (multipart/form-data)."""
        import requests as _requests
        url = f"https://api.telegram.org/bot{self._token}/sendDocument"
        try:
            resp = _requests.post(
                url,
                data={"chat_id": chat_id, "parse_mode": "HTML"},
                files={"document": (filename, file_bytes, "text/csv")},
                timeout=30,
            )
            return resp.json().get("ok", False)
        except Exception:
            return False

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

            # Unlink this chat_id from any other user first (unique constraint)
            self._table("telegram_users").update({
                "telegram_chat_id": None,
                "telegram_username": None,
                "connected_at": None,
            }).eq("telegram_chat_id", str(telegram_chat_id)).neq("user_id", user_id).execute()

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
                self._table("telegram_users").insert({
                    "user_id": user_id,
                    **payload,
                    "auto_trade_enabled": False,
                    "auto_trade_max_usd": 100,
                    "auto_trade_source": "elite15",
                    "auto_trade_hourly_limit": 5,
                    "auto_trade_daily_limit": 20,
                }).execute()

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

        token = payload.get("token", {})
        # Token-level rug gate — never notify on an unsafe token. A fake/rugged
        # "Elite bought X" alert is itself bait, so we suppress it.
        try:
            from services.bot_security import check_token_safety
            sec_ok, sec_reason = check_token_safety(token.get("address") or "")
            if not sec_ok:
                logger.debug(
                    "[NOTIFY] elite15 alert suppressed token=%s reason=%s",
                    str(token.get("address"))[:8], sec_reason,
                )
                return False
        except Exception:
            return False  # fail closed — no alert on an unverifiable token

        action = payload.get("action", "buy").upper()
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

        # Token-level rug gate — suppress alerts for unsafe tokens.
        try:
            from services.bot_security import check_token_safety
            sec_ok, sec_reason = check_token_safety(signal.get("token_address") or "")
            if not sec_ok:
                logger.debug(
                    "[NOTIFY] multi-wallet alert suppressed token=%s reason=%s",
                    str(signal.get("token_address"))[:8], sec_reason,
                )
                return False
        except Exception:
            return False  # fail closed

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
            # Route through the bot execution boundary. The selected mode
            # (Config.BOT_EXECUTION_MODE) decides what actually happens:
            #   safe_noop → record only (no funds, no key decryption)
            #   paper     → realistic simulated fill
            #   devnet/live → real Jupiter swap (key decrypted there only)
            from services.bot_execution import BotTradeRequest, get_bot_executor

            # Look up the bot wallet's public key for live routing (no key
            # material is decrypted here — that happens inside the live adapter
            # only when the mode requires it).
            public_key = None
            try:
                result = self._table("bot_wallets").select("public_key").eq(
                    "user_id", user_id
                ).limit(1).execute()
                if result.data:
                    public_key = result.data[0].get("public_key")
            except Exception:
                public_key = None

            execution = get_bot_executor().execute(
                BotTradeRequest(
                    user_id=user_id,
                    token_address=token_address,
                    side=side,
                    requested_usd=usd_amount,
                    trigger_type="auto_elite",
                    wallet_public_key=public_key,
                )
            )
            if execution.status == "filled":
                return execution.txid
            logger.warning(
                "[BOT TRADE] execution rejected at %s: %s",
                execution.stage,
                execution.reason,
            )
            return None
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

        # ── Persistent reply-keyboard buttons ────────────────────────────
        # The ☰ Menu / ❓ Help bar sends its label as plain text. Map those
        # to the menu actions before any other dispatch.
        try:
            from services import bot_screens, bot_handlers
            if text == bot_screens.MENU_BTN_LABEL:
                bot_handlers._open_main(self, chat_id)
                return
            if text == bot_screens.HELP_BTN_LABEL:
                body, keyboard = bot_screens.render_help()
                self.send_message(chat_id, body, keyboard)
                return
        except Exception as e:
            logger.error("[TELEGRAM] reply-keyboard dispatch error: %s", e)

        # ── New menu system (additive, backward-compatible) ──────────────
        # 1. Consume awaited free-text input (only fires when bot_state has an
        #    `awaiting` set). Returns False otherwise → fall through to legacy.
        # 2. New menu commands (e.g. /menu). handle_command self-guards and
        #    returns False for anything it doesn't own → fall through to legacy.
        try:
            from services import bot_handlers
            if bot_handlers.handle_text_input(self, chat_id, text, message):
                return
            if bot_handlers.handle_command(self, chat_id, text, message):
                return
        except Exception as e:
            logger.error("[TELEGRAM] new-menu message dispatch error: %s", e)
            # Fall through to legacy handling on any error.

        # ── Redirect legacy slash commands to the new button menu ────────
        # All user-facing commands are now accessible via clickable buttons
        # in /menu. Tell the user where to find them instead of executing the
        # legacy (often paper-trading-leaking) path.
        _REDIRECTED_COMMANDS = {
            "/autotrade": "Use the Auto-Trader button in /menu to toggle, set consensus, and manage your bot.",
            "/setamount": "Use the Portfolio & Sizing button in /menu to set your trade amount.",
            "/setmax": "Use the Portfolio & Sizing button in /menu to configure your deployment limits.",
            "/settings": "Use the Settings button in /menu to adjust your strategy, sizing, and notifications.",
            "/importwallet": "Use the My Wallets button in /menu → Import Trading Wallet.",
            "/mywallet": "Use the My Wallets button in /menu to view your wallets.",
            "/stop": "Use the Pause Bot button on the Auto-Trader dashboard in /menu.",
            "/mypositions": "Use the Active Trades button in /menu to view and manage your positions.",
            "/portfolio": "Use the Auto-Trader dashboard in /menu for your portfolio overview.",
            "/pnl": "Use the Auto-Trader dashboard in /menu for your PnL summary.",
            "/history": "Use the Trade History button in /menu to view your closed trades.",
        }
        cmd_key = text.split()[0].lower() if text else ""
        if cmd_key in _REDIRECTED_COMMANDS:
            self.send_message(chat_id, _REDIRECTED_COMMANDS[cmd_key])
            try:
                from services import bot_handlers
                bot_handlers.handle_command(self, chat_id, "/menu", message)
            except Exception:
                pass
            return

        if text.startswith("/start "):
            token = text.split(" ", 1)[1]

            # ── Email/magic deep-link prefixes ───────────────────────────
            # TRADE_<ca>  → open manual-trade preview for that token
            # SESSION_<chat_id> → restore the user's session (from email footer)
            # MAGIC-<token> → redeem a magic access link
            if token.startswith("TRADE_"):
                ca = token[len("TRADE_"):]
                try:
                    from services import bot_handlers, bot_state
                    if bot_handlers._load_user_ctx(self, chat_id):
                        bot_state.set_awaiting(chat_id, None)
                        bot_handlers._open_manual_preview(self, chat_id, ca)
                    else:
                        bot_handlers._open_welcome(self, chat_id)
                    return
                except Exception as e:
                    logger.error("[TELEGRAM] TRADE_ deep link failed: %s", e)
                    self.send_message(chat_id, "Could not open that trade. Use /menu.")
                    return
            if token.startswith("SESSION_"):
                try:
                    from services import bot_handlers
                    if bot_handlers._load_user_ctx(self, chat_id):
                        bot_handlers._open_main(self, chat_id)
                    else:
                        bot_handlers._open_welcome(self, chat_id)
                    return
                except Exception as e:
                    logger.error("[TELEGRAM] SESSION_ deep link failed: %s", e)
                    return
            if token.startswith("MAGIC-") or token.startswith("MAGIC_"):
                magic_token = token[len("MAGIC-"):] if token.startswith("MAGIC-") else token[len("MAGIC_"):]
                try:
                    from services import bot_handlers
                    bot_handlers.handle_text_input(self, chat_id, f"MAGIC-{magic_token}", message)
                    return
                except Exception as e:
                    logger.error("[TELEGRAM] MAGIC deep link failed: %s", e)

            user_id = self.verify_connection_token(token, chat_id, username, first_name, last_name)
            if user_id:
                # Land the freshly-linked user on the new menu.
                try:
                    from services import bot_handlers, bot_state
                    bot_state.clear_state(chat_id)
                    bot_handlers._open_main(self, chat_id)
                    return
                except Exception as e:
                    logger.error("[TELEGRAM] post-link menu open failed: %s", e)
                self.send_message(
                    chat_id,
                    "\u2705 <b>Connected!</b>\n\n"
                    "Your Sifter account is now linked.\n\n"
                    "Send /menu to open the bot.",
                )
            else:
                self.send_message(chat_id, "\u274c <b>Link failed.</b> Generate a new link from the dashboard.")
            return

        if text == "/start":
            try:
                from services import bot_handlers, bot_state
                # If user is already linked, restore their session instead of
                # kicking them back to Welcome.
                ctx = bot_handlers._load_user_ctx(self, chat_id)
                if ctx:
                    # Resume the user where they left off (last screen in Redis),
                    # falling back to the main menu for fresh/transient screens.
                    last_screen = bot_state.get_state(chat_id).get("screen")
                    bot_handlers.reopen_screen(self, chat_id, last_screen)
                    return
                # Truly new user — show Welcome.
                bot_state.clear_state(chat_id)
                bot_handlers._open_welcome(self, chat_id)
                return
            except Exception as e:
                logger.error("[TELEGRAM] welcome screen open failed: %s", e)
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
                self.send_message(chat_id, "🔒 Operator access required.")
                return
            self._get_redis().set("sifter:kill_switch", "1")
            self.send_message(chat_id, "🛑 <b>Kill switch ACTIVATED.</b> All auto-trading halted.")
            return

        if text == "/resume":
            if not self._is_operator(chat_id):
                self.send_message(chat_id, "🔒 Operator access required.")
                return
            self._get_redis().delete("sifter:kill_switch")
            self.send_message(chat_id, "✅ <b>Kill switch CLEARED.</b> Auto-trading resumed.")
            return

        if text == "/sys":
            if not self._is_operator(chat_id):
                self.send_message(chat_id, "🔒 Operator access required.")
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
            self.op_open_positions(chat_id)
            return

        if text == "/closeall":
            if not self._is_operator(chat_id):
                self.send_message(chat_id, "🔒 Operator access required.")
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
                self.send_message(chat_id, "🔒 Operator access required.")
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
            self.op_paper_stats(chat_id)
            return

        if text == "/users":
            self.op_users_report(chat_id)
            return

        if text == "/digest":
            self.op_queue_digest(chat_id)
            return

        # ── User commands ─────────────────────────────────────────────────────
        if text == "/importwallet":
            # DM-only check
            if message["chat"].get("type") != "private":
                self.send_message(chat_id, "⚠️ For security, use this command in a <b>direct message</b> to the bot.")
                return
            from services import bot_state
            bot_state.set_awaiting(chat_id, "wallet_private_key")
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
            from services import bot_state
            bot_state.clear_state(chat_id)
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
            try:
                from services import bot_screens
                body, keyboard = bot_screens.render_help()
                self.send_message(chat_id, body, keyboard)
                return
            except Exception as e:
                logger.error("[TELEGRAM] menu help failed: %s", e)
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

        # ── New menu system (additive) ───────────────────────────────────
        # Legacy callback formats keep their exact behavior below; only NEW
        # pipe-delimited categories are routed to the menu handlers. Anything
        # unrecognized falls through to the legacy no-op.
        if not (data.startswith("cp_p:") or data.startswith("cp_b:") or data.startswith("sell|")):
            parts = data.split("|")
            if len(parts) >= 2:
                try:
                    from services import bot_handlers
                    if parts[0] in bot_handlers.NEW_CATEGORIES:
                        bot_handlers.handle_callback(
                            self, chat_id, query, parts[0], parts[1], parts[2:]
                        )
                        return
                except Exception as e:
                    logger.error("[TELEGRAM] new-menu callback dispatch error: %s", e)
                    self._make_request("answerCallbackQuery", {"callback_query_id": query_id})
                    return

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
                # Route through BotExecutionRouter (NOT paper trading)
                from services.bot_execution import BotTradeRequest, get_bot_executor
                from services.bot_handlers import _acquire_action_lock

                if not _acquire_action_lock(owner_chat_id, f"legacy_sell:{token_address}"):
                    self._make_request(
                        "answerCallbackQuery",
                        {"callback_query_id": query_id, "text": "Already processing.", "show_alert": True},
                    )
                    return

                # Look up the open position for this user+token
                pos_res = self._table("bot_live_positions").select("*").eq(
                    "user_id", user_id
                ).eq("token_address", token_address).eq("status", "open").limit(1).execute()
                position = pos_res.data[0] if pos_res.data else None

                if not position:
                    self._make_request(
                        "answerCallbackQuery",
                        {"callback_query_id": query_id, "text": "No open position found for this token.", "show_alert": True},
                    )
                    return

                req = BotTradeRequest(
                    user_id=user_id,
                    token_address=token_address,
                    token_symbol=position.get("token_symbol"),
                    side="sell",
                    requested_usd=float(position.get("current_value_usd") or position.get("total_invested_usd") or 0) * (pct / 100.0),
                    sell_pct=pct,
                    trigger_type="manual",
                    signal_key=position.get("signal_key"),
                    snapshot={"price": float(position.get("avg_entry_price") or 1.0)},
                    settings={"stop_loss_pct": position.get("stop_loss_pct"), "take_profit_x": position.get("take_profit_x")},
                )
                result = get_bot_executor().execute(req)
                if result.status == "filled":
                    result_text = f"✅ Sold {pct}% — TX: {result.txid[:8]}..." if result.txid else f"✅ Sold {pct}%."
                else:
                    result_text = f"❌ Sell did not execute: {result.reason or result.message}"

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
        """Process a private key message during wallet import flow.

        Called by bot_handlers.handle_text_input when awaiting='wallet_private_key';
        the awaited state is already cleared by the caller.
        """
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

    # ── Operator reports (shared by slash commands and Operator Panel buttons) ──
    def op_open_positions(self, chat_id: str) -> None:
        """Show open paper positions. Operator-gated."""
        if not self._is_operator(chat_id):
            self.send_message(chat_id, "🔒 Operator access required.")
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

    def op_paper_stats(self, chat_id: str) -> None:
        """Show paper-trading daily stats. Operator-gated."""
        if not self._is_operator(chat_id):
            self.send_message(chat_id, "🔒 Operator access required.")
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

    def op_users_report(self, chat_id: str) -> None:
        """Show connected Telegram user counts. Operator-gated."""
        if not self._is_operator(chat_id):
            self.send_message(chat_id, "🔒 Operator access required.")
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

    def op_queue_digest(self, chat_id: str) -> None:
        """Queue the daily digest Celery task. Operator-gated."""
        if not self._is_operator(chat_id):
            self.send_message(chat_id, "🔒 Operator access required.")
            return
        try:
            from services.tasks import send_daily_digest
            send_daily_digest.delay()
            self.send_message(chat_id, "✅ <b>Daily digest task queued.</b>")
        except Exception as e:
            self.send_message(chat_id, f"❌ Failed to queue digest: <code>{html.escape(str(e)[:100])}</code>")

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
