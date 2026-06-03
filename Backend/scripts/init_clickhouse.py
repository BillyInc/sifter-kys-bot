#!/usr/bin/env python3
"""
Initialize ClickHouse database and tables for the KYS pipeline.
Run once on first deployment: python scripts/init_clickhouse.py
"""
import sys
import os

# Add Backend dir to path so we can import services
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import clickhouse_connect
from services.clickhouse_client import CH_DATABASE
from services.clickhouse_schema import (
    CREATE_TOKEN_SCANS_SQL,
    CREATE_WALLET_TOKEN_STATS_SQL,
    CREATE_WALLET_AGGREGATE_STATS_SQL,
    CREATE_WALLET_WEEKLY_SNAPSHOTS_SQL,
    CREATE_LEADERBOARD_RESULTS_SQL,
    CREATE_MV_WALLET_AGGREGATE_SQL,
    # Telegram trading-bot analytics (bot rebuild)
    CREATE_BOT_SIGNAL_LOG_SQL,
    CREATE_BOT_TRADE_LOG_SQL,
    CREATE_BOT_FEE_LOG_SQL,
    CREATE_USER_BOT_STATS_AGG_SQL,
    CREATE_MV_USER_BOT_STATS_SQL,
    CREATE_FEE_REVENUE_AGG_SQL,
    CREATE_FEE_BY_TOKEN_AGG_SQL,
    CREATE_MV_FEE_REVENUE_SQL,
    CREATE_MV_FEE_BY_TOKEN_SQL,
)


def init():
    # Connect without database first to create it
    ch = clickhouse_connect.get_client(
        host=os.environ.get('CLICKHOUSE_HOST', 'localhost'),
        port=int(os.environ.get('CLICKHOUSE_PORT', 8443)),
        username=os.environ.get('CLICKHOUSE_USER', 'default'),
        password=os.environ.get('CLICKHOUSE_PASSWORD', ''),
        secure=os.environ.get('CLICKHOUSE_SECURE', 'true').lower() == 'true',
        verify=True,
        connect_timeout=10,
        send_receive_timeout=60,
    )

    print(f"Creating database `{CH_DATABASE}`...")
    ch.command(f"CREATE DATABASE IF NOT EXISTS `{CH_DATABASE}`")

    # Reconnect with the database selected
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

    tables = [
        ("token_scans", CREATE_TOKEN_SCANS_SQL),
        ("wallet_token_stats", CREATE_WALLET_TOKEN_STATS_SQL),
        ("wallet_aggregate_stats", CREATE_WALLET_AGGREGATE_STATS_SQL),
        ("wallet_weekly_snapshots", CREATE_WALLET_WEEKLY_SNAPSHOTS_SQL),
        ("leaderboard_results", CREATE_LEADERBOARD_RESULTS_SQL),
        # Telegram trading-bot analytics (bot rebuild)
        ("bot_signal_log", CREATE_BOT_SIGNAL_LOG_SQL),
        ("bot_trade_log", CREATE_BOT_TRADE_LOG_SQL),
        ("bot_fee_log", CREATE_BOT_FEE_LOG_SQL),
        ("user_bot_stats_agg", CREATE_USER_BOT_STATS_AGG_SQL),
        ("fee_revenue_agg", CREATE_FEE_REVENUE_AGG_SQL),
        ("fee_by_token_agg", CREATE_FEE_BY_TOKEN_AGG_SQL),
    ]

    for name, sql in tables:
        print(f"  Creating table {name}...")
        ch.command(sql)

    print("  Creating materialized view mv_wallet_aggregate...")
    ch.command(CREATE_MV_WALLET_AGGREGATE_SQL)

    # Bot analytics materialized views (write into the *_agg tables above)
    for mv_name, mv_sql in [
        ("mv_user_bot_stats", CREATE_MV_USER_BOT_STATS_SQL),
        ("mv_fee_revenue", CREATE_MV_FEE_REVENUE_SQL),
        ("mv_fee_by_token", CREATE_MV_FEE_BY_TOKEN_SQL),
    ]:
        print(f"  Creating materialized view {mv_name}...")
        ch.command(mv_sql)

    print(f"\nClickHouse initialized successfully (database: {CH_DATABASE}).")
    print("Tables: token_scans, wallet_token_stats, wallet_aggregate_stats,")
    print("        wallet_weekly_snapshots, leaderboard_results,")
    print("        bot_signal_log, bot_trade_log, bot_fee_log,")
    print("        user_bot_stats_agg, fee_revenue_agg, fee_by_token_agg")
    print("Views:  mv_wallet_aggregate, mv_user_bot_stats, mv_fee_revenue, mv_fee_by_token")


if __name__ == '__main__':
    init()
