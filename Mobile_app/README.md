# Sifter Auto-Trader — React Native App

A production-ready Solana memecoin auto-trader with multi-layer MEV protection, biometric security, and tier-based signal routing.

---

## File Structure

```
SifterAutoTrader/
├── App.js                             # Entry point
├── package.json
├── .env.example                       # Fill in your keys
│
├── src/
│   ├── database/
│   │   ├── schema.sql                 # SQLite + Supabase schema
│   │   ├── DatabaseService.js         # All DB reads/writes
│   │   └── DatabaseProvider.js        # React context wrapper
│   │
│   ├── store/
│   │   ├── useStore.js                # Zustand store (tier, mode, trades)
│   │   └── StoreProvider.js
│   │
│   ├── services/
│   │   ├── FortifiedAutoTrader.js     # ★ MAIN: 13-layer protected auto-trader
│   │   ├── RealTimeMonitor.js         # WebSocket + polling wallet monitor
│   │   ├── DuplicatePrevention.js     # Hard rule: never auto-buy same token twice
│   │   ├── EliteTransactionVerifier.js # 2-check verifier (signed + ≥$100)
│   │   ├── ExtremeCaseHandler.js      # Dynamic slippage + gas (8 extreme cases)
│   │   ├── UltimateProtection.js      # MEV/sniper/honeypot protection pipeline
│   │   ├── SecureWalletService.js     # Biometric + split-key encryption
│   │   ├── KillSwitch.js              # Remote + manual emergency stop
│   │   ├── HeartbeatMonitor.js        # Uptime monitoring + auto-restart
│   │   ├── RedundantMonitor.js        # Multi-provider WebSocket failover
│   │   ├── TransactionQueue.js        # Offline queue with retry/backoff
│   │   ├── PositionSizeManager.js     # Position sizing rules
│   │   ├── WatchlistManager.js        # Degradation detection + auto-replace
│   │   ├── BackgroundService.js       # App init + background fetch config
│   │   └── NotificationService.js     # Push notification channels setup
│   │
│   ├── components/
│   │   ├── AppLock.js                 # Biometric / PIN lock screen
│   │   ├── SafeButton.js              # Debounce + double-click protection
│   │   └── ModeSwitcher.js            # Premium: toggle auto ↔ manual
│   │
│   ├── navigation/
│   │   └── AppNavigator.js            # Bottom tabs + stack navigators
│   │
│   ├── screens/
│   │   ├── DashboardScreen.js
│   │   ├── PositionsScreen.js
│   │   ├── Elite15Screen.js
│   │   ├── SettingsScreen.js
│   │   ├── ConnectWalletScreen.js
│   │   ├── WalletDetailScreen.js
│   │   └── TradeDetailScreen.js
│   │
│   └── utils/
│       └── actionDebouncer.js         # Global debounce / single-execution guard
```

---

## Signal Routing Logic

```
FREE user
  └── All signals → sendManualNotification()

PREMIUM user + tradingMode = 'auto' + source = 'elite15'
  └── executeAutoTrade()  ← bot executes all 13 layers

PREMIUM user + tradingMode = 'manual' + source = 'elite15'
  └── sendManualNotification()  (with "auto-trader is OFF" note)

ANY user + source = 'watchlist'
  └── sendManualNotification()
```

Premium users toggle auto ↔ manual instantly via **ModeSwitcher** in Settings.

---

## Position Sizing Rules

| Signal | Position Size |
|--------|--------------|
| 1 wallet (first buy) | 30% of trading balance (10% of portfolio) |
| 1 wallet (second signal) | 70% of trading balance |
| 2 wallets | 100% of trading balance |
| 3+ wallets (MEGA) | 40% of **total** portfolio |

---

## Take-Profit Schedule

| Level | Trigger | Sell |
|-------|---------|------|
| TP1 | 5x | 25% of position |
| TP2 | 10x | 25% of remaining |
| TP3 | 20x | 25% of remaining |
| TP4 | 30x | Close remainder |

---

## Duplicate Prevention (Hard Rule)

The auto-trader **never** buys the same token twice automatically.
- All purchased tokens are persisted to SQLite on every buy.
- Survives app restarts.
- To buy again: user taps **"Buy Again"** → confirms dialog → one-time override executes once.

---

## Setup

```bash
# 1. Install dependencies
npm install

# 2. Copy env template
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_ANON_KEY, HELIUS_API_KEY, SOLANATRACKER_API_KEY

# 3. Supabase: add tier/mode columns
# ALTER TABLE users ADD COLUMN user_tier TEXT DEFAULT 'free';
# ALTER TABLE users ADD COLUMN trading_mode TEXT DEFAULT 'auto';

# 4. Run
expo start
```

---

## Deployment

```bash
# Android APK
eas build --platform android

# iOS
eas build --platform ios

# Direct APK download (no app store)
eas build --platform android --profile preview
# Host the .apk on your website
```

---

## API Keys Required

| Service | Used For |
|---------|---------|
| SolanaTracker | Wallet trade monitoring (WebSocket) |
| Helius | Priority fees, MEV risk, simulations |
| Supabase | Elite 15 sync, user tier management |
| QuickNode (optional) | Redundant WebSocket provider |

---

## Security Architecture

- Private key split across two SecureStore locations (device-only encryption)
- Biometric authentication required for every transaction signing
- App lock on background with PIN fallback
- Remote kill switch checked every 60 seconds
- Self-destruct clears all keys and local data
- Post-trade sniper analysis blacklists attacking wallets
