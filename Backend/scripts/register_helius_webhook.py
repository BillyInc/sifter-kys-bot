#!/usr/bin/env python3
"""
Register/update a Helius webhook for Elite wallet SWAP monitoring.

Always fetches the current Elite 15 wallets from ClickHouse so the webhook
stays in sync with weekly reranking.

Usage:
    # From Backend/ directory:
    python scripts/register_helius_webhook.py          # register new
    python scripts/register_helius_webhook.py --update  # update existing webhook wallets
    python scripts/register_helius_webhook.py --list    # list existing webhooks

Requires HELIUS_API_KEY in .env or environment.
"""
from __future__ import annotations
import json, os, sys

# Add Backend dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import requests

HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")
WEBHOOK_URL = os.environ.get(
    "WEBHOOK_URL", "https://sifter-kys.duckdns.org/api/webhooks/helius"
)
WEBHOOK_SECRET = os.environ.get("HELIUS_WEBHOOK_SECRET", "")
ELITE_LIMIT = int(os.environ.get("ELITE_LIMIT", "15"))

API_BASE = "https://api.helius.xyz/v0/webhooks"


def _fetch_elite_wallets() -> list[str]:
    """Fetch top-ranked wallets from ClickHouse."""
    try:
        from services.clickhouse_client import get_clickhouse_client
        ch = get_clickhouse_client()
        if ch is None:
            raise RuntimeError("ClickHouse client unavailable")
        result = ch.query(
            f"SELECT wallet_address FROM wallet_aggregate_stats FINAL "
            f"WHERE tokens_qualified >= 1 "
            f"ORDER BY professional_score DESC LIMIT {ELITE_LIMIT}"
        )
        wallets = [r[0] for r in result.result_rows]
        if wallets:
            return wallets
    except Exception as exc:
        print(f"WARNING: Could not fetch from ClickHouse: {exc}")
    return []


def list_webhooks():
    """List all registered Helius webhooks."""
    resp = requests.get(f"{API_BASE}?api-key={HELIUS_API_KEY}")
    if resp.status_code == 200:
        hooks = resp.json()
        print(f"Found {len(hooks)} webhook(s):")
        for h in hooks:
            print(f"  ID: {h.get('webhookID')}")
            print(f"  URL: {h.get('webhookURL')}")
            print(f"  Wallets: {len(h.get('accountAddresses', []))}")
            print(f"  Types: {h.get('transactionTypes')}")
            print()
    else:
        print(f"ERROR: {resp.status_code} — {resp.text}")


def update_webhook(webhook_id: str, wallets: list[str]):
    """Update an existing webhook with new wallet addresses."""
    url = f"{API_BASE}/{webhook_id}?api-key={HELIUS_API_KEY}"
    payload = {"accountAddresses": wallets}
    resp = requests.put(url, json=payload)
    if resp.status_code == 200:
        print(f"SUCCESS: Updated webhook {webhook_id} with {len(wallets)} wallets")
    else:
        print(f"ERROR: {resp.status_code} — {resp.text}")
        sys.exit(1)


def register_webhook(wallets: list[str]):
    """Register a new Helius webhook."""
    if not HELIUS_API_KEY:
        print("ERROR: HELIUS_API_KEY not set")
        sys.exit(1)
    if not wallets:
        print("ERROR: No wallets to monitor")
        sys.exit(1)

    payload = {
        "webhookURL": WEBHOOK_URL,
        "transactionTypes": ["SWAP"],
        "accountAddresses": wallets,
        "webhookType": "enhanced",
    }
    if WEBHOOK_SECRET:
        payload["authHeader"] = WEBHOOK_SECRET

    print(f"Registering Helius webhook...")
    print(f"  URL: {WEBHOOK_URL}")
    print(f"  Wallets: {len(wallets)}")
    print(f"  Types: SWAP")
    print(f"  Auth: {'yes' if WEBHOOK_SECRET else 'no'}")

    resp = requests.post(f"{API_BASE}?api-key={HELIUS_API_KEY}", json=payload)
    if resp.status_code in (200, 201):
        data = resp.json()
        print(f"\nSUCCESS: Webhook registered")
        print(f"  Webhook ID: {data.get('webhookID', 'unknown')}")
        print(json.dumps(data, indent=2))
    else:
        print(f"\nERROR: {resp.status_code}")
        print(resp.text)
        sys.exit(1)


if __name__ == "__main__":
    if not HELIUS_API_KEY:
        print("ERROR: HELIUS_API_KEY not set")
        sys.exit(1)

    if "--list" in sys.argv:
        list_webhooks()
        sys.exit(0)

    # Always fetch fresh Elite wallets from ClickHouse
    print("Fetching Elite wallets from ClickHouse...")
    wallets = _fetch_elite_wallets()
    if not wallets:
        print("ERROR: No qualified wallets found in ClickHouse")
        sys.exit(1)
    print(f"  Found {len(wallets)} Elite wallets")
    for w in wallets:
        print(f"    {w}")

    if "--update" in sys.argv:
        # Find existing webhook and update it
        resp = requests.get(f"{API_BASE}?api-key={HELIUS_API_KEY}")
        hooks = resp.json() if resp.status_code == 200 else []
        matching = [h for h in hooks if h.get("webhookURL") == WEBHOOK_URL]
        if matching:
            update_webhook(matching[0]["webhookID"], wallets)
        else:
            print("No existing webhook found for this URL, registering new one...")
            register_webhook(wallets)
    else:
        register_webhook(wallets)
