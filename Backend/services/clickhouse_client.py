"""
ClickHouse client singleton for the KYS analytics pipeline.
All writes happen inside Celery tasks, never in API handlers.
API reads go through Redis first, ClickHouse only on cache miss.
"""
import os
import clickhouse_connect

_client = None
CH_DATABASE = os.environ.get('CLICKHOUSE_DATABASE', 'kys')


def get_clickhouse_client():
    """Return a singleton ClickHouse client."""
    global _client
    if _client is None:
        _client = clickhouse_connect.get_client(
            host=os.environ.get('CLICKHOUSE_HOST', 'localhost'),
            port=int(os.environ.get('CLICKHOUSE_PORT', 8443)),
            username=os.environ.get('CLICKHOUSE_USER', 'default'),
            password=os.environ.get('CLICKHOUSE_PASSWORD', ''),
            database=CH_DATABASE,
            secure=os.environ.get('CLICKHOUSE_SECURE', 'true').lower() == 'true',
            verify=True,
            compress=True,
            connect_timeout=10,
            send_receive_timeout=60,
        )
    return _client


def _dicts_to_rows(rows: list[dict]) -> tuple[list[list], list[str]]:
    """Convert list of dicts to (data, column_names) for clickhouse-connect insert()."""
    columns = list(rows[0].keys())
    data = [[row[col] for col in columns] for row in rows]
    return data, columns


def insert_token_scans(rows: list[dict]):
    """Bulk insert token scan records."""
    if not rows:
        return
    ch = get_clickhouse_client()
    data, columns = _dicts_to_rows(rows)
    ch.insert(table='token_scans', data=data, database=CH_DATABASE, column_names=columns)


def insert_wallet_token_stats(rows: list[dict]):
    """Bulk insert wallet-token stats. Fires mv_wallet_aggregate materialized view."""
    if not rows:
        return
    ch = get_clickhouse_client()
    data, columns = _dicts_to_rows(rows)
    ch.insert(table='wallet_token_stats', data=data, database=CH_DATABASE, column_names=columns)


def insert_weekly_snapshots(rows: list[dict]):
    """Bulk insert weekly snapshot rows."""
    if not rows:
        return
    ch = get_clickhouse_client()
    data, columns = _dicts_to_rows(rows)
    ch.insert(table='wallet_weekly_snapshots', data=data, database=CH_DATABASE, column_names=columns)


def insert_leaderboard_results(rows: list[dict]):
    """Bulk insert leaderboard result rows."""
    if not rows:
        return
    ch = get_clickhouse_client()
    data, columns = _dicts_to_rows(rows)
    ch.insert(table='leaderboard_results', data=data, database=CH_DATABASE, column_names=columns)


def get_wallet_stats(wallet_address: str) -> dict | None:
    """Read deduplicated aggregate stats for a wallet."""
    ch = get_clickhouse_client()
    result = ch.query(
        "SELECT * FROM wallet_aggregate_stats FINAL WHERE wallet_address = {addr:String}",
        parameters={'addr': wallet_address}
    )
    return result.first_row if result.result_rows else None


def get_wallet_token_stats_for_token(wallet_address: str, token_address: str) -> dict | None:
    """Read a specific wallet-token stat row."""
    ch = get_clickhouse_client()
    result = ch.query(
        """SELECT * FROM wallet_token_stats FINAL
           WHERE wallet_address = {wallet:String}
             AND token_address = {token:String}""",
        parameters={'wallet': wallet_address, 'token': token_address}
    )
    return result.first_row if result.result_rows else None


def query_top20_for_tokens(token_list: list[str]) -> list:
    """Top 20 wallets for a user-selected set of tokens (Section 8.1)."""
    ch = get_clickhouse_client()
    result = ch.query(
        """SELECT
            wallet_address,
            count(DISTINCT token_address) AS tokens_hit,
            avg(avg_entry_to_ath_mult) AS avg_entry_to_ath_mult,
            avg(total_roi_mult) AS avg_roi_mult,
            greatest(0, 100 - (
                stddevPop(entry_price_to_launch_mult)
                / nullIf(avg(entry_price_to_launch_mult), 0)
            ) * 100) AS consistency_score,
            (
                least(1000, log(1 + avg(avg_entry_to_ath_mult)) * 100) * 0.60 +
                least(1000, log(1 + avg(total_roi_mult)) * 100) * 0.30 +
                greatest(0, 100 - (
                    stddevPop(entry_price_to_launch_mult)
                    / nullIf(avg(entry_price_to_launch_mult), 0)
                ) * 100) * 0.10
            ) AS professional_score
        FROM wallet_token_stats FINAL
        WHERE token_address IN ({token_list:Array(String)})
          AND qualifies = 1
        GROUP BY wallet_address
        HAVING tokens_hit >= 1
        ORDER BY professional_score DESC
        LIMIT 20""",
        parameters={'token_list': token_list}
    )
    return result.named_results()


def query_elite_100() -> list:
    """Elite 100 wallets across ALL tokens (Section 8.2)."""
    ch = get_clickhouse_client()
    result = ch.query(
        """SELECT
            wallet_address,
            professional_score,
            tier,
            avg_entry_to_ath_mult,
            avg_roi_mult,
            consistency_score,
            tokens_qualified,
            win_rate,
            total_pnl_usd,
            last_active_at
        FROM wallet_aggregate_stats FINAL
        WHERE tokens_qualified >= 1
        ORDER BY professional_score DESC
        LIMIT 100"""
    )
    return result.named_results()
