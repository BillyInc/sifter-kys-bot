-- Database Schema for SIFTER KYS v7.0
-- Stores Twitter analysis, Wallet analysis, and cross-token tracking

-- ============================================================================
-- USERS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    wallet_address TEXT,
    subscription_tier TEXT DEFAULT 'free',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- TWITTER ANALYSIS RESULTS
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

CREATE INDEX IF NOT EXISTS idx_analysis_user_token 
ON analysis_results(user_id, token_address);

CREATE INDEX IF NOT EXISTS idx_analysis_timestamp 
ON analysis_results(analysis_timestamp DESC);

-- ============================================================================
-- TOP TWITTER ACCOUNTS PER ANALYSIS
-- Stores the Top 20 Twitter accounts from each analysis
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

CREATE INDEX IF NOT EXISTS idx_top_accounts_author 
ON top_accounts(author_id);

CREATE INDEX IF NOT EXISTS idx_top_accounts_analysis 
ON top_accounts(analysis_id);

-- ============================================================================
-- CROSS-TOKEN TWITTER TRACKING
-- Materialized view of Twitter accounts appearing in multiple tokens
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

CREATE INDEX IF NOT EXISTS idx_cross_token_author 
ON cross_token_tracking(author_id);

CREATE INDEX IF NOT EXISTS idx_cross_token_count 
ON cross_token_tracking(total_tokens_called DESC);

-- ============================================================================
-- TWITTER WATCHLIST
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
-- WATCHLIST GROUPS
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
-- RALLY DETAILS
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
-- WALLET ANALYSIS RESULTS (NEW)
-- Stores wallet analysis results similar to Twitter analysis
-- ============================================================================
CREATE TABLE IF NOT EXISTS wallet_analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    token_address TEXT NOT NULL,
    token_ticker TEXT,
    token_name TEXT,
    chain TEXT,
    analysis_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    days_back INTEGER,
    candle_size TEXT,
    wallet_window_before INTEGER DEFAULT 35,
    wallet_window_after INTEGER DEFAULT 0,
    rallies_found INTEGER DEFAULT 0,
    wallets_found INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_wallet_analysis_user_token 
ON wallet_analysis_results(user_id, token_address);

CREATE INDEX IF NOT EXISTS idx_wallet_analysis_timestamp 
ON wallet_analysis_results(analysis_timestamp DESC);

-- ============================================================================
-- TOP WALLETS PER ANALYSIS (NEW)
-- Stores the top wallets from each wallet analysis
-- ============================================================================
CREATE TABLE IF NOT EXISTS top_wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_analysis_id INTEGER NOT NULL,
    wallet_address TEXT NOT NULL,
    tier TEXT, -- 'S', 'A', 'B', 'C'
    pump_count INTEGER DEFAULT 0,
    tokens_hit INTEGER DEFAULT 0,
    avg_distance_to_peak REAL,
    avg_roi_to_peak REAL,
    avg_hours_to_peak REAL,
    consistency_score REAL,
    stdev_distance REAL,
    total_buys INTEGER DEFAULT 0,
    total_volume_usd REAL,
    rank_position INTEGER,
    FOREIGN KEY (wallet_analysis_id) REFERENCES wallet_analysis_results(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_top_wallets_address 
ON top_wallets(wallet_address);

CREATE INDEX IF NOT EXISTS idx_top_wallets_analysis 
ON top_wallets(wallet_analysis_id);

CREATE INDEX IF NOT EXISTS idx_top_wallets_tier 
ON top_wallets(tier);

-- ============================================================================
-- CROSS-TOKEN WALLET TRACKING (NEW)
-- Track wallets appearing across multiple tokens
-- ============================================================================
CREATE TABLE IF NOT EXISTS cross_token_wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT UNIQUE NOT NULL,
    tier TEXT,
    total_tokens_called INTEGER DEFAULT 0,
    tokens_list TEXT, -- JSON array of token tickers
    total_pumps_called INTEGER DEFAULT 0,
    avg_distance_to_peak REAL,
    avg_roi_to_peak REAL,
    consistency_score REAL,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cross_wallet_address 
ON cross_token_wallets(wallet_address);

CREATE INDEX IF NOT EXISTS idx_cross_wallet_tier 
ON cross_token_wallets(tier);

CREATE INDEX IF NOT EXISTS idx_cross_wallet_count 
ON cross_token_wallets(total_tokens_called DESC);

-- ============================================================================
-- WALLET WATCHLIST (NEW)
-- Users can watchlist high-performing wallets
-- ============================================================================
CREATE TABLE IF NOT EXISTS wallet_watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    tier TEXT,
    pump_count INTEGER DEFAULT 0,
    avg_distance_to_peak REAL,
    avg_roi_to_peak REAL,
    consistency_score REAL,
    tokens_hit TEXT, -- Comma-separated list
    notes TEXT,
    tags TEXT, -- JSON array
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE(user_id, wallet_address)
);

CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_user 
ON wallet_watchlist(user_id);

CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_tier 
ON wallet_watchlist(tier);

-- ============================================================================
-- WALLET RALLY PERFORMANCE (NEW)
-- Detailed per-rally performance for each wallet
-- ============================================================================
CREATE TABLE IF NOT EXISTS wallet_rally_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_analysis_id INTEGER NOT NULL,
    wallet_address TEXT NOT NULL,
    token_address TEXT,
    token_ticker TEXT,
    rally_date TIMESTAMP,
    entry_price REAL,
    peak_price REAL,
    distance_to_peak_pct REAL,
    roi_to_peak_pct REAL,
    hours_to_peak REAL,
    num_buys INTEGER DEFAULT 1,
    total_volume_usd REAL,
    FOREIGN KEY (wallet_analysis_id) REFERENCES wallet_analysis_results(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wallet_rally_perf_analysis 
ON wallet_rally_performance(wallet_analysis_id);

CREATE INDEX IF NOT EXISTS idx_wallet_rally_perf_wallet 
ON wallet_rally_performance(wallet_address);

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Recent Twitter analyses
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

-- View: Cross-token Twitter overlap for a user
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

-- View: Cross-token wallet overlap for a user (NEW)
CREATE VIEW IF NOT EXISTS v_user_cross_wallet_overlap AS
SELECT 
    tw.wallet_address,
    tw.tier,
    COUNT(DISTINCT war.token_address) as tokens_count,
    GROUP_CONCAT(DISTINCT war.token_ticker) as tokens_called,
    AVG(tw.avg_distance_to_peak) as avg_distance,
    AVG(tw.avg_roi_to_peak) as avg_roi,
    SUM(tw.pump_count) as total_pumps
FROM top_wallets tw
JOIN wallet_analysis_results war ON tw.wallet_analysis_id = war.id
GROUP BY tw.wallet_address, tw.tier
HAVING tokens_count >= 2
ORDER BY tokens_count DESC, avg_distance DESC;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Trigger: Update cross-token Twitter tracking after inserting top accounts
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

-- Trigger: Update cross-token wallet tracking after inserting top wallets (NEW)
CREATE TRIGGER IF NOT EXISTS update_cross_wallet_after_insert
AFTER INSERT ON top_wallets
BEGIN
    INSERT OR REPLACE INTO cross_token_wallets (
        wallet_address,
        tier,
        total_tokens_called,
        tokens_list,
        total_pumps_called,
        avg_distance_to_peak,
        avg_roi_to_peak,
        consistency_score,
        last_seen
    )
    SELECT 
        tw.wallet_address,
        MAX(tw.tier),
        COUNT(DISTINCT war.token_address),
        json_group_array(DISTINCT war.token_ticker),
        SUM(tw.pump_count),
        AVG(tw.avg_distance_to_peak),
        AVG(tw.avg_roi_to_peak),
        AVG(tw.consistency_score),
        CURRENT_TIMESTAMP
    FROM top_wallets tw
    JOIN wallet_analysis_results war ON tw.wallet_analysis_id = war.id
    WHERE tw.wallet_address = NEW.wallet_address
    GROUP BY tw.wallet_address;
END;

-- Trigger: Update user last_active on any Twitter analysis
CREATE TRIGGER IF NOT EXISTS update_user_last_active
AFTER INSERT ON analysis_results
BEGIN
    UPDATE users 
    SET last_active = CURRENT_TIMESTAMP 
    WHERE user_id = NEW.user_id;
END;

-- Trigger: Update user last_active on wallet analysis (NEW)
CREATE TRIGGER IF NOT EXISTS update_user_last_active_wallet
AFTER INSERT ON wallet_analysis_results
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