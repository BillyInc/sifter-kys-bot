-- Sifter KYS Supabase Schema (sifter_dev)
-- Auto-generated from production database 2026-03-29
-- Run against a fresh Supabase project to recreate
-- 29 tables total

CREATE SCHEMA IF NOT EXISTS sifter_dev;

-- ============================================
-- Core User Tables
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.users (
    user_id uuid PRIMARY KEY,
    wallet_address text,
    subscription_tier text DEFAULT 'free',
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.user_settings (
    user_id text PRIMARY KEY,
    email text,
    timezone text DEFAULT 'UTC',
    language text DEFAULT 'English',
    email_alerts boolean DEFAULT true,
    browser_notifications boolean DEFAULT true,
    alert_threshold integer DEFAULT 100,
    default_timeframe text DEFAULT '7d',
    default_candle text DEFAULT '5m',
    min_roi_multiplier real DEFAULT 3.0,
    theme text DEFAULT 'dark',
    compact_mode boolean DEFAULT false,
    data_refresh_rate integer DEFAULT 30,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.user_points (
    user_id text PRIMARY KEY,
    total_points integer DEFAULT 0,
    lifetime_points integer DEFAULT 0,
    current_tier text DEFAULT 'free',
    tier_multiplier numeric DEFAULT 1.0,
    daily_streak integer DEFAULT 0,
    longest_streak integer DEFAULT 0,
    last_activity_date date,
    level integer DEFAULT 1,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

-- ============================================
-- Wallet Watchlist & Monitoring
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_watchlist (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL,
    wallet_address text NOT NULL,
    tier text DEFAULT 'C',
    position integer,
    movement text,
    pump_count integer DEFAULT 0,
    avg_distance_to_peak real DEFAULT 0,
    avg_roi_to_peak real DEFAULT 0,
    consistency_score real DEFAULT 0,
    professional_score real DEFAULT 0,
    zone text,
    status text DEFAULT 'healthy',
    tokens_hit jsonb DEFAULT '[]',
    notes text DEFAULT '',
    tags jsonb DEFAULT '[]',
    alert_enabled boolean DEFAULT true,
    alert_threshold_usd real DEFAULT 100,
    last_updated timestamp with time zone DEFAULT now(),
    added_at timestamp with time zone DEFAULT now(),
    positions_changed integer DEFAULT 0,
    form jsonb DEFAULT '["neutral","neutral","neutral","neutral","neutral"]',
    degradation_alerts jsonb DEFAULT '[]',
    roi_7d real DEFAULT 0,
    roi_30d real DEFAULT 0,
    runners_7d integer DEFAULT 0,
    runners_30d integer DEFAULT 0,
    win_rate_7d real DEFAULT 0,
    last_trade_time timestamp with time zone,
    alert_on_buy boolean DEFAULT true,
    alert_on_sell boolean DEFAULT true,
    min_trade_usd numeric DEFAULT 10,
    source_type text DEFAULT 'single',
    avg_roi_mult real DEFAULT 0,
    avg_entry_to_ath real DEFAULT 0,
    tokens_qualified integer DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_activity (
    id bigserial PRIMARY KEY,
    wallet_address text NOT NULL,
    token_address text NOT NULL,
    token_ticker text,
    side text NOT NULL,
    usd_value real,
    tx_hash text NOT NULL,
    block_time bigint NOT NULL,
    signature text,
    amount numeric DEFAULT 0,
    price_per_token numeric DEFAULT 0,
    token_name text
);

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_monitor_status (
    wallet_address text PRIMARY KEY,
    last_checked_at bigint DEFAULT EXTRACT(epoch FROM now()),
    last_activity_at bigint,
    check_count integer DEFAULT 0,
    error_count integer DEFAULT 0,
    last_error text,
    is_active boolean DEFAULT true,
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_notifications (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL,
    wallet_address text NOT NULL,
    notification_type text NOT NULL,
    title text NOT NULL,
    message text,
    metadata jsonb DEFAULT '{}',
    is_read boolean DEFAULT false,
    sent_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.wallet_performance_history (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL,
    wallet_address text NOT NULL,
    date date NOT NULL,
    position integer,
    tier text,
    professional_score real,
    runners_30d integer DEFAULT 0,
    roi_30d real DEFAULT 0,
    avg_distance_to_peak real DEFAULT 0,
    form_score real DEFAULT 0,
    consistency_score real DEFAULT 0,
    created_at timestamp with time zone DEFAULT now()
);

-- ============================================
-- Twitter Watchlist
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.watchlist_accounts (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL,
    author_id text NOT NULL,
    username text,
    name text,
    followers integer DEFAULT 0,
    verified boolean DEFAULT false,
    added_at timestamp with time zone DEFAULT now(),
    tags jsonb DEFAULT '[]',
    notes text DEFAULT '',
    influence_score real DEFAULT 0,
    avg_timing real DEFAULT 0,
    pumps_called integer DEFAULT 0,
    last_updated timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.watchlist_groups (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL,
    group_name text NOT NULL,
    description text DEFAULT '',
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.group_memberships (
    id bigserial PRIMARY KEY,
    group_id bigint NOT NULL,
    account_id bigint NOT NULL,
    added_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.account_performance (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL,
    author_id text NOT NULL,
    token_address text,
    token_ticker text,
    pump_date timestamp with time zone,
    timing_minutes real,
    pump_gain real,
    confidence text,
    created_at timestamp with time zone DEFAULT now()
);

-- ============================================
-- Diary (Encrypted Notes)
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.watchlist_diary (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    wallet_address text,
    type text NOT NULL,
    encrypted_payload text NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    edited_at timestamp with time zone
);

CREATE TABLE IF NOT EXISTS sifter_dev.diary_user_salt (
    user_id text PRIMARY KEY,
    salt_b64 text NOT NULL,
    verification_token text NOT NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);

-- ============================================
-- Analysis & Caching
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.analysis_jobs (
    job_id text PRIMARY KEY,
    user_id uuid,
    status text DEFAULT 'pending',
    progress integer DEFAULT 0,
    phase text,
    results jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    tokens_total integer DEFAULT 0,
    tokens_completed integer DEFAULT 0,
    token_address text
);

CREATE TABLE IF NOT EXISTS sifter_dev.user_analysis_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    result_type text NOT NULL,
    label text,
    sublabel text,
    data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.token_analysis_cache (
    cache_key text PRIMARY KEY,
    token_address text NOT NULL,
    token_symbol text,
    min_roi_multiplier double precision,
    results jsonb NOT NULL,
    analysis_history jsonb,
    total_analyses integer DEFAULT 1,
    first_analysis timestamp DEFAULT now(),
    analyzed_at timestamp DEFAULT now(),
    created_at timestamp DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.token_qualified_wallets (
    token_address text PRIMARY KEY,
    qualified_wallets jsonb NOT NULL DEFAULT '[]',
    wallet_count integer NOT NULL DEFAULT 0,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.elite_100_cache (
    id bigserial PRIMARY KEY,
    cache_type text NOT NULL,
    data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone DEFAULT (now() + interval '1 hour')
);

CREATE TABLE IF NOT EXISTS sifter_dev.trades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_symbol text NOT NULL,
    price numeric NOT NULL,
    price_timestamp timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);

-- ============================================
-- Referral & Points System
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.referral_codes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    code text NOT NULL UNIQUE,
    active boolean DEFAULT true,
    clicks integer DEFAULT 0,
    signups integer DEFAULT 0,
    conversions integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.referrals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    referrer_user_id text NOT NULL,
    referrer_email text,
    referrer_tier text DEFAULT 'free',
    referee_user_id text NOT NULL,
    referee_email text,
    referee_tier text DEFAULT 'free',
    referral_code text NOT NULL,
    status text DEFAULT 'signed_up',
    signed_up_at timestamp with time zone DEFAULT now(),
    converted_at timestamp with time zone,
    first_month_commission numeric DEFAULT 0,
    total_recurring_commission numeric DEFAULT 0,
    total_earnings numeric DEFAULT 0,
    whop_subscription_id text,
    whop_customer_id text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.referral_earnings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    referral_id uuid,
    referrer_user_id text NOT NULL,
    referee_user_id text NOT NULL,
    amount numeric NOT NULL,
    commission_type text NOT NULL,
    commission_rate numeric,
    subscription_amount numeric,
    subscription_tier text,
    payment_status text DEFAULT 'pending',
    whop_transaction_id text,
    billing_period_start timestamp with time zone,
    paid_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.point_transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    action_type text NOT NULL,
    points_earned integer DEFAULT 0,
    base_points integer DEFAULT 0,
    multiplier_applied numeric DEFAULT 1.0,
    capped boolean DEFAULT false,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now()
);

-- ============================================
-- Telegram Integration
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.telegram_users (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL,
    telegram_chat_id text,
    telegram_username text,
    telegram_first_name text,
    telegram_last_name text,
    connection_code text,
    code_expires_at timestamp with time zone,
    connected_at timestamp with time zone,
    last_active timestamp with time zone DEFAULT now(),
    alerts_enabled boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.telegram_connection_tokens (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL,
    token text NOT NULL,
    telegram_id bigint,
    expires_at timestamp with time zone NOT NULL,
    used boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sifter_dev.telegram_linking (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    telegram_id bigint NOT NULL,
    telegram_username text,
    linking_code text,
    code_expires_at timestamp with time zone,
    linked_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

-- ============================================
-- Support & Feedback
-- ============================================

CREATE TABLE IF NOT EXISTS sifter_dev.support_tickets (
    id serial PRIMARY KEY,
    user_id text NOT NULL,
    subject text NOT NULL,
    message text NOT NULL,
    status text DEFAULT 'open',
    created_at timestamp with time zone DEFAULT now(),
    resolved_at timestamp with time zone
);

CREATE TABLE IF NOT EXISTS sifter_dev.feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dashboard_opinion text NOT NULL,
    improvements text NOT NULL,
    would_use varchar(10) NOT NULL,
    solves_problem text NOT NULL,
    referral_name text,
    referral_twitter varchar(100),
    email varchar(255),
    submitted_at timestamp with time zone DEFAULT now(),
    user_agent text,
    source varchar(50) DEFAULT 'web',
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
