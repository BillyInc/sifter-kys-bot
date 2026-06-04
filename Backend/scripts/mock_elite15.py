#!/usr/bin/env python3
"""Mock Elite 15 harness — drive the SIFTER bot against scripted scenarios.

Run the bot in PAPER mode (BOT_EXECUTION_MODE=paper), connect your real
Telegram bot, then use this CLI to seed mock Elite 15 wallets, inject buy/sell
signals, and move prices — so you can tap REAL buttons in Telegram and watch
them work against deterministic mock data.

The price oracle (set here) is read by bot_position_monitor._fetch_current_price
so TP / SL / trailing-stop fire exactly when you want them to.

USAGE
-----
  # 1. Seed 15 mock Elite wallets into the system watchlist
  python -m scripts.mock_elite15 seed

  # 2. Inject a buy signal (tier = how many wallets agree within 120s)
  python -m scripts.mock_elite15 signal --token <CA> --ticker WIF --tier 2 --usd 5000

  # 3. Move the price so the autonomous monitor reacts
  python -m scripts.mock_elite15 price --token <CA> --mult 5     # 5x entry -> TP fires
  python -m scripts.mock_elite15 price --token <CA> --mult 0.4   # -60% -> SL fires
  python -m scripts.mock_elite15 price --token <CA> --usd 0.002  # absolute price

  # 4. Elite wallet SELLS (this is a NOTIFICATION, not an auto-close)
  python -m scripts.mock_elite15 elite-sell --token <CA> --ticker WIF

  # 5. Run a full end-to-end scenario
  python -m scripts.mock_elite15 scenario tp_hit --token <CA> --ticker WIF
  python -m scripts.mock_elite15 scenario sl_hit --token <CA> --ticker WIF
  python -m scripts.mock_elite15 scenario trailing --token <CA> --ticker WIF
  python -m scripts.mock_elite15 scenario consensus_tiers --token <CA> --ticker WIF
  python -m scripts.mock_elite15 scenario rush_hour --count 50

  # 6. Inspect / clean up
  python -m scripts.mock_elite15 status
  python -m scripts.mock_elite15 reset
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

# Allow running as `python scripts/mock_elite15.py` from Backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.supabase_client import get_supabase_client, SCHEMA_NAME  # noqa: E402

# ── Mock Elite 15 wallet set (deterministic, recognizable) ────────────────────
MOCK_WALLETS = [f"MockElite{i:02d}" + "x" * (44 - 10) for i in range(1, 16)]
ELITE_SYSTEM_USER_ID = os.environ.get("ELITE_SYSTEM_USER_ID", "")

ORACLE_KEY = "sifter:mock_price:{token}"
ENTRY_KEY = "sifter:mock_entry:{token}"


def _redis():
    import redis
    return redis.Redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379"),
        decode_responses=True,
    )


# ── price oracle ──────────────────────────────────────────────────────────────

def set_price(token: str, price_usd: float) -> None:
    r = _redis()
    r.set(ORACLE_KEY.format(token=token), price_usd)
    print(f"[oracle] {token[:10]}.. price set to ${price_usd:.10f}")


def set_price_by_mult(token: str, mult: float) -> None:
    """Set price as a multiple of the recorded entry price."""
    r = _redis()
    entry = r.get(ENTRY_KEY.format(token=token))
    if entry is None:
        print(f"[oracle] No entry price recorded for {token[:10]}.. — run a signal first, "
              "or use --usd for an absolute price.")
        return
    set_price(token, float(entry) * mult)
    print(f"[oracle] = {mult}x of entry ${float(entry):.10f}")


def record_entry(token: str, price_usd: float) -> None:
    _redis().set(ENTRY_KEY.format(token=token), price_usd)


# ── seed mock Elite 15 ────────────────────────────────────────────────────────

def seed() -> None:
    if not ELITE_SYSTEM_USER_ID:
        print("⚠️  ELITE_SYSTEM_USER_ID env var not set. The Elite 15 system watchlist "
              "is owned by that user. Set it to your system user's UUID.")
        return
    sb = get_supabase_client()
    added = 0
    for idx, addr in enumerate(MOCK_WALLETS, start=1):
        tier = "S" if idx <= 8 else "A"
        try:
            sb.schema(SCHEMA_NAME).table("wallet_watchlist").upsert({
                "user_id": ELITE_SYSTEM_USER_ID,
                "wallet_address": addr,
                "alert_enabled": True,
                "tier": tier,
                "professional_score": 95 - idx,
            }, on_conflict="user_id,wallet_address").execute()
            added += 1
        except Exception as exc:
            print(f"  ! {addr[:12]}.. -> {exc}")
    print(f"[seed] {added}/15 mock Elite wallets seeded for system user {ELITE_SYSTEM_USER_ID[:8]}..")


# ── inject signals ────────────────────────────────────────────────────────────

def inject_signal(token: str, ticker: str, tier: int, usd: float, entry_price: float, fast: bool = False) -> None:
    """Inject `tier` wallet buys for the same token within the aggregation window.

    tier 1 = single, 2 = double, 3+ = mega. The aggregator groups them and
    emits one grouped signal that fans out to all auto-traders. ``fast`` skips
    the inter-wallet sleep (used by rush_hour for true concurrency)."""
    from services.signal_aggregator import SignalAggregator
    agg = SignalAggregator()
    n = max(1, tier)
    per_wallet_usd = usd / n
    for i in range(n):
        agg.receive({
            "token_address": token,
            "token_ticker": ticker,
            "wallet_address": MOCK_WALLETS[i],
            "wallet_tier": "S",
            "usd_value": per_wallet_usd,
            "side": "buy",
            "tx_hash": f"mocktx_{uuid.uuid4().hex[:16]}",
        })
        if not fast:
            print(f"[signal] wallet {i+1}/{n} bought ${per_wallet_usd:,.0f} of {ticker}")
            time.sleep(0.2)  # stay well within the 120s window
    record_entry(token, entry_price)
    set_price(token, entry_price)
    if not fast:
        print(f"[signal] Tier {tier} signal staged for {ticker}. Entry price ${entry_price:.10f}.")
        print("[signal] The flush_signal_aggregator Celery task (every 10s) will emit it. "
              "Make sure Celery beat + worker are running.")


def flush_now() -> None:
    """Force-flush the aggregator immediately (don't wait for Celery beat)."""
    from services.signal_aggregator import SignalAggregator
    from services.paper_trade_runtime import get_paper_trade_runtime  # noqa: F401

    agg = SignalAggregator()

    def _emit(grouped):
        print(f"[flush] EMIT {grouped.get('token_ticker')} "
              f"wallets={grouped.get('wallet_count')} "
              f"type={grouped.get('signal_type_resolved')} "
              f"key={grouped.get('signal_key')}")
        # Fan out to all auto-trade users via the real queue path.
        _fanout_to_autotraders(grouped)

    emitted = agg.flush_expired(_emit)
    print(f"[flush] {emitted} signal(s) emitted")


def _fanout_to_autotraders(grouped) -> None:
    """Queue a grouped signal for every auto-trade-enabled user."""
    from services.bot_autotrade import queue_autonomous_trade
    sb = get_supabase_client()
    users = (
        sb.schema(SCHEMA_NAME).table("telegram_users")
        .select("user_id")
        .eq("auto_trade_enabled", True)
        .execute()
    )
    for row in (users.data or []):
        res = queue_autonomous_trade(user_id=row["user_id"], signal=grouped, supabase=sb)
        print(f"  -> user {row['user_id'][:8]}.. : {res.get('status')} "
              f"{res.get('reason') or ''}")
        if res.get("queue_id") and res.get("status") == "pending":
            from services.bot_autotrade import execute_queued_autonomous_trade
            exec_res = execute_queued_autonomous_trade(queue_id=res["queue_id"], supabase=sb)
            print(f"     executed: {exec_res.get('status')}")


def elite_sell(token: str, ticker: str) -> None:
    """Simulate an Elite wallet SELLING the token.

    Per the strategy this is a NOTIFICATION/signal only — it does NOT auto-close
    user positions. The user decides whether to close. This verifies the sell
    notification path fires.
    """
    from services.telegram_notifier import TelegramNotifier
    sb = get_supabase_client()
    users = (
        sb.schema(SCHEMA_NAME).table("telegram_users")
        .select("telegram_chat_id, notif_elite_sell")
        .execute()
    )
    tn = TelegramNotifier()
    sent = 0
    for row in (users.data or []):
        if not row.get("notif_elite_sell"):
            continue
        chat = str(row.get("telegram_chat_id") or "")
        if not chat:
            continue
        tn.send_message(
            chat,
            f"🔴 <b>Elite Wallet Sold</b>\n\n"
            f"An Elite 15 wallet just sold <b>${ticker}</b>.\n"
            f"<code>{token}</code>\n\n"
            "This is a heads-up — your position is NOT auto-closed. "
            "Use Active Trades to manage it.",
        )
        sent += 1
    print(f"[elite-sell] Notification sent to {sent} users (notif_elite_sell ON only).")


# ── scenarios ─────────────────────────────────────────────────────────────────

def scenario(name: str, token: str, ticker: str, count: int) -> None:
    entry = 0.001  # mock entry price in USD
    if name == "tp_hit":
        print("=== SCENARIO: Take Profit ===")
        inject_signal(token, ticker, tier=2, usd=5000, entry_price=entry)
        flush_now()
        print("\nNow open Active Trades in Telegram — you should see the position.")
        print("Driving price to 5x to trigger TP...")
        time.sleep(2)
        set_price_by_mult(token, 5.0)
        print("Within 15s the position monitor will close it as closed_tp and email you.")
    elif name == "sl_hit":
        print("=== SCENARIO: Stop Loss + auto-blacklist ===")
        inject_signal(token, ticker, tier=1, usd=2000, entry_price=entry)
        flush_now()
        time.sleep(2)
        set_price_by_mult(token, 0.4)  # -60%
        print("Price dropped to 0.4x — SL fires, token auto-blacklisted (if enabled).")
    elif name == "trailing":
        print("=== SCENARIO: Trailing Stop ===")
        print("(Set a trailing stop in Strategy settings first, e.g. 20%.)")
        inject_signal(token, ticker, tier=3, usd=8000, entry_price=entry)
        flush_now()
        time.sleep(2)
        print("Ramping price up to 10x (sets the peak)...")
        set_price_by_mult(token, 10.0)
        time.sleep(16)  # let monitor record the peak
        print("Now dropping to 7.5x (>20% below the 10x peak) — trailing stop fires.")
        set_price_by_mult(token, 7.5)
    elif name == "consensus_tiers":
        print("=== SCENARIO: Consensus tiers ===")
        print("Tier 1 (single):")
        inject_signal(token + "T1", ticker + "1", tier=1, usd=1000, entry_price=entry)
        print("Tier 2 (double):")
        inject_signal(token + "T2", ticker + "2", tier=2, usd=3000, entry_price=entry)
        print("Tier 3 (mega):")
        inject_signal(token + "T3", ticker + "3", tier=3, usd=9000, entry_price=entry)
        flush_now()
        print("Check that sizing differs by tier (tier1/2 % of pool, tier3 % of total).")
    elif name == "elite_sell":
        print("=== SCENARIO: Elite sell notification ===")
        inject_signal(token, ticker, tier=2, usd=4000, entry_price=entry)
        flush_now()
        time.sleep(2)
        elite_sell(token, ticker)
        print("Verify you got a SELL NOTIFICATION but the position stayed OPEN.")
    elif name == "rush_hour":
        print(f"=== SCENARIO: Rush hour — {count} concurrent signals ===")
        import concurrent.futures as cf
        def fire(i):
            tk = f"RushToken{i:03d}" + "x" * 30
            inject_signal(tk, f"RUSH{i}", tier=(i % 3) + 1, usd=1000 + i * 10, entry_price=entry, fast=True)
        with cf.ThreadPoolExecutor(max_workers=20) as ex:
            list(ex.map(fire, range(count)))
        flush_now()
        print(f"Fired {count} signals. Check: no double-trades, queue drained, "
              "Telegram didn't drop messages, no Redis lock deadlocks.")
    elif name == "attack":
        _attack_scenarios(token, ticker)
    elif name == "rejects":
        _reject_scenarios()
    else:
        print(f"Unknown scenario: {name}")
        print("Options: tp_hit | sl_hit | trailing | consensus_tiers | elite_sell | "
              "rush_hour | attack | rejects")


def _attack_scenarios(token: str, ticker: str) -> None:
    """Inject security-attack signals and verify they are REJECTED.

    Drives queue_autonomous_trade directly so we can read back the skip_reason.
    """
    from services.bot_autotrade import queue_autonomous_trade, _load_elite_set
    sb = get_supabase_client()
    u = (
        sb.schema(SCHEMA_NAME).table("telegram_users")
        .select("user_id").eq("auto_trade_enabled", True).limit(1).execute()
    )
    if not u.data:
        print("No auto_trade_enabled user — enable auto-trade on a test account first.")
        return
    user_id = u.data[0]["user_id"]
    elite = _load_elite_set(sb)
    real = next(iter(elite)) if elite else (MOCK_WALLETS[0])

    cases = [
        ("address_poisoning", {
            "token_address": "A" * 44, "usd_value": 500, "side": "buy", "wallet_count": 1,
            "wallet_addresses": [(real[:4] + "Z" * (len(real) - 8) + real[-4:])],
        }),
        ("dust_value", {
            "token_address": "A" * 44, "usd_value": 5, "side": "buy", "wallet_count": 1,
            "wallet_addresses": [real],
        }),
        ("transfer_mimicry", {
            "token_address": "A" * 44, "usd_value": 500, "side": "buy", "wallet_count": 1,
            "event_type": "transfer", "wallet_addresses": [real],
        }),
        ("invalid_mint", {
            "token_address": "SHORT", "usd_value": 500, "side": "buy", "wallet_count": 1,
            "wallet_addresses": [real],
        }),
    ]
    print("=== SECURITY ATTACK SCENARIOS (expect REJECT) ===")
    for label, sig in cases:
        sig.setdefault("signal_key", f"attack:{label}:{uuid.uuid4().hex[:8]}")
        sig.setdefault("token_ticker", "ATTACK")
        res = queue_autonomous_trade(user_id=user_id, signal=sig, supabase=sb)
        status = res.get("status")
        reason = res.get("reason")
        ok = status == "skipped"
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: status={status} reason={reason}")


def _reject_scenarios() -> None:
    """Verify each autonomous rejection path returns the right skip_reason."""
    from services.bot_autotrade import queue_autonomous_trade
    sb = get_supabase_client()
    u = (
        sb.schema(SCHEMA_NAME).table("telegram_users")
        .select("user_id, consensus_threshold").eq("auto_trade_enabled", True).limit(1).execute()
    )
    if not u.data:
        print("No auto_trade_enabled user — enable auto-trade on a test account first.")
        return
    user_id = u.data[0]["user_id"]
    real = MOCK_WALLETS[0]
    print("=== REJECT SCENARIOS ===")
    print("(Set consensus_threshold high, blacklist a token, etc. in the bot first,")
    print(" then watch the skip_reason on each.)")

    # below_consensus: tier-1 against a high threshold
    sig = {
        "token_address": "B" * 44, "token_ticker": "BELOW", "usd_value": 500,
        "side": "buy", "wallet_count": 1, "signal_key": f"rej:below:{uuid.uuid4().hex[:8]}",
        "wallet_addresses": [real],
    }
    res = queue_autonomous_trade(user_id=user_id, signal=sig, supabase=sb)
    print(f"  below_consensus → status={res.get('status')} reason={res.get('reason')}")


# ── status / reset ────────────────────────────────────────────────────────────

def status() -> None:
    r = _redis()
    sb = get_supabase_client()
    print("=== MOCK STATUS ===")
    # Oracle prices
    keys = list(r.scan_iter(match="sifter:mock_price:*", count=100))
    print(f"Oracle prices set: {len(keys)}")
    for k in keys[:20]:
        print(f"  {k} = {r.get(k)}")
    # Open positions
    try:
        pos = sb.schema(SCHEMA_NAME).table("bot_live_positions").select(
            "token_symbol, status, total_invested_usd, trigger_type"
        ).eq("status", "open").execute()
        print(f"Open positions: {len(pos.data or [])}")
        for p in (pos.data or [])[:20]:
            print(f"  {p.get('token_symbol')} {p.get('trigger_type')} "
                  f"${p.get('total_invested_usd')}")
    except Exception as exc:
        print(f"  position query failed: {exc}")
    # Signal queue
    try:
        q = sb.schema(SCHEMA_NAME).table("bot_signal_queue").select(
            "status", count="exact"
        ).execute()
        print(f"Signal queue rows: {q.count if hasattr(q, 'count') else len(q.data or [])}")
    except Exception:
        pass


def reset() -> None:
    r = _redis()
    n = 0
    for k in r.scan_iter(match="sifter:mock_price:*", count=200):
        r.delete(k); n += 1
    for k in r.scan_iter(match="sifter:mock_entry:*", count=200):
        r.delete(k); n += 1
    for k in r.scan_iter(match="sifter:sigagg:*", count=200):
        r.delete(k); n += 1
    print(f"[reset] cleared {n} oracle/aggregator keys")
    print("[reset] Note: open positions in bot_live_positions are NOT deleted. "
          "Close them via the bot, or truncate the table manually.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Mock Elite 15 harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="Seed 15 mock Elite wallets")

    s = sub.add_parser("signal", help="Inject a buy signal")
    s.add_argument("--token", required=True)
    s.add_argument("--ticker", default="MOCK")
    s.add_argument("--tier", type=int, default=1)
    s.add_argument("--usd", type=float, default=2000)
    s.add_argument("--entry", type=float, default=0.001)

    pr = sub.add_parser("price", help="Set oracle price")
    pr.add_argument("--token", required=True)
    pr.add_argument("--mult", type=float)
    pr.add_argument("--usd", type=float)

    es = sub.add_parser("elite-sell", help="Send Elite-sell notification")
    es.add_argument("--token", required=True)
    es.add_argument("--ticker", default="MOCK")

    sc = sub.add_parser("scenario", help="Run a full scenario")
    sc.add_argument("name")
    sc.add_argument("--token", default="ScenarioToken" + "x" * 30)
    sc.add_argument("--ticker", default="MOCK")
    sc.add_argument("--count", type=int, default=50)

    sub.add_parser("flush", help="Force-flush the aggregator now")
    sub.add_parser("status", help="Show mock state")
    sub.add_parser("reset", help="Clear oracle + aggregator keys")

    args = p.parse_args()

    if args.cmd == "seed":
        seed()
    elif args.cmd == "signal":
        inject_signal(args.token, args.ticker, args.tier, args.usd, args.entry)
    elif args.cmd == "price":
        if args.mult is not None:
            set_price_by_mult(args.token, args.mult)
        elif args.usd is not None:
            set_price(args.token, args.usd)
        else:
            print("Provide --mult or --usd")
    elif args.cmd == "elite-sell":
        elite_sell(args.token, args.ticker)
    elif args.cmd == "scenario":
        scenario(args.name, args.token, args.ticker, args.count)
    elif args.cmd == "flush":
        flush_now()
    elif args.cmd == "status":
        status()
    elif args.cmd == "reset":
        reset()


if __name__ == "__main__":
    main()
