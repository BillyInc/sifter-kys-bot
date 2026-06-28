-- ============================================================================
-- Migration: telegram_bot_rebuild
-- Date:      2026-05-31
-- Schema:    sifter_dev
--
-- Adds the per-user trading-bot data layer for the menu-driven Telegram bot
-- rebuild (Sprint 1 foundation).
--
-- Conventions (match Backend/supabase_schema.sql):
--   * Idempotent: ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS.
--   * Postgres has no CREATE POLICY IF NOT EXISTS, so each policy is preceded
--     by DROP POLICY IF EXISTS to keep this file safely re-runnable.
--   * RLS: USING (auth.uid() = user_id) for user reads; WITH CHECK (true) for
--     system (service-role) writes. Closes with the standard GRANT refresh.
--
-- Safe to run after the base schema. Does NOT alter existing tables/columns
-- beyond additive ADD COLUMN IF NOT EXISTS on telegram_users.
--
-- NOTE: The signal-filter columns fake_vol_max_pct, risk_score_max,
-- min_mc_usd, max_mc_usd are INTENTIONALLY OMITTED. The auto-trade filter
-- stack is consensus_threshold + bot_token_blacklist only. Do not add them.
-- ============================================================================


-- ── A. New strategy / settings columns on telegram_users ────────────────────
-- Reuses existing auto_trade_max_usd / auto_trade_daily_limit /
-- auto_trade_hourly_limit (do NOT duplicate those here).
ALTER TABLE sifter_dev.telegram_users
    -- Consensus: how many Elite wallets must agree within the 120s window.
    -- 1 = single, 2 = double, 3 = mega (classify_signal tiers). Range 0-15.
    ADD COLUMN IF NOT EXISTS consensus_threshold  INTEGER NOT NULL DEFAULT 1,

    -- Portfolio split: % of wallet the bot may trade; remainder is reserve.
    ADD COLUMN IF NOT EXISTS trading_pool_pct     NUMERIC NOT NULL DEFAULT 50,
    -- Deployment cap: auto-pause new trades when this % of pool is deployed.
    ADD COLUMN IF NOT EXISTS max_deployment_pct   NUMERIC NOT NULL DEFAULT 80,

    -- Signal-tier position sizing.
    ADD COLUMN IF NOT EXISTS tier1_pct_of_pool    NUMERIC NOT NULL DEFAULT 30,  -- 1 wallet
    ADD COLUMN IF NOT EXISTS tier2_pct_of_pool    NUMERIC NOT NULL DEFAULT 70,  -- 2 wallets
    ADD COLUMN IF NOT EXISTS tier3_pct_of_total   NUMERIC NOT NULL DEFAULT 40,  -- 3+ wallets (% of TOTAL)

    -- Manual / flat position sizing.
    ADD COLUMN IF NOT EXISTS position_size_mode   TEXT    NOT NULL DEFAULT 'percent',  -- percent | fixed
    ADD COLUMN IF NOT EXISTS position_size_value  NUMERIC NOT NULL DEFAULT 10,

    -- Risk management.
    ADD COLUMN IF NOT EXISTS stop_loss_pct        INTEGER NOT NULL DEFAULT -50,  -- negative: -50 = -50%
    ADD COLUMN IF NOT EXISTS take_profit_x        NUMERIC NOT NULL DEFAULT 5.0,
    ADD COLUMN IF NOT EXISTS trailing_stop_pct    NUMERIC,                       -- NULL = off

    -- Access gating: 'free' (manual only) | 'autotrader' (full bot access).
    ADD COLUMN IF NOT EXISTS access_tier          TEXT    NOT NULL DEFAULT 'free',

    -- Execution preferences.
    ADD COLUMN IF NOT EXISTS slippage_bps         INTEGER NOT NULL DEFAULT 100,  -- 100 = 1%
    ADD COLUMN IF NOT EXISTS mev_protection       BOOLEAN NOT NULL DEFAULT TRUE,

    -- Notification toggles.
    ADD COLUMN IF NOT EXISTS notif_trade_open     BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_trade_close    BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_tp_hit         BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_sl_hit         BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_signal         BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_daily_summary  BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS notif_weekly_summary BOOLEAN NOT NULL DEFAULT FALSE,

    -- Quiet hours (UTC hour 0-23, NULL = feature off).
    ADD COLUMN IF NOT EXISTS quiet_hours_start    SMALLINT,
    ADD COLUMN IF NOT EXISTS quiet_hours_end      SMALLINT;


-- ── B1. bot_live_positions — per-user position ledger ───────────────────────
-- The execution boundary writes here. Parallels (never touches) paper_trade_*.
CREATE TABLE IF NOT EXISTS sifter_dev.bot_live_positions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    token_address       TEXT NOT NULL,
    token_symbol        TEXT,
    status              TEXT NOT NULL DEFAULT 'open',          -- open | closed | archived
    total_invested_usd  NUMERIC NOT NULL DEFAULT 0,
    avg_entry_price     NUMERIC NOT NULL DEFAULT 0,
    token_amount        NUMERIC NOT NULL DEFAULT 0,
    remaining_amount    NUMERIC NOT NULL DEFAULT 0,
    current_value_usd   NUMERIC NOT NULL DEFAULT 0,
    realized_pnl_usd    NUMERIC NOT NULL DEFAULT 0,
    unrealized_pnl_usd  NUMERIC NOT NULL DEFAULT 0,
    signal_key          TEXT,
    wallet_count        INTEGER NOT NULL DEFAULT 1,
    signal_type         TEXT NOT NULL DEFAULT 'single',        -- single | double | mega | manual
    execution_mode      TEXT NOT NULL DEFAULT 'safe_noop',     -- safe_noop | paper | devnet | live
    trigger_type        TEXT NOT NULL DEFAULT 'auto_elite',    -- auto_elite | manual | operator
    stop_loss_pct       INTEGER,                               -- snapshot at entry
    take_profit_x       NUMERIC,                               -- snapshot at entry
    trailing_stop_pct   NUMERIC,                               -- snapshot at entry, NULL = off
    peak_multiple       NUMERIC NOT NULL DEFAULT 1,            -- for trailing-stop tracking
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
ON sifter_dev.bot_live_positions(user_id, status, opened_at DESC)
WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_bot_live_positions_user_token
ON sifter_dev.bot_live_positions(user_id, token_address, status);

ALTER TABLE sifter_dev.bot_live_positions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own bot positions" ON sifter_dev.bot_live_positions;
CREATE POLICY "Users can view own bot positions"
    ON sifter_dev.bot_live_positions FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can manage bot positions" ON sifter_dev.bot_live_positions;
CREATE POLICY "System can manage bot positions"
    ON sifter_dev.bot_live_positions FOR ALL
    USING (true)
    WITH CHECK (true);


-- ── B2. bot_signal_queue — durable per-user signal fan-out / audit ──────────
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

ALTER TABLE sifter_dev.bot_signal_queue ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own signal queue" ON sifter_dev.bot_signal_queue;
CREATE POLICY "Users can view own signal queue"
    ON sifter_dev.bot_signal_queue FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can manage signal queue" ON sifter_dev.bot_signal_queue;
CREATE POLICY "System can manage signal queue"
    ON sifter_dev.bot_signal_queue FOR ALL
    USING (true)
    WITH CHECK (true);


-- ── B3. bot_token_blacklist — per-user blacklist (one of the two filters) ───
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
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);


-- ── B4. access_codes — invite codes (operator-issued, service-role only) ────
CREATE TABLE IF NOT EXISTS sifter_dev.access_codes (
    id            BIGSERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    tier          TEXT NOT NULL DEFAULT 'autotrader',
    max_uses      INTEGER NOT NULL DEFAULT 1,
    used_count    INTEGER NOT NULL DEFAULT 0,
    used_by       UUID REFERENCES sifter_dev.users(user_id),
    used_at       TIMESTAMPTZ,
    created_by    BIGINT,                            -- operator telegram chat_id
    expires_at    TIMESTAMPTZ,                       -- NULL = no expiry
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_access_codes_unused
ON sifter_dev.access_codes(code)
WHERE used_count < max_uses;

ALTER TABLE sifter_dev.access_codes ENABLE ROW LEVEL SECURITY;
-- No public policy: access codes are managed exclusively by service_role.


-- ── B5. magic_links — one-time deep links (operator-issued) ─────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.magic_links (
    id            BIGSERIAL PRIMARY KEY,
    token         TEXT NOT NULL UNIQUE,
    access_tier   TEXT NOT NULL DEFAULT 'autotrader',
    purpose       TEXT NOT NULL DEFAULT 'invite',    -- invite | link | session
    user_id       UUID REFERENCES sifter_dev.users(user_id),
    used          BOOLEAN NOT NULL DEFAULT FALSE,
    used_by       UUID REFERENCES sifter_dev.users(user_id),
    used_at       TIMESTAMPTZ,
    created_by    BIGINT,                            -- operator telegram chat_id
    expires_at    TIMESTAMPTZ,                       -- NULL = no expiry
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_magic_links_unused
ON sifter_dev.magic_links(token)
WHERE used = FALSE;

ALTER TABLE sifter_dev.magic_links ENABLE ROW LEVEL SECURITY;
-- No public policy: magic links are managed exclusively by service_role.


-- ── B6. bot_price_alerts — MC/price alerts ──────────────────────────────────
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
    last_fired_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bot_price_alerts_active
ON sifter_dev.bot_price_alerts(token_address, active)
WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_bot_price_alerts_user
ON sifter_dev.bot_price_alerts(user_id);

ALTER TABLE sifter_dev.bot_price_alerts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own price alerts" ON sifter_dev.bot_price_alerts;
CREATE POLICY "Users can manage own price alerts"
    ON sifter_dev.bot_price_alerts FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "System can update price alerts" ON sifter_dev.bot_price_alerts;
CREATE POLICY "System can update price alerts"
    ON sifter_dev.bot_price_alerts FOR UPDATE
    USING (true)
    WITH CHECK (true);


-- ── B7. user_notes — notes & reminders ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS sifter_dev.user_notes (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    token_address   TEXT,
    body            TEXT NOT NULL DEFAULT '',
    pinned          BOOLEAN NOT NULL DEFAULT FALSE,
    reminder_type   TEXT,                             -- NULL | time | mc
    reminder_at     TIMESTAMPTZ,
    reminder_mc_usd NUMERIC,
    reminder_fired  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_notes_user
ON sifter_dev.user_notes(user_id, created_at DESC);

ALTER TABLE sifter_dev.user_notes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own notes" ON sifter_dev.user_notes;
CREATE POLICY "Users can manage own notes"
    ON sifter_dev.user_notes FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);


-- ── B8. fee_config — platform fee singleton (wired, disabled by default) ─────
CREATE TABLE IF NOT EXISTS sifter_dev.fee_config (
    id                  SERIAL PRIMARY KEY,
    scope               TEXT NOT NULL DEFAULT 'global' UNIQUE,
    platform_fee_bps    INTEGER NOT NULL DEFAULT 100,
    treasury_wallet     TEXT,
    treasury_token_account TEXT,
    enabled             BOOLEAN NOT NULL DEFAULT FALSE,   -- fees only charged when TRUE
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by          TEXT
);

ALTER TABLE sifter_dev.fee_config ENABLE ROW LEVEL SECURITY;
-- No public policy: fee config is managed exclusively by service_role / operators.


-- ── C. Refresh grants for the new tables ────────────────────────────────────
GRANT ALL ON ALL TABLES IN SCHEMA sifter_dev TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA sifter_dev TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA sifter_dev TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA sifter_dev TO authenticated;
