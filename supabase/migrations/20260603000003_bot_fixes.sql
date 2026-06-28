-- SIFTER Bot Fix Phase — paper_mode, auto_blacklist, wallet columns
-- Schema: sifter_dev
-- Date: 2026-06-03

BEGIN;

-- Per-user paper mode toggle and auto-blacklist setting
ALTER TABLE sifter_dev.telegram_users
    ADD COLUMN IF NOT EXISTS paper_mode BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS auto_blacklist BOOLEAN NOT NULL DEFAULT TRUE;

-- bot_wallets: ensure columns for seed-phrase / private-key imports exist
ALTER TABLE sifter_dev.bot_wallets
    ADD COLUMN IF NOT EXISTS encrypted_private_key TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS wallet_type TEXT DEFAULT 'private_key';

-- bot_price_alerts: ensure active column exists for monitor task
ALTER TABLE sifter_dev.bot_price_alerts
    ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;

-- Anti-phishing personal verification phrase shown in every email.
-- Auto-generated on first email if not set; user can customize it.
ALTER TABLE sifter_dev.telegram_users
    ADD COLUMN IF NOT EXISTS anti_phishing_phrase TEXT DEFAULT NULL;

COMMIT;
