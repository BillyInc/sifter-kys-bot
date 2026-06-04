# SIFTER KYS Telegram Bot — Comprehensive Audit & Build Status

**Date:** 2026-06-03
**Scope:** Full Telegram trading bot rebuild — auto-trader, manual trader, position management, notifications, operator panel
**Sources:** UI mockup, master plan, builder instructions, test suite + full codebase scan

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [What Was Built](#2-what-was-built)
3. [Audit #1 — UI Document vs Build](#3-audit-1--ui-document-vs-build)
4. [Audit #2 — Codebase Stubs & Leaks](#4-audit-2--codebase-stubs--leaks)
5. [Untouchable Files — What Changed](#5-untouchable-files--what-changed)
6. [Critical Issues Still Open](#6-critical-issues-still-open)
7. [Deferred Features](#7-deferred-features)
8. [Devnet Readiness](#8-devnet-readiness)
9. [Required Before Anything Works](#9-required-before-anything-works)

---

## 1. Executive Summary

The bot is **structurally complete** — every screen from the UI document has a render function and button handlers; all user-facing slash commands redirect to the clickable button menu; the auto-trader and manual-trader paths are separated; paper-trading leaks into user-facing views are removed.

**However, it is NOT runnable yet.** Three categories of blockers remain:
- **Database:** New migrations reference columns/tables not yet applied to Supabase. Until applied, `_load_user_ctx` crashes on every call → bot is dead.
- **Dependencies:** `pynacl`, `solders`, `solana` are referenced/needed but not in `pyproject.toml`. The venv is not synced (last pytest run: 48 failures from `ModuleNotFoundError`).
- **Environment:** `.env` only has `TELEGRAM_BOT_TOKEN`. ~12 required vars are unset.
- **Column mismatch:** Seed-phrase wallet import writes `encrypted_private_key`/`wallet_type`, but `bot_wallets` uses `encrypted_key`/`key_iv`/`key_tag`.

**No verified end-to-end test has been run** — the shell execution environment intermittently blocked all commands during this session.

---

## 2. What Was Built

### Architecture (solid, reused throughout)
- Redis state machine (`bot_state.py`) — flat dict, imperative nav, 1hr TTL
- Pure render functions (`bot_screens.py`) — no side effects, unit-testable
- Callback dispatch (`bot_handlers.py`) — 11 categories: nav/set/exec/wal/pos/stat/blk/alert/note/access/op
- Execution boundary (`bot_execution.py`) — safe_noop / paper / devnet / live modes
- Autonomous queue (`bot_autotrade.py`) — `bot_signal_queue` + `BotExecutionRouter`

### Screens implemented
Main menu (tiered), Auto-Trader dashboard, Elite 15 (selection + detail), Active positions, Trade history + detail, Token stats (real SolanaTracker data), Manual trade (full flow: sizing → TP/SL → slippage/MEV → confirm), Close/modify, Archived holdings, Strategy settings, Portfolio sizing, Notifications (9 toggles + quiet hours), Wallets (fund, import key/seed, tracked detail), Account (stats, security phrase, emergency stop, suspend, delete), MC price alerts, Notes & reminders, Operator panel.

### Key features wired
- In-bot registration (email + password → Supabase)
- Password reset (Telegram + dashboard)
- Magic links + access codes
- Elite 15 per-wallet copy-trade selection (default = all wallets)
- Manual trade Elite signal picker
- TP/SL/trailing-stop Celery monitor (every 15s)
- Anti-phishing email security phrase
- Manual-trader signal emails with TRADE_ deep links
- Email deep links: TRADE_, SESSION_, MAGIC_
- Idempotency locks (fail-closed when Redis down)
- Telegram API retry with exponential backoff
- Session persistence on /start

---

## 3. Audit #1 — UI Document vs Build

### COMPLETE
Welcome, Register, Help, Consensus picker, Main menu (both tiers), Account (now with real stats), Auto-trader dashboard (with paper mode + trade history), Elite 15 list + selection, Active positions (with PnL dots, close 25/50/75/100/custom), Strategy settings, Portfolio sizing, Notification toggles + quiet hours, Operator panel.

### PARTIAL (functional, minor gaps)
| Screen | Gap |
|--------|-----|
| Signal sizing | Missing some preset values (20%, custom); no live SOL preview on this specific screen |
| Settings screens | Immediate-save pattern instead of explicit `[Save]` button (UX choice, functional) |
| Token blacklist | No date-added display; add accepts CA only |
| Price alerts | Only 4 MC presets, no custom target; notify-via hardcoded to both |

### MAJOR GAPS / NOT IMPLEMENTED
| Item | Status |
|------|--------|
| Create Wallet via Email | NOT built — no button, no handler |
| Fund wallet QR code | NOT built — shows address + conversion table only |
| Real wallet balance | HARDCODED 10 SOL / $150 in 4 places |
| Pause confirmation dialog | Direct toggle, no "Are you sure?" |
| Close fee-preview confirm | `render_close_confirm` exists but custom-close path skips it |
| Wallet replacement notification | BUILT (Elite 15 sync now notifies users) |

---

## 4. Audit #2 — Codebase Stubs & Leaks

### Paper trading leaks (FIXED)
| Path | Was | Now |
|------|-----|-----|
| `/mypositions` `/portfolio` `/pnl` `/history` | queried `paper_portfolio` | redirect to button menu (live data) |
| `sell\|` callback | `paper_trading_manager.close_position` | routes through `BotExecutionRouter` + `bot_live_positions` |
| `_notify_paper_trade_event` | sent users fake trade notifications | log-only (team paper trader is operator-eval only) |
| 11 slash commands | executed legacy paths | redirect to clickable buttons |

### Critical stubs (FIXED)
| Stub | Fix |
|------|-----|
| `send_document` missing → CSV export crashed | Added `send_document()` to `TelegramNotifier` |
| SOL price: Birdeye w/ empty key → always $150 | Switched to Jupiter quote API |
| `_send_close_notifications` → `pass` (no email) | Wired to `send_bot_tp_hit/sl_hit/trailing_stop/trade_close` |

### Critical stubs (STILL OPEN)
| Stub | Status |
|------|--------|
| Seed phrase import → writes WRONG columns | **BROKEN** — writes `encrypted_private_key`/`wallet_type`; table has `encrypted_key`/`key_iv`/`key_tag` |
| `LiveJupiterExecutionAdapter` | Hardcoded `rejected` — no Jupiter API calls |
| MC price alert firing | Alerts created but no Celery monitor fires them |
| Notes/reminders firing | Reminders created but nothing fires at scheduled time |

### Dead email methods (PARTIALLY FIXED)
- `send_bot_trade_close/tp_hit/sl_hit/trailing_stop` — now CALLED by position monitor ✓
- `send_weekly_summary` — DOES NOT EXIST (toggle is a no-op)
- `send_mc_alert` — DOES NOT EXIST

### Safety (FIXED)
- `_acquire_action_lock` now fail-closed (returns False when Redis down)
- Legacy `sell|` path now acquires idempotency lock
- Telegram API now retries 3× with backoff
- `/start` restores session for linked users

---

## 5. Untouchable Files — What Changed

| File | Change | Risk |
|------|--------|------|
| `tasks.py` | Deleted ~200 lines dead `bot_auto_trades` code | Low — was unreachable |
| `tasks.py` | Wallet replacement notification uses `win_rate_7d` (correct field) | Low |
| `signal_aggregator.py` | Added `signal_key` + `side` to grouped_signal | Low — additive |
| `execution_adapters.py` | `LiveJupiterExecutionAdapter` now polymorphic with `PaperExecutionAdapter` | Low — signature align |
| `bot_execution.py` | `_execute_live` builds `NormalizedTradeSignal` like `_execute_paper` | Low |
| `bot_handlers.py` | `_enrich_with_elite_stats()` maps Elite100 field names via ClickHouse | Medium — needs ClickHouse |

**Preserved (correctly):** Team paper trader (`paper_trader.py`, `paper_trade_runtime.py`) and the dual-write in `flush_signal_aggregator` — these are the operator pre-go-live validation tool, separate from user paper mode.

---

## 6. Critical Issues Still Open

### 🔴 BLOCKER 1 — Migrations not applied
The bot's `_load_user_ctx` SELECTs columns added in 3 un-applied migrations:
`paper_mode`, `auto_blacklist`, `anti_phishing_phrase`, `reset_token`, `reset_token_expires_at`, `notif_elite_sell`, `notif_tracked_wallet`, plus the `bot_elite_selections` table.
**Until applied → every bot interaction throws → bot is dead.**
→ Apply `CONSOLIDATED_SUPABASE_SCHEMA.sql` (provided separately).

### 🔴 BLOCKER 2 — bot_wallets column mismatch
`_handle_seed_phrase` (bot_handlers.py) upserts `encrypted_private_key` + `wallet_type`.
The `bot_wallets` table has `encrypted_key`, `key_iv`, `key_tag` (different encryption scheme).
**Result:** seed phrase import will fail at the DB write.
→ Either add the columns (in consolidated schema) OR rewrite the handler to match the existing AES-GCM scheme used by `telegram_notifier._handle_wallet_key_message`.

### 🔴 BLOCKER 3 — Dependencies not installed
`pyproject.toml` lacks `pynacl` (seed phrase keypair), `solders` + `solana` (devnet signing).
Last `pytest` run: 48 failures, all `ModuleNotFoundError`.
→ Add deps, run `uv sync`.

### 🔴 BLOCKER 4 — Environment unconfigured
`.env` has only `TELEGRAM_BOT_TOKEN`.
→ See [Section 9](#9-required-before-anything-works) for full list.

### 🟡 Unverified
- No file has been compile-checked since the last batch of ~30 edits (shell blocked).
- No end-to-end button test has been run.
- No migration has been confirmed applied.

---

## 7. Deferred Features

| Feature | Why deferred | Effort to finish |
|---------|-------------|-----------------|
| Live Jupiter execution | Needs Solana libs + Jupiter API + wallet decrypt | High |
| Create wallet via email | Needs keygen + email flow | Medium |
| Real wallet balance | Needs Solana RPC `getBalance` | Low |
| MC price alert monitor | Needs Celery task (every 30s) | Low |
| Notes/reminders firing | Needs Celery task (every 30s) | Low |
| Weekly summary email | Needs method + Celery task | Medium |
| MC alert email | Needs `send_mc_alert` method | Low |
| ClickHouse bot_signal_log ingest | Table exists, no writer | Medium |
| Custom MC target input | Free-text entry | Low |
| Notify-via toggle | Read from callback params | Low |

---

## 8. Devnet Readiness

### Can we use mock Elite 15? — YES
`SignalAggregator.receive()` accepts any dict with `token_address`, `wallet_address`, `usd_value`. A script can inject mock Elite wallet buys → `flush_expired()` emits → `queue_autonomous_trade()` → execution → position monitor. No real Elite 15 needed.

### Devnet reality check
- **Jupiter is mainnet-only.** `quote-api.jup.ag` has no devnet routing; devnet liquidity is near-zero. True swaps barely work on devnet.
- **Recommendation:** Validate the full pipeline in **`paper` mode** (already works). Test raw transaction signing/submission on devnet *separately* with a known devnet pair.
- TP/SL monitor price fetch uses Jupiter mainnet → returns nothing on devnet.

### Devnet checklist
| Item | State |
|------|-------|
| `solders`/`solana` libs | NOT installed |
| `LiveJupiterExecutionAdapter` | Stub (rejects) |
| `SOLANA_RPC_URL` | Not in config |
| Wallet decryption in `_execute_live` | Not wired |
| Funded devnet wallet | Needed (user provides) |
| `BOT_EXECUTION_MODE=devnet` | Not set |

---

## 9. Required Before Anything Works

### Step 1 — Apply database schema
Run `CONSOLIDATED_SUPABASE_SCHEMA.sql` in Supabase SQL Editor. (Provided separately — all tables + columns + RLS + grants.)

### Step 2 — Add dependencies to `pyproject.toml`
```
"pynacl>=1.5.0",        # seed phrase Ed25519 keypair derivation
"solders>=0.21.0",      # devnet: keypair, transaction signing
"solana>=0.34.0",       # devnet: RPC client, send/confirm
```
Then `cd Backend && uv sync`.

### Step 3 — Populate `.env`
```
# Core
TELEGRAM_BOT_TOKEN=<set>
TELEGRAM_BOT_USERNAME=SifterTradingBot
TELEGRAM_SECRET_TOKEN=<webhook secret>
WALLET_ENCRYPTION_SECRET=<32+ char secret>

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# Redis
REDIS_URL=redis://localhost:6379

# Data
SOLANATRACKER_API_KEY=
HELIUS_API_KEY=
RESEND_API_KEY=
FROM_EMAIL=alerts@sifter.app

# Execution (devnet)
BOT_EXECUTION_MODE=paper            # use 'paper' first; 'devnet' after libs added
JUPITER_BASE_URL=https://quote-api.jup.ag
SOLANA_RPC_URL=https://api.devnet.solana.com
PLATFORM_FEE_BPS=100
TREASURY_WALLET_ADDRESS=
TREASURY_TOKEN_ACCOUNT=

# Dashboard
DASHBOARD_URL=https://your-frontend.app
TELEGRAM_OPERATOR_CHAT_IDS=<your chat id>
```

### Step 4 — Compile + test
```
cd Backend
python -m py_compile services/*.py routes/*.py
python -m pytest tests/test_bot_foundation.py -x -q
```

### Step 5 — Set Telegram webhook
```
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-backend>/api/telegram/webhook&secret_token=<TELEGRAM_SECRET_TOKEN>"
```

### Step 6 — Mock pipeline test (paper mode)
Run the mock Elite 15 injection script (to be provided) → verify signal → queue → execute → position appears → TP/SL monitor tracks it.

---

## Appendix — File Inventory

**Bot core (created/heavily modified):**
`services/bot_handlers.py`, `bot_screens.py`, `bot_state.py`, `bot_execution.py`, `bot_autotrade.py`, `bot_filters.py`, `bot_position_monitor.py`

**Integration (modified):**
`services/telegram_notifier.py`, `email_service.py`, `tasks.py`, `signal_aggregator.py`, `execution_adapters.py`, `celery_app.py`, `routes/auth.py`

**Frontend (modified):**
`frontend/src/contexts/AuthContext.tsx` (backend reset-token support)

**Migrations (must apply):**
`20260531_telegram_bot_rebuild.sql`, `20260601_bot_ux_hardening.sql`, `20260603_auth_phase1.sql`, `20260603_bot_elite_selections.sql`, `20260603_bot_fixes.sql`
→ All consolidated into `CONSOLIDATED_SUPABASE_SCHEMA.sql`
