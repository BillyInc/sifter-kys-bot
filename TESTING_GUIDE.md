# SIFTER Bot — Testing Guide

What to test on **mock data**, what to test on **Solana devnet + Jupiter**, the
**env vars** to wire, and the full **feature checklist** for the manual trader,
the auto-trader, and the Telegram bot itself.

---

## 0. Test ladder — where each thing belongs

| Layer | Funds | What it proves | Tooling |
|-------|-------|----------------|---------|
| **Unit / isolation** | none | Filter logic, security defenses, screen routing | `pytest tests/` |
| **Mock data (paper mode)** | none | Full strategy: signals → queue → fill → TP/SL → notifications. Tap real buttons. | `scripts/mock_elite15.py` + live bot |
| **Devnet + Jupiter** | test SOL | REAL swap mechanics: signing, submit, confirm, slippage, gas/priority, platform fee, MEV path | `BOT_EXECUTION_MODE=devnet` + `scripts/load_test.py --devnet` + `wallet_test.py --devnet` |
| **Mainnet (live)** | real $ | Production | After all above green; see `docs/GO_LIVE.md` |

**Rule:** strategy correctness → mock/paper. On-chain mechanics → devnet. Never validate strategy on devnet (no liquidity) or mechanics on paper (no chain).

---

## 1. Environment variables to wire

Copy `Backend/.env.example` → `Backend/.env` and fill. Grouped by when you need them:

### Always required (the bot won't run without these)
```
TELEGRAM_BOT_TOKEN=            # @BotFather
TELEGRAM_BOT_USERNAME=         # no @, for deep links
TELEGRAM_SECRET_TOKEN=         # webhook auth; bot 403s without it
WALLET_ENCRYPTION_SECRET=      # 32+ chars
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
REDIS_URL=redis://localhost:6379
SOLANATRACKER_API_KEY=         # token data + ticker search
ELITE_SYSTEM_USER_ID=          # UUID owning the Elite 15 watchlist (security allow-list)
```

### Needed for mock/paper testing
```
BOT_EXECUTION_MODE=paper
RESEND_API_KEY=                # to actually receive emails (else logged only)
FROM_EMAIL=alerts@sifter.app
DASHBOARD_URL=                 # for reset-password / login buttons
```

### Needed for devnet
```
BOT_EXECUTION_MODE=devnet
SOLANA_RPC_URL=https://api.devnet.solana.com
SOLANA_NETWORK=devnet
JUPITER_BASE_URL=https://quote-api.jup.ag
```

### Needed for live (mainnet)
```
BOT_EXECUTION_MODE=live
SOLANA_NETWORK=mainnet-beta
SOLANA_RPC_URL=https://<paid-mainnet-rpc>
LIVE_TRADING_CONFIRMED=true
TREASURY_WALLET_ADDRESS=
TREASURY_TOKEN_ACCOUNT=
PLATFORM_FEE_BPS=100
```

### Operator / optional
```
TELEGRAM_OPERATOR_CHAT_IDS=    # comma-separated
HELIUS_API_KEY=               # real Elite wallet monitoring
ADMIN_EMAIL=                  # error alerts
CLICKHOUSE_*                  # fee log / trade analytics
```

---

## 2. What to test on MOCK DATA (paper mode)

Start: bot in `paper`, Celery beat + worker running, real Telegram connected.
Seed: `python -m scripts.mock_elite15 seed`.

### Auto-trader — signal pipeline
| Test | Command | Expect |
|------|---------|--------|
| Tier 1 single | `scenario consensus_tiers` | 1-wallet → "single", sized by tier1_pct_of_pool |
| Tier 2 double | (same) | 2 wallets ≤120s → "double", tier2 sizing |
| Tier 3 mega | (same) | 3+ wallets → "mega", tier3 % of TOTAL |
| TP hit | `scenario tp_hit` | position opens → price→5x → closes `closed_tp` → email |
| SL hit | `scenario sl_hit` | price→0.4x → `closed_sl` → auto-blacklist if ON |
| Trailing stop | `scenario trailing` | peak at 10x, drop to 7.5x → `closed_trailing` |
| Elite SELL | `scenario elite_sell` | **notification only — position stays OPEN** |

### Auto-trader — rejection paths
| Test | Setup | Expect skip_reason |
|------|-------|--------------------|
| Below consensus | threshold=3, inject tier-1 | `below_consensus` |
| Blacklisted | blacklist token first | `blacklisted` |
| Wallet not selected | select only wallet #1, signal from #5 | `wallet_not_selected` |
| Duplicate open | inject same token twice | `duplicate_open_position` |
| Hourly limit | set hourly=1, inject 2 | `hourly_limit` |
| Deployment limit | fill pool past max | `deployment_limit` |

Run all rejects: `python -m scripts.mock_elite15 scenario rejects`.

### SECURITY — address poisoning / mimicry (critical)
`python -m scripts.mock_elite15 scenario attack` — verify each REJECTS:
- Address poisoning (look-alike wallet, same first4/last4) → `address_poisoning`
- Dust bait (<$50) → `dust_value`
- Transfer-in mimicry (tokens sent TO wallet, not bought) → `non_swap_event`
- Invalid/impostor mint → `invalid_mint`
Also covered by `pytest tests/test_bot_security.py` (12 tests).

### Manual trader (tap-through against mock data)
`python -m scripts.mock_elite15 manual prep --token <CA> --ticker WIF` sets a live price, then tap:
| Flow | Tap sequence | Expect |
|------|-------------|--------|
| Token stats (CA) | Token Stats → paste CA | MC/liq/vol/holders, NO risk score |
| Token stats (ticker) | Token Stats → type "WIF" | search results or direct preview |
| Manual buy | Manual Trade → Paste CA → Trade This → size 25% → TP 5x → SL -50% → Slippage 1% → Review → Execute | position appears in Active Trades |
| Per-trade slippage/MEV | (in preview) Slippage & MEV → 2%, MEV ON | reflected on confirm |
| Fee on confirm | (confirm screen) | platform fee 1% + "you receive" shown |
| Elite signal picker | Manual Trade → Use Recent Elite Signal | last-6h tokens listed → tap → preview |
| Close 50% | Active Trades → Close 50% | confirm w/ gross/fee/net → 50% sells, 50% remains |
| Custom close % | Close Custom % → enter 33 | confirm → 33% sells |
| Take 50% + run | Take 50% + Run | 50% sells, remainder archived (TP removed, SL kept) |
| Archive / restore | Archive → Archived Holdings → Restore | back to Active with default TP/SL |

### Telegram bot itself
| Feature | Test | Expect |
|---------|------|--------|
| Registration | /start → Register via Bot → email → password | account created, welcome email |
| Login session | /start when linked | restored to Main Menu (not Welcome) |
| Password reset | Account → Forgot Password → email | reset email w/ anti-phishing phrase; link → dashboard `/reset-password?token=` |
| Anti-phishing phrase | Account → Change Security Phrase | phrase appears in every email |
| Wallet: private key import | My Wallets → Import Private Key | message deleted, wallet stored |
| Wallet: seed phrase | Import Seed Phrase → 12/24 words | message deleted, wallet stored |
| Wallet: create via email | Create New Wallet (Email) | keypair generated, secret emailed |
| Fund screen | My Wallets → Fund | address + $→SOL table |
| Notifications | Notifications → toggle each | 9 toggles + quiet hours persist |
| MC price alert | set alert → `mock_elite15 price` past target | Telegram + email fire (≤30s) |
| Notes/reminders | New Reminder (1h) | fires via `check_bot_reminders` |
| Account: emergency stop | Account → Emergency Stop | auto-trade off, pending cancelled |
| Account: suspend/delete | (danger zone) | suspend keeps data; delete needs "DELETE" typed |
| CSV export | Trade History → Export CSV | file attachment arrives |
| Operator panel | (operator chat) → Operator Panel | health, kill switch, codes, fees |
| Button responsiveness | tap any button | ack < 200ms (spinner stops) — `latency_probe` |
| Rush hour | `scenario rush_hour --count 50` | no double-trades, queue drains |

### Notification timing (mock)
- Trade entry / TP / SL → Telegram ≤10s, email ≤30s
- Quiet hours → Telegram suppressed, email still sends, trades still execute
- Dual delivery → both fire independently (email not blocked by Telegram)

---

## 3. What to test on SOLANA DEVNET + JUPITER

Devnet validates **real on-chain mechanics** that mocks/paper cannot. Switch:
```
BOT_EXECUTION_MODE=devnet
SOLANA_RPC_URL=https://api.devnet.solana.com
```
Fund a wallet: `solana airdrop 2 <pubkey> --url devnet`.

> ⚠️ Jupiter routing is mainnet-only. Devnet liquidity is near-zero, so use a
> known devnet test pair or wrapped-SOL transfers. Devnet proves *mechanics*,
> not strategy (strategy stays in paper).

| What to test | How | Why devnet (not mock) |
|--------------|-----|----------------------|
| Keypair sign + submit + confirm | `wallet_test.py --devnet --fund <secret>` | real Ed25519 signing + RPC confirmation |
| Quote accuracy | devnet buy, compare quote vs fill | real Jupiter /v6/quote |
| **Slippage enforcement** | set slippage 0.5% then 5%, observe fills | only real swaps enforce slippage |
| **Gas / priority fee** | MEV ON vs OFF, compare priority lamports | real `prioritizationFeeLamports` |
| **Platform/wallet fee** | enable fee_config, buy → check `bot_fee_log` + treasury | real `platformFeeBps` + `feeAccount` deduction |
| **MEV-protected path** | MEV ON → `useSharedAccounts`/priority | real anti-sandwich routing |
| Buy **and** sell | full round trip on devnet | sell path + fee on sell |
| Tx failure handling | force a bad route | NO position written on failure (data integrity) |
| Confirmation latency | time submit→confirm | real network timing |
| **Rush hour (real)** | `load_test.py --devnet --signals 50` | fill latency + slippage widening + priority-fee competition under load; assert no double-trades |

### Devnet acceptance criteria
- [ ] 1 real buy confirms on devnet, position written with real `entry_txid`
- [ ] 1 real sell confirms, `exit_txid` + `bot_fee_log` row written
- [ ] Slippage setting changes the min-received
- [ ] MEV ON shows a non-zero priority fee; OFF shows ~0
- [ ] Platform fee lands in treasury (when fee_config.enabled)
- [ ] A failed swap leaves NO orphan position
- [ ] `load_test --devnet` holds all invariants

---

## 4. Run order (copy/paste)

```bash
cd Backend

# 0. Install + provision
uv sync
# (apply CONSOLIDATED_SUPABASE_SCHEMA.sql in Supabase SQL editor)
cp .env.example .env   # then fill it

# 1. Unit / isolation (no infra needed)
uv run pytest tests/test_bot_security.py tests/test_bot_scenarios.py -q
uv run pytest tests/test_bot_foundation.py tests/test_bot_buttons.py -q
uv run python -m scripts.wallet_test

# 2. Mock data (paper) — start bot + celery first, then:
uv run python -m scripts.mock_elite15 seed
uv run python -m scripts.mock_elite15 scenario tp_hit --token <CA> --ticker WIF
uv run python -m scripts.mock_elite15 scenario attack --token <CA>
uv run python -m scripts.mock_elite15 scenario rejects
uv run python -m scripts.latency_probe --iterations 50
uv run python -m scripts.load_test --signals 200
# ... tap real buttons per section 2 ...

# 3. Devnet (real mechanics)
# set BOT_EXECUTION_MODE=devnet, SOLANA_RPC_URL=devnet, fund a wallet
uv run python -m scripts.wallet_test --devnet --fund <secret_b58>
uv run python -m scripts.load_test --devnet --signals 50
# ... do a real buy + sell via the bot, verify bot_fee_log + txids ...

# 4. Live — only after all above green; follow docs/GO_LIVE.md
```

---

## 5. Schema status

The consolidated schema (`CONSOLIDATED_SUPABASE_SCHEMA.sql`) was re-audited
against all new code. **One gap was found and fixed:** `user_notes.reminder_token`
(read by the MC-based reminder task) was missing — now added, plus an idempotent
"patch existing deployments" section so already-created tables get the new
columns (`reminder_token`, price-alert `triggered`/`active`, `bot_wallets`
seed-phrase columns, telegram_users `paper_mode`/`auto_blacklist`/
`anti_phishing_phrase`/`reset_token`/`notif_elite_sell`/`notif_tracked_wallet`).

All other columns referenced by new code (`bot_live_positions`, `fee_config`,
`bot_wallets`, `bot_signal_queue`) already exist in the schema. **Re-run the
consolidated file** — it is idempotent and safe on an existing database.
