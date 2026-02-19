"""
Celery Scheduled Tasks - Production Cron Jobs
These run on Celery Beat scheduler (time-based, recurring)
For on-demand analysis workers, see worker_tasks.py (RQ)
"""
from celery_app import celery
from datetime import datetime
import os


@celery.task(name='tasks.daily_stats_refresh')
def daily_stats_refresh():
    """
    Daily stats refresh at 3am UTC
    Updates all watchlist wallet metrics
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
            'status': 'success',
            'result': result,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] Daily refresh failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.weekly_rerank_all')
def weekly_rerank_all():
    """
    Weekly rerank on Sunday at 4am UTC
    Reranks all user watchlists
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
            'status': 'success',
            'result': result,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] Weekly rerank failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.four_week_degradation_check')
def four_week_degradation_check():
    """
    4-week degradation check every 28 days at 5am UTC
    Identifies wallets with declining performance over 4 weeks
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
            'status': 'success',
            'result': result,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] 4-week check failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.refresh_elite_100')
def refresh_elite_100():
    """
    Refresh Elite 100 rankings every hour
    Generates top 100 performing wallets across all metrics
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
        print(f"  - By Score: {len(score_wallets)} wallets")
        print(f"  - By ROI: {len(roi_wallets)} wallets")
        print(f"  - By Runners: {len(runners_wallets)} wallets")
        
        return {
            'status': 'success',
            'counts': {
                'score': len(score_wallets),
                'roi': len(roi_wallets),
                'runners': len(runners_wallets)
            },
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] Elite 100 refresh failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.refresh_community_top_100')
def refresh_community_top_100():
    """
    Refresh Community Top 100 every hour
    Shows most-added wallets this week
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
            'status': 'success',
            'count': len(wallets),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] Community Top 100 refresh failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.flush_redis_to_duckdb')
def flush_redis_to_duckdb():
    """
    Flush Redis hot cache → DuckDB cold storage (every hour)

    Strategy:
    - Workers write to Redis only (read_only=True DuckDB)
    - This task runs on Celery Beat every hour
    - It uses the Flask-side analyzer (read_only=False) to read Redis
      and write everything into DuckDB for persistence
    - On Redis restart, DuckDB automatically refills Redis on cache misses

    Cache tables flushed:
      - wallet_token_cache  (PnL + entry data)     [pnl:{wallet}:{token}]
      - wallet_runner_cache (runner history)        [runners:{wallet}]
      - token_runner_cache  (is-runner check)       [token_runner:{token}]
      - token_ath_cache     (ATH data)              [token_ath:{token}]
      - token_info_cache    (token metadata)        [token_info:{token}]
      - token_security_cache (security checks)      [token_security:{token}]
      - token_launch_cache  (launch price)          [launch_price:{token}]
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

        # Connect to DuckDB in read-write mode (Flask/Celery process)
        duckdb_path = 'wallet_analytics.duckdb'
        con = duckdb.connect(duckdb_path)

        stats = {
            'pnl': 0,
            'runners': 0,
            'token_runner': 0,
            'token_ath': 0,
            'token_info': 0,
            'token_security': 0,
            'launch_price': 0,
            'errors': 0
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

                # Key format: pnl:{wallet}:{token}
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

                # Key format: runners:{wallet}
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
            'status': 'success',
            'stats': stats,
            'total_flushed': total_flushed,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"\n[FLUSH TASK] ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.send_telegram_alert_async')
def send_telegram_alert_async(user_id: str, alert_type: str, alert_data: dict):
    """
    Async Telegram alert sender
    Called by wallet monitor for background alert delivery
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
            ).eq('user_id', user_id).eq('wallet_address', alert_data.get('wallet_address')).limit(1).execute()
            
            wallet_info = wallet_result.data[0] if wallet_result.data else {'tier': 'C', 'consistency_score': 0}
            
            payload = {
                'wallet': {
                    'address': alert_data.get('wallet_address', ''),
                    'tier': wallet_info.get('tier', 'C'),
                    'consistency_score': wallet_info.get('consistency_score', 0)
                },
                'action': alert_data.get('side', 'buy'),
                'token': {
                    'address': alert_data.get('token_address', ''),
                    'symbol': alert_data.get('token_ticker', 'UNKNOWN'),
                    'name': alert_data.get('token_name', 'Unknown')
                },
                'trade': {
                    'amount_tokens': alert_data.get('token_amount', 0),
                    'amount_usd': alert_data.get('usd_value', 0),
                    'price': alert_data.get('price', 0),
                    'tx_hash': alert_data.get('tx_hash', ''),
                    'dex': alert_data.get('dex', 'unknown'),
                    'timestamp': alert_data.get('block_time', 0)
                },
                'links': {
                    'solscan': f"https://solscan.io/tx/{alert_data.get('tx_hash', '')}",
                    'birdeye': f"https://birdeye.so/token/{alert_data.get('token_address', '')}",
                    'dexscreener': f"https://dexscreener.com/solana/{alert_data.get('token_address', '')}"
                }
            }
            
            telegram_notifier.send_wallet_alert(user_id, payload, alert_data.get('activity_id'))
            
        elif alert_type == 'multi_wallet':
            telegram_notifier.send_multi_wallet_signal_alert(user_id, alert_data)
        
        return {
            'status': 'sent',
            'user_id': user_id,
            'alert_type': alert_type
        }
        
    except Exception as e:
        print(f"[TELEGRAM TASK] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e)
        }