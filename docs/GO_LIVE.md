# SIFTER Bot — Going Live

How to move the bot from testing to real-money trading, safely.

## Execution modes (the ladder)

| Mode | Funds | Chain | Use |
|------|-------|-------|-----|
| `safe_noop` | none | none | UI/flow testing — records positions only |
| `paper` | none | none | Strategy validation with simulated fills |
| `devnet` | test SOL | Solana devnet | Validate REAL swap mechanics (MEV, slippage, gas, fee) |
| `live` | REAL money | mainnet-beta | Production |

Set via `BOT_EXECUTION_MODE` in `.env`. **Always climb the ladder in order.**

---

## Stage 1 — Paper (validate strategy)
```
BOT_EXECUTION_MODE=paper
```
Run the bot + Celery beat/worker. Use `scripts/mock_elite15.py` to drive every scenario. Confirm: signals → positions → TP/SL/trailing → notifications all behave. No funds at risk.

## Stage 2 — Devnet (validate mechanics)
```
BOT_EXECUTION_MODE=devnet
SOLANA_RPC_URL=https://api.devnet.solana.com
SOLANA_NETWORK=devnet
JUPITER_BASE_URL=https://quote-api.jup.ag
```
1. Create/import a wallet, fund it with devnet SOL (`solana airdrop 2 <pubkey> --url devnet`).
2. Note: Jupiter routing is mainnet-only — devnet swaps work only on known devnet pairs or wrapped-SOL transfers. This stage validates **signing, submission, confirmation, fee deduction, priority/MEV fee** — NOT strategy (use paper for that).
3. Run `scripts/load_test.py --devnet` to confirm behavior under load.

## Stage 3 — Live (real money)

**Prerequisites — the router REFUSES live mode unless ALL are true:**
1. `WALLET_ENCRYPTION_SECRET` set (32+ chars)
2. `TREASURY_WALLET_ADDRESS` + `TREASURY_TOKEN_ACCOUNT` set
3. `fee_config.enabled = true` in Supabase (if charging fees)
4. `SOLANA_RPC_URL` → a mainnet RPC (Helius/Triton/QuickNode, NOT public)
5. Redis reachable (kill switch must be checkable — fails closed otherwise)
6. **`LIVE_TRADING_CONFIRMED=true`** — the explicit final switch

```
BOT_EXECUTION_MODE=live
SOLANA_NETWORK=mainnet-beta
SOLANA_RPC_URL=https://<your-mainnet-rpc>
LIVE_TRADING_CONFIRMED=true
TREASURY_WALLET_ADDRESS=<your treasury>
TREASURY_TOKEN_ACCOUNT=<treasury ATA>
```

If any prerequisite is missing, `BotExecutionRouter._resolve_mode()` logs a CRITICAL banner and **downgrades to `safe_noop`** — it will not silently trade with a misconfiguration.

### Safety properties (already built)
- **Price oracle disabled in live** — test prices (`sifter:mock_price:*`) are ignored when mode is `live`, so test data can never leak into real trades.
- **Kill switch fails closed** — if Redis is unreachable, execution is blocked.
- **Idempotency fails closed** — if Redis is down, action locks deny (no unprotected double-trades).
- **Security screen** — address poisoning / ticker mimicry / dust / transfer-in fakes are rejected before any trade.
- **Fee logged** — every live buy/sell writes `bot_fee_log` (ClickHouse).

### Operator kill switch (emergency)
From the operator panel → Kill Switch, or set Redis `sifter:kill_switch=1`. Blocks ALL new trades globally. Open positions keep their TP/SL.

### Rollback
Set `LIVE_TRADING_CONFIRMED=false` (instant downgrade to safe_noop on next trade) or `BOT_EXECUTION_MODE=paper`. Restart workers.

---

## Pre-flight checklist before flipping to live
- [ ] Paper-mode scenarios all pass
- [ ] Devnet swap confirmed end-to-end (1 real buy + 1 real sell)
- [ ] Treasury wallet funded for fee account rent
- [ ] Mainnet RPC tested (not rate-limited)
- [ ] `WALLET_ENCRYPTION_SECRET` backed up securely
- [ ] Kill switch tested (set + clear)
- [ ] Operator chat IDs configured
- [ ] `CONSOLIDATED_SUPABASE_SCHEMA.sql` applied
- [ ] `uv sync` run (solders/solana/pynacl present)
- [ ] Start with a small `auto_trade_max_usd` cap per user
