-- SIFTER Bot Auth Phase 1 — Password Reset & In-Bot Registration
-- Schema: sifter_dev
-- Date: 2026-06-03
--
-- Adds reset_token support to telegram_users for the password-reset flow.
-- The reset_token stores a secrets.token_urlsafe(48) value with a 1-hour TTL.
-- Both Telegram bot and dashboard reset flows write to the same columns.

BEGIN;

-- Add reset token columns to telegram_users
ALTER TABLE sifter_dev.telegram_users
    ADD COLUMN IF NOT EXISTS reset_token TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMPTZ DEFAULT NULL;

-- Index for quick token lookup during password reset
CREATE INDEX IF NOT EXISTS idx_telegram_users_reset_token
    ON sifter_dev.telegram_users(reset_token)
    WHERE reset_token IS NOT NULL;

-- Add any missing notification columns (for Phase 4 preparation)
ALTER TABLE sifter_dev.telegram_users
    ADD COLUMN IF NOT EXISTS notif_elite_sell BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS notif_tracked_wallet BOOLEAN NOT NULL DEFAULT TRUE;

COMMIT;
