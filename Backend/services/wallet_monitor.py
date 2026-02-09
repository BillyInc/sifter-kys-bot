"""
wallet_monitor.py - Real-time Wallet Activity Monitor
Continuously polls Birdeye API for transactions from watched wallets
Creates notifications when activity matches user alert settings
Supports Telegram alerts integration
"""

import sqlite3
import requests
import time
import json
from datetime import datetime
from collections import defaultdict
import threading
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.telegram_notifier import TelegramNotifier


class WalletActivityMonitor:
    """
    Monitors wallets in real-time and creates notifications.
    Runs as a background service polling Birdeye API.
    """

    def __init__(self, birdeye_api_key, db_path='watchlists.db', poll_interval=120,
                 telegram_notifier: Optional['TelegramNotifier'] = None):
        self.birdeye_key = birdeye_api_key
        self.db_path = db_path
        self.poll_interval = poll_interval  # seconds (default: 2 minutes)
        self.birdeye_txs_url = "https://public-api.birdeye.so/defi/v3/token/txs"
        self.running = False
        self.monitor_thread = None

        # Telegram notifier for sending alerts
        self.telegram_notifier = telegram_notifier

        # *** CRITICAL: Initialize database tables before starting ***
        self._ensure_database_initialized()

        telegram_status = "Enabled" if telegram_notifier else "Disabled"
        print(f"""
╔══════════════════════════════════════════════════════════════════╗
║           WALLET ACTIVITY MONITOR - INITIALIZED                  ║
╚══════════════════════════════════════════════════════════════════╝
  📊 Database: {db_path}
  🔄 Poll Interval: {poll_interval}s ({poll_interval/60:.1f} minutes)
  🔑 Birdeye API: Configured
  📱 Telegram Alerts: {telegram_status}
""")

    def _ensure_database_initialized(self):
        """Ensure all required database tables exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Check if critical tables exist
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name IN (
                    'wallet_watchlist',
                    'wallet_activity',
                    'wallet_notifications',
                    'wallet_monitor_status'
                )
            """)

            existing_tables = {row[0] for row in cursor.fetchall()}
            required_tables = {
                'wallet_watchlist',
                'wallet_activity',
                'wallet_notifications',
                'wallet_monitor_status'
            }

            missing_tables = required_tables - existing_tables

            if missing_tables:
                print(f"\n⚠️  Missing tables: {', '.join(missing_tables)}")
                print("   Creating required tables...")

                # Create missing tables
                self._create_required_tables(cursor)
                conn.commit()

                print("✅ Database tables created successfully\n")
            else:
                print("✅ All required database tables exist\n")

        except Exception as e:
            print(f"❌ Error checking/creating database tables: {e}")
            raise
        finally:
            conn.close()

    def _create_required_tables(self, cursor):
        """Create all required tables for wallet monitoring"""

        # Wallet watchlist table
        cursor.execute("""
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
                UNIQUE(user_id, wallet_address)
            )
        """)

        # Check if alert columns exist, add them if they don't
        cursor.execute("PRAGMA table_info(wallet_watchlist)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        alert_columns = {
            'alert_enabled': 'BOOLEAN DEFAULT TRUE',
            'alert_on_buy': 'BOOLEAN DEFAULT TRUE',
            'alert_on_sell': 'BOOLEAN DEFAULT FALSE',
            'min_trade_usd': 'REAL DEFAULT 100',
            'last_updated': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
        }

        for col_name, col_def in alert_columns.items():
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"""
                        ALTER TABLE wallet_watchlist
                        ADD COLUMN {col_name} {col_def}
                    """)
                    print(f"  ✓ Added column: {col_name}")
                except Exception as e:
                    print(f"  ⚠️ Could not add column {col_name}: {e}")

        # Now create the index (only if alert_enabled column exists)
        if 'alert_enabled' in existing_columns or 'alert_enabled' in alert_columns:
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_wallet_watchlist_alerts_enabled
                    ON wallet_watchlist(alert_enabled) WHERE alert_enabled = TRUE
                """)
            except Exception as e:
                print(f"  ⚠️ Could not create index: {e}")

        # Wallet activity table
        cursor.execute("""
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
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wallet_activity_wallet
            ON wallet_activity(wallet_address)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wallet_activity_time
            ON wallet_activity(block_time DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wallet_activity_tx_hash
            ON wallet_activity(tx_hash)
        """)

        # Wallet notifications table
        cursor.execute("""
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
                FOREIGN KEY (activity_id) REFERENCES wallet_activity(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wallet_notifications_user
            ON wallet_notifications(user_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wallet_notifications_user_unread
            ON wallet_notifications(user_id, read_at) WHERE read_at IS NULL
        """)

        # Wallet monitor status table (CRITICAL)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_monitor_status (
                wallet_address TEXT PRIMARY KEY,
                last_checked_at INTEGER DEFAULT (strftime('%s', 'now')),
                last_activity_at INTEGER,
                check_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                last_error TEXT,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_monitor_status_last_checked
            ON wallet_monitor_status(last_checked_at)
        """)

        # Users table (might be needed)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                wallet_address TEXT,
                subscription_tier TEXT DEFAULT 'free',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create demo user
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, subscription_tier)
            VALUES ('demo_user', 'free')
        """)

    def start(self):
        """Start the monitoring service in a background thread"""
        if self.running:
            print("⚠️ Monitor already running")
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print(f"✅ Wallet monitor started (polling every {self.poll_interval/60:.1f} min)")

    def stop(self):
        """Stop the monitoring service"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        print("🛑 Wallet monitor stopped")

    def _monitor_loop(self):
        """Main monitoring loop - runs continuously"""
        print(f"\n{'='*80}")
        print(f"🚀 MONITORING STARTED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if self.telegram_notifier:
            print(f"📱 Telegram alerts: ENABLED")
        print(f"{'='*80}\n")

        while self.running:
            try:
                cycle_start = time.time()

                # Get all wallets that need monitoring
                wallets_to_monitor = self._get_monitored_wallets()

                if not wallets_to_monitor:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] No wallets to monitor, sleeping...")
                    time.sleep(self.poll_interval)
                    continue

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Monitoring {len(wallets_to_monitor)} wallets...")

                # Check each wallet for new activity
                for wallet_info in wallets_to_monitor:
                    if not self.running:
                        break

                    self._check_wallet_activity(wallet_info)

                # Update cycle stats
                cycle_duration = time.time() - cycle_start
                print(f"✓ Cycle complete in {cycle_duration:.1f}s")

                # Sleep until next poll
                sleep_time = max(0, self.poll_interval - cycle_duration)
                if sleep_time > 0:
                    print(f"💤 Sleeping {sleep_time:.1f}s until next cycle...\n")
                    time.sleep(sleep_time)

            except Exception as e:
                print(f"\n❌ ERROR in monitor loop: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(30)  # Brief pause before retrying

    def _get_monitored_wallets(self):
        """Get all wallets that have alerts enabled from any user"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get unique wallets with alert settings from all users
        cursor.execute("""
            SELECT DISTINCT
                ww.wallet_address,
                ww.tier,
                wms.last_checked_at,
                wms.last_activity_at
            FROM wallet_watchlist ww
            LEFT JOIN wallet_monitor_status wms ON ww.wallet_address = wms.wallet_address
            WHERE ww.alert_enabled = 1
            ORDER BY wms.last_checked_at ASC NULLS FIRST
        """)

        wallets = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return wallets

    def _check_wallet_activity(self, wallet_info):
        """Check a single wallet for new transactions - ENHANCED"""
        wallet_address = wallet_info['wallet_address']
        last_checked = wallet_info['last_checked_at'] or 0
        
        lookback_buffer = 300
        after_time = max(0, last_checked - lookback_buffer)
        before_time = int(time.time())
        
        try:
            # Fetch ALL recent trades (not just first buys)
            transactions = self._fetch_wallet_all_trades(
                wallet_address,
                after_time=after_time,
                before_time=before_time
            )
            
            if transactions:
                print(f"  {wallet_address[:8]}... → {len(transactions)} new tx(s)")
                
                new_activities = []
                tokens_bought = defaultdict(list)  # Track buys by token
                
                for tx in transactions:
                    activity_id = self._save_wallet_activity(tx, wallet_address)
                    if activity_id:
                        new_activities.append({
                            'activity_id': activity_id,
                            'tx': tx
                        })
                        
                        # Track buys for multi-wallet detection
                        if tx.get('side') == 'buy':
                            tokens_bought[tx.get('token_address')].append({
                                'wallet': wallet_address,
                                'tier': wallet_info.get('tier', 'C'),
                                'usd_value': tx.get('usd_value', 0)
                            })
                
                # Create notifications for users watching this wallet
                if new_activities:
                    self._create_notifications_for_wallet(wallet_address, new_activities)
                
                # Check for multi-wallet signals
                for token_address, wallets_buying in tokens_bought.items():
                    signal = self._detect_multi_wallet_signal(token_address, wallets_buying)
                    if signal:
                        self._create_signal_alert(signal)
            
            self._update_monitor_status(
                wallet_address,
                last_checked_at=before_time,
                last_activity_at=before_time if transactions else wallet_info['last_activity_at'],
                success=True
            )
        
        except Exception as e:
            print(f"  ❌ Error checking {wallet_address[:8]}...: {e}")
            self._update_monitor_status(
                wallet_address,
                last_checked_at=before_time,
                success=False,
                error_message=str(e)
            )

    def _fetch_wallet_all_trades(self, wallet_address, after_time, before_time):
        """Fetch ALL trades (buys AND sells) for a wallet"""
        # Use Solana Tracker trades endpoint
        url = f"https://data.solanatracker.io/wallet/{wallet_address}/trades"
        headers = {
            'accept': 'application/json',
            'x-api-key': self.birdeye_key  # Or solanatracker_key
        }
        params = {
            'since_time': after_time * 1000,  # Convert to ms
            'limit': 100
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return data.get('trades', [])
        except Exception as e:
            print(f"Error fetching trades: {e}")
        
        return []

    def _detect_multi_wallet_signal(self, token_address, wallets_buying):
        """Detect if multiple high-tier wallets bought same token"""
        if len(wallets_buying) < 2:
            return None
        
        # Calculate signal strength
        signal_strength = 0
        tier_weights = {'S': 4, 'A': 3, 'B': 2, 'C': 1}
        
        for wallet_info in wallets_buying:
            signal_strength += tier_weights.get(wallet_info['tier'], 1)
        
        # Strong signal if 2+ wallets AND combined strength ≥ 5
        if signal_strength >= 5:
            return {
                'token_address': token_address,
                'signal_strength': signal_strength,
                'wallet_count': len(wallets_buying),
                'wallets': wallets_buying,
                'timestamp': int(time.time())
            }
        
        return None

    def _create_signal_alert(self, signal):
        """Create alert for multi-wallet signal"""
        print(f"  🚨 MULTI-WALLET SIGNAL: {signal['wallet_count']} wallets bought {signal['token_address'][:8]}...")
        
        # Create notifications for ALL users with ANY of these wallets
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        wallet_addresses = [w['wallet'] for w in signal['wallets']]
        placeholders = ','.join(['?'] * len(wallet_addresses))
        
        cursor.execute(f"""
            SELECT DISTINCT user_id
            FROM wallet_watchlist
            WHERE wallet_address IN ({placeholders})
            AND alert_enabled = 1
        """, wallet_addresses)
        
        users = [row[0] for row in cursor.fetchall()]
        
        for user_id in users:
            # Send high-priority Telegram alert
            if self.telegram_notifier:
                self.telegram_notifier.send_multi_wallet_signal_alert(
                    user_id,
                    signal
                )
        
        conn.close()

    def _fetch_wallet_transactions(self, wallet_address, after_time, before_time, chain='solana'):
        """Fetch transactions for a wallet from Birdeye"""
        headers = {
            'accept': 'application/json',
            'x-chain': chain,
            'X-API-KEY': self.birdeye_key
        }

        transactions = []

        # TODO: Implement proper wallet transaction fetching
        # Options:
        # 1. Track which tokens each wallet trades and monitor those token pairs
        # 2. Use Birdeye's wallet-specific endpoints if available
        # 3. Use on-chain RPC calls for more comprehensive monitoring

        return transactions

    def _save_wallet_activity(self, tx, wallet_address):
        """Save transaction to wallet_activity table"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO wallet_activity (
                    wallet_address,
                    token_address,
                    token_ticker,
                    token_name,
                    side,
                    token_amount,
                    usd_value,
                    price,
                    tx_hash,
                    block_time,
                    detected_at,
                    from_address,
                    to_address,
                    dex,
                    is_processed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                wallet_address,
                tx.get('token_address'),
                tx.get('token_ticker'),
                tx.get('token_name'),
                tx.get('side'),
                tx.get('token_amount', 0),
                tx.get('usd_value', 0),
                tx.get('price', 0),
                tx.get('tx_hash'),
                tx.get('block_time'),
                int(time.time()),
                tx.get('from_address'),
                tx.get('to_address'),
                tx.get('dex'),
                False
            ))

            activity_id = cursor.lastrowid
            conn.commit()
            conn.close()

            return activity_id if activity_id > 0 else None

        except sqlite3.IntegrityError:
            # Transaction already exists (duplicate tx_hash)
            conn.close()
            return None
        except Exception as e:
            print(f"    ⚠️ Error saving activity: {e}")
            conn.close()
            return None

    def _get_wallet_info(self, user_id: str, wallet_address: str) -> dict:
        """Get wallet tier and stats from watchlist for Telegram alerts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT tier, consistency_score
            FROM wallet_watchlist
            WHERE user_id = ? AND wallet_address = ?
        ''', (user_id, wallet_address))

        result = cursor.fetchone()
        conn.close()

        if result:
            return {'tier': result[0] or 'C', 'consistency_score': result[1] or 0}
        return {'tier': 'C', 'consistency_score': 0}

    def _send_telegram_alert(self, user_id: str, wallet_address: str, tx: dict, activity_id: int):
        """Send Telegram alert for wallet activity"""
        if not self.telegram_notifier:
            return

        try:
            # Get wallet tier/stats from watchlist
            wallet_info = self._get_wallet_info(user_id, wallet_address)

            # Format alert payload
            alert_payload = {
                'wallet': {
                    'address': wallet_address,
                    'tier': wallet_info.get('tier', 'C'),
                    'consistency_score': wallet_info.get('consistency_score', 0)
                },
                'action': tx.get('side', 'buy'),
                'token': {
                    'address': tx.get('token_address', ''),
                    'symbol': tx.get('token_ticker', 'UNKNOWN'),
                    'name': tx.get('token_name', 'Unknown')
                },
                'trade': {
                    'amount_tokens': tx.get('token_amount', 0),
                    'amount_usd': tx.get('usd_value', 0),
                    'price': tx.get('price', 0),
                    'tx_hash': tx.get('tx_hash', ''),
                    'dex': tx.get('dex', 'unknown'),
                    'timestamp': tx.get('block_time', int(time.time()))
                },
                'links': {
                    'solscan': f"https://solscan.io/tx/{tx.get('tx_hash', '')}",
                    'birdeye': f"https://birdeye.so/token/{tx.get('token_address', '')}",
                    'dexscreener': f"https://dexscreener.com/solana/{tx.get('token_address', '')}"
                }
            }

            # Send to Telegram
            self.telegram_notifier.send_wallet_alert(user_id, alert_payload, activity_id)
            print(f"    📱 Telegram alert sent to user {user_id}")

        except Exception as e:
            print(f"    ⚠️ Error sending Telegram alert: {e}")

    def _create_notifications_for_wallet(self, wallet_address, activities):
        """Create notifications for all users watching this wallet"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get all users watching this wallet with their alert settings
        cursor.execute("""
            SELECT
                user_id,
                alert_on_buy,
                alert_on_sell,
                min_trade_usd
            FROM wallet_watchlist
            WHERE wallet_address = ?
            AND alert_enabled = 1
        """, (wallet_address,))

        watchers = cursor.fetchall()

        if not watchers:
            conn.close()
            return

        notifications_created = 0

        for activity in activities:
            tx = activity['tx']
            activity_id = activity['activity_id']

            for watcher in watchers:
                # Check if transaction meets user's alert criteria
                if self._should_notify(tx, dict(watcher)):
                    try:
                        cursor.execute("""
                            INSERT INTO wallet_notifications (
                                user_id,
                                wallet_address,
                                activity_id,
                                sent_at,
                                token_ticker,
                                token_name,
                                side,
                                usd_value,
                                tx_hash
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            watcher['user_id'],
                            wallet_address,
                            activity_id,
                            int(time.time()),
                            tx.get('token_ticker'),
                            tx.get('token_name'),
                            tx.get('side'),
                            tx.get('usd_value', 0),
                            tx.get('tx_hash')
                        ))

                        notifications_created += 1

                        # Send Telegram alert
                        if self.telegram_notifier:
                            self._send_telegram_alert(
                                watcher['user_id'],
                                wallet_address,
                                tx,
                                activity_id
                            )

                    except Exception as e:
                        print(f"    ⚠️ Error creating notification: {e}")

        conn.commit()
        conn.close()

        if notifications_created > 0:
            print(f"    🔔 Created {notifications_created} notification(s)")

    def _should_notify(self, tx, settings):
        """Determine if user should be notified about this transaction"""
        side = tx.get('side', '').lower()
        usd_value = tx.get('usd_value', 0)

        # Check side (buy/sell)
        if side == 'buy' and not settings['alert_on_buy']:
            return False

        if side == 'sell' and not settings['alert_on_sell']:
            return False

        # Check minimum USD value
        if usd_value < settings['min_trade_usd']:
            return False

        return True

    def _update_monitor_status(self, wallet_address, last_checked_at,
                               last_activity_at=None, success=True, error_message=None):
        """Update monitoring status for a wallet"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if status exists
        cursor.execute("""
            SELECT wallet_address FROM wallet_monitor_status
            WHERE wallet_address = ?
        """, (wallet_address,))

        exists = cursor.fetchone() is not None

        if exists:
            # Update existing status
            if success:
                cursor.execute("""
                    UPDATE wallet_monitor_status
                    SET last_checked_at = ?,
                        last_activity_at = COALESCE(?, last_activity_at),
                        check_count = check_count + 1,
                        error_count = 0,
                        last_error = NULL
                    WHERE wallet_address = ?
                """, (last_checked_at, last_activity_at, wallet_address))
            else:
                cursor.execute("""
                    UPDATE wallet_monitor_status
                    SET last_checked_at = ?,
                        check_count = check_count + 1,
                        error_count = error_count + 1,
                        last_error = ?
                    WHERE wallet_address = ?
                """, (last_checked_at, error_message, wallet_address))
        else:
            # Insert new status
            cursor.execute("""
                INSERT INTO wallet_monitor_status (
                    wallet_address,
                    last_checked_at,
                    last_activity_at,
                    check_count,
                    error_count,
                    last_error,
                    is_active
                ) VALUES (?, ?, ?, 1, ?, ?, 1)
            """, (
                wallet_address,
                last_checked_at,
                last_activity_at,
                0 if success else 1,
                None if success else error_message
            ))

        conn.commit()
        conn.close()

    def get_monitoring_stats(self):
        """Get current monitoring statistics"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Active wallets being monitored
        cursor.execute("""
            SELECT COUNT(DISTINCT wallet_address) as active_wallets
            FROM wallet_watchlist
            WHERE alert_enabled = 1
        """)
        active_wallets = cursor.fetchone()['active_wallets']

        # Recent activity (last hour)
        one_hour_ago = int(time.time()) - 3600
        cursor.execute("""
            SELECT COUNT(*) as recent_activities
            FROM wallet_activity
            WHERE detected_at > ?
        """, (one_hour_ago,))
        recent_activities = cursor.fetchone()['recent_activities']

        # Pending notifications
        cursor.execute("""
            SELECT COUNT(*) as pending_notifications
            FROM wallet_notifications
            WHERE read_at IS NULL AND dismissed_at IS NULL
        """)
        pending_notifications = cursor.fetchone()['pending_notifications']

        # Monitor health
        cursor.execute("""
            SELECT
                COUNT(*) as total_monitored,
                SUM(CASE WHEN error_count > 0 THEN 1 ELSE 0 END) as with_errors,
                AVG(check_count) as avg_checks
            FROM wallet_monitor_status
        """)
        health = cursor.fetchone()

        conn.close()

        return {
            'active_wallets': active_wallets,
            'recent_activities': recent_activities,
            'pending_notifications': pending_notifications,
            'monitor_health': {
                'total_monitored': health['total_monitored'],
                'with_errors': health['with_errors'],
                'avg_checks': round(health['avg_checks'], 1) if health['avg_checks'] else 0
            },
            'running': self.running,
            'poll_interval_seconds': self.poll_interval,
            'telegram_enabled': self.telegram_notifier is not None
        }


    def force_check_wallet(self, wallet_address):
        """Manually trigger a check for a specific wallet (for testing/debugging)"""
        wallet_info = {
            'wallet_address': wallet_address,
            'tier': None,
            'last_checked_at': 0,
            'last_activity_at': None
        }

        print(f"\n🔍 Force checking wallet: {wallet_address[:8]}...")
        self._check_wallet_activity(wallet_info)
        print(f"✅ Check complete\n")


# =============================================================================
# HELPER FUNCTIONS FOR API INTEGRATION
# =============================================================================

def get_recent_wallet_activity(db_path, wallet_address=None, limit=50):
    """Get recent wallet activity (for API endpoint)"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if wallet_address:
        cursor.execute("""
            SELECT *
            FROM wallet_activity
            WHERE wallet_address = ?
            ORDER BY block_time DESC
            LIMIT ?
        """, (wallet_address, limit))
    else:
        cursor.execute("""
            SELECT *
            FROM wallet_activity
            ORDER BY block_time DESC
            LIMIT ?
        """, (limit,))

    activities = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return activities


def get_user_notifications(db_path, user_id, unread_only=False, limit=50):
    """Get notifications for a user (for API endpoint)"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if unread_only:
        cursor.execute("""
            SELECT
                wn.*,
                wa.token_address,
                wa.price,
                wa.block_time
            FROM wallet_notifications wn
            LEFT JOIN wallet_activity wa ON wn.activity_id = wa.id
            WHERE wn.user_id = ?
            AND wn.read_at IS NULL
            AND wn.dismissed_at IS NULL
            ORDER BY wn.sent_at DESC
            LIMIT ?
        """, (user_id, limit))
    else:
        cursor.execute("""
            SELECT
                wn.*,
                wa.token_address,
                wa.price,
                wa.block_time
            FROM wallet_notifications wn
            LEFT JOIN wallet_activity wa ON wn.activity_id = wa.id
            WHERE wn.user_id = ?
            ORDER BY wn.sent_at DESC
            LIMIT ?
        """, (user_id, limit))

    notifications = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return notifications


def mark_notification_read(db_path, notification_id, user_id):
    """Mark a notification as read"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE wallet_notifications
        SET read_at = ?
        WHERE id = ? AND user_id = ?
    """, (int(time.time()), notification_id, user_id))

    success = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return success


def mark_all_notifications_read(db_path, user_id):
    """Mark all notifications as read for a user"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE wallet_notifications
        SET read_at = ?
        WHERE user_id = ? AND read_at IS NULL
    """, (int(time.time()), user_id))

    count = cursor.rowcount
    conn.commit()
    conn.close()

    return count


def update_alert_settings(db_path, user_id, wallet_address, settings):
    """Update alert settings for a wallet"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE wallet_watchlist
        SET alert_enabled = ?,
            alert_on_buy = ?,
            alert_on_sell = ?,
            min_trade_usd = ?,
            last_updated = ?
        WHERE user_id = ? AND wallet_address = ?
    """, (
        settings.get('alert_enabled', True),
        settings.get('alert_on_buy', True),
        settings.get('alert_on_sell', False),
        settings.get('min_trade_usd', 100),
        int(time.time()),
        user_id,
        wallet_address
    ))

    success = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return success


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == '__main__':
    import os

    BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY', '')

    monitor = WalletActivityMonitor(
        birdeye_api_key=BIRDEYE_API_KEY,
        db_path='watchlists.db',
        poll_interval=120  # 2 minutes
    )

    print("\n🎯 Wallet Activity Monitor")
    print("   Press Ctrl+C to stop\n")

    try:
        monitor.start()

        # Keep main thread alive and print stats periodically
        while True:
            time.sleep(300)  # Every 5 minutes
            stats = monitor.get_monitoring_stats()

            print(f"\n{'='*80}")
            print(f"MONITORING STATS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*80}")
            print(f"  Active Wallets: {stats['active_wallets']}")
            print(f"  Recent Activities (1h): {stats['recent_activities']}")
            print(f"  Pending Notifications: {stats['pending_notifications']}")
            print(f"  Monitor Health: {stats['monitor_health']}")
            print(f"  Telegram: {'Enabled' if stats['telegram_enabled'] else 'Disabled'}")
            print(f"{'='*80}\n")

    except KeyboardInterrupt:
        print("\n\n⚠️ Received shutdown signal...")
        monitor.stop()
        print("✅ Monitor stopped gracefully\n")