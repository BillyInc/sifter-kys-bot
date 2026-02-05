#!/usr/bin/env python3
"""
migrate_add_telegram.py - Add Telegram tables to existing database
Run this to add Telegram support to your existing watchlists.db
"""

import sqlite3
import sys
import os

def migrate_telegram_tables(db_path='watchlists.db'):
    """Add Telegram tables to existing database"""
    
    print(f"\n{'='*80}")
    print(f"TELEGRAM MIGRATION")
    print(f"{'='*80}")
    print(f"Database: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Read migration SQL
        with open('add_telegram_tables.sql', 'r') as f:
            migration_sql = f.read()
        
        # Execute migration
        cursor.executescript(migration_sql)
        conn.commit()
        
        # Verify tables were created
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name IN ('telegram_users', 'telegram_notification_log')
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"\n✅ Migration successful!")
        print(f"\nCreated tables:")
        for table in tables:
            print(f"  ✓ {table}")
        
        if len(tables) == 2:
            print(f"\n{'='*80}")
            print(f"✅ TELEGRAM TABLES READY")
            print(f"{'='*80}\n")
            return True
        else:
            print(f"\n⚠️  Some tables may not have been created")
            return False
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return False
    
    finally:
        conn.close()


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'watchlists.db'
    success = migrate_telegram_tables(db_path)
    
    sys.exit(0 if success else 1)