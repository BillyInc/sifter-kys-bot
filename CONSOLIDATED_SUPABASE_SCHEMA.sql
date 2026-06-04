-- ============================================================================
-- SIFTER KYS — CONSOLIDATED SUPABASE SCHEMA FOR TELEGRAM BOT
-- ============================================================================
-- Run this entire file in the Supabase SQL Editor (or psql) to provision every
-- table, column, index, RLS policy, and grant the Telegram bot needs.
--
-- Schema: sifter_dev
-- Idempotent: safe to re-run (IF NOT EXISTS / DROP POLICY IF EXISTS).
--
-- PREREQUISITE: sifter_dev.users and sifter_dev.telegram_users must already
-- exist (created by Backend/supabase_schema.sql). This file is additive and
-- includes the base bot columns in case they are missing.
--
-- ORDER:
--   0. Schema + base tables (users, telegram_users base bot columns, bot_wallets)
--   1. telegram_users — ALL bot strategy/settings/notification columns
--   2. bot_live_positions
--   3. bot_signal_queue
--   4. bot_token_blacklist
--   5. bot_elite_selections           (NEW — Elite 15 copy-trade selection)
--   6. access_codes
--   7. magic_links
--   8. bot_price_alerts
--   9. user_notes
--  10. fee_config
--  11. bot_wallets extra columns       (seed-phrase / wallet_type support)
--  12. Grants
-- ============================================================================


-- ────────────────────────────────────────────────────────────────────────────
-- 0. SCHEMA + BASE PREREQUISITES
-- ────────────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS sifter_dev;

-- users (extends auth.users) — created by base schema; included for safety.
CREATE TABLE IF NOT EXISTS sifter_dev.users (
    user_id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    wallet_address    TEXT,
    subscription_tier TEXT DEFAULT 'free',
    email             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- telegram_users — created by base schema; included for safety.
CREATE TABLE IF NOT EXISTS sifter_dev.telegram_users (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    telegram_chat_id   TEXT,
    telegram_username  TEXT,
    connection_code    TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_users_user_id  ON sifter_dev.telegram_users(user_id);
CREATE INDEX IF NOT EXISTS idx_telegram_users_chat_id  ON sifter_dev.telegram_users(telegram_chat_id);

ALTER TABLE sifter_dev.telegram_users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own telegram connection" ON sifter_dev.telegram_users;
CREATE POLICY "Users can view own telegram connection"
    ON sifter_dev.telegram_users FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own telegram connection" ON sifter_dev.telegram_users;
CREATE POLICY "Users can update own telegram connection"
    ON sifter_dev.telegram_users FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can insert telegram connections" ON sifter_dev.telegram_users;
CREATE POLICY "System can insert telegram connections"
    ON sifter_dev.telegram_users FOR INSERT WITH CHECK (true);


-- ────────────────────────────────────────────────────────────────────────────
-- 1. telegram_users — ALL BOT COLUMNS (strategy, settings, notifications, auth)
-- ────────────────────────────────────────────────────────────────────────────
ALTER TABLE sifter_dev.telegram_users
    -- Auto-trade core
    ADD COLUMN IF NOT EXISTS auto_trade_enabled      BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS auto_trade_max_usd       NUMERIC NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS auto_trade_hourly_limit  INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS auto_trade_daily_limit   INTEGER NOT NULL DEFAULT 8,
    ADD COLUMN IF NOT EXISTS auto_trade_source        TEXT,

    -- Consensus + portfolio
    ADD COLUMN IF NOT EXISTS consensus_threshold      INTEGER NOT NULL DEFAULT 1,   -- 0-15
    ADD COLUMN IF NOT EXISTS trading_pool_pct         NUMERIC NOT NULL DEFAULT 50,
    ADD COLUMN IF NOT EXISTS max_deployment_pct       NUMERIC NOT NULL DEFAULT 80,

    -- Signal-tier sizing
    ADD COLUMN IF NOT EXISTS tier1_pct_of_pool        NUMERIC NOT NULL DEFAULT 30,
    ADD COLUMN IF NOT EXISTS tier2_pct_of_pool        NUMERIC NOT NULL DEFAULT 70,
    ADD COLUMN IF NOT EXISTS tier3_pct_of_total       NUMERIC NOT NULL DEFAULT 40,

    -- Manual / flat sizing
    ADD COLUMN IF NOT EXISTS position_size_mode       TEXT    NOT NULL DEFAULT 'percent',
    ADD COLUMN IF NOT EXISTS position_size_value      NUMERIC NOT NULL DEFAULT 10,

    -- Risk management
    ADD COLUMN IF NOT EXISTS stop_loss_pct            INTEGER NOT NULL DEFAULT -50,
    ADD COLUMN IF NOT EXISTS take_profit_x            NUMERIC NOT NULL DEFAULT 5.0,
    ADD COLUMN IF NOT EXISTS trailing_stop_pct        NUMERIC,                       -- NULL = off
    ADD COLUMN IF NOT EXISTS auto_blacklist           BOOLEAN NOT NULL DEFAULT TRUE, -- auto-BL on SL

    -- Access gating
    ADD COLUMN IF NOT EXISTS access_tier              TEXT    NOT NULL DEFAULT 'free',

    -- Execution preferences
    ADD COLUMN IF NOT EXISTS slippage_bps             INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS mev_protection           BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS paper_mode               BOOLEAN NOT NULL DEFAULT FALSE,

    -- Notification toggles
    ADD COLUMN IF NOT EXISTS notif_trade_open         BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_trade_close        BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_tp_hit             BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_sl_hit             BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_signal             BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_elite_sell         BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS notif_tracked_wallet     BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_daily_summary      BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_weekly_summary     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS alerts_enabled           BOOLEAN NOT NULL DEFAULT TRUE,

    -- Quiet hours (UTC 0-23, NULL = off)
    ADD COLUMN IF NOT EXISTS quiet_hours_start        SMALLINT,
    ADD COLUMN IF NOT EXISTS quiet_hours_end          SMALLINT,

    -- Password reset (one-time token, 1hr TTL) — used by both bot + dashboard
    ADD COLUMN IF NOT EXISTS reset_token              TEXT,
    ADD COLUMN IF NOT EXISTS reset_token_expires_at   TIMESTAMPTZ,

    -- Anti-phishing email security phrase
    ADD COLUMN IF NOT EXISTS anti_phishing_phrase     TEXT;

CREATE INDEX IF NOT EXISTS idx_telegram_users_reset_token
ON sifter_dev.telegram_users(reset_token)
WHERE reset_token IS NOT NULL;


-- ────────────────────────────────────────────────────────────────────────────
-- 2. bot_live_positions — per-user live/paper position ledger
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.bot_live_positions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    token_address       TEXT NOT NULL,
    token_symbol        TEXT,
    status              TEXT NOT NULL DEFAULT 'open',        -- open | closed | archived
    total_invested_usd  NUMERIC NOT NULL DEFAULT 0,
    avg_entry_price     NUMERIC NOT NULL DEFAULT 0,
    token_amount        NUMERIC NOT NULL DEFAULT 0,
    remaining_amount    NUMERIC NOT NULL DEFAULT 0,
    current_value_usd   NUMERIC NOT NULL DEFAULT 0,
    realized_pnl_usd    NUMERIC NOT NULL DEFAULT 0,
    unrealized_pnl_usd  NUMERIC NOT NULL DEFAULT 0,
    roi_pct             NUMERIC,
    roi_mult            NUMERIC,
    signal_key          TEXT,
    wallet_count        INTEGER NOT NULL DEFAULT 1,
    signal_type         TEXT NOT NULL DEFAULT 'single',      -- single | double | mega | manual
    execution_mode      TEXT NOT NULL DEFAULT 'safe_noop',   -- safe_noop | paper | devnet | live
    trigger_type        TEXT NOT NULL DEFAULT 'auto_elite',  -- auto_elite | manual | operator
    stop_loss_pct       INTEGER,
    take_profit_x       NUMERIC,
    trailing_stop_pct   NUMERIC,
    peak_multiple       NUMERIC NOT NULL DEFAULT 1,
    entry_txid          TEXT,
    exit_txid           TEXT,
    exits_taken         JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    opened_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checked_at     TIMESTAMPTZ,
    closed_at           TIMESTAMPTZ,
    close_reason        TEXT
);

CREATE INDEX IF NOT EXISTS idx_bot_live_positions_user_open
ON sifter_dev.bot_live_positions(user_id, status, opened_at DESC) WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_bot_live_positions_user_token
ON sifter_dev.bot_live_positions(user_id, token_address, status);

CREATE INDEX IF NOT EXISTS idx_bot_live_positions_user_id_status
ON sifter_dev.bot_live_positions(user_id, id, status);

-- One open position per user/token (double-click / duplicate-worker guard)
CREATE UNIQUE INDEX IF NOT EXISTS ux_bot_live_positions_user_token_open
ON sifter_dev.bot_live_positions(user_id, token_address) WHERE status = 'open';

ALTER TABLE sifter_dev.bot_live_positions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own bot positions" ON sifter_dev.bot_live_positions;
CREATE POLICY "Users can view own bot positions"
    ON sifter_dev.bot_live_positions FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can manage bot positions" ON sifter_dev.bot_live_positions;
CREATE POLICY "System can manage bot positions"
    ON sifter_dev.bot_live_positions FOR ALL USING (true) WITH CHECK (true);


-- ────────────────────────────────────────────────────────────────────────────
-- 3. bot_signal_queue — durable per-user signal fan-out / audit
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.bot_signal_queue (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    signal_key           TEXT NOT NULL,
    token_address        TEXT NOT NULL,
    token_ticker         TEXT,
    side                 TEXT NOT NULL DEFAULT 'buy',
    wallet_count         INTEGER NOT NULL DEFAULT 1,
    signal_type          TEXT NOT NULL DEFAULT 'single',
    total_usd            NUMERIC NOT NULL DEFAULT 0,
    requested_usd        NUMERIC,
    status               TEXT NOT NULL DEFAULT 'pending',
    -- pending | executed | skipped | blacklisted | rate_limited | error
    skip_reason          TEXT,
    bot_live_position_id BIGINT REFERENCES sifter_dev.bot_live_positions(id) ON DELETE SET NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, signal_key)
);

CREATE INDEX IF NOT EXISTS idx_bot_signal_queue_user_status
ON sifter_dev.bot_signal_queue(user_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bot_signal_queue_status_updated
ON sifter_dev.bot_signal_queue(status, updated_at DESC);

ALTER TABLE sifter_dev.bot_signal_queue ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own signal queue" ON sifter_dev.bot_signal_queue;
CREATE POLICY "Users can view own signal queue"
    ON sifter_dev.bot_signal_queue FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can manage signal queue" ON sifter_dev.bot_signal_queue;
CREATE POLICY "System can manage signal queue"
    ON sifter_dev.bot_signal_queue FOR ALL USING (true) WITH CHECK (true);


-- ────────────────────────────────────────────────────────────────────────────
-- 4. bot_token_blacklist — per-user blacklist (one of two filters)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.bot_token_blacklist (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    token_address TEXT NOT NULL,
    token_symbol  TEXT,
    reason        TEXT NOT NULL DEFAULT 'manual',   -- manual | rug | auto_sl
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, token_address)
);

CREATE INDEX IF NOT EXISTS idx_bot_token_blacklist_user
ON sifter_dev.bot_token_blacklist(user_id, token_address);

ALTER TABLE sifter_dev.bot_token_blacklist ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own blacklist" ON sifter_dev.bot_token_blacklist;
CREATE POLICY "Users can manage own blacklist"
    ON sifter_dev.bot_token_blacklist FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can manage blacklist" ON sifter_dev.bot_token_blacklist;
CREATE POLICY "System can manage blacklist"
    ON sifter_dev.bot_token_blacklist FOR ALL USING (true) WITH CHECK (true);


-- ────────────────────────────────────────────────────────────────────────────
-- 5. bot_elite_selections — which Elite 15 wallets a user copy-trades (NEW)
--    Empty for a user = copy ALL Elite 15 (the default).
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.bot_elite_selections (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    wallet_address  TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, wallet_address)
);

CREATE INDEX IF NOT EXISTS idx_bot_elite_selections_user
ON sifter_dev.bot_elite_selections(user_id, enabled);

ALTER TABLE sifter_dev.bot_elite_selections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own elite selections" ON sifter_dev.bot_elite_selections;
CREATE POLICY "Users can manage own elite selections"
    ON sifter_dev.bot_elite_selections FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can read elite selections" ON sifter_dev.bot_elite_selections;
CREATE POLICY "System can read elite selections"
    ON sifter_dev.bot_elite_selections FOR ALL USING (true) WITH CHECK (true);


-- ────────────────────────────────────────────────────────────────────────────
-- 6. access_codes — invite codes (operator-issued, service-role only)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.access_codes (
    id            BIGSERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    tier          TEXT NOT NULL DEFAULT 'autotrader',
    max_uses      INTEGER NOT NULL DEFAULT 1,
    used_count    INTEGER NOT NULL DEFAULT 0,
    used_by       UUID REFERENCES sifter_dev.users(user_id),
    used_at       TIMESTAMPTZ,
    created_by    BIGINT,                            -- operator telegram chat_id
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_access_codes_unused
ON sifter_dev.access_codes(code) WHERE used_count < max_uses;

ALTER TABLE sifter_dev.access_codes ENABLE ROW LEVEL SECURITY;
-- No public policy: service_role only.


-- ────────────────────────────────────────────────────────────────────────────
-- 7. magic_links — one-time deep links (operator-issued)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.magic_links (
    id            BIGSERIAL PRIMARY KEY,
    token         TEXT NOT NULL UNIQUE,
    access_tier   TEXT NOT NULL DEFAULT 'autotrader',
    purpose       TEXT NOT NULL DEFAULT 'invite',    -- invite | link | session
    user_id       UUID REFERENCES sifter_dev.users(user_id),
    used          BOOLEAN NOT NULL DEFAULT FALSE,
    used_by       UUID REFERENCES sifter_dev.users(user_id),
    used_at       TIMESTAMPTZ,
    created_by    BIGINT,
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_magic_links_unused
ON sifter_dev.magic_links(token) WHERE used = FALSE;

ALTER TABLE sifter_dev.magic_links ENABLE ROW LEVEL SECURITY;
-- No public policy: service_role only.


-- ────────────────────────────────────────────────────────────────────────────
-- 8. bot_price_alerts — MC/price alerts
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.bot_price_alerts (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    token_address   TEXT NOT NULL,
    token_symbol    TEXT,
    direction       TEXT NOT NULL DEFAULT 'above',   -- above | below
    target_price    NUMERIC,
    target_mc_usd   NUMERIC,
    target_mult     NUMERIC,
    notify_telegram BOOLEAN NOT NULL DEFAULT TRUE,
    notify_email    BOOLEAN NOT NULL DEFAULT TRUE,
    repeat_on_hit   BOOLEAN NOT NULL DEFAULT FALSE,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    triggered       BOOLEAN NOT NULL DEFAULT FALSE,
    triggered_at    TIMESTAMPTZ,
    last_fired_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bot_price_alerts_active
ON sifter_dev.bot_price_alerts(token_address, active) WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_bot_price_alerts_user
ON sifter_dev.bot_price_alerts(user_id);

ALTER TABLE sifter_dev.bot_price_alerts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own price alerts" ON sifter_dev.bot_price_alerts;
CREATE POLICY "Users can manage own price alerts"
    ON sifter_dev.bot_price_alerts FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can update price alerts" ON sifter_dev.bot_price_alerts;
CREATE POLICY "System can update price alerts"
    ON sifter_dev.bot_price_alerts FOR ALL USING (true) WITH CHECK (true);


-- ────────────────────────────────────────────────────────────────────────────
-- 9. user_notes — notes & reminders
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.user_notes (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    token_address   TEXT,
    body            TEXT NOT NULL DEFAULT '',
    pinned          BOOLEAN NOT NULL DEFAULT FALSE,
    reminder_type   TEXT,                             -- NULL | time | mc
    reminder_at     TIMESTAMPTZ,
    reminder_token  TEXT,                             -- token CA for MC-based reminders
    reminder_mc_usd NUMERIC,
    reminder_fired  BOOLEAN NOT NULL DEFAULT FALSE,
    notify_telegram BOOLEAN NOT NULL DEFAULT TRUE,
    notify_email    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_notes_user
ON sifter_dev.user_notes(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_notes_reminders
ON sifter_dev.user_notes(reminder_fired, reminder_at)
WHERE reminder_type IS NOT NULL AND reminder_fired = FALSE;

ALTER TABLE sifter_dev.user_notes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own notes" ON sifter_dev.user_notes;
CREATE POLICY "Users can manage own notes"
    ON sifter_dev.user_notes FOR ALL
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can manage notes" ON sifter_dev.user_notes;
CREATE POLICY "System can manage notes"
    ON sifter_dev.user_notes FOR ALL USING (true) WITH CHECK (true);


-- ────────────────────────────────────────────────────────────────────────────
-- 10. fee_config — platform fee singleton (wired, disabled by default)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.fee_config (
    id                     SERIAL PRIMARY KEY,
    scope                  TEXT NOT NULL DEFAULT 'global' UNIQUE,
    platform_fee_bps       INTEGER NOT NULL DEFAULT 100,
    treasury_wallet        TEXT,
    treasury_token_account TEXT,
    enabled                BOOLEAN NOT NULL DEFAULT FALSE,   -- fees only charged when TRUE
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by             TEXT
);

INSERT INTO sifter_dev.fee_config (scope, platform_fee_bps, enabled)
VALUES ('global', 100, FALSE)
ON CONFLICT (scope) DO NOTHING;

ALTER TABLE sifter_dev.fee_config ENABLE ROW LEVEL SECURITY;
-- No public policy: service_role / operators only.


-- ────────────────────────────────────────────────────────────────────────────
-- 11. bot_wallets — trading wallet store (+ seed-phrase support columns)
--     Base table (encrypted_key/key_iv/key_tag) created by base schema.
--     The bot's seed-phrase import path uses encrypted_private_key + wallet_type;
--     both schemes are supported by adding the columns below.
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.bot_wallets (
    id             BIGSERIAL PRIMARY KEY,
    user_id        UUID NOT NULL UNIQUE REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    public_key     TEXT NOT NULL,
    encrypted_key  TEXT,         -- AES-GCM scheme (private key import)
    key_iv         TEXT,
    key_tag        TEXT,
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_trade_at  TIMESTAMPTZ
);

ALTER TABLE sifter_dev.bot_wallets
    ADD COLUMN IF NOT EXISTS encrypted_private_key TEXT,                       -- Fernet scheme (seed phrase)
    ADD COLUMN IF NOT EXISTS wallet_type           TEXT DEFAULT 'private_key'; -- private_key | seed_phrase | email

ALTER TABLE sifter_dev.bot_wallets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own bot wallet" ON sifter_dev.bot_wallets;
CREATE POLICY "Users can manage own bot wallet"
    ON sifter_dev.bot_wallets FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can manage bot wallets" ON sifter_dev.bot_wallets;
CREATE POLICY "System can manage bot wallets"
    ON sifter_dev.bot_wallets FOR ALL USING (true) WITH CHECK (true);


-- ────────────────────────────────────────────────────────────────────────────
-- 11b. PATCH EXISTING DEPLOYMENTS (CREATE TABLE IF NOT EXISTS won't add columns
--      to tables that already exist — these ALTERs are idempotent and safe).
-- ────────────────────────────────────────────────────────────────────────────
ALTER TABLE sifter_dev.user_notes
    ADD COLUMN IF NOT EXISTS reminder_token  TEXT,
    ADD COLUMN IF NOT EXISTS reminder_mc_usd NUMERIC,
    ADD COLUMN IF NOT EXISTS notify_telegram BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notify_email    BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE sifter_dev.bot_price_alerts
    ADD COLUMN IF NOT EXISTS triggered    BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS triggered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS active       BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE sifter_dev.bot_wallets
    ADD COLUMN IF NOT EXISTS encrypted_private_key TEXT,
    ADD COLUMN IF NOT EXISTS wallet_type           TEXT DEFAULT 'private_key';

ALTER TABLE sifter_dev.telegram_users
    ADD COLUMN IF NOT EXISTS paper_mode           BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS auto_blacklist       BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS anti_phishing_phrase TEXT,
    ADD COLUMN IF NOT EXISTS reset_token          TEXT,
    ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS notif_elite_sell     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS notif_tracked_wallet BOOLEAN NOT NULL DEFAULT TRUE;


-- ────────────────────────────────────────────────────────────────────────────
-- 12. GRANTS — refresh for all bot tables
-- ────────────────────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA sifter_dev TO service_role, authenticated, anon;
GRANT ALL ON ALL TABLES IN SCHEMA sifter_dev TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA sifter_dev TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA sifter_dev TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA sifter_dev TO authenticated;

-- ============================================================================
-- END — Bot is now provisioned. Verify with:
--   SELECT table_name FROM information_schema.tables WHERE table_schema='sifter_dev'
--     AND table_name LIKE 'bot_%' OR table_name IN ('access_codes','magic_links','user_notes','fee_config');
-- ============================================================================
