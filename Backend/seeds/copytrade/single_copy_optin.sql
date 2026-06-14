-- =====================================================================
-- single_copy_optin.sql  —  opt-in table for gated single-wallet copy (STEP 7)
-- Run AFTER SETUP_ALL.sql. Idempotent. Schema: sifter_dev.
-- Default behavior is OFF: a user must insert a row here to auto-copy a
-- List-A elite single, and even then it only fires WITH confluence (>=1 other
-- tracked co-buyer) and a per-wallet daily cap of 2 (enforced in code).
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS sifter_dev.bot_single_copy_optins (
  user_id        TEXT NOT NULL,
  wallet_address TEXT NOT NULL,
  enabled        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (user_id, wallet_address)
);
CREATE INDEX IF NOT EXISTS idx_single_copy_optins_wallet
  ON sifter_dev.bot_single_copy_optins(wallet_address) WHERE enabled;

COMMIT;
