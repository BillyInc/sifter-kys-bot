-- Performance indexes for KYS Supabase tables
-- Run via Supabase SQL Editor or psql
-- Created: 2026-03-29

-- Wallet watchlist indexes
CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_user_id ON sifter_dev.wallet_watchlist(user_id);
CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_wallet_addr ON sifter_dev.wallet_watchlist(wallet_address);
CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_user_wallet ON sifter_dev.wallet_watchlist(user_id, wallet_address);

-- Notifications indexes
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON sifter_dev.wallet_notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_sent_at ON sifter_dev.wallet_notifications(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread ON sifter_dev.wallet_notifications(user_id, is_read) WHERE is_read = false;

-- Analysis jobs indexes
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_user_id ON sifter_dev.analysis_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_status ON sifter_dev.analysis_jobs(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_created ON sifter_dev.analysis_jobs(created_at DESC);

-- User analysis history
CREATE INDEX IF NOT EXISTS idx_user_history_user_id ON sifter_dev.user_analysis_history(user_id);
CREATE INDEX IF NOT EXISTS idx_user_history_created ON sifter_dev.user_analysis_history(created_at DESC);

-- Wallet activity
CREATE INDEX IF NOT EXISTS idx_wallet_activity_wallet ON sifter_dev.wallet_activity(wallet_address);
CREATE INDEX IF NOT EXISTS idx_wallet_activity_block_time ON sifter_dev.wallet_activity(block_time DESC);

-- Referral system
CREATE INDEX IF NOT EXISTS idx_referral_codes_code ON sifter_dev.referral_codes(code) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON sifter_dev.referrals(referrer_user_id);

-- Token cache
CREATE INDEX IF NOT EXISTS idx_token_cache_address ON sifter_dev.token_analysis_cache(token_address);

-- Support tickets
CREATE INDEX IF NOT EXISTS idx_support_tickets_user ON sifter_dev.support_tickets(user_id);
