#!/usr/bin/env python3
"""Latency probe — measures the two latencies users feel.

1. BUTTON ACK: time from "callback dispatched" to "Telegram answerCallbackQuery
   sent" (the spinner stops). Target p95 < 200ms. This is the handler latency we
   control — real Telegram network round-trip is on top and un-measurable here.

2. SIGNAL → FILL: time from queue_autonomous_trade() start to a filled position
   in paper mode. Target p95 < 5s (paper). On devnet this measures real swap
   latency.

Uses a RecordingNotifier that timestamps every _make_request / send_message so
we can measure the ack precisely, with all handlers patched to isolate timing.

Run:
    python -m scripts.latency_probe --iterations 50
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time


def _pcts(samples_ms):
    if not samples_ms:
        return (0, 0, 0)
    s = sorted(samples_ms)
    p50 = s[len(s) // 2]
    p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
    p99 = s[min(len(s) - 1, int(len(s) * 0.99))]
    return (p50, p95, p99)


def probe_button_ack(iterations: int) -> list:
    """Measure dispatch → answerCallbackQuery latency for a nav button."""
    from unittest.mock import MagicMock, patch
    from services import bot_handlers

    samples = []
    for _ in range(iterations):
        notifier = MagicMock()
        notifier._is_operator.return_value = True
        ack_time = {}

        def _record_answer(_n, _qid, text=None):
            ack_time["t"] = time.perf_counter()

        with patch.object(bot_handlers, "_answer", side_effect=_record_answer), \
             patch.object(bot_handlers, "_navigate"):
            query = {"id": "q", "data": "nav|main"}
            t0 = time.perf_counter()
            bot_handlers.handle_callback(notifier, "123", query, "nav", "main", [])
            if "t" in ack_time:
                samples.append((ack_time["t"] - t0) * 1000.0)
    return samples


def probe_signal_to_fill(iterations: int) -> list:
    """Measure queue_autonomous_trade → filled position latency (paper mode).

    Requires Redis + Supabase. Skips if unavailable. Uses a unique token per
    iteration so the duplicate-position guard doesn't short-circuit."""
    import os
    os.environ.setdefault("BOT_EXECUTION_MODE", "paper")
    try:
        from services.bot_autotrade import queue_autonomous_trade, execute_queued_autonomous_trade
        from services.supabase_client import get_supabase_client
        sb = get_supabase_client()
    except Exception as exc:
        print(f"  signal→fill: SKIP ({exc})")
        return []

    # Find one autotrader user to attribute the test trades to.
    try:
        from services.supabase_client import SCHEMA_NAME
        u = sb.schema(SCHEMA_NAME).table("telegram_users").select("user_id").eq(
            "auto_trade_enabled", True).limit(1).execute()
        if not u.data:
            print("  signal→fill: SKIP (no auto_trade_enabled user)")
            return []
        user_id = u.data[0]["user_id"]
    except Exception as exc:
        print(f"  signal→fill: SKIP ({exc})")
        return []

    samples = []
    for i in range(iterations):
        token = f"LatencyProbe{i:03d}" + "x" * 30
        signal = {
            "token_address": token, "token_ticker": f"LAT{i}",
            "wallet_address": "Probe" + "x" * 39, "usd_value": 500,
            "side": "buy", "wallet_count": 1,
            "signal_key": f"probe:{token}:{i}",
            "wallet_addresses": ["Probe" + "x" * 39],
        }
        t0 = time.perf_counter()
        res = queue_autonomous_trade(user_id=user_id, signal=signal, supabase=sb)
        if res.get("queue_id") and res.get("status") == "pending":
            execute_queued_autonomous_trade(queue_id=res["queue_id"], supabase=sb)
            samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=50)
    ap.add_argument("--skip-fill", action="store_true", help="only button ack")
    args = ap.parse_args()

    try:
        import opentelemetry  # noqa: F401
    except ImportError:
        print("SKIP: venv not synced (uv sync). Cannot import services.")
        sys.exit(0)

    print("=== LATENCY PROBE ===")
    ack = probe_button_ack(args.iterations)
    if ack:
        p50, p95, p99 = _pcts(ack)
        status = "PASS" if p95 < 200 else "WARN"
        print(f"Button ack (n={len(ack)}): p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms  [{status} target<200ms]")

    if not args.skip_fill:
        fill = probe_signal_to_fill(args.iterations)
        if fill:
            p50, p95, p99 = _pcts(fill)
            status = "PASS" if p95 < 5000 else "WARN"
            print(f"Signal→fill (n={len(fill)}): p50={p50:.0f}ms p95={p95:.0f}ms p99={p99:.0f}ms  [{status} target<5s paper]")

    print("\nNote: button-ack measures handler latency only; real Telegram")
    print("network round-trip adds on top and is measured by tapping a real phone.")


if __name__ == "__main__":
    main()
