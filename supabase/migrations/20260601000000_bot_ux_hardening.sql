-- ============================================================================
-- Migration: bot_ux_hardening
-- Date:      2026-06-01
-- Schema:    sifter_dev
--
-- Adds defensive indexes used by the UX-complete autonomous/manual bot paths.
-- Historical migrations are left untouched.
-- ============================================================================

-- One open position per user/token. This prevents double-clicks, queue retries,
-- or duplicate workers from opening the same token twice for the same user.
CREATE UNIQUE INDEX IF NOT EXISTS ux_bot_live_positions_user_token_open
ON sifter_dev.bot_live_positions(user_id, token_address)
WHERE status = 'open';

-- Fast lookup for stale-button handling and close/modify screens.
CREATE INDEX IF NOT EXISTS idx_bot_live_positions_user_id_status
ON sifter_dev.bot_live_positions(user_id, id, status);

-- Fast queue inspection by state for operators and worker retries.
CREATE INDEX IF NOT EXISTS idx_bot_signal_queue_status_updated
ON sifter_dev.bot_signal_queue(status, updated_at DESC);
