-- Paper trader ops, notification normalization, and operator controls.
-- This migration supersedes the historical notification_elite15_autotrade_patch.sql
-- and is safe to run against an already-patched sifter_dev schema.

CREATE SCHEMA IF NOT EXISTS sifter_dev;

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
  signal_key TEXT,
  wallet_count INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bot_auto_trades_pending
  ON sifter_dev.bot_auto_trades(user_id, status, created_at)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_bot_auto_trades_signal_key
  ON sifter_dev.bot_auto_trades(user_id, token_address, signal_key);

ALTER TABLE sifter_dev.bot_auto_trades ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'sifter_dev'
      AND tablename = 'bot_auto_trades'
      AND policyname = 'Users can view own bot trades'
  ) THEN
    CREATE POLICY "Users can view own bot trades"
      ON sifter_dev.bot_auto_trades FOR SELECT
      USING (auth.uid() = user_id);
  END IF;
END $$;

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

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'sifter_dev'
      AND tablename = 'bot_wallets'
      AND policyname = 'Users can manage own bot wallet'
  ) THEN
    CREATE POLICY "Users can manage own bot wallet"
      ON sifter_dev.bot_wallets FOR ALL
      USING (auth.uid() = user_id);
  END IF;
END $$;

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

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'sifter_dev'
      AND tablename = 'paper_trade_positions'
      AND policyname = 'Users can view paper positions'
  ) THEN
    CREATE POLICY "Users can view paper positions"
      ON sifter_dev.paper_trade_positions FOR SELECT
      USING (true);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'sifter_dev'
      AND tablename = 'paper_trade_events'
      AND policyname = 'Users can view paper trade events'
  ) THEN
    CREATE POLICY "Users can view paper trade events"
      ON sifter_dev.paper_trade_events FOR SELECT
      USING (true);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS sifter_dev.paper_trader_settings (
  id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id = TRUE),
  paper_trader_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  execution_mode TEXT NOT NULL DEFAULT 'paper',
  quote_ttl_seconds INTEGER NOT NULL DEFAULT 15,
  min_liquidity_usd NUMERIC NOT NULL DEFAULT 10000,
  max_price_impact_bps INTEGER NOT NULL DEFAULT 500,
  default_slippage_bps INTEGER NOT NULL DEFAULT 250,
  default_priority_fee_lamports INTEGER NOT NULL DEFAULT 500000,
  max_retry_count INTEGER NOT NULL DEFAULT 2,
  latency_ms INTEGER NOT NULL DEFAULT 1500,
  partial_fill_probability NUMERIC NOT NULL DEFAULT 0.15,
  route_failure_probability NUMERIC NOT NULL DEFAULT 0.08,
  no_route_probability NUMERIC NOT NULL DEFAULT 0.05,
  email_digest_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  immediate_failure_alerts BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_by UUID REFERENCES sifter_dev.users(user_id)
);

INSERT INTO sifter_dev.paper_trader_settings (id)
VALUES (TRUE)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS sifter_dev.paper_trade_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status TEXT NOT NULL DEFAULT 'running',
  source TEXT NOT NULL DEFAULT 'operator',
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  stopped_at TIMESTAMPTZ,
  started_by UUID REFERENCES sifter_dev.users(user_id),
  stopped_by UUID REFERENCES sifter_dev.users(user_id),
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_trade_runs_status
  ON sifter_dev.paper_trade_runs(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS sifter_dev.paper_trade_logs (
  id BIGSERIAL PRIMARY KEY,
  run_id UUID REFERENCES sifter_dev.paper_trade_runs(id) ON DELETE SET NULL,
  severity TEXT NOT NULL DEFAULT 'info',
  component TEXT NOT NULL,
  event_type TEXT NOT NULL,
  status TEXT,
  signal_key TEXT,
  token_address TEXT,
  message TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_trade_logs_time
  ON sifter_dev.paper_trade_logs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_paper_trade_logs_severity
  ON sifter_dev.paper_trade_logs(severity, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_paper_trade_logs_run
  ON sifter_dev.paper_trade_logs(run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS sifter_dev.paper_trade_email_recipients (
  id BIGSERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  digest_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  failure_alert_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE sifter_dev.paper_trader_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.paper_trade_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.paper_trade_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.paper_trade_email_recipients ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'sifter_dev'
      AND tablename = 'paper_trader_settings'
      AND policyname = 'Authenticated can view paper trader settings'
  ) THEN
    CREATE POLICY "Authenticated can view paper trader settings"
      ON sifter_dev.paper_trader_settings FOR SELECT
      USING (auth.uid() IS NOT NULL);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'sifter_dev'
      AND tablename = 'paper_trade_runs'
      AND policyname = 'Authenticated can view paper trade runs'
  ) THEN
    CREATE POLICY "Authenticated can view paper trade runs"
      ON sifter_dev.paper_trade_runs FOR SELECT
      USING (auth.uid() IS NOT NULL);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'sifter_dev'
      AND tablename = 'paper_trade_logs'
      AND policyname = 'Authenticated can view paper trade logs'
  ) THEN
    CREATE POLICY "Authenticated can view paper trade logs"
      ON sifter_dev.paper_trade_logs FOR SELECT
      USING (auth.uid() IS NOT NULL);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'sifter_dev'
      AND tablename = 'paper_trade_email_recipients'
      AND policyname = 'Authenticated can view email recipients'
  ) THEN
    CREATE POLICY "Authenticated can view email recipients"
      ON sifter_dev.paper_trade_email_recipients FOR SELECT
      USING (auth.uid() IS NOT NULL);
  END IF;
END $$;
