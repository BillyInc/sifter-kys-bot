-- Add unique constraint to prevent duplicate signal execution at DB level
-- Run in Supabase SQL Editor

-- bot_auto_trades: unique per user per signal
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_auto_trades_user_signal_unique
    ON sifter_dev.bot_auto_trades (user_id, signal_key)
    WHERE signal_key IS NOT NULL;

-- paper_trades: prevent duplicate paper trades per user per signal
ALTER TABLE sifter_dev.paper_trades
    ADD COLUMN IF NOT EXISTS signal_key text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_trades_user_signal_unique
    ON sifter_dev.paper_trades (user_id, signal_key)
    WHERE signal_key IS NOT NULL;
