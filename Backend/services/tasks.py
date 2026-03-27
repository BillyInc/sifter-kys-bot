"""
Celery Scheduled Tasks - Production Cron Jobs
These run on Celery Beat scheduler (time-based, recurring)
For on-demand analysis workers, see worker_tasks.py (RQ)

Tasks:
  daily_stats_refresh          — daily 3am UTC
  weekly_rerank_all            — Sunday 4am UTC
  four_week_degradation_check  — 1st & 29th of month 5am UTC
  refresh_elite_100            — every hour (:00)
  refresh_community_top_100    — every hour (:15)
  flush_redis_to_duckdb        — every hour (:30)
  invalidate_stale_ath_caches  — every hour (:45)  NEW
  purge_stale_analysis_cache   — one-time / on-demand  NEW
  send_telegram_alert_async    — on-demand (queued by wallet monitor)
"""
from celery_app import celery
from datetime import datetime, date, timedelta
import json
import os
import traceback

import redis as redis_lib


# =============================================================================
# DAILY STATS REFRESH
# =============================================================================

@celery.task(name='tasks.daily_stats_refresh')
def daily_stats_refresh():
    """
    Daily stats refresh at 3am UTC.
    Reads aggregate stats from ClickHouse and syncs them to Supabase wallet_watchlist.

    Fields synced (per architecture doc section 10):
        professional_score, consistency_score, win_rate, roi_30d,
        runners_30d, avg_roi_mult, avg_entry_to_ath, tokens_qualified,
        last_updated
    Note: `tier` is only written by weekly_rerank_all — not touched here.
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Daily Stats Refresh - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        from services.clickhouse_client import get_clickhouse_client

        supabase = get_supabase_client()
        ch = get_clickhouse_client()

        # 1. Get all watchlisted wallet addresses from Supabase
        print("[DAILY] Fetching watchlisted wallets from Supabase...")
        watchlist_resp = (
            supabase.schema(SCHEMA_NAME)
            .table('wallet_watchlist')
            .select('wallet_address')
            .execute()
        )
        if not watchlist_resp.data:
            print("[DAILY] No wallets in watchlist — nothing to refresh.")
            return {
                'status':    'success',
                'wallets':   0,
                'synced':    0,
                'timestamp': datetime.utcnow().isoformat()
            }

        addresses = list({row['wallet_address'] for row in watchlist_resp.data})
        print(f"[DAILY] Found {len(addresses)} unique wallet addresses")

        # 2. Bulk read latest aggregate stats from ClickHouse
        print("[DAILY] Querying ClickHouse wallet_aggregate_stats FINAL...")
        result = ch.query(
            """SELECT
                wallet_address,
                professional_score,
                consistency_score,
                win_rate,
                total_roi_pct,
                tokens_qualified,
                avg_roi_mult,
                avg_entry_to_ath_mult
            FROM kys.wallet_aggregate_stats FINAL
            WHERE wallet_address IN {addrs:Array(String)}""",
            parameters={'addrs': addresses}
        )
        ch_rows = result.named_results()
        stats_by_wallet = {r['wallet_address']: r for r in ch_rows}
        print(f"[DAILY] Got stats for {len(stats_by_wallet)} wallets from ClickHouse")

        # 3. Batch upsert computed fields back to Supabase
        synced = 0
        errors = 0
        now_iso = datetime.utcnow().isoformat()

        BATCH_SIZE = 50
        for i in range(0, len(addresses), BATCH_SIZE):
            batch = addresses[i:i + BATCH_SIZE]
            for addr in batch:
                stats = stats_by_wallet.get(addr)
                if not stats:
                    continue
                try:
                    supabase.schema(SCHEMA_NAME).table('wallet_watchlist').update({
                        'professional_score': float(stats.get('professional_score', 0)),
                        'consistency_score':  float(stats.get('consistency_score', 0)),
                        'win_rate':           float(stats.get('win_rate', 0)),
                        'roi_30d':            float(stats.get('total_roi_pct', 0)),
                        'runners_30d':        int(stats.get('tokens_qualified', 0)),
                        'avg_roi_mult':       float(stats.get('avg_roi_mult', 0)),
                        'avg_entry_to_ath':   float(stats.get('avg_entry_to_ath_mult', 0)),
                        'tokens_qualified':   int(stats.get('tokens_qualified', 0)),
                        'last_updated':       now_iso,
                    }).eq('wallet_address', addr).execute()
                    synced += 1
                except Exception as e:
                    errors += 1
                    print(f"[DAILY] Error updating {addr[:12]}...: {e}")

        print(f"\n[CELERY TASK] Daily refresh complete")
        print(f"  Wallets found:   {len(addresses)}")
        print(f"  CH stats loaded: {len(stats_by_wallet)}")
        print(f"  Synced:          {synced}")
        print(f"  Errors:          {errors}")
        return {
            'status':    'success',
            'wallets':   len(addresses),
            'ch_loaded': len(stats_by_wallet),
            'synced':    synced,
            'errors':    errors,
            'timestamp': now_iso
        }

    except Exception as e:
        print(f"\n[CELERY TASK] Daily refresh failed: {e}")
        traceback.print_exc()
        return {
            'status':    'error',
            'error':     str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


# =============================================================================
# WEEKLY RERANK
# =============================================================================

@celery.task(name='tasks.weekly_rerank_all')
def weekly_rerank_all():
    """
    Weekly rerank on Sunday at 4am UTC.
    1. Reads ALL wallets from ClickHouse ordered by professional_score DESC
    2. Assigns tiers: S (top 5%), A (6-20%), B (21-50%), C (bottom 50%)
    3. Writes weekly snapshot to ClickHouse wallet_weekly_snapshots
    4. Writes Elite 100 to ClickHouse leaderboard_results
    5. Caches Elite 100 in Redis (7-day TTL)
    6. Syncs tiers back to Supabase wallet_watchlist
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Weekly Rerank - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        from services.clickhouse_client import (
            get_clickhouse_client, insert_weekly_snapshots,
            insert_leaderboard_results, query_elite_100,
        )

        supabase = get_supabase_client()
        ch = get_clickhouse_client()

        # ----------------------------------------------------------------
        # 1. Read ALL wallets ordered by professional_score DESC
        # ----------------------------------------------------------------
        print("[RERANK] Querying all wallets from ClickHouse...")
        result = ch.query(
            """SELECT
                wallet_address,
                professional_score,
                consistency_score,
                win_rate,
                total_roi_pct,
                tokens_qualified,
                avg_roi_mult,
                avg_entry_to_ath_mult,
                total_pnl_usd,
                last_active_at
            FROM kys.wallet_aggregate_stats FINAL
            ORDER BY professional_score DESC"""
        )
        all_wallets = result.named_results()
        total = len(all_wallets)
        print(f"[RERANK] Loaded {total} wallets from ClickHouse")

        if total == 0:
            print("[RERANK] No wallets found — nothing to rank.")
            return {
                'status':    'success',
                'wallets':   0,
                'timestamp': datetime.utcnow().isoformat()
            }

        # ----------------------------------------------------------------
        # 2. Assign tiers by percentile position
        # ----------------------------------------------------------------
        print("[RERANK] Assigning tiers...")
        today = date.today()
        snapshot_rows = []
        tier_map = {}  # wallet_address -> tier

        for rank_idx, wallet in enumerate(all_wallets):
            pct = (rank_idx + 1) / total  # percentile position (1-based)
            if pct <= 0.05:
                tier = 'S'
            elif pct <= 0.20:
                tier = 'A'
            elif pct <= 0.50:
                tier = 'B'
            else:
                tier = 'C'

            addr = wallet['wallet_address']
            tier_map[addr] = tier

            # Match wallet_weekly_snapshots schema columns exactly
            week_start = today - timedelta(days=today.weekday())  # snap to Monday
            snapshot_rows.append({
                'wallet_address':     addr,
                'week_start':         week_start,
                'tokens_qualified':   int(wallet.get('tokens_qualified', 0)),
                'wins':               0,  # not available in aggregate stats
                'losses':             0,
                'win_rate':           float(wallet.get('win_rate', 0)),
                'avg_roi_mult':       float(wallet.get('avg_roi_mult', 0)),
                'professional_score': float(wallet.get('professional_score', 0)),
                'tier':               tier,
                'consistency_score':  float(wallet.get('consistency_score', 0)),
                'position_in_elite':  rank_idx + 1 if rank_idx < 100 else 0,
            })

        tier_counts = {}
        for t in tier_map.values():
            tier_counts[t] = tier_counts.get(t, 0) + 1
        print(f"[RERANK] Tier distribution: {tier_counts}")

        # ----------------------------------------------------------------
        # 3. Write weekly snapshots to ClickHouse
        # ----------------------------------------------------------------
        print(f"[RERANK] Writing {len(snapshot_rows)} weekly snapshots to ClickHouse...")
        insert_weekly_snapshots(snapshot_rows)

        # ----------------------------------------------------------------
        # 4. Write Elite 100 to ClickHouse leaderboard_results
        # ----------------------------------------------------------------
        # Match leaderboard_results schema columns exactly
        elite_100 = all_wallets[:100]
        leaderboard_rows = []
        for rank_idx, wallet in enumerate(elite_100):
            addr = wallet['wallet_address']
            leaderboard_rows.append({
                'result_key':           'elite100',
                'leaderboard_type':     'elite100',
                'user_id':              '',
                'token_set':            '[]',
                'rank':                 rank_idx + 1,
                'wallet_address':       addr,
                'professional_score':   float(wallet.get('professional_score', 0)),
                'tier':                 tier_map[addr],
                'avg_entry_to_ath_mult': float(wallet.get('avg_entry_to_ath_mult', 0)),
                'avg_roi_mult':         float(wallet.get('avg_roi_mult', 0)),
                'consistency_score':    float(wallet.get('consistency_score', 0)),
                'tokens_qualified':     int(wallet.get('tokens_qualified', 0)),
                'win_rate':             float(wallet.get('win_rate', 0)),
                'total_pnl_usd':        float(wallet.get('total_pnl_usd', 0)),
                'expires_at':           datetime.utcnow() + timedelta(days=7),
            })
        print(f"[RERANK] Writing {len(leaderboard_rows)} Elite 100 rows to ClickHouse...")
        insert_leaderboard_results(leaderboard_rows)

        # ----------------------------------------------------------------
        # 5. Cache Elite 100 in Redis (7-day TTL)
        # ----------------------------------------------------------------
        print("[RERANK] Caching Elite 100 in Redis...")
        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        r = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=10)

        elite_payload = []
        for row in leaderboard_rows:
            serializable = dict(row)
            # Convert datetime to string for JSON serialization
            if 'expires_at' in serializable:
                serializable['expires_at'] = str(serializable['expires_at'])
            elite_payload.append(serializable)

        r.set('kys:elite100', json.dumps(elite_payload), ex=604800)
        print("[RERANK] Redis kys:elite100 cached with 7-day TTL")

        # ----------------------------------------------------------------
        # 6. Sync tiers to Supabase wallet_watchlist
        # ----------------------------------------------------------------
        print("[RERANK] Syncing tiers to Supabase wallet_watchlist...")
        synced = 0
        errors = 0
        for addr, tier in tier_map.items():
            try:
                supabase.schema(SCHEMA_NAME).table('wallet_watchlist').update({
                    'tier':         tier,
                    'last_updated': datetime.utcnow().isoformat(),
                }).eq('wallet_address', addr).execute()
                synced += 1
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"[RERANK] Error syncing tier for {addr[:12]}...: {e}")

        print(f"\n[CELERY TASK] Weekly rerank complete")
        print(f"  Total wallets:    {total}")
        print(f"  Snapshots:        {len(snapshot_rows)}")
        print(f"  Elite 100:        {len(leaderboard_rows)}")
        print(f"  Tiers synced:     {synced}")
        print(f"  Errors:           {errors}")
        return {
            'status':      'success',
            'total':       total,
            'snapshots':   len(snapshot_rows),
            'elite_100':   len(leaderboard_rows),
            'tiers':       tier_counts,
            'synced':      synced,
            'errors':      errors,
            'timestamp':   datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[CELERY TASK] Weekly rerank failed: {e}")
        traceback.print_exc()
        return {
            'status':    'error',
            'error':     str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


# =============================================================================
# 4-WEEK DEGRADATION CHECK
# =============================================================================

@celery.task(name='tasks.four_week_degradation_check')
def four_week_degradation_check():
    """
    4-week degradation check (1st & 29th of month at 5am UTC).
    Queries wallet_weekly_snapshots for wallets with 4+ weeks of data
    in the last 28 days, compares first vs last snapshot, and flags
    degraded wallets with status='critical' in Supabase.

    Degradation thresholds (architecture doc section 11):
        - ROI drop > 200% (half of 400% floor equivalent)
        - Win rate drop >= 20 percentage points
        - Elite position drop >= 5 positions
        - Consistency drop >= 20 points
        - Win rate dropped to 0
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] 4-Week Degradation Check - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        from services.clickhouse_client import get_clickhouse_client

        supabase = get_supabase_client()
        ch = get_clickhouse_client()

        cutoff_date = date.today() - timedelta(days=28)

        # ----------------------------------------------------------------
        # 1. Query wallets with 4+ snapshots in the last 28 days
        #    Use groupArray() to get ordered arrays per wallet
        # ----------------------------------------------------------------
        print(f"[DEGRADATION] Querying snapshots since {cutoff_date}...")
        result = ch.query(
            """SELECT
                wallet_address,
                groupArray(week_start)         AS dates,
                groupArray(avg_roi_mult)       AS roi_arr,
                groupArray(win_rate)           AS wr_arr,
                groupArray(position_in_elite)  AS rank_arr,
                groupArray(consistency_score)  AS cs_arr
            FROM (
                SELECT *
                FROM kys.wallet_weekly_snapshots FINAL
                WHERE week_start >= {cutoff:Date}
                ORDER BY wallet_address, week_start ASC
            )
            GROUP BY wallet_address
            HAVING length(dates) >= 4""",
            parameters={'cutoff': cutoff_date}
        )
        wallets = result.named_results()
        print(f"[DEGRADATION] Found {len(wallets)} wallets with 4+ weeks of data")

        # ----------------------------------------------------------------
        # 2. Compare first vs last snapshot and flag degraded wallets
        # ----------------------------------------------------------------
        degraded = []
        for w in wallets:
            addr = w['wallet_address']
            reasons = []

            roi_first = float(w['roi_arr'][0])
            roi_last  = float(w['roi_arr'][-1])
            wr_first  = float(w['wr_arr'][0])
            wr_last   = float(w['wr_arr'][-1])
            rank_first = int(w['rank_arr'][0])
            rank_last  = int(w['rank_arr'][-1])
            cs_first  = float(w['cs_arr'][0])
            cs_last   = float(w['cs_arr'][-1])

            roi_drop = roi_first - roi_last
            wr_drop  = wr_first - wr_last
            cs_drop  = cs_first - cs_last

            # ROI drop > 200%
            if roi_drop > 200:
                reasons.append(f"ROI dropped {roi_drop:.1f}% (>{200}% threshold)")

            # Win rate drop >= 20 percentage points
            if wr_drop >= 20:
                reasons.append(f"Win rate dropped {wr_drop:.1f}pp (>={20}pp threshold)")

            # Win rate dropped to 0
            if wr_last == 0 and wr_first > 0:
                reasons.append("Win rate dropped to 0%")

            # Elite position drop >= 5 (only if both are ranked)
            if rank_first > 0 and rank_last > 0:
                rank_drop = rank_last - rank_first  # higher rank number = worse
                if rank_drop >= 5:
                    reasons.append(f"Elite rank dropped {rank_drop} positions")

            # Consistency drop >= 20 points
            if cs_drop >= 20:
                reasons.append(f"Consistency dropped {cs_drop:.1f}pts (>={20}pt threshold)")

            if reasons:
                degraded.append({
                    'wallet_address': addr,
                    'reasons':        reasons,
                })

        print(f"[DEGRADATION] {len(degraded)} wallets flagged as degraded")

        # ----------------------------------------------------------------
        # 3. Flag degraded wallets in Supabase
        # ----------------------------------------------------------------
        flagged = 0
        errors = 0
        for entry in degraded:
            try:
                supabase.schema(SCHEMA_NAME).table('wallet_watchlist').update({
                    'status':       'critical',
                    'last_updated': datetime.utcnow().isoformat(),
                }).eq('wallet_address', entry['wallet_address']).execute()
                flagged += 1
                if flagged <= 10:
                    print(f"  Flagged {entry['wallet_address'][:12]}...: "
                          f"{'; '.join(entry['reasons'])}")
            except Exception as e:
                errors += 1
                print(f"[DEGRADATION] Error flagging {entry['wallet_address'][:12]}...: {e}")

        print(f"\n[CELERY TASK] 4-week degradation check complete")
        print(f"  Wallets checked: {len(wallets)}")
        print(f"  Degraded:        {len(degraded)}")
        print(f"  Flagged:         {flagged}")
        print(f"  Errors:          {errors}")
        return {
            'status':    'success',
            'checked':   len(wallets),
            'degraded':  len(degraded),
            'flagged':   flagged,
            'errors':    errors,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[CELERY TASK] 4-week check failed: {e}")
        traceback.print_exc()
        return {
            'status':    'error',
            'error':     str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


# =============================================================================
# ELITE 100 REFRESH
# =============================================================================

@celery.task(name='tasks.refresh_elite_100')
def refresh_elite_100():
    """
    Refresh Elite 100 rankings every hour (top of hour).
    Generates top 100 performing wallets across all metrics.
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Elite 100 Refresh - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        from services.elite_100_manager import get_elite_manager
        manager = get_elite_manager()

        score_wallets   = manager.generate_elite_100('score')
        roi_wallets     = manager.generate_elite_100('roi')
        runners_wallets = manager.generate_elite_100('runners')

        print(f"\n[CELERY TASK] Elite 100 refresh complete")
        print(f"  - By Score:   {len(score_wallets)} wallets")
        print(f"  - By ROI:     {len(roi_wallets)} wallets")
        print(f"  - By Runners: {len(runners_wallets)} wallets")

        return {
            'status': 'success',
            'counts': {
                'score':   len(score_wallets),
                'roi':     len(roi_wallets),
                'runners': len(runners_wallets)
            },
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[CELERY TASK] Elite 100 refresh failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status':    'error',
            'error':     str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


# =============================================================================
# COMMUNITY TOP 100 REFRESH
# =============================================================================

@celery.task(name='tasks.refresh_community_top_100')
def refresh_community_top_100():
    """
    Refresh Community Top 100 every hour (:15 past).
    Shows most-added wallets this week.
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Community Top 100 Refresh - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        from services.elite_100_manager import get_elite_manager
        manager = get_elite_manager()

        wallets = manager.generate_community_top_100()

        print(f"\n[CELERY TASK] Community Top 100 refresh complete: {len(wallets)} wallets")
        return {
            'status':    'success',
            'count':     len(wallets),
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[CELERY TASK] Community Top 100 refresh failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status':    'error',
            'error':     str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


# =============================================================================
# REDIS → DUCKDB FLUSH
# =============================================================================

@celery.task(name='tasks.flush_redis_to_duckdb')
def flush_redis_to_duckdb():
    """
    Flush Redis hot cache → DuckDB cold storage (every hour, :30 past).

    Strategy:
    - Workers write to Redis only (read_only=True DuckDB)
    - This task runs on Celery Beat every hour
    - It uses the Flask-side analyzer (read_only=False) to read Redis
      and write everything into DuckDB for persistence
    - On Redis restart, DuckDB automatically refills Redis on cache misses

    Cache tables flushed:
      wallet_token_cache   (PnL + entry data)    [pnl:{wallet}:{token}]
      wallet_runner_cache  (runner history)       [runners:{wallet}]
      token_runner_cache   (is-runner check)      [token_runner:{token}]
      token_ath_cache      (ATH data)             [token_ath:{token}]
      token_info_cache     (token metadata)       [token_info:{token}]
      token_security_cache (security checks)      [token_security:{token}]
      token_launch_cache   (launch price)         [launch_price:{token}]
    """
    print(f"\n{'='*80}")
    print(f"[FLUSH TASK] Redis → DuckDB flush starting - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        import redis as redis_lib
        import json
        import duckdb
        import time

        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        r = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=10)

        duckdb_path = 'wallet_analytics.duckdb'
        con = duckdb.connect(duckdb_path)

        stats = {
            'pnl':            0,
            'runners':        0,
            'token_runner':   0,
            'token_ath':      0,
            'token_info':     0,
            'token_security': 0,
            'launch_price':   0,
            'errors':         0
        }

        now = time.time()

        # ----------------------------------------------------------------
        # 1. Flush PnL cache: pnl:{wallet}:{token}
        # ----------------------------------------------------------------
        print(f"[FLUSH] Scanning pnl:* keys...")
        pnl_keys = list(r.scan_iter("pnl:*"))
        print(f"[FLUSH] Found {len(pnl_keys)} PnL keys")

        for key in pnl_keys:
            try:
                raw = r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)

                parts = key.split(':', 2)
                if len(parts) != 3:
                    continue
                _, wallet, token = parts

                con.execute("""
                    INSERT OR REPLACE INTO wallet_token_cache
                    (wallet, token, realized, unrealized, total_invested,
                     entry_price, first_buy_time, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    wallet, token,
                    data.get('realized', 0),
                    data.get('unrealized', 0),
                    data.get('total_invested', 0),
                    data.get('entry_price'),
                    data.get('first_buy_time'),
                    now
                ])
                stats['pnl'] += 1
            except Exception as e:
                stats['errors'] += 1
                print(f"[FLUSH] PnL error for {key}: {e}")

        # ----------------------------------------------------------------
        # 2. Flush runner history cache: runners:{wallet}
        # ----------------------------------------------------------------
        print(f"[FLUSH] Scanning runners:* keys...")
        runner_keys = list(r.scan_iter("runners:*"))
        print(f"[FLUSH] Found {len(runner_keys)} runner keys")

        for key in runner_keys:
            try:
                raw = r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)

                wallet = key.split(':', 1)[1]

                con.execute("""
                    INSERT OR REPLACE INTO wallet_runner_cache
                    (wallet, other_runners, stats, last_updated)
                    VALUES (?, ?, ?, ?)
                """, [
                    wallet,
                    json.dumps(data.get('other_runners', [])),
                    json.dumps(data.get('stats', {})),
                    now
                ])
                stats['runners'] += 1
            except Exception as e:
                stats['errors'] += 1
                print(f"[FLUSH] Runner error for {key}: {e}")

        # ----------------------------------------------------------------
        # 3. Flush token runner check cache: token_runner:{token}
        # ----------------------------------------------------------------
        print(f"[FLUSH] Scanning token_runner:* keys...")
        token_runner_keys = list(r.scan_iter("token_runner:*"))
        print(f"[FLUSH] Found {len(token_runner_keys)} token_runner keys")

        for key in token_runner_keys:
            try:
                raw = r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)

                token = key.split(':', 1)[1]

                con.execute("""
                    INSERT OR REPLACE INTO token_runner_cache
                    (token, runner_info, last_updated)
                    VALUES (?, ?, ?)
                """, [token, json.dumps(data), now])
                stats['token_runner'] += 1
            except Exception as e:
                stats['errors'] += 1
                print(f"[FLUSH] Token runner error for {key}: {e}")

        # ----------------------------------------------------------------
        # 4. Flush ATH cache: token_ath:{token}
        # ----------------------------------------------------------------
        print(f"[FLUSH] Scanning token_ath:* keys...")
        ath_keys = list(r.scan_iter("token_ath:*"))
        print(f"[FLUSH] Found {len(ath_keys)} ATH keys")

        for key in ath_keys:
            try:
                raw = r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)

                token = key.split(':', 1)[1]

                con.execute("""
                    INSERT OR REPLACE INTO token_ath_cache
                    (token, highest_price, timestamp, last_updated)
                    VALUES (?, ?, ?, ?)
                """, [
                    token,
                    data.get('highest_price', 0),
                    data.get('timestamp', 0),
                    now
                ])
                stats['token_ath'] += 1
            except Exception as e:
                stats['errors'] += 1
                print(f"[FLUSH] ATH error for {key}: {e}")

        # ----------------------------------------------------------------
        # 5. Flush token info cache: token_info:{token}
        # ----------------------------------------------------------------
        print(f"[FLUSH] Scanning token_info:* keys...")
        info_keys = list(r.scan_iter("token_info:*"))
        print(f"[FLUSH] Found {len(info_keys)} token_info keys")

        for key in info_keys:
            try:
                raw = r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)

                token = key.split(':', 1)[1]

                con.execute("""
                    INSERT OR REPLACE INTO token_info_cache
                    (token, symbol, name, liquidity, volume_24h,
                     price, holders, age_days, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    token,
                    data.get('symbol', 'UNKNOWN'),
                    data.get('name', 'Unknown'),
                    data.get('liquidity', 0),
                    data.get('volume_24h', 0),
                    data.get('price', 0),
                    data.get('holders', 0),
                    data.get('age_days', 0),
                    now
                ])
                stats['token_info'] += 1
            except Exception as e:
                stats['errors'] += 1
                print(f"[FLUSH] Token info error for {key}: {e}")

        # ----------------------------------------------------------------
        # 6. Flush security cache: token_security:{token}
        # ----------------------------------------------------------------
        print(f"[FLUSH] Scanning token_security:* keys...")
        security_keys = list(r.scan_iter("token_security:*"))
        print(f"[FLUSH] Found {len(security_keys)} security keys")

        for key in security_keys:
            try:
                raw = r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)

                token = key.split(':', 1)[1]

                con.execute("""
                    INSERT OR REPLACE INTO token_security_cache
                    (token, security_data, last_updated)
                    VALUES (?, ?, ?)
                """, [token, json.dumps(data), now])
                stats['token_security'] += 1
            except Exception as e:
                stats['errors'] += 1
                print(f"[FLUSH] Security error for {key}: {e}")

        # ----------------------------------------------------------------
        # 7. Flush launch price cache: launch_price:{token}
        # ----------------------------------------------------------------
        print(f"[FLUSH] Scanning launch_price:* keys...")
        launch_keys = list(r.scan_iter("launch_price:*"))
        print(f"[FLUSH] Found {len(launch_keys)} launch_price keys")

        for key in launch_keys:
            try:
                raw = r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)

                token = key.split(':', 1)[1]
                price = data.get('price')
                if price is None:
                    continue

                con.execute("""
                    INSERT OR REPLACE INTO token_launch_cache
                    (token, launch_price, last_updated)
                    VALUES (?, ?, ?)
                """, [token, price, now])
                stats['launch_price'] += 1
            except Exception as e:
                stats['errors'] += 1
                print(f"[FLUSH] Launch price error for {key}: {e}")

        con.close()

        total_flushed = sum(v for k, v in stats.items() if k != 'errors')

        print(f"\n[FLUSH TASK] ✅ Complete - {datetime.utcnow().isoformat()}")
        print(f"  PnL records:       {stats['pnl']}")
        print(f"  Runner histories:  {stats['runners']}")
        print(f"  Token runners:     {stats['token_runner']}")
        print(f"  ATH records:       {stats['token_ath']}")
        print(f"  Token info:        {stats['token_info']}")
        print(f"  Security checks:   {stats['token_security']}")
        print(f"  Launch prices:     {stats['launch_price']}")
        print(f"  Total flushed:     {total_flushed}")
        print(f"  Errors:            {stats['errors']}")

        return {
            'status':        'success',
            'stats':         stats,
            'total_flushed': total_flushed,
            'timestamp':     datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[FLUSH TASK] ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status':    'error',
            'error':     str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


# =============================================================================
# ATH CACHE INVALIDATION
# =============================================================================

@celery.task(name='tasks.invalidate_stale_ath_caches')
def invalidate_stale_ath_caches():
    """
    Hourly ATH invalidation (:45 past every hour).

    For every cached token result in Redis:
      1. Pull the current ATH from token_ath:{address}
      2. Pull the ATH baked into the cached result (stored per wallet as ath_price)
      3. If current ATH > cached ATH * 1.10 (moved >10%):
           - Delete the Redis cache:token:{address} key
           - Mark the Supabase analysis_jobs row as 'stale'
         so the next search triggers a fresh pipeline with correct scores.

    Scores affected by a stale ATH:
      distance_to_ath_pct, entry_to_ath_multiplier, professional_score
    """
    print(f"\n{'='*80}")
    print(f"[ATH INVALIDATION] Starting - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        import redis as redis_lib
        import json

        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        r = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=10)

        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()

        stats = {
            'scanned':     0,
            'invalidated': 0,
            'no_ath_data': 0,
            'up_to_date':  0,
            'errors':      0,
        }

        cache_keys = list(r.scan_iter("cache:token:*"))
        print(f"[ATH INVALIDATION] Found {len(cache_keys)} cached token results to check")

        for key in cache_keys:
            try:
                stats['scanned'] += 1
                token_address = key.split('cache:token:', 1)[1]

                # Current ATH from Redis (written by pipeline / analyzer)
                current_ath_raw = r.get(f"token_ath:{token_address}")
                if not current_ath_raw:
                    stats['no_ath_data'] += 1
                    continue

                current_ath_price = json.loads(current_ath_raw).get('highest_price', 0)
                if not current_ath_price:
                    stats['no_ath_data'] += 1
                    continue

                # ATH baked into the cached result
                cached_raw = r.get(key)
                if not cached_raw:
                    continue

                cached_result  = json.loads(cached_raw)
                cached_wallets = cached_result.get('wallets', [])
                cached_ath     = next(
                    (w.get('ath_price', 0) for w in cached_wallets if w.get('ath_price')),
                    0
                )

                if cached_ath <= 0:
                    stats['no_ath_data'] += 1
                    continue

                ath_move_pct = ((current_ath_price / cached_ath) - 1) * 100

                if current_ath_price > cached_ath * 1.10:
                    # Delete stale Redis key
                    r.delete(key)

                    # Mark Supabase row stale so the fallback path doesn't serve it
                    try:
                        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                            'status': 'stale',
                            'phase':  'ath_invalidated'
                        }).eq('token_address', token_address).eq('status', 'completed').execute()
                    except Exception as se:
                        print(f"  ⚠️ Supabase update failed for {token_address[:8]}: {se}")

                    stats['invalidated'] += 1
                    print(f"  🗑️  Invalidated {token_address[:8]}... "
                          f"ATH moved +{ath_move_pct:.1f}% "
                          f"(${cached_ath:.8f} → ${current_ath_price:.8f})")
                else:
                    stats['up_to_date'] += 1

            except Exception as e:
                stats['errors'] += 1
                print(f"  ⚠️ Error processing {key}: {e}")

        print(f"\n[ATH INVALIDATION] ✅ Complete - {datetime.utcnow().isoformat()}")
        print(f"  Scanned:     {stats['scanned']}")
        print(f"  Invalidated: {stats['invalidated']}")
        print(f"  Up to date:  {stats['up_to_date']}")
        print(f"  No ATH data: {stats['no_ath_data']}")
        print(f"  Errors:      {stats['errors']}")

        return {
            'status':    'success',
            'stats':     stats,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[ATH INVALIDATION] ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status':    'error',
            'error':     str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


# =============================================================================
# STALE CACHE PURGE (ONE-TIME / ON-DEMAND)
# =============================================================================

@celery.task(name='tasks.purge_stale_analysis_cache')
def purge_stale_analysis_cache():
    """
    ONE-TIME TASK — run once after deploying the scoring model change
    (realized ROI → total ROI as the 30% weight in calculate_wallet_relative_score).

    What it does:
      1. Deletes all cache:token:* keys from Redis — no stale results served
      2. Marks all completed analysis_jobs rows in Supabase as 'stale' so the
         Supabase fallback path re-runs the pipeline instead of returning
         incorrectly-scored results
      3. Leaves the rows themselves intact for audit/history

    After this runs, every token search triggers a fresh pipeline that scores
    wallets using the corrected weights (60% entry, 30% total ROI, 10% realized).
    New results are cached normally and served on subsequent searches.

    To trigger:
        celery -A celery_app call tasks.purge_stale_analysis_cache

    Or via Supabase SQL editor (equivalent manual version):
        UPDATE sifter_dev.analysis_jobs
        SET status = 'stale', phase = 'scoring_model_updated'
        WHERE status = 'completed';
    """
    print(f"\n{'='*80}")
    print(f"[CACHE PURGE] Starting stale cache purge - {datetime.utcnow().isoformat()}")
    print(f"  Reason: scoring model changed (realized ROI → total ROI as 30% weight)")
    print(f"{'='*80}\n")

    try:
        import redis as redis_lib

        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        r = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=10)

        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()

        stats = {
            'redis_keys_deleted':   0,
            'supabase_rows_staled': 0,
            'errors':               0,
        }

        # ----------------------------------------------------------------
        # 1. Delete all cached token results from Redis
        # ----------------------------------------------------------------
        print(f"[CACHE PURGE] Scanning cache:token:* keys in Redis...")
        cache_keys = list(r.scan_iter("cache:token:*"))
        print(f"[CACHE PURGE] Found {len(cache_keys)} Redis cache keys to delete")

        if cache_keys:
            batch_size = 500
            for i in range(0, len(cache_keys), batch_size):
                batch = cache_keys[i:i + batch_size]
                try:
                    r.delete(*batch)
                    stats['redis_keys_deleted'] += len(batch)
                    print(f"  Deleted batch {i//batch_size + 1}: {len(batch)} keys")
                except Exception as e:
                    stats['errors'] += 1
                    print(f"  ⚠️ Batch delete error: {e}")

        print(f"\n[CACHE PURGE] ✓ Redis: deleted {stats['redis_keys_deleted']} cache keys")

        # ----------------------------------------------------------------
        # 2. Mark all completed analysis_jobs rows as 'stale' in Supabase
        # ----------------------------------------------------------------
        print(f"\n[CACHE PURGE] Marking completed Supabase cache rows as stale...")
        try:
            result = supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                'status': 'stale',
                'phase':  'scoring_model_updated'
            }).eq('status', 'completed').execute()

            affected = len(result.data) if result.data else 0
            stats['supabase_rows_staled'] = affected
            print(f"[CACHE PURGE] ✓ Supabase: marked {affected} rows as stale")

        except Exception as e:
            stats['errors'] += 1
            print(f"[CACHE PURGE] ⚠️ Supabase update failed: {e}")
            print(f"  Run manually in Supabase SQL editor:")
            print(f"    UPDATE sifter_dev.analysis_jobs")
            print(f"    SET status = 'stale', phase = 'scoring_model_updated'")
            print(f"    WHERE status = 'completed';")

        print(f"\n[CACHE PURGE] ✅ Complete - {datetime.utcnow().isoformat()}")
        print(f"  Redis keys deleted:    {stats['redis_keys_deleted']}")
        print(f"  Supabase rows staled:  {stats['supabase_rows_staled']}")
        print(f"  Errors:                {stats['errors']}")
        print(f"\n  Next search for any token will run a fresh pipeline")
        print(f"  and cache results with the correct total-ROI scoring.")

        return {
            'status':    'success',
            'stats':     stats,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[CACHE PURGE] ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status':    'error',
            'error':     str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


# =============================================================================
# TELEGRAM ALERT (ON-DEMAND, QUEUED BY WALLET MONITOR)
# =============================================================================

@celery.task(name='tasks.send_telegram_alert_async')
def send_telegram_alert_async(user_id: str, alert_type: str, alert_data: dict):
    """
    Async Telegram alert sender.
    Called by wallet monitor for background alert delivery.
    """
    try:
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            print(f"[TELEGRAM TASK] Notifier not configured")
            return {'status': 'skipped', 'reason': 'no_notifier'}

        from services.telegram_notifier import TelegramNotifier
        telegram_notifier = TelegramNotifier(bot_token)

        if alert_type == 'trade':
            from services.supabase_client import get_supabase_client, SCHEMA_NAME
            supabase = get_supabase_client()

            wallet_result = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select(
                'tier, consistency_score'
            ).eq('user_id', user_id).eq(
                'wallet_address', alert_data.get('wallet_address')
            ).limit(1).execute()

            wallet_info = wallet_result.data[0] if wallet_result.data else {
                'tier': 'C', 'consistency_score': 0
            }

            payload = {
                'wallet': {
                    'address':           alert_data.get('wallet_address', ''),
                    'tier':              wallet_info.get('tier', 'C'),
                    'consistency_score': wallet_info.get('consistency_score', 0)
                },
                'action': alert_data.get('side', 'buy'),
                'token': {
                    'address': alert_data.get('token_address', ''),
                    'symbol':  alert_data.get('token_ticker', 'UNKNOWN'),
                    'name':    alert_data.get('token_name', 'Unknown')
                },
                'trade': {
                    'amount_tokens': alert_data.get('token_amount', 0),
                    'amount_usd':    alert_data.get('usd_value', 0),
                    'price':         alert_data.get('price', 0),
                    'tx_hash':       alert_data.get('tx_hash', ''),
                    'dex':           alert_data.get('dex', 'unknown'),
                    'timestamp':     alert_data.get('block_time', 0)
                },
                'links': {
                    'solscan':     f"https://solscan.io/tx/{alert_data.get('tx_hash', '')}",
                    'birdeye':     f"https://birdeye.so/token/{alert_data.get('token_address', '')}",
                    'dexscreener': f"https://dexscreener.com/solana/{alert_data.get('token_address', '')}"
                }
            }

            telegram_notifier.send_wallet_alert(user_id, payload, alert_data.get('activity_id'))

        elif alert_type == 'multi_wallet':
            telegram_notifier.send_multi_wallet_signal_alert(user_id, alert_data)

        return {
            'status':     'sent',
            'user_id':    user_id,
            'alert_type': alert_type
        }

    except Exception as e:
        print(f"[TELEGRAM TASK] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error':  str(e)
        }