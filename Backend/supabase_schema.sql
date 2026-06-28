-- Supabase Schema for Sifter Watchlist
-- Uses a dedicated 'sifter_dev' schema to isolate from other applications
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor)

-- ============================================
-- CREATE DEDICATED SCHEMA
-- ============================================

CREATE SCHEMA IF NOT EXISTS sifter_dev;

-- Grant usage to authenticated users and service role
GRANT USAGE ON SCHEMA sifter_dev TO authenticated;
GRANT USAGE ON SCHEMA sifter_dev TO service_role;
GRANT USAGE ON SCHEMA sifter_dev TO anon;

-- ============================================
-- TABLES
-- ============================================

-- Users table (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS sifter_dev.users (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    wallet_address TEXT,
    subscription_tier TEXT DEFAULT 'free',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Watchlist accounts table
CREATE TABLE IF NOT EXISTS sifter_dev.watchlist_accounts (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    author_id TEXT NOT NULL,
    username TEXT,
    name TEXT,
    followers INTEGER DEFAULT 0,
    verified BOOLEAN DEFAULT FALSE,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    tags JSONB DEFAULT '[]'::jsonb,
    notes TEXT DEFAULT '',
    influence_score REAL DEFAULT 0,
    avg_timing REAL DEFAULT 0,
    pumps_called INTEGER DEFAULT 0,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, author_id)
);

-- Account performance tracking
CREATE TABLE IF NOT EXISTS sifter_dev.account_performance (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    author_id TEXT NOT NULL,
    token_address TEXT,
    token_ticker TEXT,
    pump_date TIMESTAMPTZ,
    timing_minutes REAL,
    pump_gain REAL,
    confidence TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Watchlist groups/folders
CREATE TABLE IF NOT EXISTS sifter_dev.watchlist_groups (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    group_name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, group_name)
);

-- Group memberships (many-to-many)
CREATE TABLE IF NOT EXISTS sifter_dev.group_memberships (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL REFERENCES sifter_dev.watchlist_groups(id) ON DELETE CASCADE,
    account_id BIGINT NOT NULL REFERENCES sifter_dev.watchlist_accounts(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(group_id, account_id)
);

-- ============================================
-- INDEXES
-- ============================================

CREATE INDEX IF NOT EXISTS idx_watchlist_accounts_user_id ON sifter_dev.watchlist_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_accounts_author_id ON sifter_dev.watchlist_accounts(author_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_accounts_influence ON sifter_dev.watchlist_accounts(influence_score DESC);
CREATE INDEX IF NOT EXISTS idx_account_performance_user_id ON sifter_dev.account_performance(user_id);
CREATE INDEX IF NOT EXISTS idx_account_performance_author_id ON sifter_dev.account_performance(author_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_groups_user_id ON sifter_dev.watchlist_groups(user_id);
CREATE INDEX IF NOT EXISTS idx_group_memberships_group_id ON sifter_dev.group_memberships(group_id);
CREATE INDEX IF NOT EXISTS idx_group_memberships_account_id ON sifter_dev.group_memberships(account_id);

-- ============================================
-- ENABLE ROW LEVEL SECURITY
-- ============================================

ALTER TABLE sifter_dev.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.watchlist_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.account_performance ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.watchlist_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.group_memberships ENABLE ROW LEVEL SECURITY;

-- ============================================
-- RLS POLICIES
-- ============================================

-- Users policies
CREATE POLICY "Users can view own profile"
    ON sifter_dev.users FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own profile"
    ON sifter_dev.users FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own profile"
    ON sifter_dev.users FOR UPDATE
    USING (auth.uid() = user_id);

-- Watchlist accounts policies
CREATE POLICY "Users can view own watchlist"
    ON sifter_dev.watchlist_accounts FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert to own watchlist"
    ON sifter_dev.watchlist_accounts FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own watchlist"
    ON sifter_dev.watchlist_accounts FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete from own watchlist"
    ON sifter_dev.watchlist_accounts FOR DELETE
    USING (auth.uid() = user_id);

-- Account performance policies
CREATE POLICY "Users can view own performance data"
    ON sifter_dev.account_performance FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own performance data"
    ON sifter_dev.account_performance FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own performance data"
    ON sifter_dev.account_performance FOR DELETE
    USING (auth.uid() = user_id);

-- Watchlist groups policies
CREATE POLICY "Users can view own groups"
    ON sifter_dev.watchlist_groups FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own groups"
    ON sifter_dev.watchlist_groups FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own groups"
    ON sifter_dev.watchlist_groups FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own groups"
    ON sifter_dev.watchlist_groups FOR DELETE
    USING (auth.uid() = user_id);

-- Group memberships policies (user must own the group)
CREATE POLICY "Users can view memberships of own groups"
    ON sifter_dev.group_memberships FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM sifter_dev.watchlist_groups
            WHERE id = group_memberships.group_id
            AND user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert memberships to own groups"
    ON sifter_dev.group_memberships FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM sifter_dev.watchlist_groups
            WHERE id = group_memberships.group_id
            AND user_id = auth.uid()
        )
    );

CREATE POLICY "Users can delete memberships from own groups"
    ON sifter_dev.group_memberships FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM sifter_dev.watchlist_groups
            WHERE id = group_memberships.group_id
            AND user_id = auth.uid()
        )
    );

-- ============================================
-- FUNCTION: Auto-create user profile on signup
-- ============================================

CREATE OR REPLACE FUNCTION sifter_dev.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO sifter_dev.users (user_id)
    VALUES (NEW.id)
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to auto-create user profile
DROP TRIGGER IF EXISTS on_auth_user_created_sifter_dev ON auth.users;
CREATE TRIGGER on_auth_user_created_sifter_dev
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION sifter_dev.handle_new_user();

-- ============================================
-- GRANTS FOR SERVICE ROLE AND AUTHENTICATED
-- ============================================

-- Grant all privileges on tables to service_role (backend operations)
GRANT ALL ON ALL TABLES IN SCHEMA sifter_dev TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA sifter_dev TO service_role;

-- Grant select/insert/update/delete to authenticated users (client operations via RLS)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA sifter_dev TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA sifter_dev TO authenticated;

-- Grant select to anon for public data (if any)
GRANT SELECT ON ALL TABLES IN SCHEMA sifter_dev TO anon;

-- Add to sifter_dev schema in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_performance_history (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL,
    date DATE NOT NULL,
    position INTEGER,
    tier TEXT,
    professional_score REAL,
    runners_30d INTEGER DEFAULT 0,
    roi_30d REAL DEFAULT 0,
    form_score REAL,
    consistency_score REAL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, wallet_address, date)
);

CREATE INDEX IF NOT EXISTS idx_wallet_perf_history_user 
ON sifter_dev.wallet_performance_history(user_id);

CREATE INDEX IF NOT EXISTS idx_wallet_perf_history_wallet 
ON sifter_dev.wallet_performance_history(wallet_address);

CREATE INDEX IF NOT EXISTS idx_wallet_perf_history_date 
ON sifter_dev.wallet_performance_history(date DESC);

-- RLS Policy
ALTER TABLE sifter_dev.wallet_performance_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own performance history"
    ON sifter_dev.wallet_performance_history FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "System can insert performance history"
    ON sifter_dev.wallet_performance_history FOR INSERT
    WITH CHECK (true);


-- Run this in Supabase Dashboard → SQL Editor

CREATE TABLE IF NOT EXISTS sifter_dev.telegram_users (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    telegram_chat_id TEXT UNIQUE,
    telegram_username TEXT,
    telegram_first_name TEXT,
    telegram_last_name TEXT,
    connection_code TEXT UNIQUE,
    code_expires_at TIMESTAMPTZ,
    connected_at TIMESTAMPTZ,
    last_active TIMESTAMPTZ DEFAULT NOW(),
    alerts_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_users_user_id 
ON sifter_dev.telegram_users(user_id);

CREATE INDEX IF NOT EXISTS idx_telegram_users_chat_id 
ON sifter_dev.telegram_users(telegram_chat_id);

CREATE INDEX IF NOT EXISTS idx_telegram_users_code 
ON sifter_dev.telegram_users(connection_code) 
WHERE connection_code IS NOT NULL;

-- RLS Policies
ALTER TABLE sifter_dev.telegram_users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own telegram connection"
    ON sifter_dev.telegram_users FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can update own telegram connection"
    ON sifter_dev.telegram_users FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "System can insert telegram connections"
    ON sifter_dev.telegram_users FOR INSERT
    WITH CHECK (true);

-- ============================================
-- TELEGRAM CONNECTION TOKENS
-- One-time deep-link tokens for the /start <token> account-linking flow.
-- Managed entirely server-side (service_role); RLS denies anon/authenticated
-- since tokens are sensitive (anyone with a token can link a chat to the account).
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.telegram_connection_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    telegram_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_conn_tokens_token
ON sifter_dev.telegram_connection_tokens(token);

CREATE INDEX IF NOT EXISTS idx_telegram_conn_tokens_user_unused
ON sifter_dev.telegram_connection_tokens(user_id) WHERE used = FALSE;

ALTER TABLE sifter_dev.telegram_connection_tokens ENABLE ROW LEVEL SECURITY;
-- No anon/authenticated policies on purpose: only service_role (which bypasses
-- RLS) touches this table, via the backend linking flow.

-- ============================================
-- WALLET WATCHLIST TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_watchlist (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL,
    tier TEXT DEFAULT 'C',
    pump_count INTEGER DEFAULT 0,
    avg_distance_to_peak REAL DEFAULT 0,
    avg_roi_to_peak REAL DEFAULT 0,
    consistency_score REAL DEFAULT 0,
    tokens_hit JSONB DEFAULT '[]'::jsonb,
    notes TEXT DEFAULT '',
    tags JSONB DEFAULT '[]'::jsonb,
    -- Alert settings
    alert_enabled BOOLEAN DEFAULT FALSE,
    alert_threshold_usd REAL DEFAULT 1000,
    last_alert_at TIMESTAMPTZ,
    -- Timestamps
    added_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, wallet_address)
);

CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_user_id
ON sifter_dev.wallet_watchlist(user_id);

CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_wallet
ON sifter_dev.wallet_watchlist(wallet_address);

CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_tier
ON sifter_dev.wallet_watchlist(tier);

CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_alerts
ON sifter_dev.wallet_watchlist(user_id, alert_enabled)
WHERE alert_enabled = TRUE;

ALTER TABLE sifter_dev.wallet_watchlist ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own wallet watchlist"
    ON sifter_dev.wallet_watchlist FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert to own wallet watchlist"
    ON sifter_dev.wallet_watchlist FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own wallet watchlist"
    ON sifter_dev.wallet_watchlist FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete from own wallet watchlist"
    ON sifter_dev.wallet_watchlist FOR DELETE
    USING (auth.uid() = user_id);

-- ============================================
-- WALLET NOTIFICATIONS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_notifications (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL,
    notification_type TEXT NOT NULL, -- 'buy', 'sell', 'alert', 'degradation', 'promotion'
    title TEXT NOT NULL,
    message TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}'::jsonb,
    is_read BOOLEAN DEFAULT FALSE,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    telegram_sent BOOLEAN DEFAULT FALSE,
    telegram_sent_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_wallet_notifications_user
ON sifter_dev.wallet_notifications(user_id, sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_wallet_notifications_unread
ON sifter_dev.wallet_notifications(user_id, is_read)
WHERE is_read = FALSE;

ALTER TABLE sifter_dev.wallet_notifications ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own notifications"
    ON sifter_dev.wallet_notifications FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "System can insert notifications"
    ON sifter_dev.wallet_notifications FOR INSERT
    WITH CHECK (true);

CREATE POLICY "Users can update own notifications"
    ON sifter_dev.wallet_notifications FOR UPDATE
    USING (auth.uid() = user_id);

-- ============================================
-- NOTIFICATION FLAT COLUMNS + AUTO-TRADE
-- ============================================

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

ALTER TABLE sifter_dev.telegram_users
    ADD COLUMN IF NOT EXISTS auto_trade_hourly_limit INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS auto_trade_daily_limit INTEGER NOT NULL DEFAULT 8;

ALTER TABLE sifter_dev.bot_auto_trades
    ADD COLUMN IF NOT EXISTS signal_key TEXT,
    ADD COLUMN IF NOT EXISTS wallet_count INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_bot_auto_trades_signal_key
ON sifter_dev.bot_auto_trades(user_id, token_address, signal_key);

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

-- ============================================
-- WALLET ACTIVITY TABLE (Monitor Events)
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_activity (
    id BIGSERIAL PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    token_address TEXT NOT NULL,
    token_ticker TEXT,
    token_name TEXT,
    side TEXT NOT NULL, -- 'buy' or 'sell'
    amount NUMERIC,
    usd_value NUMERIC,
    price_per_token NUMERIC,
    signature TEXT UNIQUE,
    block_time TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wallet_activity_wallet
ON sifter_dev.wallet_activity(wallet_address, block_time DESC);

CREATE INDEX IF NOT EXISTS idx_wallet_activity_token
ON sifter_dev.wallet_activity(token_address);

CREATE INDEX IF NOT EXISTS idx_wallet_activity_time
ON sifter_dev.wallet_activity(block_time DESC);

-- Partition hint: Consider partitioning by block_time for large datasets
-- No RLS needed - this is system data accessed via service role

-- ============================================
-- WALLET MONITOR STATUS TABLE (Health)
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_monitor_status (
    id BIGSERIAL PRIMARY KEY,
    wallet_address TEXT UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    last_checked_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ,
    check_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    avg_check_duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wallet_monitor_active
ON sifter_dev.wallet_monitor_status(is_active, last_checked_at);

-- No RLS - system table accessed via service role

-- ============================================
-- REFRESH GRANTS FOR NEW TABLES
-- ============================================

GRANT ALL ON ALL TABLES IN SCHEMA sifter_dev TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA sifter_dev TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA sifter_dev TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA sifter_dev TO authenticated;

-- ============================================
-- RPC FUNCTIONS
-- ============================================

-- Function to atomically increment check_count and error_count
CREATE OR REPLACE FUNCTION sifter_dev.increment_check_count(
    p_wallet_address TEXT,
    p_error_increment INTEGER DEFAULT 0
)
RETURNS VOID AS $$
BEGIN
    UPDATE sifter_dev.wallet_monitor_status
    SET
        check_count = check_count + 1,
        error_count = error_count + p_error_increment
    WHERE wallet_address = p_wallet_address;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute to service role
GRANT EXECUTE ON FUNCTION sifter_dev.increment_check_count(TEXT, INTEGER) TO service_role;
