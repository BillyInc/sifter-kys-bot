-- Notification + Elite15 + Telegram auto-trade patch
-- Run in Supabase SQL editor against the sifter_dev schema.

ALTER TABLE sifter_dev.telegram_users
  ADD COLUMN IF NOT EXISTS auto_trade_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS auto_trade_max_usd NUMERIC NOT NULL DEFAULT 100,
  ADD COLUMN IF NOT EXISTS auto_trade_source TEXT NOT NULL DEFAULT 'elite15',
  ADD COLUMN IF NOT EXISTS auto_trade_hourly_limit INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS auto_trade_daily_limit INTEGER NOT NULL DEFAULT 8;

ALTER TABLE sifter_dev.wallet_notifications
  ADD COLUMN IF NOT EXISTS side TEXT,
  ADD COLUMN IF NOT EXISTS token_ticker TEXT,
  ADD COLUMN IF NOT EXISTS token_name TEXT,
  ADD COLUMN IF NOT EXISTS token_address TEXT,
  ADD COLUMN IF NOT EXISTS usd_value NUMERIC,
  ADD COLUMN IF NOT EXISTS tx_hash TEXT,
  ADD COLUMN IF NOT EXISTS wallet_tier TEXT,
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'watchlist';

CREATE INDEX IF NOT EXISTS idx_wallet_notifications_source_unread
  ON sifter_dev.wallet_notifications(user_id, source, is_read)
  WHERE is_read = FALSE;

CREATE TABLE IF NOT EXISTS sifter_dev.bot_auto_trades (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
  source TEXT NOT NULL DEFAULT 'elite15',
  side TEXT NOT NULL,
  token_address TEXT NOT NULL,
  token_ticker TEXT,
  usd_amount NUMERIC NOT NULL DEFAULT 0,
  wallet_address TEXT,
  wallet_tier TEXT DEFAULT 'S',
  tx_hash_signal TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  result_txid TEXT,
  error_message TEXT,
  notification_id BIGINT REFERENCES sifter_dev.wallet_notifications(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE sifter_dev.bot_auto_trades
  ADD COLUMN IF NOT EXISTS signal_key TEXT,
  ADD COLUMN IF NOT EXISTS wallet_count INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_bot_auto_trades_pending
  ON sifter_dev.bot_auto_trades(user_id, status, created_at)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_bot_auto_trades_signal_key
  ON sifter_dev.bot_auto_trades(user_id, token_address, signal_key);

ALTER TABLE sifter_dev.bot_auto_trades ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own bot trades"
  ON sifter_dev.bot_auto_trades FOR SELECT
  USING (auth.uid() = user_id);

CREATE TABLE IF NOT EXISTS sifter_dev.bot_wallets (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL UNIQUE REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
  public_key TEXT NOT NULL,
  encrypted_key TEXT NOT NULL,
  key_iv TEXT NOT NULL,
  key_tag TEXT NOT NULL,
  registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_trade_at TIMESTAMPTZ
);

ALTER TABLE sifter_dev.bot_wallets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own bot wallet"
  ON sifter_dev.bot_wallets FOR ALL
  USING (auth.uid() = user_id);

CREATE TABLE IF NOT EXISTS sifter_dev.paper_trade_positions (
  id BIGSERIAL PRIMARY KEY,
  token_address TEXT NOT NULL,
  token_ticker TEXT,
  entry_price_usd NUMERIC NOT NULL DEFAULT 0,
  entry_size_usd NUMERIC NOT NULL DEFAULT 0,
  token_amount NUMERIC NOT NULL DEFAULT 0,
  remaining_amount NUMERIC NOT NULL DEFAULT 0,
  realized_pnl_usd NUMERIC NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open',
  wallet_count INTEGER NOT NULL DEFAULT 1,
  signal_type TEXT NOT NULL DEFAULT 'single',
  signal_key TEXT NOT NULL UNIQUE,
  signal_wallets JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  peak_multiple NUMERIC NOT NULL DEFAULT 1,
  exits_taken JSONB NOT NULL DEFAULT '[]'::jsonb,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_checked_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  close_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_paper_trade_positions_status
  ON sifter_dev.paper_trade_positions(status, opened_at DESC);

CREATE INDEX IF NOT EXISTS idx_paper_trade_positions_token
  ON sifter_dev.paper_trade_positions(token_address, status);

CREATE TABLE IF NOT EXISTS sifter_dev.paper_trade_events (
  id BIGSERIAL PRIMARY KEY,
  token_address TEXT NOT NULL,
  token_ticker TEXT,
  event_type TEXT NOT NULL,
  reason TEXT,
  signal_key TEXT,
  wallet_count INTEGER NOT NULL DEFAULT 1,
  usd_amount NUMERIC,
  price_usd NUMERIC,
  multiple NUMERIC,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_trade_events_time
  ON sifter_dev.paper_trade_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_paper_trade_events_signal
  ON sifter_dev.paper_trade_events(signal_key, created_at DESC);

ALTER TABLE sifter_dev.paper_trade_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.paper_trade_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view paper positions"
  ON sifter_dev.paper_trade_positions FOR SELECT
  USING (true);

CREATE POLICY "Users can view paper trade events"
  ON sifter_dev.paper_trade_events FOR SELECT
  USING (true);
