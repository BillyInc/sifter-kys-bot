import sqlite3
from datetime import datetime
import json
from typing import List, Dict, Optional


class WatchlistDatabase:
    """
    Manages user watchlists with SQLite database
    Stores accounts, tags, notes, and performance tracking
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
        
        # Watchlist accounts table
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
        """
        Create new user
        
        Args:
            user_id: Unique user identifier
            wallet_address: Optional wallet address
        
        Returns:
            True if successful
        """
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
    
    
    def add_to_watchlist(
        self,
        user_id: str,
        account: Dict
    ) -> bool:
        """
        Add account to user's watchlist
        
        Args:
            user_id: User identifier
            account: Dictionary with account data
        
        Returns:
            True if successful
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Ensure user exists
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
        """
        Get user's watchlist
        
        Args:
            user_id: User identifier
            group_id: Optional group filter
        
        Returns:
            List of watchlist accounts
        """
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
        """
        Remove account from watchlist
        
        Args:
            user_id: User identifier
            author_id: Twitter author ID to remove
        
        Returns:
            True if successful
        """
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
    
    
    def update_account_notes(
        self,
        user_id: str,
        author_id: str,
        notes: str = None,
        tags: List[str] = None
    ) -> bool:
        """
        Update account notes and tags
        
        Args:
            user_id: User identifier
            author_id: Twitter author ID
            notes: Optional notes text
            tags: Optional list of tags
        
        Returns:
            True if successful
        """
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
    
    
    def track_performance(
        self,
        user_id: str,
        author_id: str,
        token_data: Dict
    ) -> bool:
        """
        Track account performance on a specific token
        
        Args:
            user_id: User identifier
            author_id: Twitter author ID
            token_data: Dictionary with token/pump data
        
        Returns:
            True if successful
        """
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
        """
        Get performance history for an account
        
        Args:
            user_id: User identifier
            author_id: Twitter author ID
        
        Returns:
            List of performance records
        """
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
        """
        Create a watchlist group/folder
        
        Args:
            user_id: User identifier
            group_name: Name of the group
            description: Optional description
        
        Returns:
            Group ID if successful, None otherwise
        """
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
        """
        Add account to a group
        
        Args:
            group_id: Group ID
            account_id: Watchlist account ID
        
        Returns:
            True if successful
        """
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
        """
        Get all groups for a user
        
        Args:
            user_id: User identifier
        
        Returns:
            List of groups
        """
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
    
    
    def get_watchlist_stats(self, user_id: str) -> Dict:
        """
        Get statistics about user's watchlist
        
        Args:
            user_id: User identifier
        
        Returns:
            Dictionary with stats
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Total accounts
            cursor.execute('''
                SELECT COUNT(*) FROM watchlist_accounts WHERE user_id = ?
            ''', (user_id,))
            total_accounts = cursor.fetchone()[0]
            
            # Average influence
            cursor.execute('''
                SELECT AVG(influence_score) FROM watchlist_accounts WHERE user_id = ?
            ''', (user_id,))
            avg_influence = cursor.fetchone()[0] or 0
            
            # Total pumps tracked
            cursor.execute('''
                SELECT SUM(pumps_called) FROM watchlist_accounts WHERE user_id = ?
            ''', (user_id,))
            total_pumps = cursor.fetchone()[0] or 0
            
            # Best performer
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