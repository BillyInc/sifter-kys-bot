-- SIFTER Bot Phase 3 — Elite 15 Wallet Selection for Copy-Trading
-- Schema: sifter_dev
-- Date: 2026-06-03
--
-- Users can select WHICH Elite 15 wallets their auto-trader copy-trades.
-- The auto-trader only fires on signals from selected wallets.
-- Manual trade Elite signal picker shows signals from ALL wallets.

BEGIN;

CREATE TABLE IF NOT EXISTS sifter_dev.bot_elite_selections (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES sifter_dev.users(user_id) ON DELETE CASCADE,
    wallet_address TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, wallet_address)
);

CREATE INDEX IF NOT EXISTS idx_bot_elite_selections_user
    ON sifter_dev.bot_elite_selections(user_id, enabled);

ALTER TABLE sifter_dev.bot_elite_selections ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own elite selections"
    ON sifter_dev.bot_elite_selections FOR ALL
    USING (auth.uid() = user_id);

COMMIT;
