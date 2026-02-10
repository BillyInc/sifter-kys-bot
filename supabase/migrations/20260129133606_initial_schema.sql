-- Supabase Schema for Sifter Watchlist
-- Uses a dedicated 'sifter_dev' schema to isolate from other applications

-- ============================================
-- CREATE DEDICATED SCHEMA
-- ============================================

CREATE SCHEMA IF NOT EXISTS sifter_dev;

-- Grant usage to authenticated users and service role
GRANT USAGE ON SCHEMA sifter_dev TO authenticated;
GRANT USAGE ON SCHEMA sifter_dev TO service_role;
GRANT USAGE ON SCHEMA sifter_dev TO anon;

-- ============================================
-- TABLE
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

-- Wallet watchlist table
CREATE TABLE IF NOT EXISTS sifter_dev.wallet_watchlist (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL,
    tier TEXT DEFAULT 'C',
    pump_count INTEGER DEFAULT 0,
    avg_distance_to_peak REAL DEFAULT 0,
    avg_roi_to_peak REAL DEFAULT 0,
    consistency_score REAL DEFAULT 0,
    tokens_hit TEXT[] DEFAULT '{}',
    notes TEXT DEFAULT '',
    tags JSONB DEFAULT '[]'::jsonb,
    alert_enabled BOOLEAN DEFAULT TRUE,
    alert_threshold_usd REAL DEFAULT 100,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, wallet_address)
);

-- Wallet activity/notifications table
CREATE TABLE IF NOT EXISTS sifter_dev.wallet_notifications (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    is_read BOOLEAN DEFAULT FALSE,
    sent_at TIMESTAMPTZ DEFAULT NOW()
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
CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_user_id ON sifter_dev.wallet_watchlist(user_id);
CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_address ON sifter_dev.wallet_watchlist(wallet_address);
CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_tier ON sifter_dev.wallet_watchlist(tier);
CREATE INDEX IF NOT EXISTS idx_wallet_notifications_user_id ON sifter_dev.wallet_notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_wallet_notifications_unread ON sifter_dev.wallet_notifications(user_id, is_read) WHERE is_read = FALSE;

-- ============================================
-- ENABLE ROW LEVEL SECURITY
-- ============================================

ALTER TABLE sifter_dev.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.watchlist_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.account_performance ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.watchlist_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.group_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.wallet_watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE sifter_dev.wallet_notifications ENABLE ROW LEVEL SECURITY;

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

-- Wallet watchlist policies
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

-- Wallet notifications policies
CREATE POLICY "Users can view own notifications"
    ON sifter_dev.wallet_notifications FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own notifications"
    ON sifter_dev.wallet_notifications FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own notifications"
    ON sifter_dev.wallet_notifications FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own notifications"
    ON sifter_dev.wallet_notifications FOR DELETE
    USING (auth.uid() = user_id);

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
