"""
migrate_db.py — Run this ONCE to patch your existing watchlists.db.

If you have a fresh DB or are about to delete and recreate it, you don't
need this — just run init_database.py instead. This is only for patching
a live database that already has data you want to keep.

Usage:
    python migrate_db.py
"""

import sqlite3
import os


def migrate(db_path='watchlists.db'):
    if not os.path.exists(db_path):
        print(f"❌ {db_path} not found. Run init_database.py first.")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    errors = 0

    print(f"\n{'='*60}")
    print("MIGRATING watchlists.db")
    print(f"{'='*60}\n")

    # --------------------------------------------------------
    # FIX: wallet_watchlist — add missing alert columns
    # These exist in init_database.py but were missing from
    # the watchlist_db.py CREATE TABLE, so if watchlist_db.py
    # created the table first, these columns won't exist.
    # --------------------------------------------------------
    alert_columns = [
        ("alert_enabled",  "BOOLEAN DEFAULT 1"),
        ("alert_on_buy",   "BOOLEAN DEFAULT 1"),
        ("alert_on_sell",  "BOOLEAN DEFAULT 0"),
        ("min_trade_usd",  "REAL DEFAULT 100"),
    ]

    for col_name, col_def in alert_columns:
        try:
            cursor.execute(f"ALTER TABLE wallet_watchlist ADD COLUMN {col_name} {col_def}")
            print(f"  ✓ wallet_watchlist: added {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e):
                print(f"  · wallet_watchlist: {col_name} already exists (ok)")
            else:
                print(f"  ✗ wallet_watchlist: {col_name} — {e}")
                errors += 1

    # --------------------------------------------------------
    # Verify wallet_notifications has read_at (it should if
    # init_database.py created it, but just in case)
    # --------------------------------------------------------
    try:
        cursor.execute("PRAGMA table_info(wallet_notifications)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'read_at' not in columns:
            cursor.execute("ALTER TABLE wallet_notifications ADD COLUMN read_at INTEGER DEFAULT NULL")
            print(f"  ✓ wallet_notifications: added read_at")
        else:
            print(f"  · wallet_notifications: read_at already exists (ok)")

        if 'dismissed_at' not in columns:
            cursor.execute("ALTER TABLE wallet_notifications ADD COLUMN dismissed_at INTEGER DEFAULT NULL")
            print(f"  ✓ wallet_notifications: added dismissed_at")
        else:
            print(f"  · wallet_notifications: dismissed_at already exists (ok)")

    except sqlite3.OperationalError as e:
        print(f"  ✗ wallet_notifications check failed: {e}")
        errors += 1

    conn.commit()
    conn.close()

    if errors == 0:
        print(f"\n✅ Migration complete — no errors.")
        print(f"   You can now restart your Flask server.\n")
        return True
    else:
        print(f"\n⚠️  Migration finished with {errors} error(s). Check above.\n")
        return False


if __name__ == '__main__':
    migrate()