import sqlite3
from datetime import datetime
import json
from typing import List, Dict, Optional


class WatchlistDatabase:
    """
    Manages user watchlists with SQLite database
    Stores Twitter accounts AND wallets, tags, notes, and performance tracking
    """
    
    def __init__(self, db_path: str = 'watchlists.db'):
        """
        Initialize database connection
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.init_database()
    
    
    def init_database(self):
        """Create tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table (for multi-user support)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                wallet_address TEXT,
                subscription_tier TEXT DEFAULT 'free'
            )
        ''')
        
        # Twitter Watchlist accounts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watchlist_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                username TEXT,
                name TEXT,
                followers INTEGER,
                verified BOOLEAN DEFAULT 0,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tags TEXT,
                notes TEXT,
                influence_score REAL,
                avg_timing REAL,
                pumps_called INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, author_id)
            )
        ''')
        
        # NEW: Wallet watchlist table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                wallet_address TEXT NOT NULL,
                tier TEXT,
                pump_count INTEGER,
                avg_distance_to_peak REAL,
                avg_roi_to_peak REAL,
                consistency_score REAL,
                tokens_hit TEXT,
                notes TEXT,
                tags TEXT,
                added_at INTEGER,
                last_updated INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, wallet_address)
            )
        ''')
        
        # Performance tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS account_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                token_address TEXT,
                token_ticker TEXT,
                pump_date TIMESTAMP,
                timing_minutes REAL,
                pump_gain REAL,
                confidence TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Watchlist groups/folders
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watchlist_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                group_name TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, group_name)
            )
        ''')
        
        # Group memberships
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_memberships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES watchlist_groups(id),
                FOREIGN KEY (account_id) REFERENCES watchlist_accounts(id),
                UNIQUE(group_id, account_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        
        print(f"[WATCHLIST DB] Database initialized at {self.db_path}")
    
    
    def create_user(self, user_id: str, wallet_address: str = None) -> bool:
        """Create new user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, wallet_address)
                VALUES (?, ?)
            ''', (user_id, wallet_address))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[WATCHLIST DB] Error creating user: {e}")
            return False
    
    
    # =========================================================================
    # TWITTER ACCOUNT WATCHLIST METHODS (EXISTING)
    # =========================================================================
    
    def add_to_watchlist(self, user_id: str, account: Dict) -> bool:
        """Add Twitter account to user's watchlist"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            self.create_user(user_id)
            
            tags = json.dumps(account.get('tags', []))
            
            cursor.execute('''
                INSERT OR REPLACE INTO watchlist_accounts 
                (user_id, author_id, username, name, followers, verified,
                 tags, notes, influence_score, avg_timing, pumps_called, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                user_id,
                account['author_id'],
                account.get('username'),
                account.get('name'),
                account.get('followers', 0),
                account.get('verified', False),
                tags,
                account.get('notes', ''),
                account.get('influence_score', 0),
                account.get('avg_timing', 0),
                account.get('pumps_called', 0)
            ))
            
            conn.commit()
            conn.close()
            
            print(f"[WATCHLIST DB] Added @{account.get('username')} to {user_id}'s watchlist")
            return True
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error adding to watchlist: {e}")
            return False
    
    
    def get_watchlist(self, user_id: str, group_id: int = None) -> List[Dict]:
        """Get user's Twitter watchlist"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if group_id:
                cursor.execute('''
                    SELECT w.* FROM watchlist_accounts w
                    JOIN group_memberships gm ON w.id = gm.account_id
                    WHERE w.user_id = ? AND gm.group_id = ?
                    ORDER BY w.influence_score DESC
                ''', (user_id, group_id))
            else:
                cursor.execute('''
                    SELECT * FROM watchlist_accounts
                    WHERE user_id = ?
                    ORDER BY influence_score DESC
                ''', (user_id,))
            
            rows = cursor.fetchall()
            conn.close()
            
            accounts = []
            for row in rows:
                account = dict(row)
                account['tags'] = json.loads(account['tags']) if account['tags'] else []
                accounts.append(account)
            
            return accounts
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching watchlist: {e}")
            return []
    
    
    def remove_from_watchlist(self, user_id: str, author_id: str) -> bool:
        """Remove Twitter account from watchlist"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM watchlist_accounts
                WHERE user_id = ? AND author_id = ?
            ''', (user_id, author_id))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error removing from watchlist: {e}")
            return False
    
    
    def update_account_notes(self, user_id: str, author_id: str, 
                            notes: str = None, tags: List[str] = None) -> bool:
        """Update Twitter account notes and tags"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if notes is not None and tags is not None:
                cursor.execute('''
                    UPDATE watchlist_accounts
                    SET notes = ?, tags = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND author_id = ?
                ''', (notes, json.dumps(tags), user_id, author_id))
            elif notes is not None:
                cursor.execute('''
                    UPDATE watchlist_accounts
                    SET notes = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND author_id = ?
                ''', (notes, user_id, author_id))
            elif tags is not None:
                cursor.execute('''
                    UPDATE watchlist_accounts
                    SET tags = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND author_id = ?
                ''', (json.dumps(tags), user_id, author_id))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error updating notes: {e}")
            return False
    
    
    def get_watchlist_stats(self, user_id: str) -> Dict:
        """Get statistics about user's Twitter watchlist"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT COUNT(*) FROM watchlist_accounts WHERE user_id = ?
            ''', (user_id,))
            total_accounts = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT AVG(influence_score) FROM watchlist_accounts WHERE user_id = ?
            ''', (user_id,))
            avg_influence = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT SUM(pumps_called) FROM watchlist_accounts WHERE user_id = ?
            ''', (user_id,))
            total_pumps = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT username, influence_score 
                FROM watchlist_accounts 
                WHERE user_id = ?
                ORDER BY influence_score DESC
                LIMIT 1
            ''', (user_id,))
            best = cursor.fetchone()
            
            conn.close()
            
            return {
                'total_accounts': total_accounts,
                'avg_influence': round(avg_influence, 1),
                'total_pumps_tracked': total_pumps,
                'best_performer': {
                    'username': best[0] if best else None,
                    'influence': best[1] if best else 0
                }
            }
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching stats: {e}")
            return {}
    
    
    # =========================================================================
    # NEW: WALLET WATCHLIST METHODS
    # =========================================================================
    
    def add_wallet_to_watchlist(self, user_id: str, wallet_data: Dict) -> bool:
        """
        Add a wallet to user's watchlist
        
        Args:
            user_id: User ID
            wallet_data: {
                'wallet_address': '0x...',
                'tier': 'S',
                'pump_count': 12,
                'avg_distance_to_peak': 87.5,
                'avg_roi_to_peak': 345.2,
                'consistency_score': 92.1,
                'tokens_hit': ['PEPE', 'PNUT'],
                'notes': 'Optional notes',
                'tags': ['tag1', 'tag2']
            }
        """
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            self.create_user(user_id)
            
            import time
            tags = json.dumps(wallet_data.get('tags', []))
            tokens = ','.join(wallet_data.get('tokens_hit', []))
            
            c.execute('''
                INSERT OR REPLACE INTO wallet_watchlist 
                (user_id, wallet_address, tier, pump_count, avg_distance_to_peak, 
                 avg_roi_to_peak, consistency_score, tokens_hit, notes, tags, 
                 added_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                wallet_data['wallet_address'],
                wallet_data.get('tier', 'C'),
                wallet_data.get('pump_count', 0),
                wallet_data.get('avg_distance_to_peak', 0),
                wallet_data.get('avg_roi_to_peak', 0),
                wallet_data.get('consistency_score', 0),
                tokens,
                wallet_data.get('notes', ''),
                tags,
                int(time.time()),
                int(time.time())
            ))
            
            conn.commit()
            conn.close()
            
            print(f"[WATCHLIST DB] Added wallet {wallet_data['wallet_address'][:8]}... to watchlist")
            return True
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error adding wallet: {e}")
            return False
    
    
    def get_wallet_watchlist(self, user_id: str, tier_filter: str = None) -> List[Dict]:
        """Get user's watched wallets, optionally filtered by tier"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            if tier_filter:
                c.execute('''
                    SELECT * FROM wallet_watchlist 
                    WHERE user_id = ? AND tier = ?
                    ORDER BY pump_count DESC, avg_distance_to_peak DESC
                ''', (user_id, tier_filter))
            else:
                c.execute('''
                    SELECT * FROM wallet_watchlist 
                    WHERE user_id = ?
                    ORDER BY 
                        CASE tier 
                            WHEN 'S' THEN 1 
                            WHEN 'A' THEN 2 
                            WHEN 'B' THEN 3 
                            ELSE 4 
                        END,
                        pump_count DESC
                ''', (user_id,))
            
            rows = c.fetchall()
            conn.close()
            
            wallets = []
            for row in rows:
                wallets.append({
                    'wallet_address': row[2],
                    'tier': row[3],
                    'pump_count': row[4],
                    'avg_distance_to_peak': row[5],
                    'avg_roi_to_peak': row[6],
                    'consistency_score': row[7],
                    'tokens_hit': row[8].split(',') if row[8] else [],
                    'notes': row[9],
                    'tags': json.loads(row[10]) if row[10] else [],
                    'added_at': row[11],
                    'last_updated': row[12]
                })
            
            return wallets
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching wallet watchlist: {e}")
            return []
    
    
    def remove_wallet_from_watchlist(self, user_id: str, wallet_address: str) -> bool:
        """Remove wallet from watchlist"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            c.execute('''
                DELETE FROM wallet_watchlist
                WHERE user_id = ? AND wallet_address = ?
            ''', (user_id, wallet_address))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error removing wallet: {e}")
            return False
    
    
    def update_wallet_notes(self, user_id: str, wallet_address: str,
                           notes: str = None, tags: List[str] = None) -> bool:
        """Update wallet notes and tags"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            import time
            
            if notes is not None and tags is not None:
                c.execute('''
                    UPDATE wallet_watchlist
                    SET notes = ?, tags = ?, last_updated = ?
                    WHERE user_id = ? AND wallet_address = ?
                ''', (notes, json.dumps(tags), int(time.time()), user_id, wallet_address))
            elif notes is not None:
                c.execute('''
                    UPDATE wallet_watchlist
                    SET notes = ?, last_updated = ?
                    WHERE user_id = ? AND wallet_address = ?
                ''', (notes, int(time.time()), user_id, wallet_address))
            elif tags is not None:
                c.execute('''
                    UPDATE wallet_watchlist
                    SET tags = ?, last_updated = ?
                    WHERE user_id = ? AND wallet_address = ?
                ''', (json.dumps(tags), int(time.time()), user_id, wallet_address))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error updating wallet notes: {e}")
            return False
    
    
    def get_wallet_stats(self, user_id: str) -> Dict:
        """Get statistics about user's wallet watchlist"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            c.execute('SELECT COUNT(*) FROM wallet_watchlist WHERE user_id = ?', (user_id,))
            total_wallets = c.fetchone()[0]
            
            c.execute('SELECT COUNT(*) FROM wallet_watchlist WHERE user_id = ? AND tier = ?', (user_id, 'S'))
            s_tier_count = c.fetchone()[0]
            
            c.execute('SELECT AVG(avg_distance_to_peak) FROM wallet_watchlist WHERE user_id = ?', (user_id,))
            avg_distance = c.fetchone()[0] or 0
            
            c.execute('SELECT SUM(pump_count) FROM wallet_watchlist WHERE user_id = ?', (user_id,))
            total_pumps = c.fetchone()[0] or 0
            
            conn.close()
            
            return {
                'total_wallets': total_wallets,
                's_tier_count': s_tier_count,
                'avg_distance': avg_distance,
                'total_pumps': total_pumps
            }
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching wallet stats: {e}")
            return {}
    
    
    # =========================================================================
    # PERFORMANCE TRACKING & GROUPS (EXISTING)
    # =========================================================================
    
    def track_performance(self, user_id: str, author_id: str, token_data: Dict) -> bool:
        """Track account performance on a specific token"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO account_performance
                (user_id, author_id, token_address, token_ticker, 
                 pump_date, timing_minutes, pump_gain, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                author_id,
                token_data.get('token_address'),
                token_data.get('token_ticker'),
                token_data.get('pump_date'),
                token_data.get('timing_minutes'),
                token_data.get('pump_gain'),
                token_data.get('confidence')
            ))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error tracking performance: {e}")
            return False
    
    
    def get_account_history(self, user_id: str, author_id: str) -> List[Dict]:
        """Get performance history for an account"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM account_performance
                WHERE user_id = ? AND author_id = ?
                ORDER BY pump_date DESC
            ''', (user_id, author_id))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching history: {e}")
            return []
    
    
    def create_group(self, user_id: str, group_name: str, description: str = '') -> Optional[int]:
        """Create a watchlist group/folder"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO watchlist_groups (user_id, group_name, description)
                VALUES (?, ?, ?)
            ''', (user_id, group_name, description))
            
            group_id = cursor.lastrowid
            
            conn.commit()
            conn.close()
            return group_id
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error creating group: {e}")
            return None
    
    
    def add_to_group(self, group_id: int, account_id: int) -> bool:
        """Add account to a group"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO group_memberships (group_id, account_id)
                VALUES (?, ?)
            ''', (group_id, account_id))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error adding to group: {e}")
            return False
    
    
    def get_user_groups(self, user_id: str) -> List[Dict]:
        """Get all groups for a user"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT g.*, COUNT(gm.account_id) as account_count
                FROM watchlist_groups g
                LEFT JOIN group_memberships gm ON g.id = gm.group_id
                WHERE g.user_id = ?
                GROUP BY g.id
                ORDER BY g.created_at DESC
            ''', (user_id,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching groups: {e}")
            return []