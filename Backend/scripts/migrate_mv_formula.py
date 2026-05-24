#!/usr/bin/env python3
"""
Migration: DROP and recreate mv_wallet_aggregate with updated professional_score formula.

The formula changes from 60/30/10 to 50/20/20/10 weights:
  50% — runner quality (entry vs ATH)
  20% — early entry (entry vs launch, was dead weight at 0%)
  20% — realized ROI
  10% — consistency/discipline

After running this script, trigger requalification to repopulate aggregates:
    celery -A celery_app call tasks.requalify_existing_data

Usage:
    cd Backend && python scripts/migrate_mv_formula.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import clickhouse_connect
from services.clickhouse_client import CH_DATABASE
from services.clickhouse_schema import DROP_MV_WALLET_AGGREGATE_SQL, CREATE_MV_WALLET_AGGREGATE_SQL


def migrate():
    ch = clickhouse_connect.get_client(
        host=os.environ.get('CLICKHOUSE_HOST', 'localhost'),
        port=int(os.environ.get('CLICKHOUSE_PORT', 8443)),
        username=os.environ.get('CLICKHOUSE_USER', 'default'),
        password=os.environ.get('CLICKHOUSE_PASSWORD', ''),
        database=CH_DATABASE,
        secure=os.environ.get('CLICKHOUSE_SECURE', 'true').lower() == 'true',
        verify=True,
        connect_timeout=10,
        send_receive_timeout=60,
    )

    print(f"Connected to ClickHouse ({CH_DATABASE})")

    print("Dropping old mv_wallet_aggregate...")
    ch.command(DROP_MV_WALLET_AGGREGATE_SQL)
    print("  Done.")

    print("Creating mv_wallet_aggregate with new 50/20/20/10 formula...")
    ch.command(CREATE_MV_WALLET_AGGREGATE_SQL)
    print("  Done.")

    # Verify
    result = ch.query("SHOW CREATE VIEW mv_wallet_aggregate")
    print(f"\nMV recreated successfully.")
    print(f"Next step: run requalification to repopulate wallet_aggregate_stats:")
    print(f"  celery -A celery_app call tasks.requalify_existing_data")
    print(f"  OR: cd Backend && python -c \"from tasks.wallet_qualification import requalify_existing_data; requalify_existing_data()\"")


if __name__ == "__main__":
    migrate()
