"""
Token Discovery Pipeline (Section 5 & 6.1 of architecture doc)

Three SolanaTracker endpoints polled every 5 minutes:
  - just_graduated: tokens that just passed pump.fun graduation threshold (High priority)
  - newly_launched: brand new token launches (Medium priority)
  - trending_runners: tokens currently pumping with volume (Highest priority, second-pass)

Flow:
  1. Poll just_graduated + newly_launched -> first-pass scan
  2. Poll trending_runners -> trigger second-pass patch for pending tokens
  3. New tokens inserted into ClickHouse token_scans
  4. Wallet qualification tasks enqueued for each new token
"""
import json
import os
import time
import uuid
from datetime import datetime

import redis
import requests

from celery_app import celery
from services.clickhouse_client import get_clickhouse_client, insert_token_scans

SOLANATRACKER_BASE = "https://data.solanatracker.io"
SOLANATRACKER_KEY = os.environ.get('SOLANATRACKER_API_KEY', '')

# Redis keys
KNOWN_TOKENS_KEY = 'kys:known_tokens'        # SET of all seen token addresses (30d TTL)
PENDING_TOKENS_KEY = 'kys:pending_tokens'     # SET of tokens awaiting second-pass (30d TTL)
QUALIFIED_TOKENS_KEY = 'kys:qualified_tokens'  # SET of tokens that passed 10x filter


def get_redis():
    """Return a Redis client from the configured REDIS_URL."""
    return redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))


def fetch_solanatracker(endpoint: str) -> list:
    """Fetch from SolanaTracker API with error handling."""
    url = f"{SOLANATRACKER_BASE}/{endpoint}"
    headers = {'x-api-key': SOLANATRACKER_KEY} if SOLANATRACKER_KEY else {}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[TOKEN DISCOVERY] Error fetching {endpoint}: {e}")
        return []


def build_token_scan_row(token_data: dict, endpoint: str) -> dict:
    """Build a token_scans row from SolanaTracker response data."""
    pools = token_data.get('pools', [{}])
    pool = pools[0] if pools else {}

    token_info = token_data.get('token', token_data)
    address = token_info.get('mint', token_info.get('address', token_data.get('address', '')))

    # Price data
    price = pool.get('price', {})
    current_price = price.get('usd', 0) if isinstance(price, dict) else 0

    # Market data
    market_cap = token_data.get('marketCap', token_data.get('market_cap', 0))
    volume_24h = token_data.get('volume24h', token_data.get('volume', 0))
    liquidity = pool.get('liquidity', {}).get('usd', 0) if isinstance(pool.get('liquidity'), dict) else 0

    # ATH data (may need separate fetch)
    ath_price = token_data.get('athPrice', current_price)
    launch_price = token_data.get('launchPrice', 0)

    launch_to_ath = ath_price / launch_price if launch_price > 0 else 0
    launch_to_current = current_price / launch_price if launch_price > 0 else 0

    return {
        'token_address': address,
        'scan_id': str(uuid.uuid4()),
        'discovered_via': endpoint,
        'scan_timestamp': datetime.utcnow(),
        'launch_price': launch_price,
        'current_price': current_price,
        'ath_price': ath_price,
        'launch_to_ath_mult': launch_to_ath,
        'launch_to_current_mult': launch_to_current,
        'qualified_10x': 1 if launch_to_ath >= 10 else 0,
        'qualified_30x': 1 if launch_to_ath >= 30 else 0,
        'market_cap_usd': market_cap,
        'volume_24h_usd': volume_24h,
        'liquidity_usd': liquidity,
        'holder_count': token_data.get('holders', 0),
        'scan_window_days': 30,
        'token_symbol': token_info.get('symbol', ''),
        'token_name': token_info.get('name', ''),
    }


@celery.task(bind=True, max_retries=3, default_retry_delay=30, name='tasks.discover_new_tokens')
def discover_new_tokens(self):
    """
    Poll just_graduated, newly_launched, trending_runners.
    For each new token not already in kys:known_tokens Redis set:
      - Insert into token_scans
      - Enqueue wallet_qualification_scan task (first_pass)
    For tokens already in kys:pending_tokens that appear on trending_runners:
      - Enqueue second_pass_patch task
    """
    r = get_redis()
    scan_rows = []
    new_count = 0
    second_pass_count = 0

    # -- First-pass: just_graduated + newly_launched --
    first_pass_endpoints = [
        ('tokens/multi/graduated', 'just_graduated'),
        ('tokens/latest', 'newly_launched'),
    ]
    for api_endpoint, discovered_via in first_pass_endpoints:
        tokens = fetch_solanatracker(api_endpoint)
        time.sleep(1)  # Rate limit padding between endpoints
        for token in tokens:
            token_info = token.get('token', token)
            addr = token_info.get('mint', token_info.get('address', token.get('address', '')))
            if not addr:
                continue

            # Skip if already known
            if r.sismember(KNOWN_TOKENS_KEY, addr):
                continue

            # Mark as known (30-day TTL on the set)
            r.sadd(KNOWN_TOKENS_KEY, addr)
            r.expire(KNOWN_TOKENS_KEY, 86400 * 30)

            # Also mark as pending second-pass
            r.sadd(PENDING_TOKENS_KEY, addr)
            r.expire(PENDING_TOKENS_KEY, 86400 * 30)

            # Build scan row
            row = build_token_scan_row(token, discovered_via)
            if row['token_address']:
                scan_rows.append(row)
                new_count += 1

                # Enqueue first-pass wallet scan
                from tasks.wallet_qualification import wallet_qualification_scan
                wallet_qualification_scan.delay(addr, 'first_pass')

    # -- Second-pass: trending_runners --
    time.sleep(2)  # Rate limit padding
    runners = fetch_solanatracker('tokens/trending')
    for token in runners:
        token_info = token.get('token', token)
        addr = token_info.get('mint', token_info.get('address', token.get('address', '')))
        if not addr:
            continue

        if r.sismember(PENDING_TOKENS_KEY, addr):
            # Token was first-pass scanned, now trending -- run second pass
            from tasks.wallet_qualification import second_pass_patch
            second_pass_patch.delay(addr, token)
            second_pass_count += 1
        elif not r.sismember(KNOWN_TOKENS_KEY, addr):
            # Brand new from trending -- add and first-pass scan
            r.sadd(KNOWN_TOKENS_KEY, addr)
            r.expire(KNOWN_TOKENS_KEY, 86400 * 30)

            r.sadd(PENDING_TOKENS_KEY, addr)
            r.expire(PENDING_TOKENS_KEY, 86400 * 30)

            row = build_token_scan_row(token, 'trending_runners')
            if row['token_address']:
                scan_rows.append(row)
                new_count += 1

                from tasks.wallet_qualification import wallet_qualification_scan
                wallet_qualification_scan.delay(addr, 'first_pass')

    # Bulk insert all new token scans into ClickHouse
    if scan_rows:
        try:
            insert_token_scans(scan_rows)
        except Exception as e:
            print(f"[TOKEN DISCOVERY] ClickHouse insert error: {e}")

    result = {
        'new_tokens': new_count,
        'second_pass_triggered': second_pass_count,
        'total_scanned': len(scan_rows),
        'timestamp': datetime.utcnow().isoformat(),
    }
    print(f"[TOKEN DISCOVERY] {result}")
    return result
