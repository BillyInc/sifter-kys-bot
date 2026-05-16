#!/usr/bin/env python3
"""
One-time script to fix ClickHouse wallet_token_stats qualification data.

Problem: All 148K rows have qualifies=0 because _get_token_ath_mult() returned 0
for every token (SolanaTracker never provided launch prices). The old qualification
required BOTH wallet >5x ROI AND token >30x ATH — since ATH was always 0, every
row was marked as "loss".

Fix: Requalify using wallet ROI alone (>= 5x realized = win, near 5x = draw).
Re-insert rows with fresh updated_at so ReplacingMergeTree deduplicates.
Also recreates the MV with NULL-safe formula.

Usage:
    cd Backend
    python scripts/requalify_clickhouse_data.py

    # Or dry-run first:
    python scripts/requalify_clickhouse_data.py --dry-run
"""
import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import clickhouse_connect
from services.clickhouse_client import CH_DATABASE
from services.clickhouse_schema import CREATE_MV_WALLET_AGGREGATE_SQL

# Thresholds (match wallet_qualification.py)
WIN_WALLET_MULT = 5.0
SECOND_PASS_MIN_SPEND = 75.0


def get_write_client():
    """Get a ClickHouse client with write access."""
    return clickhouse_connect.get_client(
        host=os.environ.get('CLICKHOUSE_HOST', 'localhost'),
        port=int(os.environ.get('CLICKHOUSE_PORT', 8443)),
        username=os.environ.get('CLICKHOUSE_USER', 'default'),
        password=os.environ.get('CLICKHOUSE_PASSWORD', ''),
        database=CH_DATABASE,
        secure=os.environ.get('CLICKHOUSE_SECURE', 'true').lower() == 'true',
        verify=True,
        compress=True,
        connect_timeout=30,
        send_receive_timeout=300,
    )


def requalify_outcome(realized_roi_mult, total_spent_usd):
    """Compute outcome and qualifies using wallet ROI only (no ATH requirement)."""
    if total_spent_usd < SECOND_PASS_MIN_SPEND:
        return "loss", 0

    if realized_roi_mult > WIN_WALLET_MULT:
        return "win", 1

    if abs(realized_roi_mult - WIN_WALLET_MULT) < 0.5:
        return "draw", 0

    return "loss", 0


def recreate_mv(ch):
    """Drop and recreate the materialized view with NULL-safe formula."""
    print("\n[MV] Dropping old mv_wallet_aggregate...")
    ch.command("DROP VIEW IF EXISTS mv_wallet_aggregate")
    print("[MV] Creating mv_wallet_aggregate with NULL-safe formula...")
    ch.command(CREATE_MV_WALLET_AGGREGATE_SQL)
    print("[MV] Materialized view recreated successfully.")


def requalify_data(ch, dry_run=False, start_offset=0):
    """Read all wallet_token_stats, recompute outcome/qualifies, re-insert."""
    print("\n[REQUALIFY] Reading all rows from wallet_token_stats FINAL...")

    # Get total count first
    count_result = ch.query("SELECT count() FROM wallet_token_stats FINAL")
    total_rows = count_result.first_row[0]
    print(f"[REQUALIFY] Total rows to process: {total_rows:,}")
    if start_offset > 0:
        print(f"[REQUALIFY] Resuming from offset {start_offset:,}")

    # Columns we need to read and re-insert
    columns = [
        'wallet_address', 'token_address', 'scan_id',
        'first_entry_price', 'first_entry_usd', 'first_entry_timestamp',
        'entry_price_to_launch_mult', 'avg_entry_price', 'avg_entry_to_ath_mult',
        'all_buys', 'all_sells', 'buy_count', 'sell_count',
        'total_spent_usd', 'realized_pnl_usd', 'unrealized_pnl_usd',
        'total_pnl_usd', 'realized_roi_mult', 'total_roi_mult',
        'qualifies', 'outcome', 'disqualify_reason', 'wallet_source',
    ]

    batch_size = 5000
    stats = {'wins': 0, 'draws': 0, 'losses': 0, 'total': 0, 'changed': 0}
    start_time = time.time()

    # Read in batches using LIMIT/OFFSET
    offset = start_offset
    while offset < total_rows:
        query = f"""
            SELECT {', '.join(columns)}
            FROM wallet_token_stats FINAL
            ORDER BY wallet_address, token_address
            LIMIT {batch_size} OFFSET {offset}
        """
        result = ch.query(query)
        rows = list(result.named_results())

        if not rows:
            break

        # Recompute each row
        insert_data = []
        insert_columns = columns + ['updated_at']

        for row in rows:
            old_outcome = row['outcome']
            old_qualifies = row['qualifies']

            new_outcome, new_qualifies = requalify_outcome(
                row['realized_roi_mult'],
                row['total_spent_usd'],
            )

            # Clear disqualify_reason for rows that now qualify
            disqualify_reason = row['disqualify_reason']
            if new_qualifies == 1:
                disqualify_reason = ''

            # Track stats
            stats['total'] += 1
            if new_outcome == 'win':
                stats['wins'] += 1
            elif new_outcome == 'draw':
                stats['draws'] += 1
            else:
                stats['losses'] += 1

            if new_outcome != old_outcome or new_qualifies != old_qualifies:
                stats['changed'] += 1

            # Build row for re-insert
            row_data = [
                row['wallet_address'], row['token_address'], row['scan_id'],
                row['first_entry_price'], row['first_entry_usd'], row['first_entry_timestamp'],
                row['entry_price_to_launch_mult'], row['avg_entry_price'], row['avg_entry_to_ath_mult'],
                row['all_buys'], row['all_sells'], row['buy_count'], row['sell_count'],
                row['total_spent_usd'], row['realized_pnl_usd'], row['unrealized_pnl_usd'],
                row['total_pnl_usd'], row['realized_roi_mult'], row['total_roi_mult'],
                new_qualifies, new_outcome, disqualify_reason, row['wallet_source'],
                datetime.now(timezone.utc),
            ]
            insert_data.append(row_data)

        # Bulk insert the batch
        if not dry_run and insert_data:
            ch.insert(
                table='wallet_token_stats',
                data=insert_data,
                column_names=insert_columns,
            )

        offset += len(rows)
        elapsed = time.time() - start_time
        rate = stats['total'] / elapsed if elapsed > 0 else 0
        print(
            f"  Batch {offset // batch_size}: "
            f"{stats['total']:,}/{total_rows:,} rows "
            f"({stats['wins']} wins, {stats['draws']} draws, {stats['losses']} losses, "
            f"{stats['changed']} changed) "
            f"[{rate:.0f} rows/s]"
        )

    elapsed = time.time() - start_time
    print(f"\n[REQUALIFY] {'DRY RUN ' if dry_run else ''}Complete in {elapsed:.1f}s")
    print(f"  Total rows:    {stats['total']:,}")
    print(f"  Wins:          {stats['wins']:,}")
    print(f"  Draws:         {stats['draws']:,}")
    print(f"  Losses:        {stats['losses']:,}")
    print(f"  Changed:       {stats['changed']:,}")

    return stats


def verify(ch):
    """Run verification queries after requalification."""
    print("\n[VERIFY] Checking requalified data...")

    # Check qualifies distribution
    result = ch.query(
        "SELECT qualifies, outcome, count() as cnt "
        "FROM wallet_token_stats FINAL "
        "GROUP BY qualifies, outcome "
        "ORDER BY qualifies DESC, outcome"
    )
    print("\n  qualifies | outcome | count")
    print("  ----------|---------|------")
    for row in result.named_results():
        print(f"  {row['qualifies']:>9} | {row['outcome']:<7} | {row['cnt']:,}")

    # Check aggregate stats
    result = ch.query(
        "SELECT count() as total, "
        "countIf(tokens_qualified > 0) as with_qualified, "
        "avg(professional_score) as avg_score, "
        "max(professional_score) as max_score "
        "FROM wallet_aggregate_stats FINAL"
    )
    row = result.first_row
    print(f"\n  Aggregate stats:")
    print(f"    Total wallets:       {row[0]:,}")
    print(f"    With qualified:      {row[1]:,}")
    print(f"    Avg prof. score:     {row[2]:.2f}")
    print(f"    Max prof. score:     {row[3]:.2f}")

    # Top 15
    result = ch.query(
        "SELECT wallet_address, professional_score, tokens_qualified, "
        "avg_roi_mult, win_rate, total_pnl_usd "
        "FROM wallet_aggregate_stats FINAL "
        "WHERE tokens_qualified > 0 "
        "ORDER BY professional_score DESC "
        "LIMIT 15"
    )
    print(f"\n  Top 15 wallets:")
    print(f"  {'Wallet':<46} {'Score':>7} {'Qual':>5} {'ROI':>8} {'WR%':>6} {'PnL USD':>12}")
    print(f"  {'-'*46} {'-'*7} {'-'*5} {'-'*8} {'-'*6} {'-'*12}")
    for row in result.named_results():
        print(
            f"  {row['wallet_address'][:44]:<46} "
            f"{row['professional_score']:>7.1f} "
            f"{row['tokens_qualified']:>5} "
            f"{row['avg_roi_mult']:>8.1f} "
            f"{row['win_rate']:>6.1f} "
            f"{row['total_pnl_usd']:>12,.2f}"
        )


def main():
    dry_run = '--dry-run' in sys.argv
    skip_mv = '--skip-mv' in sys.argv

    # Parse --resume-from N
    resume_from = 0
    for arg in sys.argv:
        if arg.startswith('--resume-from='):
            resume_from = int(arg.split('=')[1])

    if dry_run:
        print("=" * 70)
        print("  DRY RUN MODE — no data will be written")
        print("=" * 70)

    ch = get_write_client()
    print(f"Connected to ClickHouse (database: {CH_DATABASE})")

    # Step 1: Recreate MV with NULL-safe formula
    if not dry_run and not skip_mv:
        recreate_mv(ch)
    elif skip_mv:
        print("\n[MV] Skipped (--skip-mv)")

    # Step 2: Requalify all rows
    stats = requalify_data(ch, dry_run=dry_run, start_offset=resume_from)

    # Step 3: Verify
    if not dry_run:
        # Give CH a moment to process the MV inserts
        print("\n[VERIFY] Waiting 5s for MV to process...")
        time.sleep(5)
        verify(ch)
    else:
        print(f"\n[DRY RUN] Would have changed {stats['changed']:,} rows")
        print(f"  New wins:  {stats['wins']:,}")
        print(f"  New draws: {stats['draws']:,}")


if __name__ == '__main__':
    main()
