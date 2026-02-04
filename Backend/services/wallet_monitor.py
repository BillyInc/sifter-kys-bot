"""
wallet_monitor.py - Real-time Wallet Activity Monitor

Continuously polls SolanaTracker API for transactions from watched wallets
Creates notifications when activity matches user alert settings
"""

import sqlite3
import requests
import time
import json
from datetime import datetime
from collections import defaultdict
import threading

# =============================================================================
# DATABASE SCHEMA
# =============================================================================

def init_wallet_monitor_tables(db_path):
    """Initialize tables for wallet monitoring"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Table: watched_wallets
    # Stores which users are watching which wallets with their alert settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watched_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            wallet_address TEXT NOT NULL,
            alert_enabled INTEGER DEFAULT 1,
            alert_on_buy INTEGER DEFAULT 1,
            alert_on_sell INTEGER DEFAULT 1,
            min_trade_usd REAL DEFAULT 0,
            added_at INTEGER,
            UNIQUE(user_id, wallet_address)
        )
    ''')
    
    # Table: wallet_activity
    # Stores all detected transactions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallet_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            tx_hash TEXT NOT NULL,
            token_address TEXT,
            token_ticker TEXT,
            token_name TEXT,
            side TEXT,
            token_amount REAL,
            usd_value REAL,
            price REAL,
            block_time INTEGER,
            detected_at INTEGER,
            from_address TEXT,
            to_address TEXT,
            dex TEXT,
            UNIQUE(tx_hash)
        )
    ''')
    
    # Table: wallet_notifications
    # Stores notifications generated for users
    # FIX: uses `read INTEGER DEFAULT 0` consistently.
    # init_database.py previously defined this table with `read_at INTEGER DEFAULT NULL`
    # which conflicted with every query in this file. Standardised on `read` (0/1).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallet_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            wallet_address TEXT NOT NULL,
            activity_id INTEGER,
            notification_type TEXT,
            message TEXT,
            created_at INTEGER,
            read INTEGER DEFAULT 0,
            FOREIGN KEY (activity_id) REFERENCES wallet_activity(id)
        )
    ''')
    
    # Table: wallet_monitor_status
    # Tracks monitoring status per wallet
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallet_monitor_status (
            wallet_address TEXT PRIMARY KEY,
            last_checked_at INTEGER,
            last_activity_at INTEGER,
            check_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            last_error TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_recent_wallet_activity(db_path, limit=50):
    """Get recent wallet activity across all monitored wallets"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM wallet_activity
        ORDER BY block_time DESC
        LIMIT ?
    ''', (limit,))
    
    columns = [desc[0] for desc in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    conn.close()
    return results

def get_user_notifications(db_path, user_id, unread_only=True):
    """Get notifications for a specific user"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # FIX: query uses n.read (matches the CREATE TABLE above).
    # Previously this worked fine here but init_database.py would create the
    # table first with `read_at` instead, so `n.read` would not exist.
    if unread_only:
        cursor.execute('''
            SELECT n.*, a.tx_hash, a.token_ticker, a.side, a.usd_value
            FROM wallet_notifications n
            LEFT JOIN wallet_activity a ON n.activity_id = a.id
            WHERE n.user_id = ? AND n.read = 0
            ORDER BY n.created_at DESC
        ''', (user_id,))
    else:
        cursor.execute('''
            SELECT n.*, a.tx_hash, a.token_ticker, a.side, a.usd_value
            FROM wallet_notifications n
            LEFT JOIN wallet_activity a ON n.activity_id = a.id
            WHERE n.user_id = ?
            ORDER BY n.created_at DESC
            LIMIT 100
        ''', (user_id,))
    
    columns = [desc[0] for desc in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    conn.close()
    return results

def mark_notification_read(db_path, notification_id, user_id):
    """Mark a notification as read"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE wallet_notifications
        SET read = 1
        WHERE id = ? AND user_id = ?
    ''', (notification_id, user_id))
    
    conn.commit()
    conn.close()

def mark_all_notifications_read(db_path, user_id):
    """Mark all notifications as read for a user"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE wallet_notifications
        SET read = 1
        WHERE user_id = ?
    ''', (user_id,))
    
    conn.commit()
    conn.close()

def update_alert_settings(db_path, user_id, wallet_address, settings):
    """Update alert settings for a watched wallet"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    update_fields = []
    values = []
    
    if 'alert_enabled' in settings:
        update_fields.append('alert_enabled = ?')
        values.append(1 if settings['alert_enabled'] else 0)
    
    if 'alert_on_buy' in settings:
        update_fields.append('alert_on_buy = ?')
        values.append(1 if settings['alert_on_buy'] else 0)
    
    if 'alert_on_sell' in settings:
        update_fields.append('alert_on_sell = ?')
        values.append(1 if settings['alert_on_sell'] else 0)
    
    if 'min_trade_usd' in settings:
        update_fields.append('min_trade_usd = ?')
        values.append(settings['min_trade_usd'])
    
    if update_fields:
        values.extend([user_id, wallet_address])
        query = f'''
            UPDATE watched_wallets
            SET {', '.join(update_fields)}
            WHERE user_id = ? AND wallet_address = ?
        '''
        cursor.execute(query, values)
        conn.commit()
    
    conn.close()

# =============================================================================
# WALLET ACTIVITY MONITOR CLASS
# =============================================================================

class WalletActivityMonitor:
    """
    Monitors watched wallets for new transactions and generates notifications
    """
    
    def __init__(self, solanatracker_api_key, db_path='watchlists.db', poll_interval=120):
        """
        Initialize the wallet monitor
        
        Args:
            solanatracker_api_key: API key for SolanaTracker
            db_path: Path to SQLite database
            poll_interval: Seconds between polls (default: 120 = 2 minutes)
        """
        self.st_key = solanatracker_api_key
        self.db_path = db_path
        self.poll_interval = poll_interval
        
        # Initialize database tables
        init_wallet_monitor_tables(db_path)
        
        # Thread control
        self.running = False
        self.monitor_thread = None
        
        print(f"  ✓ WalletActivityMonitor initialized (poll every {poll_interval}s)")
    
    def _get_solanatracker_headers(self):
        """Get headers for SolanaTracker API requests"""
        return {
            'accept': 'application/json',
            'x-api-key': self.st_key
        }
    
    def _fetch_wallet_transactions(self, wallet_address, after_time, before_time):
        """
        Fetch recent transactions using SolanaTracker trades endpoint
        
        Args:
            wallet_address: Solana wallet address
            after_time: Unix timestamp (seconds) - fetch trades after this time
            before_time: Unix timestamp (seconds) - fetch trades before this time
            
        Returns:
            List of transaction dictionaries
        """
        headers = self._get_solanatracker_headers()
        transactions = []
        
        try:
            url = f'https://data.solanatracker.io/wallet/{wallet_address}/trades'
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                print(f"  ⚠️ SolanaTracker API returned {response.status_code} for {wallet_address[:8]}...")
                return []
            
            data = response.json()
            trades = data.get('trades', [])
            
            for trade in trades:
                trade_time = trade.get('time', 0) / 1000  # Convert ms to seconds
                
                # Filter by time window
                if trade_time < after_time or trade_time > before_time:
                    continue
                
                # Determine side: if from=SOL, it's a buy; if to=SOL, it's a sell
                from_token = trade.get('from', {}).get('address')
                to_token = trade.get('to', {}).get('address')
                is_sol_from = from_token == 'So11111111111111111111111111111111111111112'
                
                side = 'buy' if is_sol_from else 'sell'
                token_address = to_token if is_sol_from else from_token
                token_info = trade.get('to' if is_sol_from else 'from', {}).get('token', {})
                
                transactions.append({
                    'tx_hash': trade.get('tx'),
                    'token_address': token_address,
                    'token_ticker': token_info.get('symbol', 'UNKNOWN'),
                    'token_name': token_info.get('name', 'Unknown'),
                    'side': side,
                    'token_amount': trade.get('to' if is_sol_from else 'from', {}).get('amount', 0),
                    'usd_value': trade.get('volume', {}).get('usd', 0),
                    'price': trade.get('price', {}).get('usd', 0),
                    'block_time': int(trade_time),
                    'from_address': from_token,
                    'to_address': to_token,
                    'dex': trade.get('program', 'unknown')
                })
        
        except Exception as e:
            print(f"  ❌ Error fetching trades for {wallet_address[:8]}...: {e}")
        
        return transactions
    
    def _save_wallet_activity(self, wallet_address, transactions):
        """Save new transactions to database"""
        if not transactions:
            return []
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        activity_ids = []
        
        for tx in transactions:
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO wallet_activity (
                        wallet_address, tx_hash, token_address, token_ticker, token_name,
                        side, token_amount, usd_value, price, block_time, detected_at,
                        from_address, to_address, dex
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    wallet_address,
                    tx['tx_hash'],
                    tx['token_address'],
                    tx['token_ticker'],
                    tx['token_name'],
                    tx['side'],
                    tx['token_amount'],
                    tx['usd_value'],
                    tx['price'],
                    tx['block_time'],
                    int(time.time()),
                    tx['from_address'],
                    tx['to_address'],
                    tx['dex']
                ))
                
                if cursor.lastrowid > 0:
                    activity_ids.append(cursor.lastrowid)
            
            except sqlite3.IntegrityError:
                # Transaction already exists
                pass
        
        conn.commit()
        conn.close()
        
        return activity_ids
    
    def _create_notifications_for_wallet(self, wallet_address, activity_ids):
        """Create notifications for users watching this wallet"""
        if not activity_ids:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get all users watching this wallet
        cursor.execute('''
            SELECT user_id, alert_enabled, alert_on_buy, alert_on_sell, min_trade_usd
            FROM watched_wallets
            WHERE wallet_address = ? AND alert_enabled = 1
        ''', (wallet_address,))
        
        watchers = cursor.fetchall()
        
        for user_id, alert_enabled, alert_on_buy, alert_on_sell, min_trade_usd in watchers:
            for activity_id in activity_ids:
                # Get activity details
                cursor.execute('''
                    SELECT side, usd_value, token_ticker, token_amount
                    FROM wallet_activity
                    WHERE id = ?
                ''', (activity_id,))
                
                activity = cursor.fetchone()
                if not activity:
                    continue
                
                side, usd_value, token_ticker, token_amount = activity
                
                # Check alert filters
                if side == 'buy' and not alert_on_buy:
                    continue
                if side == 'sell' and not alert_on_sell:
                    continue
                if usd_value < min_trade_usd:
                    continue
                
                # Create notification
                message = f"Wallet {wallet_address[:8]}... {side.upper()} {token_amount:.4f} {token_ticker} (${usd_value:.2f})"
                
                # FIX: inserts `read = 0` matching the CREATE TABLE definition
                cursor.execute('''
                    INSERT INTO wallet_notifications (
                        user_id, wallet_address, activity_id, notification_type,
                        message, created_at, read
                    ) VALUES (?, ?, ?, ?, ?, ?, 0)
                ''', (user_id, wallet_address, activity_id, side, message, int(time.time())))
        
        conn.commit()
        conn.close()
    
    def _update_monitor_status(self, wallet_address, error=None):
        """Update monitoring status for a wallet"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if error:
            cursor.execute('''
                INSERT INTO wallet_monitor_status (wallet_address, last_checked_at, check_count, error_count, last_error)
                VALUES (?, ?, 1, 1, ?)
                ON CONFLICT(wallet_address) DO UPDATE SET
                    last_checked_at = ?,
                    check_count = check_count + 1,
                    error_count = error_count + 1,
                    last_error = ?
            ''', (wallet_address, int(time.time()), error, int(time.time()), error))
        else:
            cursor.execute('''
                INSERT INTO wallet_monitor_status (wallet_address, last_checked_at, check_count)
                VALUES (?, ?, 1)
                ON CONFLICT(wallet_address) DO UPDATE SET
                    last_checked_at = ?,
                    check_count = check_count + 1
            ''', (wallet_address, int(time.time()), int(time.time())))
        
        conn.commit()
        conn.close()
    
    def _get_watched_wallets(self):
        """Get list of all watched wallets"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT wallet_address
            FROM watched_wallets
            WHERE alert_enabled = 1
        ''')
        
        wallets = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        return wallets
    
    def _monitor_loop(self):
        """Main monitoring loop - runs in separate thread"""
        print(f"\n{'='*80}")
        print(f"WALLET MONITOR STARTED")
        print(f"Poll interval: {self.poll_interval}s")
        print(f"{'='*80}\n")
        
        while self.running:
            try:
                wallets = self._get_watched_wallets()
                
                if wallets:
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking {len(wallets)} watched wallets...")
                    
                    current_time = int(time.time())
                    after_time = current_time - self.poll_interval - 60  # Add 60s buffer
                    
                    for wallet in wallets:
                        try:
                            # Fetch recent transactions
                            transactions = self._fetch_wallet_transactions(
                                wallet_address=wallet,
                                after_time=after_time,
                                before_time=current_time
                            )
                            
                            if transactions:
                                print(f"  ✓ {wallet[:8]}... found {len(transactions)} new transactions")
                                
                                # Save to database
                                activity_ids = self._save_wallet_activity(wallet, transactions)
                                
                                # Create notifications
                                self._create_notifications_for_wallet(wallet, activity_ids)
                            
                            # Update status
                            self._update_monitor_status(wallet)
                        
                        except Exception as e:
                            error_msg = str(e)
                            print(f"  ❌ {wallet[:8]}... error: {error_msg}")
                            self._update_monitor_status(wallet, error=error_msg)
                
                # Sleep until next poll
                time.sleep(self.poll_interval)
            
            except Exception as e:
                print(f"  ❌ Monitor loop error: {e}")
                time.sleep(60)  # Wait 1 minute on error before retrying
    
    def start(self):
        """Start the monitoring thread"""
        if self.running:
            print("  ⚠️ Monitor already running")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        print("  ✓ Wallet monitor started")
    
    def stop(self):
        """Stop the monitoring thread"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        print("  ✓ Wallet monitor stopped")
    
    def add_watched_wallet(self, user_id, wallet_address, alert_settings=None):
        """Add a wallet to the watch list"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        settings = alert_settings or {}
        
        cursor.execute('''
            INSERT OR REPLACE INTO watched_wallets (
                user_id, wallet_address, alert_enabled, alert_on_buy, alert_on_sell,
                min_trade_usd, added_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            wallet_address,
            1 if settings.get('alert_enabled', True) else 0,
            1 if settings.get('alert_on_buy', True) else 0,
            1 if settings.get('alert_on_sell', True) else 0,
            settings.get('min_trade_usd', 0),
            int(time.time())
        ))
        
        conn.commit()
        conn.close()
    
    def remove_watched_wallet(self, user_id, wallet_address):
        """Remove a wallet from the watch list"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM watched_wallets
            WHERE user_id = ? AND wallet_address = ?
        ''', (user_id, wallet_address))
        
        conn.commit()
        conn.close()
    
    def update_alert_settings(self, user_id, wallet_address, settings):
        """Update alert settings for a watched wallet"""
        update_alert_settings(self.db_path, user_id, wallet_address, settings)
    
    def get_monitoring_stats(self):
        """Get monitoring statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(DISTINCT wallet_address) FROM watched_wallets WHERE alert_enabled = 1')
        active_wallets = cursor.fetchone()[0]
        
        # FIX: queries `read = 0` matching the CREATE TABLE definition
        cursor.execute('SELECT COUNT(*) FROM wallet_notifications WHERE read = 0')
        pending_notifications = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'running': self.running,
            'active_wallets': active_wallets,
            'pending_notifications': pending_notifications,
            'poll_interval': self.poll_interval
        }