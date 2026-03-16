-- Schema: sifter_dev (Supabase sync)
CREATE TABLE IF NOT EXISTS elite_15 (
  wallet_address TEXT PRIMARY KEY,
  rank INTEGER NOT NULL,
  professional_score REAL NOT NULL,
  tier TEXT CHECK(tier IN ('S', 'A', 'B', 'C', 'F')) NOT NULL,
  roi_30d REAL DEFAULT 0,
  runners_30d INTEGER DEFAULT 0,
  win_rate_7d REAL DEFAULT 0,
  consistency_score REAL DEFAULT 0,
  last_trade_time TIMESTAMP,
  last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watchlist (
  wallet_address TEXT PRIMARY KEY,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  status TEXT CHECK(status IN ('healthy', 'warning', 'critical')) DEFAULT 'healthy',
  current_rank INTEGER,
  rank_change INTEGER DEFAULT 0,
  degradation_alerts TEXT, -- JSON array
  auto_replace BOOLEAN DEFAULT false,
  replacement_for TEXT,
  replaced_by TEXT,
  last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (wallet_address) REFERENCES elite_15(wallet_address)
);

CREATE TABLE IF NOT EXISTS active_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_address TEXT NOT NULL,
  token_symbol TEXT NOT NULL,
  entry_price REAL NOT NULL,
  entry_size REAL NOT NULL,
  remaining_size REAL NOT NULL,
  entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  signal_type TEXT CHECK(signal_type IN ('single', 'double', 'multi')) NOT NULL,
  wallet_count INTEGER NOT NULL,
  triggering_wallets TEXT NOT NULL, -- JSON array
  total_usd_signal REAL NOT NULL,
  tp1_executed BOOLEAN DEFAULT 0,
  tp2_executed BOOLEAN DEFAULT 0,
  tp3_executed BOOLEAN DEFAULT 0,
  tp4_executed BOOLEAN DEFAULT 0,
  is_active BOOLEAN DEFAULT 1,
  closed_at TIMESTAMP,
  final_pnl REAL,
  UNIQUE(token_address, is_active)
);

CREATE TABLE IF NOT EXISTS trade_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id INTEGER,
  action TEXT CHECK(action IN ('buy', 'sell_tp1', 'sell_tp2', 'sell_tp3', 'sell_tp4', 'close')),
  amount REAL NOT NULL,
  price REAL NOT NULL,
  usd_value REAL NOT NULL,
  tx_signature TEXT UNIQUE,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (trade_id) REFERENCES active_trades(id)
);

CREATE TABLE IF NOT EXISTS purchased_tokens (
  token_address TEXT PRIMARY KEY,
  first_bought_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  tx_signature TEXT,
  wallet_address TEXT,
  usd_amount REAL
);

CREATE TABLE IF NOT EXISTS signals_buffer (
  token_address TEXT PRIMARY KEY,
  wallets TEXT NOT NULL, -- JSON array
  total_usd REAL NOT NULL,
  first_seen TIMESTAMP NOT NULL,
  last_seen TIMESTAMP NOT NULL,
  wallet_count INTEGER NOT NULL,
  expires_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS sniper_blacklist (
  wallet_address TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  evidence_tx TEXT,
  token TEXT,
  detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  data TEXT, -- JSON
  is_read BOOLEAN DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Default settings
INSERT OR IGNORE INTO user_settings (key, value) VALUES
  ('portfolio_total', '10000'),
  ('trading_percent', '0.10'),
  ('auto_trade_enabled', 'true'),
  ('min_buy_usd', '100'),
  ('signal_window_seconds', '15'),
  ('degradation_days', '7'),
  ('degradation_min_roi', '5'),
  ('auto_replace_wallets', 'true'),
  ('api_key_solanatracker', ''),
  ('api_key_helius', ''),
  ('wallet_connected', 'false'),
  ('wallet_address', ''),
  ('encrypted_private_key', ''),
  ('db_version', '2'),
  ('trading_mode', 'auto'),
  ('user_tier', 'free');

-- Supabase schema additions
-- ALTER TABLE users ADD COLUMN user_tier TEXT DEFAULT 'free';
-- ALTER TABLE users ADD COLUMN trading_mode TEXT DEFAULT 'auto';
