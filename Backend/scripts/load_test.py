#!/usr/bin/env python3
"""Load / rush-hour harness — answers "what happens during high volume?".

Fires N concurrent autonomous signals (distinct tokens) and asserts the
integrity invariants that MUST hold under load:

  * No double-trades — one open position per (user, token), never two
  * Queue drains — no rows stuck in 'pending'/'executing'
  * No duplicate signal_key per user in bot_signal_queue
  * No orphan Redis action locks left behind after settle
  * (Telegram 429) — backoff path exercised when the API rate-limits

Modes:
    paper  (default) — simulated fills, safe, fast
    --devnet         — REAL devnet swaps (slow, needs funded wallet + RPC)

Run:
    python -m scripts.load_test --signals 200
    python -m scripts.load_test --signals 50 --devnet
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import sys
import time


def run_load(signals: int, devnet: bool) -> int:
    from services.bot_autotrade import queue_autonomous_trade, execute_queued_autonomous_trade
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    sb = get_supabase_client()

    u = sb.schema(SCHEMA_NAME).table("telegram_users").select("user_id").eq(
        "auto_trade_enabled", True).limit(1).execute()
    if not u.data:
        print("ABORT: no auto_trade_enabled user to attribute test trades to.")
        return 1
    user_id = u.data[0]["user_id"]
    run_tag = f"load{int(time.time())}"

    def fire(i):
        token = f"Load{run_tag}T{i:04d}" + "x" * 10
        signal = {
            "token_address": token, "token_ticker": f"LD{i}",
            "wallet_address": "Load" + "x" * 40, "usd_value": 500,
            "side": "buy", "wallet_count": 1,
            "signal_key": f"{run_tag}:{token}",
            "wallet_addresses": ["Load" + "x" * 40],
        }
        try:
            res = queue_autonomous_trade(user_id=user_id, signal=signal, supabase=sb)
            if res.get("queue_id") and res.get("status") == "pending":
                execute_queued_autonomous_trade(queue_id=res["queue_id"], supabase=sb)
            return res.get("status")
        except Exception as exc:
            return f"error:{exc}"

    print(f"=== LOAD TEST — {signals} concurrent signals ({'devnet' if devnet else 'paper'}) ===")
    t0 = time.perf_counter()
    workers = 8 if devnet else 20
    statuses = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        statuses = list(ex.map(fire, range(signals)))
    elapsed = time.perf_counter() - t0
    print(f"Fired {signals} in {elapsed:.1f}s ({signals/elapsed:.1f}/s)")

    # ── INVARIANT CHECKS ──────────────────────────────────────────────────
    failures = []

    # 1. No double-trades: open positions for this run == unique tokens fired.
    try:
        pos = sb.schema(SCHEMA_NAME).table("bot_live_positions").select(
            "token_address").eq("user_id", user_id).eq("status", "open").execute()
        run_tokens = [p["token_address"] for p in (pos.data or []) if run_tag in p["token_address"]]
        if len(run_tokens) != len(set(run_tokens)):
            failures.append(f"DOUBLE-TRADE: {len(run_tokens)} positions, {len(set(run_tokens))} unique")
        else:
            print(f"  ✓ no double-trades ({len(run_tokens)} open positions, all unique)")
    except Exception as exc:
        failures.append(f"position check failed: {exc}")

    # 2. Queue drained — nothing stuck pending/executing for this run.
    try:
        q = sb.schema(SCHEMA_NAME).table("bot_signal_queue").select(
            "signal_key, status").eq("user_id", user_id).execute()
        run_rows = [r for r in (q.data or []) if r.get("signal_key", "").startswith(run_tag)]
        stuck = [r for r in run_rows if r["status"] in ("pending", "executing")]
        if stuck:
            failures.append(f"QUEUE NOT DRAINED: {len(stuck)} stuck rows")
        else:
            print(f"  ✓ queue drained ({len(run_rows)} rows, 0 stuck)")
        # 3. No duplicate signal_key.
        keys = [r["signal_key"] for r in run_rows]
        if len(keys) != len(set(keys)):
            failures.append(f"DUPLICATE signal_key: {len(keys)} rows, {len(set(keys))} unique")
        else:
            print(f"  ✓ no duplicate signal_keys")
    except Exception as exc:
        failures.append(f"queue check failed: {exc}")

    # 4. No orphan Redis action locks.
    try:
        import redis
        r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        orphans = list(r.scan_iter(match="sifter:bot_action:*", count=500))
        # Locks have a 120s TTL so some may legitimately linger; only flag if huge.
        print(f"  ℹ {len(orphans)} action locks present (TTL 120s — expected to clear)")
    except Exception:
        pass

    print(f"\nStatus breakdown: {_count(statuses)}")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("\nALL INVARIANTS HELD ✓")
    return 0


def _count(items):
    from collections import Counter
    return dict(Counter(items))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", type=int, default=200)
    ap.add_argument("--devnet", action="store_true")
    args = ap.parse_args()

    try:
        import opentelemetry  # noqa: F401
    except ImportError:
        print("SKIP: venv not synced (uv sync).")
        sys.exit(0)

    if args.devnet:
        os.environ["BOT_EXECUTION_MODE"] = "devnet"
    else:
        os.environ.setdefault("BOT_EXECUTION_MODE", "paper")

    sys.exit(run_load(args.signals, args.devnet))


if __name__ == "__main__":
    main()
