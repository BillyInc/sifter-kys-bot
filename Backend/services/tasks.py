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
  sync_elite_15_to_monitor     — every hour (:05)
  send_telegram_alert_async    — on-demand (queued by wallet monitor)
"""
import logging

from celery_app import celery
from datetime import datetime
import os

logger = logging.getLogger(__name__)


# =============================================================================
# DAILY STATS REFRESH
# =============================================================================

@celery.task(name='tasks.daily_stats_refresh')
def daily_stats_refresh():
    """
    Daily stats refresh at 3am UTC.
    Updates all watchlist wallet metrics.
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Daily Stats Refresh - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        from services.watchlist_stats_updater import get_updater
        updater = get_updater()

        result = updater.daily_stats_refresh()

        print(f"\n[CELERY TASK] Daily refresh complete: {result}")
        return {
            'status':    'success',
            'result':    result,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[CELERY TASK] Daily refresh failed: {e}")
        import traceback
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
    Reranks all user watchlists.
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Weekly Rerank - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        from services.watchlist_stats_updater import get_updater
        updater = get_updater()

        result = updater.weekly_rerank_all()

        print(f"\n[CELERY TASK] Weekly rerank complete: {result}")
        return {
            'status':    'success',
            'result':    result,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[CELERY TASK] Weekly rerank failed: {e}")
        import traceback
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
    4-week degradation check every 28 days at 5am UTC.
    Identifies wallets with declining performance over 4 weeks.
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] 4-Week Degradation Check - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        from services.watchlist_stats_updater import get_updater
        updater = get_updater()

        result = updater.four_week_degradation_check()

        print(f"\n[CELERY TASK] 4-week check complete: {result}")
        return {
            'status':    'success',
            'result':    result,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[CELERY TASK] 4-week check failed: {e}")
        import traceback
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
    Async Telegram notification with Elite 15 auto-trade queueing.
    """
    try:
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            return {'status': 'skipped', 'reason': 'no_token'}

        from services.telegram_notifier import TelegramNotifier
        from services.supabase_client import get_supabase_client, SCHEMA_NAME

        telegram_notifier = TelegramNotifier(bot_token)
        supabase = get_supabase_client()

        wallet_address = alert_data.get('wallet_address', '')
        wallet_result = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select(
            'tier, consistency_score'
        ).eq('user_id', user_id).eq('wallet_address', wallet_address).limit(1).execute()

        wallet_info = wallet_result.data[0] if wallet_result.data else {
            'tier': alert_data.get('wallet_tier', 'S' if alert_type == 'elite15_trade' else 'C'),
            'consistency_score': 0,
        }

        payload = {
            'wallet': {
                'address': wallet_address,
                'tier': wallet_info.get('tier', 'C'),
                'consistency_score': wallet_info.get('consistency_score', 0),
            },
            'action': alert_data.get('side', 'buy'),
            'source': alert_data.get('source', 'watchlist'),
            'token': {
                'address': alert_data.get('token_address', ''),
                'symbol': alert_data.get('token_ticker', 'UNKNOWN'),
                'name': alert_data.get('token_name', 'Unknown'),
            },
            'trade': {
                'amount_usd': alert_data.get('usd_value', 0),
                'amount_tokens': alert_data.get('token_amount', 0),
                'price': alert_data.get('price', 0),
                'tx_hash': alert_data.get('tx_hash', ''),
                'dex': alert_data.get('dex', 'unknown'),
                'timestamp': alert_data.get('block_time', 0),
            },
            'links': {
                'solscan': f"https://solscan.io/tx/{alert_data.get('tx_hash', '')}",
                'birdeye': f"https://birdeye.so/token/{alert_data.get('token_address', '')}",
                'dexscreener': f"https://dexscreener.com/solana/{alert_data.get('token_address', '')}",
            },
        }

        if alert_type == 'elite15_trade':
            if hasattr(telegram_notifier, 'send_elite15_alert'):
                telegram_notifier.send_elite15_alert(user_id, payload)
            else:
                telegram_notifier.send_wallet_alert(user_id, payload, alert_data.get('activity_id'))
            if alert_data.get('side') == 'buy':
                _queue_bot_auto_trade(
                    user_id=user_id,
                    alert_data=alert_data,
                    notification_id=alert_data.get('notification_id'),
                    supabase=supabase,
                    schema_name=SCHEMA_NAME,
                )
        elif alert_type in ('watchlist_trade', 'trade'):
            if hasattr(telegram_notifier, 'send_watchlist_alert'):
                telegram_notifier.send_watchlist_alert(user_id, payload)
            else:
                telegram_notifier.send_wallet_alert(user_id, payload, alert_data.get('activity_id'))
        elif alert_type == 'multi_wallet':
            telegram_notifier.send_multi_wallet_signal_alert(user_id, alert_data)
        else:
            telegram_notifier.send_wallet_alert(user_id, payload, alert_data.get('activity_id'))

        try:
            from services.alert_router import alert, P1, P2
            alert(P2, "TELEGRAM", f"Signal processed: {alert_type} for user {user_id[:8]}",
                  details={"alert_type": alert_type, "token": alert_data.get("token_ticker", "UNKNOWN")})
        except ImportError:
            pass

        return {
            'status': 'sent',
            'user_id': user_id,
            'alert_type': alert_type
        }

    except Exception as e:
        print(f"[TELEGRAM TASK] Error: {e}")
        import traceback
        traceback.print_exc()
        try:
            from services.alert_router import alert, P1
            alert(P1, "TELEGRAM", f"Signal processing failed: {e}",
                  details={"user_id": user_id, "alert_type": alert_type, "error": str(e)})
        except ImportError:
            pass
        return {
            'status': 'error',
            'error': str(e)
        }


def _queue_bot_auto_trade(user_id, alert_data, notification_id, supabase, schema_name):
    """Create a pending bot_auto_trades row when Elite 15 auto-trade is enabled."""
    try:
        tg_result = supabase.schema(schema_name).table('telegram_users').select(
            'auto_trade_enabled, auto_trade_max_usd, auto_trade_hourly_limit, auto_trade_daily_limit'
        ).eq('user_id', user_id).limit(1).execute()

        if not tg_result.data or not tg_result.data[0].get('auto_trade_enabled'):
            return

        row_cfg = tg_result.data[0]
        max_usd = float(row_cfg.get('auto_trade_max_usd') or 100)
        hourly_limit = int(row_cfg.get('auto_trade_hourly_limit') or 1)
        daily_limit = int(row_cfg.get('auto_trade_daily_limit') or 8)
        usd_amount = min(float(alert_data.get('usd_value') or 0), max_usd)

        # Portfolio-based position cap (40% per token)
        try:
            from services.supabase_client import get_supabase_client, SCHEMA_NAME
            sb = get_supabase_client()
            token_address = alert_data.get('token_address', '')
            # Check existing position in this token
            existing = sb.schema(SCHEMA_NAME).table("paper_portfolio").select(
                "total_invested_usd"
            ).eq("user_id", user_id).eq("token_address", token_address).eq("status", "open").execute()
            existing_usd = float(existing.data[0]["total_invested_usd"]) if existing.data else 0

            # Get total portfolio value
            all_positions = sb.schema(SCHEMA_NAME).table("paper_portfolio").select(
                "total_invested_usd"
            ).eq("user_id", user_id).eq("status", "open").execute()
            portfolio_total = sum(float(p["total_invested_usd"]) for p in (all_positions.data or []))

            # Per-token cap: 40% of portfolio (minimum $1000 assumed portfolio if no positions)
            effective_portfolio = max(portfolio_total, 1000.0)
            per_token_cap = effective_portfolio * 0.40
            headroom = max(0, per_token_cap - existing_usd)

            if headroom <= 0:
                print(f"[TRADE] Position cap reached for {token_address[:8]} — user {user_id[:8]}")
                return {"status": "skipped", "reason": "position_cap_reached"}

            usd_amount = min(usd_amount, headroom)
        except Exception as cap_exc:
            print(f"[TRADE] Position cap check failed (proceeding): {cap_exc}")

        signal_key = alert_data.get('signal_key')

        now = datetime.utcnow()
        one_hour_ago = now.replace(minute=0, second=0, microsecond=0).isoformat()
        one_day_ago = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        hourly_count = supabase.schema(schema_name).table('bot_auto_trades').select(
            'id', count='exact'
        ).eq('user_id', user_id).in_('status', ['pending', 'executing', 'executed']).gte(
            'created_at', one_hour_ago
        ).execute().count or 0
        daily_count = supabase.schema(schema_name).table('bot_auto_trades').select(
            'id', count='exact'
        ).eq('user_id', user_id).in_('status', ['pending', 'executing', 'executed']).gte(
            'created_at', one_day_ago
        ).execute().count or 0

        if hourly_count >= hourly_limit or daily_count >= daily_limit:
            return

        if signal_key:
            duplicate = supabase.schema(schema_name).table('bot_auto_trades').select(
                'id'
            ).eq('user_id', user_id).eq('signal_key', signal_key).limit(1).execute()
            if duplicate.data:
                return

        row = supabase.schema(schema_name).table('bot_auto_trades').insert({
            'user_id': user_id,
            'source': 'elite15',
            'side': alert_data.get('side', 'buy'),
            'token_address': alert_data.get('token_address', ''),
            'token_ticker': alert_data.get('token_ticker', 'UNKNOWN'),
            'usd_amount': usd_amount,
            'wallet_address': alert_data.get('wallet_address', ''),
            'wallet_tier': alert_data.get('wallet_tier', 'S'),
            'tx_hash_signal': alert_data.get('tx_hash', ''),
            'signal_key': signal_key,
            'wallet_count': alert_data.get('wallet_count', 1),
            'status': 'pending',
            'notification_id': notification_id,
        }).execute()

        if row.data:
            execute_bot_auto_trade.delay(row.data[0]['id'])
    except Exception as e:
        print(f"[TELEGRAM TASK] Failed to queue auto-trade for {user_id[:8]}...: {e}")


@celery.task(name='tasks.execute_bot_auto_trade', max_retries=2)
def execute_bot_auto_trade(trade_id: int):
    """Execute a queued bot auto-trade via TelegramNotifier."""
    # Kill switch check — block execution if active
    try:
        import redis as redis_lib
        _r = redis_lib.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        if _r.get("sifter:kill_switch") == b"1":
            print(f"[KILL SWITCH] Blocked trade {trade_id} — kill switch active")
            try:
                from services.alert_router import alert, P0
                alert(P0, "KILL_SWITCH", f"Trade {trade_id} blocked by kill switch")
            except ImportError:
                pass
            return {"status": "skipped", "reason": "kill_switch_active"}
    except Exception as _ks_exc:
        print(f"[KILL SWITCH] Redis check failed: {_ks_exc}")
        # Fail open — do not block trading if Redis itself is down

    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    supabase = get_supabase_client()
    try:
        result = supabase.schema(SCHEMA_NAME).table('bot_auto_trades').select('*').eq(
            'id', trade_id
        ).limit(1).execute()
        if not result.data:
            return {'status': 'not_found'}

        trade = result.data[0]
        if trade['status'] != 'pending':
            return {'status': 'skipped', 'reason': trade['status']}

        supabase.schema(SCHEMA_NAME).table('bot_auto_trades').update({
            'status': 'executing',
            'updated_at': datetime.utcnow().isoformat(),
        }).eq('id', trade_id).eq('status', 'pending').execute()

        existing = supabase.schema(SCHEMA_NAME).table('bot_auto_trades').select('id').eq(
            'user_id', trade['user_id']
        ).eq('token_address', trade['token_address']).eq('side', 'buy').neq(
            'id', trade_id
        ).in_(
            'status', ['pending', 'executing', 'executed']
        ).execute()
        if existing.data:
            supabase.schema(SCHEMA_NAME).table('bot_auto_trades').update({
                'status': 'skipped',
                'error_message': 'duplicate_buy_prevention',
                'updated_at': datetime.utcnow().isoformat(),
            }).eq('id', trade_id).execute()
            return {'status': 'skipped', 'reason': 'duplicate'}

        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        from services.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier(bot_token)
        result_txid = notifier.execute_auto_trade_for_user(
            user_id=trade['user_id'],
            token_address=trade['token_address'],
            side=trade['side'],
            usd_amount=float(trade['usd_amount']),
        )

        if not result_txid:
            raise RuntimeError('execute_auto_trade_for_user returned None')

        supabase.schema(SCHEMA_NAME).table('bot_auto_trades').update({
            'status': 'executed',
            'result_txid': result_txid,
            'updated_at': datetime.utcnow().isoformat(),
        }).eq('id', trade_id).execute()

        if hasattr(notifier, 'send_auto_trade_confirmation'):
            notifier.send_auto_trade_confirmation(trade['user_id'], trade, result_txid)
        return {'status': 'executed', 'txid': result_txid}
    except Exception as e:
        print(f"[BOT TRADE] Error for {trade_id}: {e}")
        try:
            from services.alert_router import alert, P0
            alert(P0, "TRADE", f"Trade execution failed: {e}", details={"trade_id": trade_id})
        except ImportError:
            pass
        try:
            supabase.schema(SCHEMA_NAME).table('bot_auto_trades').update({
                'status': 'failed',
                'error_message': str(e)[:500],
                'updated_at': datetime.utcnow().isoformat(),
            }).eq('id', trade_id).execute()
            bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
            if bot_token:
                from services.telegram_notifier import TelegramNotifier
                trade_result = supabase.schema(SCHEMA_NAME).table('bot_auto_trades').select('*').eq(
                    'id', trade_id
                ).limit(1).execute()
                if trade_result.data and hasattr(TelegramNotifier(bot_token), 'send_auto_trade_failed'):
                    TelegramNotifier(bot_token).send_auto_trade_failed(
                        trade_result.data[0]['user_id'],
                        trade_result.data[0],
                        str(e),
                    )
        except Exception:
            pass
        return {'status': 'error', 'error': str(e)}


@celery.task(name='tasks.send_paper_trader_daily_digest')
def send_paper_trader_daily_digest():
    """Send the daily paper trader HTML digest to configured recipients."""
    try:
        from services.paper_trade_email import PaperTradeEmailService
        from services.paper_trade_runtime import get_paper_trade_runtime
        from services.paper_trader import PaperTrader

        runtime = get_paper_trade_runtime()
        settings = runtime.get_settings()
        if not settings.get('email_digest_enabled', True):
            return {'status': 'skipped', 'reason': 'digest_disabled'}

        trader = PaperTrader()
        summary = trader.get_summary()
        failure_report = trader.get_failure_report()
        logs = runtime.recent_logs(limit=25, severity='critical') + runtime.recent_logs(limit=25, severity='error')
        sent = PaperTradeEmailService().send_daily_digest(
            summary=summary,
            failure_report=failure_report,
            logs=logs,
        )
        runtime.log(
            severity='info' if sent else 'warning',
            component='email',
            event_type='daily_digest',
            status='sent' if sent else 'skipped',
            message='Paper trader daily digest sent' if sent else 'Paper trader daily digest skipped',
            payload={'configured': PaperTradeEmailService().is_configured()},
        )
        # Include buffered P2 alerts in digest
        try:
            from services.alert_router import flush_digest_buffer
            buffered = flush_digest_buffer()
            if buffered:
                print(f"[DIGEST] Flushed {len(buffered)} buffered alerts")
        except ImportError:
            pass

        return {'status': 'sent' if sent else 'skipped'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


# =============================================================================
# NOTIFICATION TTL — PURGE OLD NOTIFICATIONS
# =============================================================================

@celery.task(name='tasks.purge_old_notifications')
def purge_old_notifications():
    """Delete notifications older than 30 days."""
    print(f"[CELERY TASK] Purging old notifications - {datetime.utcnow().isoformat()}")
    try:
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        from datetime import timedelta
        supabase = get_supabase_client()
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
        result = supabase.schema(SCHEMA_NAME).table('wallet_notifications').delete().lt('sent_at', cutoff).execute()
        count = len(result.data) if result.data else 0
        print(f"[PURGE] Deleted {count} notifications older than 30 days")
        return {'status': 'success', 'deleted': count}
    except Exception as e:
        print(f"[PURGE] Failed: {e}")
        return {'status': 'error', 'error': str(e)}


# =============================================================================
# ELITE 15 MONITOR SYNC
# =============================================================================

ELITE_SYSTEM_USER_ID = '00000000-0000-0000-0000-000000000001'


def _sync_helius_webhook(wallet_addresses: list[str]) -> bool:
    """Update the Helius webhook to monitor the given wallet addresses."""
    import requests as req
    from config import Config

    api_key = Config.HELIUS_API_KEY
    if not api_key:
        logger.warning("[ELITE SYNC] HELIUS_API_KEY not set, skipping webhook sync")
        return False

    webhook_url = os.environ.get(
        "WEBHOOK_URL", "https://sifter-kys.duckdns.org/api/webhooks/helius"
    )

    try:
        # Find existing webhook for our URL
        resp = req.get(
            f"https://api.helius.xyz/v0/webhooks?api-key={api_key}", timeout=15
        )
        if resp.status_code != 200:
            logger.error("[ELITE SYNC] Helius list webhooks failed: %d", resp.status_code)
            return False

        hooks = resp.json()
        matching = [h for h in hooks if h.get("webhookURL") == webhook_url]

        if matching:
            # Update existing webhook
            wh_id = matching[0]["webhookID"]
            resp = req.put(
                f"https://api.helius.xyz/v0/webhooks/{wh_id}?api-key={api_key}",
                json={"accountAddresses": wallet_addresses},
                timeout=15,
            )
            if resp.status_code == 200:
                logger.info("[ELITE SYNC] Updated Helius webhook %s with %d wallets", wh_id, len(wallet_addresses))
                return True
            logger.error("[ELITE SYNC] Helius update failed: %d %s", resp.status_code, resp.text[:200])
        else:
            logger.warning("[ELITE SYNC] No Helius webhook found for %s — run register_helius_webhook.py first", webhook_url)

    except Exception as exc:
        logger.error("[ELITE SYNC] Helius webhook sync error: %s", str(exc)[:200])

    return False


@celery.task(name='tasks.sync_elite_15_to_monitor')
def sync_elite_15_to_monitor():
    """
    Sync top 15 Elite wallets into wallet_watchlist with alerts enabled.
    Runs every hour at :05 (after Elite 100 refresh at :00).
    The wallet monitor will then poll these wallets and fire notifications.
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Elite 15 Monitor Sync - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")

    try:
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        from services.elite_100_manager import get_elite_manager

        supabase = get_supabase_client()
        manager = get_elite_manager()

        # 1. Get current Elite 100, take top 15
        elite_100 = manager.get_cached_elite_100('score')
        if not elite_100:
            print("[ELITE SYNC] No Elite 100 data — regenerating...")
            elite_100 = manager.generate_elite_100('score')

        elite_15 = elite_100[:15]
        elite_15_addresses = {w.get('wallet_address') for w in elite_15 if w.get('wallet_address')}
        print(f"[ELITE SYNC] Current Elite 15: {len(elite_15_addresses)} wallets")

        # 2. Get existing system-user watchlist entries
        existing_resp = (
            supabase.schema(SCHEMA_NAME)
            .table('wallet_watchlist')
            .select('wallet_address')
            .eq('user_id', ELITE_SYSTEM_USER_ID)
            .execute()
        )
        existing_addresses = {row['wallet_address'] for row in existing_resp.data} if existing_resp.data else set()

        # 3. Add new Elite 15 wallets
        to_add = elite_15_addresses - existing_addresses
        added = 0
        for addr in to_add:
            wallet_data = next((w for w in elite_15 if w.get('wallet_address') == addr), {})
            try:
                supabase.schema(SCHEMA_NAME).table('wallet_watchlist').insert({
                    'user_id': ELITE_SYSTEM_USER_ID,
                    'wallet_address': addr,
                    'alert_enabled': True,
                    'tier': wallet_data.get('tier', ''),
                    'professional_score': float(wallet_data.get('professional_score', 0)),
                    'added_at': datetime.utcnow().isoformat(),
                }).execute()
                added += 1
            except Exception as e:
                print(f"[ELITE SYNC] Error adding {addr[:12]}...: {e}")

        # 4. Remove wallets that dropped out of Elite 15
        to_remove = existing_addresses - elite_15_addresses
        removed = 0
        for addr in to_remove:
            try:
                supabase.schema(SCHEMA_NAME).table('wallet_watchlist').delete().eq(
                    'user_id', ELITE_SYSTEM_USER_ID
                ).eq('wallet_address', addr).execute()
                removed += 1
            except Exception as e:
                print(f"[ELITE SYNC] Error removing {addr[:12]}...: {e}")

        # 5. Sync Helius webhook with updated wallet list
        helius_synced = False
        if to_add or to_remove:
            helius_synced = _sync_helius_webhook(list(elite_15_addresses))

        print(f"\n[ELITE SYNC] Complete")
        print(f"  Elite 15 wallets:  {len(elite_15_addresses)}")
        print(f"  Already monitored: {len(existing_addresses & elite_15_addresses)}")
        print(f"  Added:             {added}")
        print(f"  Removed:           {removed}")
        print(f"  Helius synced:     {helius_synced}")

        return {
            'status': 'success',
            'elite_15': len(elite_15_addresses),
            'added': added,
            'removed': removed,
            'helius_synced': helius_synced,
            'timestamp': datetime.utcnow().isoformat(),
        }

    except Exception as e:
        print(f"\n[ELITE SYNC] Failed: {e}")
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'error': str(e)}


# =============================================================================
# DAILY EMAIL SUMMARIES
# =============================================================================

@celery.task(name='tasks.send_daily_email_summaries')
def send_daily_email_summaries():
    """Send daily paper trading + Elite summary emails at 8am UTC."""
    print(f"\n[CELERY TASK] Daily Email Summaries - {datetime.utcnow().isoformat()}")

    try:
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        from services.email_service import get_email_service

        supabase = get_supabase_client()
        email_svc = get_email_service()

        # Get users with email alerts enabled
        result = (
            supabase.schema(SCHEMA_NAME)
            .table('user_settings')
            .select('user_id, email')
            .eq('email_alerts', True)
            .execute()
        )
        users = result.data if result.data else []
        print(f"[EMAIL] Found {len(users)} users with email alerts enabled")

        sent = 0
        errors = 0
        for user in users:
            email = user.get('email')
            user_id = user.get('user_id')
            if not email or not user_id:
                continue
            try:
                email_svc.send_daily_summary(user_id, email)
                sent += 1
            except Exception as e:
                errors += 1
                print(f"[EMAIL] Error sending to {email}: {e}")

        print(f"[EMAIL] Sent {sent} daily summaries, {errors} errors")
        return {'status': 'success', 'sent': sent, 'errors': errors}

    except Exception as e:
        print(f"[EMAIL] Daily summary task failed: {e}")
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'error': str(e)}


# =============================================================================
# PAPER TRADER EXIT CHECKER — runs every 2 minutes independently
# =============================================================================

@celery.task(name='tasks.check_paper_trader_exits')
def check_paper_trader_exits():
    """
    Check all open paper trade positions for take-profit and stop-loss exits.

    Runs every 2 minutes on its own Celery beat schedule, completely independent
    of the wallet monitor polling interval. This ensures open positions are
    evaluated frequently even when the wallet monitor is running slowly.

    Take-profit tiers: 5x (sell 25%), 10x (sell 33%), 20x (sell 50%), 30x (sell 100%)
    Stop-loss: closes position if price drops to 0.30x of entry (dead token)
    Max age: closes position after 14 days regardless of price
    """
    try:
        from services.paper_trading_manager import get_paper_trading_manager
        ptm = get_paper_trading_manager()
        result = ptm.check_exits()
        return {"status": "ok", **result}
    except Exception as exc:
        print(f"[EXIT CHECKER] Failed: {exc}")
        try:
            from services.alert_router import alert, P0
            alert(P0, "EXIT_CHECKER", f"Exit checker task crashed: {exc}")
        except ImportError:
            pass
        return {"status": "error", "error": str(exc)}


# =============================================================================
# SIGNAL AGGREGATOR TASKS
# =============================================================================

@celery.task(name='tasks.ingest_helius_signal')
def ingest_helius_signal(signal: dict):
    """Receive one raw Helius signal, annotate with qualification status, pass to aggregator."""
    try:
        token_address = signal.get("token_address", "")
        wallet_address = signal.get("wallet_address", "")

        # Qualification gate — annotate signal (soft gate, doesn't block)
        from services.redis_pool import get_redis_client
        r = get_redis_client()
        is_qualified = r.sismember("kys:qualified_tokens", token_address)
        is_known = r.sismember("kys:known_tokens", token_address) or r.sismember("kys:pending_tokens", token_address)
        signal["token_qualified"] = bool(is_qualified)
        signal["token_known"] = bool(is_known)

        from services.signal_aggregator import get_aggregator
        get_aggregator().receive(signal)
        logger.info(
            "[SIGNAL] action=ingest status=ok token=%s wallet=%s qualified=%s",
            token_address[:8], wallet_address[:8], is_qualified,
        )
        return {"status": "ok", "qualified": bool(is_qualified)}
    except Exception as exc:
        logger.error("[SIGNAL] action=ingest status=error error=%s", str(exc)[:200])
        return {"status": "error", "error": str(exc)}


@celery.task(name='tasks.flush_signal_aggregator')
def flush_signal_aggregator():
    """Called every 10s by Celery beat. Emits grouped signals whose window expired."""
    try:
        from services.signal_aggregator import get_aggregator
        from services.paper_trader import PaperTrader

        agg = get_aggregator()
        trader = PaperTrader()

        def emit(grouped_signal: dict):
            trader.process_signal(grouped_signal)

            from services.supabase_client import get_supabase_client, SCHEMA_NAME
            supabase = get_supabase_client()
            users = (
                supabase.schema(SCHEMA_NAME)
                .table("telegram_users")
                .select("user_id, auto_trade_enabled, auto_trade_max_usd, auto_trade_source, alerts_enabled")
                .eq("alerts_enabled", True)
                .eq("auto_trade_enabled", True)
                .execute()
                .data or []
            )

            for user in users:
                user_id = user.get("user_id")
                if not user_id:
                    continue
                if user.get("auto_trade_source", "elite15") not in ("elite15", "all"):
                    continue
                send_telegram_alert_async.delay(
                    user_id,
                    "elite15_trade",
                    {**grouped_signal, "auto_trade_max_usd": user.get("auto_trade_max_usd", 100)},
                )

        emitted = agg.flush_expired(emit_callback=emit)
        return {"status": "ok", "emitted": emitted, "pending": agg.get_pending_count()}

    except Exception as exc:
        logger.error("[AGGREGATOR] action=flush status=error error=%s", str(exc)[:200])
        return {"status": "error", "error": str(exc)}
