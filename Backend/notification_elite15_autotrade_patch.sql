-- Notification + Elite15 + Telegram auto-trade patch
-- Run in Supabase SQL editor against the sifter_dev schema.

ALTER TABLE sifter_dev.telegram_users
  ADD COLUMN IF NOT EXISTS auto_trade_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS auto_trade_max_usd NUMERIC NOT NULL DEFAULT 100,
  ADD COLUMN IF NOT EXISTS auto_trade_source TEXT NOT NULL DEFAULT 'elite15';

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

CREATE INDEX IF NOT EXISTS idx_bot_auto_trades_pending
  ON sifter_dev.bot_auto_trades(user_id, status, created_at)
  WHERE status = 'pending';

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
