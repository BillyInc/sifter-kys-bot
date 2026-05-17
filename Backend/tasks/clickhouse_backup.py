"""
Celery task: back up ClickHouse analytics tables to Supabase PostgreSQL.

Runs weekly (Monday 2:00 AM UTC) via Beat schedule.  Each CH table is read
in 1 000-row batches using SELECT ... FINAL and upserted into a mirrored
Supabase table prefixed with ``ch_backup_``.
"""

import logging
from datetime import datetime, date

from celery_app import celery
from services.clickhouse_client import get_clickhouse_client, CH_DATABASE
from services.supabase_client import get_supabase_client, SCHEMA_NAME

logger = logging.getLogger(__name__)

BATCH_SIZE = 1_000

# ── table definitions ───────────────────────────────────────────────
# (ch_table, supabase_table, columns, on_conflict key(s))
TABLE_SPECS = [
    {
        "ch_table": "token_scans",
        "sb_table": "ch_backup_token_scans",
        "columns": [
            "token_address", "scan_id", "discovered_via", "scan_timestamp",
            "launch_price", "current_price", "ath_price", "launch_to_ath_mult",
            "market_cap_usd", "volume_24h_usd", "liquidity_usd", "holder_count",
            "token_symbol", "token_name", "updated_at",
        ],
        "on_conflict": "token_address,scan_id",
    },
    {
        "ch_table": "wallet_token_stats",
        "sb_table": "ch_backup_wallet_token_stats",
        "columns": [
            "wallet_address", "token_address", "scan_id",
            "first_entry_price", "first_entry_usd", "first_entry_timestamp",
            "total_spent_usd", "realized_pnl_usd", "unrealized_pnl_usd",
            "total_pnl_usd", "realized_roi_mult", "total_roi_mult",
            "qualifies", "outcome", "wallet_source", "updated_at",
        ],
        "on_conflict": "wallet_address,token_address,scan_id",
    },
    {
        "ch_table": "wallet_aggregate_stats",
        "sb_table": "ch_backup_wallet_aggregate_stats",
        "columns": [
            "wallet_address", "tokens_appeared_in", "tokens_qualified",
            "wins", "losses", "win_rate", "avg_roi_mult", "total_pnl_usd",
            "professional_score", "tier", "consistency_score", "updated_at",
        ],
        "on_conflict": "wallet_address",
    },
]


def _serialize_value(val):
    """Convert ClickHouse-native types to JSON-safe values for Supabase."""
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return val


def _backup_table(ch, supabase, spec: dict) -> dict:
    """Stream one CH table into Supabase in batches. Returns stats dict."""
    ch_table = spec["ch_table"]
    sb_table = spec["sb_table"]
    columns = spec["columns"]
    on_conflict = spec["on_conflict"]

    col_list = ", ".join(columns)
    query = f"SELECT {col_list} FROM `{CH_DATABASE}`.`{ch_table}` FINAL"

    total_rows = 0
    total_upserted = 0
    errors = 0

    # Read all rows via the client (returns list of dicts)
    try:
        rows = ch.query(query).named_results()
    except Exception as exc:
        logger.error("Failed to query CH table %s: %s", ch_table, exc)
        return {
            "table": ch_table,
            "rows_read": 0,
            "rows_upserted": 0,
            "errors": 1,
            "error_detail": str(exc),
        }

    batch: list[dict] = []

    for row in rows:
        total_rows += 1
        record = {col: _serialize_value(row[col]) for col in columns}
        batch.append(record)

        if len(batch) >= BATCH_SIZE:
            try:
                supabase.schema(SCHEMA_NAME).table(sb_table).upsert(
                    batch, on_conflict=on_conflict
                ).execute()
                total_upserted += len(batch)
                logger.info(
                    "[%s] upserted batch (%d rows so far)", sb_table, total_upserted
                )
            except Exception as exc:
                errors += 1
                logger.error(
                    "[%s] batch upsert failed at row %d: %s",
                    sb_table, total_rows, exc,
                )
            batch = []

    # flush remaining rows
    if batch:
        try:
            supabase.schema(SCHEMA_NAME).table(sb_table).upsert(
                batch, on_conflict=on_conflict
            ).execute()
            total_upserted += len(batch)
            logger.info(
                "[%s] upserted final batch (%d rows total)", sb_table, total_upserted
            )
        except Exception as exc:
            errors += 1
            logger.error("[%s] final batch upsert failed: %s", sb_table, exc)

    return {
        "table": ch_table,
        "rows_read": total_rows,
        "rows_upserted": total_upserted,
        "errors": errors,
    }


@celery.task(name="tasks.backup_clickhouse_to_supabase", bind=True, max_retries=2)
def backup_clickhouse_to_supabase(self):
    """Back up all ClickHouse analytics tables to Supabase PostgreSQL."""
    logger.info("Starting ClickHouse -> Supabase backup")

    ch = get_clickhouse_client()
    supabase = get_supabase_client()
    results = []

    for spec in TABLE_SPECS:
        logger.info("Backing up %s -> %s ...", spec["ch_table"], spec["sb_table"])
        stats = _backup_table(ch, supabase, spec)
        results.append(stats)

    summary = {
        "tables": len(results),
        "total_rows_read": sum(r["rows_read"] for r in results),
        "total_rows_upserted": sum(r["rows_upserted"] for r in results),
        "total_errors": sum(r["errors"] for r in results),
        "details": results,
    }

    logger.info("Backup complete: %s", summary)
    return summary
