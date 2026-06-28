#!/usr/bin/env python3
"""
Register/verify the Telegram bot webhook + command menu.

Idempotent — safe to re-run any time (after a token rotation, server move, or
if the webhook drifts). This is the reproducible replacement for the one-off
`curl ... setWebhook` that the bot previously relied on.

Usage (from Backend/ directory):
    python scripts/setup_telegram_webhook.py            # set webhook + register menu, then verify
    python scripts/setup_telegram_webhook.py --info     # show current getWebhookInfo
    python scripts/setup_telegram_webhook.py --delete    # remove the webhook
    python scripts/setup_telegram_webhook.py --no-menu   # set webhook only, skip setMyCommands

Requires in .env / environment:
    TELEGRAM_BOT_TOKEN       (required)
    TELEGRAM_SECRET_TOKEN    (required — echoed in X-Telegram-Bot-Api-Secret-Token; webhook fails closed without it)
    TELEGRAM_WEBHOOK_URL     (optional — defaults to the prod duckdns endpoint)
"""
from __future__ import annotations
import os
import sys

# Add Backend dir to path so `config` / `services` import cleanly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN", "")
WEBHOOK_URL = os.environ.get(
    "TELEGRAM_WEBHOOK_URL", "https://sifter-kys.duckdns.org/api/telegram/webhook"
)
# Subscribe to my_chat_member too so the bot learns when users block/unblock or
# start/stop it (the previous manual setup only had message + callback_query).
ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _api(method: str, payload: dict | None = None) -> dict:
    resp = requests.post(f"{API_BASE}/{method}", json=payload or {}, timeout=15)
    try:
        return resp.json()
    except ValueError:
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}


def show_info() -> dict:
    info = _api("getWebhookInfo").get("result", {})
    print("Current webhook:")
    print(f"  url:                  {info.get('url') or '(none)'}")
    print(f"  pending_update_count: {info.get('pending_update_count')}")
    print(f"  ip_address:           {info.get('ip_address')}")
    print(f"  max_connections:      {info.get('max_connections')}")
    print(f"  allowed_updates:      {info.get('allowed_updates')}")
    if info.get("last_error_message"):
        print(f"  ⚠️ last_error:        {info.get('last_error_message')} (at {info.get('last_error_date')})")
    return info


def delete_webhook() -> None:
    res = _api("deleteWebhook", {"drop_pending_updates": False})
    print("deleteWebhook:", "ok" if res.get("ok") else res)


def set_webhook() -> None:
    res = _api(
        "setWebhook",
        {
            "url": WEBHOOK_URL,
            "secret_token": SECRET_TOKEN,
            "allowed_updates": ALLOWED_UPDATES,
            "drop_pending_updates": False,
            "max_connections": 40,
        },
    )
    if res.get("ok"):
        print(f"SUCCESS: webhook set → {WEBHOOK_URL}")
    else:
        print(f"ERROR setting webhook: {res}")
        sys.exit(1)


def configure_menu() -> None:
    """Register the command list + menu button via the notifier (single source of truth)."""
    try:
        from services.telegram_notifier import TelegramNotifier
        TelegramNotifier(BOT_TOKEN).configure_bot_ui()
    except Exception as exc:  # never fail the webhook setup over menu config
        print(f"WARNING: configure_bot_ui failed: {exc}")


def main() -> None:
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    # Confirm the token is live before doing anything.
    me = _api("getMe")
    if not me.get("ok"):
        print(f"ERROR: token invalid/revoked — {me.get('description', me)}")
        sys.exit(1)
    print(f"Bot: @{me['result'].get('username')} (id {me['result'].get('id')})")

    if "--info" in sys.argv:
        show_info()
        return
    if "--delete" in sys.argv:
        delete_webhook()
        return

    if not SECRET_TOKEN:
        print(
            "ERROR: TELEGRAM_SECRET_TOKEN not set — the webhook handler fails closed "
            "without it, so registering would make every update get rejected. Set it first."
        )
        sys.exit(1)

    set_webhook()
    if "--no-menu" not in sys.argv:
        configure_menu()

    print("\nVerifying:")
    info = show_info()
    if info.get("url") != WEBHOOK_URL:
        print("⚠️ Webhook URL mismatch after set — check for errors above.")
        sys.exit(1)
    print("\n✅ Telegram webhook is registered and healthy.")


if __name__ == "__main__":
    main()
