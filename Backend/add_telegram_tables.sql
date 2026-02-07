-- ============================================================================
-- TELEGRAM USER LINKING
-- ============================================================================
-- Links user accounts to their Telegram chat IDs

CREATE TABLE IF NOT EXISTS telegram_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE,
    telegram_chat_id TEXT NOT NULL UNIQUE,
    telegram_username TEXT,
    telegram_first_name TEXT,
    telegram_last_name TEXT,
    connection_code TEXT UNIQUE,
    code_expires_at INTEGER,
    connected_at INTEGER DEFAULT (strftime('%s', 'now')),
    last_active INTEGER DEFAULT (strftime('%s', 'now')),
    alerts_enabled BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_users_user_id 
ON telegram_users(user_id);

CREATE INDEX IF NOT EXISTS idx_telegram_users_chat_id 
ON telegram_users(telegram_chat_id);

CREATE INDEX IF NOT EXISTS idx_telegram_users_code 
ON telegram_users(connection_code) WHERE connection_code IS NOT NULL;

-- ============================================================================
-- TELEGRAM NOTIFICATION LOG
-- ============================================================================
-- Tracks all Telegram notifications sent

CREATE TABLE IF NOT EXISTS telegram_notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    telegram_chat_id TEXT NOT NULL,
    activity_id INTEGER NOT NULL,
    message_id TEXT,
    sent_at INTEGER DEFAULT (strftime('%s', 'now')),
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (activity_id) REFERENCES wallet_activity(id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_log_user 
ON telegram_notification_log(user_id);

CREATE INDEX IF NOT EXISTS idx_telegram_log_sent_at 
ON telegram_notification_log(sent_at DESC);

