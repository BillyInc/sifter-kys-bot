-- Database Schema for SIFTER KYS v3.0
-- Stores analysis results, cross-token tracking, and smart watchlist

-- ============================================================================
-- USERS TABLE (existing - updated)
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    wallet_address TEXT,
    subscription_tier TEXT DEFAULT 'free',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- ANALYSIS RESULTS (NEW)
-- Stores Top 20 results from each token analysis for cross-token overlap
-- ============================================================================
CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    token_address TEXT NOT NULL,
    token_ticker TEXT,
    token_name TEXT,
    chain TEXT,
    analysis_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    time_range TEXT,
    candle_size TEXT,
    rallies_found INTEGER DEFAULT 0,
    tweets_found INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_analysis_user_token 
ON analysis_results(user_id, token_address);

CREATE INDEX IF NOT EXISTS idx_analysis_timestamp 
ON analysis_results(analysis_timestamp DESC);

-- ============================================================================
-- TOP ACCOUNTS PER ANALYSIS (NEW)
-- Stores the Top 20 accounts from each analysis
-- ============================================================================
CREATE TABLE IF NOT EXISTS top_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL,
    author_id TEXT NOT NULL,
    username TEXT,
    name TEXT,
    followers INTEGER DEFAULT 0,
    verified BOOLEAN DEFAULT FALSE,
    pumps_called INTEGER DEFAULT 0,
    avg_timing REAL,
    earliest_call REAL,
    influence_score REAL,
    high_confidence_count INTEGER DEFAULT 0,
    rank_position INTEGER,
    FOREIGN KEY (analysis_id) REFERENCES analysis_results(id) ON DELETE CASCADE
);

-- Index for cross-token queries
CREATE INDEX IF NOT EXISTS idx_top_accounts_author 
ON top_accounts(author_id);

CREATE INDEX IF NOT EXISTS idx_top_accounts_analysis 
ON top_accounts(analysis_id);

-- ============================================================================
-- CROSS-TOKEN TRACKING (NEW)
-- Materialized view of accounts appearing in multiple tokens
-- ============================================================================
CREATE TABLE IF NOT EXISTS cross_token_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id TEXT UNIQUE NOT NULL,
    username TEXT,
    total_tokens_called INTEGER DEFAULT 0,
    tokens_list TEXT, -- JSON array of token tickers
    total_pumps_called INTEGER DEFAULT 0,
    avg_influence_score REAL,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for lookups
CREATE INDEX IF NOT EXISTS idx_cross_token_author 
ON cross_token_tracking(author_id);

CREATE INDEX IF NOT EXISTS idx_cross_token_count 
ON cross_token_tracking(total_tokens_called DESC);

-- ============================================================================
-- WATCHLIST (existing - keeping as is)
-- ============================================================================
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    username TEXT,
    name TEXT,
    followers INTEGER,
    verified BOOLEAN DEFAULT FALSE,
    influence_score REAL,
    avg_timing REAL,
    pumps_called INTEGER,
    tags TEXT,
    notes TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    group_id INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (group_id) REFERENCES watchlist_groups(id),
    UNIQUE(user_id, author_id)
);

-- ============================================================================
-- WATCHLIST GROUPS (existing)
-- ============================================================================
CREATE TABLE IF NOT EXISTS watchlist_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    group_name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- ============================================================================
-- SMART WATCHLIST CONFIGURATION (NEW)
-- Settings for automated notifications
-- ============================================================================
CREATE TABLE IF NOT EXISTS watchlist_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT UNIQUE NOT NULL,
    notify_new_contracts BOOLEAN DEFAULT TRUE,
    notify_trending BOOLEAN DEFAULT TRUE,
    min_liquidity_usd INTEGER DEFAULT 50000,
    monitored_chains TEXT, -- JSON array: ["solana", "base", "ethereum"]
    notification_method TEXT DEFAULT 'app', -- 'app', 'email', 'telegram'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- ============================================================================
-- NOTIFICATION HISTORY (NEW)
-- Track what notifications were sent
-- ============================================================================
CREATE TABLE IF NOT EXISTS notification_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    token_address TEXT,
    token_ticker TEXT,
    notification_type TEXT, -- 'new_contract', 'trending', 'high_liquidity'
    tweet_id TEXT,
    tweet_text TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_notification_user_time 
ON notification_history(user_id, sent_at DESC);

-- ============================================================================
-- INTERACTION ANALYSIS CACHE (NEW)
-- Cache results of interaction analysis to save API quota
-- ============================================================================
CREATE TABLE IF NOT EXISTS interaction_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_ids_hash TEXT UNIQUE NOT NULL, -- Hash of sorted account IDs
    coordination_index INTEGER,
    coordination_level TEXT, -- 'High', 'Medium', 'Low'
    total_interactions INTEGER,
    reciprocity REAL,
    clustering REAL,
    density REAL,
    analysis_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    timeframe_days INTEGER,
    expires_at TIMESTAMP -- Cache expiration (7 days)
);

CREATE INDEX IF NOT EXISTS idx_interaction_hash 
ON interaction_analysis(account_ids_hash);

CREATE INDEX IF NOT EXISTS idx_interaction_expiry 
ON interaction_analysis(expires_at);

-- ============================================================================
-- RALLY DETAILS (NEW)
-- Store detailed rally information for reference
-- ============================================================================
CREATE TABLE IF NOT EXISTS rally_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL,
    rally_number INTEGER NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    total_gain REAL,
    peak_gain REAL,
    rally_type TEXT,
    candles_count INTEGER,
    volume_usd REAL,
    tweets_found INTEGER DEFAULT 0,
    high_confidence_tweets INTEGER DEFAULT 0,
    FOREIGN KEY (analysis_id) REFERENCES analysis_results(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rally_analysis 
ON rally_details(analysis_id);

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Recent analyses
CREATE VIEW IF NOT EXISTS v_recent_analyses AS
SELECT 
    ar.id,
    ar.user_id,
    ar.token_ticker,
    ar.token_name,
    ar.chain,
    ar.analysis_timestamp,
    ar.rallies_found,
    COUNT(DISTINCT ta.author_id) as unique_accounts,
    SUM(CASE WHEN ta.rank_position <= 10 THEN 1 ELSE 0 END) as top_10_accounts
FROM analysis_results ar
LEFT JOIN top_accounts ta ON ar.id = ta.analysis_id
GROUP BY ar.id
ORDER BY ar.analysis_timestamp DESC;

-- View: Cross-token overlap for a user
CREATE VIEW IF NOT EXISTS v_user_cross_token_overlap AS
SELECT 
    ta.author_id,
    ta.username,
    COUNT(DISTINCT ar.token_address) as tokens_count,
    GROUP_CONCAT(DISTINCT ar.token_ticker) as tokens_called,
    AVG(ta.influence_score) as avg_influence,
    SUM(ta.pumps_called) as total_pumps
FROM top_accounts ta
JOIN analysis_results ar ON ta.analysis_id = ar.id
GROUP BY ta.author_id, ta.username
HAVING tokens_count >= 2
ORDER BY tokens_count DESC, avg_influence DESC;

-- ============================================================================
-- STORED PROCEDURES (SQLite doesn't support them, but here are the queries)
-- ============================================================================

-- Query: Get cross-token overlap for a user
-- SELECT * FROM v_user_cross_token_overlap WHERE author_id IN (
--     SELECT DISTINCT author_id FROM top_accounts 
--     WHERE analysis_id IN (
--         SELECT id FROM analysis_results WHERE user_id = ?
--     )
-- );

-- Query: Update cross-token tracking after new analysis
-- INSERT OR REPLACE INTO cross_token_tracking (
--     author_id, username, total_tokens_called, tokens_list, 
--     total_pumps_called, avg_influence_score, last_seen
-- )
-- SELECT 
--     author_id,
--     MAX(username),
--     COUNT(DISTINCT token_address),
--     json_group_array(DISTINCT token_ticker),
--     SUM(pumps_called),
--     AVG(influence_score),
--     CURRENT_TIMESTAMP
-- FROM (
--     SELECT ta.*, ar.token_address, ar.token_ticker
--     FROM top_accounts ta
--     JOIN analysis_results ar ON ta.analysis_id = ar.id
-- )
-- GROUP BY author_id;

-- Query: Clean expired interaction analysis cache
-- DELETE FROM interaction_analysis WHERE expires_at < CURRENT_TIMESTAMP;

-- ============================================================================
-- SAMPLE TRIGGERS
-- ============================================================================

-- Trigger: Update cross-token tracking after inserting top accounts
CREATE TRIGGER IF NOT EXISTS update_cross_token_after_insert
AFTER INSERT ON top_accounts
BEGIN
    INSERT OR REPLACE INTO cross_token_tracking (
        author_id,
        username,
        total_tokens_called,
        tokens_list,
        total_pumps_called,
        avg_influence_score,
        last_seen
    )
    SELECT 
        ta.author_id,
        MAX(ta.username),
        COUNT(DISTINCT ar.token_address),
        json_group_array(DISTINCT ar.token_ticker),
        SUM(ta.pumps_called),
        AVG(ta.influence_score),
        CURRENT_TIMESTAMP
    FROM top_accounts ta
    JOIN analysis_results ar ON ta.analysis_id = ar.id
    WHERE ta.author_id = NEW.author_id
    GROUP BY ta.author_id;
END;

-- Trigger: Update user last_active on any analysis
CREATE TRIGGER IF NOT EXISTS update_user_last_active
AFTER INSERT ON analysis_results
BEGIN
    UPDATE users 
    SET last_active = CURRENT_TIMESTAMP 
    WHERE user_id = NEW.user_id;
END;

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Create demo user
INSERT OR IGNORE INTO users (user_id, subscription_tier) 
VALUES ('demo_user', 'free');