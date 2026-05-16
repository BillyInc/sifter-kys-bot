#!/usr/bin/env python3
"""
Register a Helius webhook for Elite wallet SWAP monitoring.

Usage:
    HELIUS_API_KEY=xxx WEBHOOK_URL=https://your-domain.com/api/webhooks/helius \
        python scripts/register_helius_webhook.py

Requires:
    - HELIUS_API_KEY: Your Helius API key
    - WEBHOOK_URL: Public URL where Helius will POST events
    - HELIUS_WEBHOOK_SECRET (optional): Secret to set for auth header verification
"""
from __future__ import annotations
import json, os, sys
import requests

HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
WEBHOOK_SECRET = os.environ.get("HELIUS_WEBHOOK_SECRET", "")

# Placeholder — replace with actual Elite wallet addresses
ELITE_WALLETS: list[str] = [
    # "WalletAddress1...",
    # "WalletAddress2...",
]


def register_webhook():
    if not HELIUS_API_KEY:
        print("ERROR: HELIUS_API_KEY not set")
        sys.exit(1)
    if not WEBHOOK_URL:
        print("ERROR: WEBHOOK_URL not set")
        sys.exit(1)
    if not ELITE_WALLETS:
        print("WARNING: ELITE_WALLETS is empty — webhook will not monitor any wallets")
        print("  Add wallet addresses to the ELITE_WALLETS list in this script")

    url = f"https://api.helius.xyz/v0/webhooks?api-key={HELIUS_API_KEY}"

    payload = {
        "webhookURL": WEBHOOK_URL,
        "transactionTypes": ["SWAP"],
        "accountAddresses": ELITE_WALLETS,
        "webhookType": "enhanced",
    }

    if WEBHOOK_SECRET:
        payload["authHeader"] = WEBHOOK_SECRET

    print(f"Registering Helius webhook...")
    print(f"  URL: {WEBHOOK_URL}")
    print(f"  Wallets: {len(ELITE_WALLETS)}")
    print(f"  Types: SWAP")
    print(f"  Auth: {'yes' if WEBHOOK_SECRET else 'no'}")

    resp = requests.post(url, json=payload)

    if resp.status_code == 200:
        data = resp.json()
        print(f"\nSUCCESS: Webhook registered")
        print(f"  Webhook ID: {data.get('webhookID', 'unknown')}")
        print(json.dumps(data, indent=2))
    else:
        print(f"\nERROR: {resp.status_code}")
        print(resp.text)
        sys.exit(1)


if __name__ == "__main__":
    register_webhook()
