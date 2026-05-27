#!/usr/bin/env python3
"""
Migration: Elite 15 pipeline v3.

1. wallet_token_stats  — add all new columns (ALTER IF NOT EXISTS, safe to re-run)
2. wallet_aggregate_stats — add new columns
3. mv_wallet_aggregate — DROP + recreate
4. Backfill wallet_aggregate_stats from existing wallet_token_stats rows

Run:
    cd Backend && python scripts/migrate_elite15.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import clickhouse_connect
from services.clickhouse_client import CH_DATABASE
from services.clickhouse_schema import DROP_MV_WALLET_AGGREGATE_SQL, CREATE_MV_WALLET_AGGREGATE_SQL

ALTER_TOKEN_STATS = [
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS last_buy_timestamp    DateTime  DEFAULT toDateTime(0)",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS first_sell_timestamp  DateTime  DEFAULT toDateTime(0)",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS sell_time             DateTime  DEFAULT toDateTime(0)",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS hold_time_secs        Int64     DEFAULT 0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS entry_vs_launch_mult  Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS ath_price_raw         Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS launch_price_raw      Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS token_creation_time   DateTime  DEFAULT toDateTime(0)",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS current_price_usd     Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS tokens_bought_native  Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS tokens_sold_native    Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS current_balance       Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS current_value_usd     Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS avg_cost_per_token    Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS avg_sell_size_usd     Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS trade_count           UInt16    DEFAULT 0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS sell_proceeds_usd     Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS roi_pct               Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS token_name            String    DEFAULT ''",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS token_symbol          String    DEFAULT ''",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS token_image           String    DEFAULT ''",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS token_decimals        UInt8     DEFAULT 0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS market_cap_usd        Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS liquidity_usd         Float64   DEFAULT 0.0",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS primary_market        String    DEFAULT ''",
    "ALTER TABLE wallet_token_stats ADD COLUMN IF NOT EXISTS first_buyer_rank      UInt16    DEFAULT 0",
]

ALTER_AGGREGATE_STATS = [
    "ALTER TABLE wallet_aggregate_stats ADD COLUMN IF NOT EXISTS tokens_traded_30d         UInt32  DEFAULT 0",
    "ALTER TABLE wallet_aggregate_stats ADD COLUMN IF NOT EXISTS avg_roi_pct               Float64 DEFAULT 0.0",
    "ALTER TABLE wallet_aggregate_stats ADD COLUMN IF NOT EXISTS total_sell_proceeds_usd   Float64 DEFAULT 0.0",
    "ALTER TABLE wallet_aggregate_stats ADD COLUMN IF NOT EXISTS total_realized_pnl_usd    Float64 DEFAULT 0.0",
    "ALTER TABLE wallet_aggregate_stats ADD COLUMN IF NOT EXISTS total_unrealized_pnl_usd  Float64 DEFAULT 0.0",
    "ALTER TABLE wallet_aggregate_stats ADD COLUMN IF NOT EXISTS avg_hold_time_secs        Float64 DEFAULT 0.0",
]

BACKFILL_SQL = """
INSERT INTO wallet_aggregate_stats (
    wallet_address, tokens_appeared_in, tokens_qualified, tokens_traded_30d,
    wins, draws, losses, win_rate,
    avg_entry_to_ath_mult, avg_entry_from_launch_mult,
    total_roi_pct, avg_roi_pct, avg_roi_mult,
    avg_spend_per_token_usd, total_spent_usd, total_sell_proceeds_usd,
    total_pnl_usd, total_realized_pnl_usd, total_unrealized_pnl_usd,
    avg_hold_time_secs, consistency_score, entry_price_multipliers,
    professional_score, tier, last_active_token, last_active_at, updated_at
)
SELECT
    wallet_address,
    countDistinct(token_address)    AS tokens_appeared_in,
    countIf(qualifies = 1)          AS tokens_qualified,
    countIf(
        qualifies = 1
        AND first_entry_timestamp >= (now() - toIntervalDay(30))
    )                               AS tokens_traded_30d,
    countIf(outcome = 'win')        AS wins,
    countIf(outcome = 'draw')       AS draws,
    countIf(outcome = 'loss')       AS losses,
    if(
        countIf(outcome IN ('win','draw','loss')) > 0,
        countIf(outcome = 'win') * 100.0
            / countIf(outcome IN ('win','draw','loss')),
        0
    )                               AS win_rate,
    ifNull(avgIf(wallet_token_stats.avg_entry_to_ath_mult,      qualifies = 1), 0)  AS avg_entry_to_ath_mult,
    ifNull(avgIf(wallet_token_stats.entry_price_to_launch_mult, qualifies = 1), 0)  AS avg_entry_from_launch_mult,
    0.0                             AS total_roi_pct,
    ifNull(avgIf(wallet_token_stats.roi_pct,                    qualifies = 1), 0)  AS avg_roi_pct,
    ifNull(avgIf(wallet_token_stats.total_roi_mult,             qualifies = 1), 0)  AS avg_roi_mult,
    avg(wallet_token_stats.total_spent_usd)            AS avg_spend_per_token_usd,
    sum(wallet_token_stats.total_spent_usd)            AS total_spent_usd,
    sum(wallet_token_stats.sell_proceeds_usd)          AS total_sell_proceeds_usd,
    sum(wallet_token_stats.total_pnl_usd)              AS total_pnl_usd,
    sum(wallet_token_stats.realized_pnl_usd)           AS total_realized_pnl_usd,
    sum(wallet_token_stats.unrealized_pnl_usd)         AS total_unrealized_pnl_usd,
    ifNull(avgIf(wallet_token_stats.hold_time_secs, qualifies = 1 AND wallet_token_stats.hold_time_secs > 0), 0) AS avg_hold_time_secs,
    if(
        ifNull(avgIf(wallet_token_stats.entry_price_to_launch_mult, qualifies = 1), 0) > 0,
        greatest(0, 100 - (
            ifNull(stddevPopIf(wallet_token_stats.entry_price_to_launch_mult, qualifies = 1), 0)
            / avgIf(wallet_token_stats.entry_price_to_launch_mult, qualifies = 1)
        ) * 100),
        50
    )                               AS consistency_score,
    ''                              AS entry_price_multipliers,
    (
        least(1000, log(1 + ifNull(avgIf(wallet_token_stats.avg_entry_to_ath_mult,      qualifies=1), 0)) * 100) * 0.50 +
        least(1000, log(1 + ifNull(avgIf(wallet_token_stats.entry_price_to_launch_mult, qualifies=1), 0)) * 100) * 0.20 +
        least(1000, log(1 + ifNull(avgIf(wallet_token_stats.total_roi_mult,             qualifies=1), 0)) * 100) * 0.20 +
        greatest(0, 100 - ifNull(
            stddevPopIf(wallet_token_stats.entry_price_to_launch_mult, qualifies=1)
            / nullIf(avgIf(wallet_token_stats.entry_price_to_launch_mult, qualifies=1), 0)
        , 0) * 100) * 0.10
    )                               AS professional_score,
    ''                              AS tier,
    ifNull(argMaxIf(token_address, first_entry_timestamp, qualifies=1), '') AS last_active_token,
    ifNull(maxIf(first_entry_timestamp, qualifies=1), now())  AS last_active_at,
    now()                           AS updated_at
FROM wallet_token_stats
GROUP BY wallet_address
"""


def migrate():
    ch = clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        port=int(os.environ.get("CLICKHOUSE_PORT", 8443)),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        database=CH_DATABASE,
        secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
        verify=True, connect_timeout=10, send_receive_timeout=120,
    )
    print(f"Connected to ClickHouse ({CH_DATABASE})")

    print(f"\n[1/4] wallet_token_stats — adding {len(ALTER_TOKEN_STATS)} columns")
    for stmt in ALTER_TOKEN_STATS:
        col = stmt.split("ADD COLUMN IF NOT EXISTS ")[1].split()[0]
        print(f"  {col} ...", end=" ")
        ch.command(stmt)
        print("OK")

    print(f"\n[2/4] wallet_aggregate_stats — adding {len(ALTER_AGGREGATE_STATS)} columns")
    for stmt in ALTER_AGGREGATE_STATS:
        col = stmt.split("ADD COLUMN IF NOT EXISTS ")[1].split()[0]
        print(f"  {col} ...", end=" ")
        ch.command(stmt)
        print("OK")

    print("\n[3/4] Rebuilding mv_wallet_aggregate")
    print("  Dropping ...", end=" ")
    ch.command(DROP_MV_WALLET_AGGREGATE_SQL)
    print("OK")
    print("  Creating ...", end=" ")
    ch.command(CREATE_MV_WALLET_AGGREGATE_SQL)
    print("OK")

    print("\n[4/4] Backfilling wallet_aggregate_stats")
    ch.command(BACKFILL_SQL)
    count = ch.query("SELECT count() FROM wallet_aggregate_stats FINAL").result_rows[0][0]
    print(f"  OK — {count} aggregate rows")

    print("\nMigration complete.")
    print("Deploy code, then: celery -A celery_app call tasks.leaderboard_discovery_scan")


if __name__ == "__main__":
    migrate()
