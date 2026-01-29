"""
init_database.py - Database Initialization Script
Creates all required tables for the wallet monitoring system
Run this before starting the wallet monitor
"""

import sqlite3
import os

def init_database(db_path='watchlists.db'):
    """Initialize database with all required tables"""
    
    print(f"\n{'='*80}")
    print(f"DATABASE INITIALIZATION")
    print(f"{'='*80}")
    print(f"Database: {db_path}")
    
    # Check if database already exists
    db_exists = os.path.exists(db_path)
    if db_exists:
        print(f"⚠️  Database already exists - will add missing tables")
    else:
        print(f"✨ Creating new database")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Read and execute the schema
    schema_sql = """
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
-- ============================================================================
CREATE TABLE IF NOT EXISTS cross_token_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id TEXT UNIQUE NOT NULL,
    username TEXT,
    total_tokens_called INTEGER DEFAULT 0,
    tokens_list TEXT,
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
-- WALLET ANALYSIS RESULTS
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
-- TOP WALLETS PER ANALYSIS
-- ============================================================================
CREATE TABLE IF NOT EXISTS top_wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_analysis_id INTEGER NOT NULL,
    wallet_address TEXT NOT NULL,
    tier TEXT,
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
-- CROSS-TOKEN WALLET TRACKING
-- ============================================================================
CREATE TABLE IF NOT EXISTS cross_token_wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT UNIQUE NOT NULL,
    tier TEXT,
    total_tokens_called INTEGER DEFAULT 0,
    tokens_list TEXT,
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
-- WALLET WATCHLIST (WITH ALERT SETTINGS)
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
    tokens_hit TEXT,
    notes TEXT,
    tags TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    alert_enabled BOOLEAN DEFAULT TRUE,
    alert_on_buy BOOLEAN DEFAULT TRUE,
    alert_on_sell BOOLEAN DEFAULT FALSE,
    min_trade_usd REAL DEFAULT 100,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE(user_id, wallet_address)
);

CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_user 
ON wallet_watchlist(user_id);

CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_tier 
ON wallet_watchlist(tier);

CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_alerts_enabled
ON wallet_watchlist(alert_enabled) WHERE alert_enabled = TRUE;

-- ============================================================================
-- WALLET ACTIVITY LOG
-- ============================================================================
CREATE TABLE IF NOT EXISTS wallet_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    token_address TEXT NOT NULL,
    token_ticker TEXT,
    token_name TEXT,
    side TEXT NOT NULL,
    token_amount REAL,
    usd_value REAL,
    price REAL,
    tx_hash TEXT UNIQUE NOT NULL,
    block_time INTEGER NOT NULL,
    detected_at INTEGER DEFAULT (strftime('%s', 'now')),
    from_address TEXT,
    to_address TEXT,
    dex TEXT,
    is_processed BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_wallet_activity_wallet 
ON wallet_activity(wallet_address);

CREATE INDEX IF NOT EXISTS idx_wallet_activity_time 
ON wallet_activity(block_time DESC);

CREATE INDEX IF NOT EXISTS idx_wallet_activity_token 
ON wallet_activity(token_address);

CREATE INDEX IF NOT EXISTS idx_wallet_activity_tx_hash 
ON wallet_activity(tx_hash);

CREATE INDEX IF NOT EXISTS idx_wallet_activity_unprocessed
ON wallet_activity(is_processed) WHERE is_processed = FALSE;

-- ============================================================================
-- WALLET NOTIFICATIONS
-- ============================================================================
CREATE TABLE IF NOT EXISTS wallet_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    activity_id INTEGER NOT NULL,
    sent_at INTEGER DEFAULT (strftime('%s', 'now')),
    read_at INTEGER DEFAULT NULL,
    dismissed_at INTEGER DEFAULT NULL,
    token_ticker TEXT,
    token_name TEXT,
    side TEXT,
    usd_value REAL,
    tx_hash TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (activity_id) REFERENCES wallet_activity(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wallet_notifications_user 
ON wallet_notifications(user_id);

CREATE INDEX IF NOT EXISTS idx_wallet_notifications_user_unread 
ON wallet_notifications(user_id, read_at) WHERE read_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_wallet_notifications_sent_at 
ON wallet_notifications(sent_at DESC);

-- ============================================================================
-- WALLET RALLY PERFORMANCE
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
-- MONITORING STATUS (CRITICAL FOR WALLET MONITOR)
-- ============================================================================
CREATE TABLE IF NOT EXISTS wallet_monitor_status (
    wallet_address TEXT PRIMARY KEY,
    last_checked_at INTEGER DEFAULT (strftime('%s', 'now')),
    last_activity_at INTEGER,
    check_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_monitor_status_last_checked
ON wallet_monitor_status(last_checked_at);

-- ============================================================================
-- SCHEMA VERSION
-- ============================================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);
"""
    
    try:
        # Execute the schema
        cursor.executescript(schema_sql)
        
        # Insert/update schema version
        cursor.execute("""
            INSERT OR REPLACE INTO schema_version (version, description) 
            VALUES ('7.0', 'Real-time wallet activity monitoring and alert system')
        """)
        
        # Create demo user if not exists
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, subscription_tier) 
            VALUES ('demo_user', 'free')
        """)
        
        conn.commit()
        
        # Verify critical tables exist
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            ORDER BY name
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"\n✅ Database initialized successfully!")
        print(f"\nCreated/verified {len(tables)} tables:")
        
        critical_tables = [
            'wallet_watchlist',
            'wallet_activity', 
            'wallet_notifications',
            'wallet_monitor_status'
        ]
        
        for table in critical_tables:
            status = "✓" if table in tables else "✗"
            print(f"  {status} {table}")
        
        # Check if all critical tables exist
        all_exist = all(table in tables for table in critical_tables)
        
        if all_exist:
            print(f"\n{'='*80}")
            print(f"✅ ALL CRITICAL TABLES READY - Wallet monitor can now start!")
            print(f"{'='*80}\n")
            return True
        else:
            print(f"\n⚠️  Some critical tables are missing!")
            return False
        
    except Exception as e:
        print(f"\n❌ Error initializing database: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        conn.close()


if __name__ == '__main__':
    import sys
    
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'watchlists.db'
    success = init_database(db_path)
    
    sys.exit(0 if success else 1)