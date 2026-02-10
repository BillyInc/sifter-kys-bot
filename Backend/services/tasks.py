from redis import Redis
import json
import asyncio
import os  # Add this


def perform_wallet_analysis(data):
    """Main coordinator - splits work by STEPS, not just tokens"""
    tokens = data.get('tokens', [])
    user_id = data.get('user_id', 'default_user')
    
    if len(tokens) == 1:
        # SINGLE TOKEN - Split the 6 steps across workers
        return analyze_single_token_parallel(tokens[0], user_id, data.get('job_id'))
    
    else:
        # MULTIPLE TOKENS - Split by token AND steps
        return analyze_multiple_tokens_parallel(tokens, user_id, data.get('job_id'))


def analyze_single_token_parallel(token, user_id, parent_job_id):
    """Split ONE token's analysis across 5 workers"""
    from flask import current_app
    redis = Redis(host='localhost', port=6379)
    q = current_app.config['RQ_QUEUE']
    
    print(f"\n[PARALLEL ANALYSIS] Splitting {token['ticker']} across workers...")
    
    # ✅ STEP 1-4: Fetch data in parallel (4 workers)
    data_jobs = []
    
    # Worker 1: Top traders
    job1 = q.enqueue('tasks.fetch_top_traders', {
        'token': token,
        'parent_job_id': parent_job_id
    })
    data_jobs.append(('top_traders', job1.id))
    
    # Worker 2: First buyers
    job2 = q.enqueue('tasks.fetch_first_buyers', {
        'token': token,
        'parent_job_id': parent_job_id
    })
    data_jobs.append(('first_buyers', job2.id))
    
    # Worker 3: Birdeye trades
    job3 = q.enqueue('tasks.fetch_birdeye_trades', {
        'token': token,
        'parent_job_id': parent_job_id
    })
    data_jobs.append(('birdeye_trades', job3.id))
    
    # Worker 4: Recent trades
    job4 = q.enqueue('tasks.fetch_recent_trades', {
        'token': token,
        'parent_job_id': parent_job_id
    })
    data_jobs.append(('recent_trades', job4.id))
    
    # Wait for all data fetching to complete
    all_wallets = set()
    wallet_data = {}
    
    import time
    while True:
        completed = 0
        for data_type, job_id in data_jobs:
            result = redis.get(f"job_result:{job_id}")
            if result:
                completed += 1
                data = json.loads(result)
                
                # Merge wallets from each source
                all_wallets.update(data['wallets'])
                wallet_data.update(data['wallet_data'])
        
        if completed == len(data_jobs):
            break
        
        time.sleep(1)
    
    print(f"  ✓ Data fetching complete: {len(all_wallets)} wallets found")
    
    # ✅ STEP 5: Fetch PnL in parallel batches (use remaining workers)
    wallet_list = list(all_wallets)
    batch_size = len(wallet_list) // 5 + 1  # Split across 5 workers
    
    pnl_jobs = []
    for i in range(0, len(wallet_list), batch_size):
        batch = wallet_list[i:i+batch_size]
        job = q.enqueue('tasks.fetch_pnl_batch', {
            'wallets': batch,
            'token': token,
            'wallet_data': {w: wallet_data[w] for w in batch if w in wallet_data},
            'parent_job_id': parent_job_id
        })
        pnl_jobs.append(job.id)
    
    # Wait for PnL fetching
    qualified_wallets = []
    while True:
        completed = 0
        for job_id in pnl_jobs:
            result = redis.get(f"job_result:{job_id}")
            if result:
                completed += 1
                qualified_wallets.extend(json.loads(result))
        
        if completed == len(pnl_jobs):
            break
        
        time.sleep(1)
    
    print(f"  ✓ PnL fetching complete: {len(qualified_wallets)} qualified")
    
    # ✅ STEP 6: Fetch 30-day history in parallel batches
    history_jobs = []
    batch_size = len(qualified_wallets) // 5 + 1
    
    for i in range(0, len(qualified_wallets), batch_size):
        batch = qualified_wallets[i:i+batch_size]
        job = q.enqueue('tasks.fetch_runner_history_batch', {
            'wallets': batch,
            'token': token,
            'parent_job_id': parent_job_id
        })
        history_jobs.append(job.id)
    
    # Wait for history fetching
    final_wallets = []
    while True:
        completed = 0
        for job_id in history_jobs:
            result = redis.get(f"job_result:{job_id}")
            if result:
                completed += 1
                final_wallets.extend(json.loads(result))
        
        if completed == len(history_jobs):
            break
        
        time.sleep(1)
    
    # ✅ Final scoring and ranking
    from routes.wallets import get_wallet_analyzer
    analyzer = get_wallet_analyzer()
    
    # Get ATH for scoring
    ath_data = analyzer.get_token_ath(token['address'])
    ath_price = ath_data.get('highest_price', 0) if ath_data else 0
    
    # Calculate max values for relative scoring
    max_entry_to_ath = max((w.get('entry_to_ath_multiplier', 0) for w in final_wallets), default=1)
    max_realized_roi = max((w.get('realized_multiplier', 0) for w in final_wallets), default=1)
    max_total_roi = max((w.get('total_multiplier', 0) for w in final_wallets), default=1)
    
    # Score and rank
    for wallet in final_wallets:
        wallet['ath_price'] = ath_price
        scoring = analyzer.calculate_wallet_relative_score(
            wallet, max_entry_to_ath, max_realized_roi, max_total_roi
        )
        wallet.update(scoring)
    
    final_wallets.sort(key=lambda x: x['professional_score'], reverse=True)
    
    result = {
        'success': True,
        'token': token,
        'wallets': final_wallets[:50],
        'total': len(final_wallets)
    }
    
    # Cache result
    redis.set(f"job_result:{parent_job_id}", json.dumps(result), ex=3600)
    return result


def analyze_multiple_tokens_parallel(tokens, user_id, parent_job_id):
    """Split multiple tokens - each token gets step-level parallelization"""
    from flask import current_app
    redis = Redis(host='localhost', port=6379)
    q = current_app.config['RQ_QUEUE']
    
    print(f"\n[MULTI-TOKEN PARALLEL] Analyzing {len(tokens)} tokens...")
    
    # Create sub-jobs for each token
    token_jobs = []
    for token in tokens:
        job = q.enqueue('tasks.analyze_single_token_parallel', 
            token, user_id, f"{parent_job_id}_token_{token['address'][:8]}"
        )
        token_jobs.append((token, job.id))
    
    # Wait for all tokens to complete
    all_results = []
    import time
    while True:
        completed = 0
        for token, job_id in token_jobs:
            result = redis.get(f"job_result:{job_id}")
            if result:
                completed += 1
                all_results.append(json.loads(result))
        
        if completed == len(token_jobs):
            break
        
        time.sleep(2)
    
    # Aggregate results (token overlap logic)
    from collections import defaultdict
    wallet_hits = defaultdict(lambda: {
        'wallet': None,
        'tokens_hit': [],
        'performances': [],
        'professional_scores': []
    })
    
    for token_result in all_results:
        token = token_result['token']
        for wallet in token_result['wallets']:
            addr = wallet['wallet']
            
            if wallet_hits[addr]['wallet'] is None:
                wallet_hits[addr]['wallet'] = addr
            
            wallet_hits[addr]['tokens_hit'].append(token['ticker'])
            wallet_hits[addr]['performances'].append({
                'token': token['ticker'],
                'professional_score': wallet['professional_score'],
                'roi_multiplier': wallet['roi_multiplier']
            })
            wallet_hits[addr]['professional_scores'].append(wallet['professional_score'])
    
    # Rank by token overlap + score
    ranked = []
    for addr, data in wallet_hits.items():
        ranked.append({
            'wallet': addr,
            'token_count': len(data['tokens_hit']),
            'tokens_hit': data['tokens_hit'],
            'avg_score': sum(data['professional_scores']) / len(data['professional_scores']),
            'performances': data['performances']
        })
    
    ranked.sort(key=lambda x: (x['token_count'], x['avg_score']), reverse=True)
    
    final_result = {
        'success': True,
        'wallets': ranked[:50],
        'total': len(ranked)
    }
    
    redis.set(f"job_result:{parent_job_id}", json.dumps(final_result), ex=3600)
    return final_result


# ========================================
# SUB-TASK WORKERS (Each runs on separate worker)
# ========================================

def fetch_top_traders(data):
    """Worker 1: Fetch top traders"""
    from routes.wallets import get_wallet_analyzer
    
    analyzer = get_wallet_analyzer()
    token = data['token']
    
    url = f"{analyzer.st_base_url}/top-traders/{token['address']}"
    response = analyzer.fetch_with_retry(
        url,
        analyzer._get_solanatracker_headers(),
        semaphore=analyzer.solana_tracker_semaphore
    )
    
    wallets = set()
    wallet_data = {}
    
    if response:
        traders = response if isinstance(response, list) else []
        for trader in traders:
            wallet = trader.get('wallet')
            if wallet:
                wallets.add(wallet)
                
                cached = analyzer._get_cached_pnl_and_entry(wallet, token['address'])
                
                wallet_data[wallet] = {
                    'source': 'top_traders',
                    'pnl_data': trader,
                    'earliest_entry': cached['first_buy_time'] if cached else None,
                    'entry_price': cached['entry_price'] if cached else None
                }
    
    result = {'wallets': list(wallets), 'wallet_data': wallet_data}
    
    redis = Redis(host='localhost', port=6379)
    redis.set(f"job_result:{data.get('job_id')}", json.dumps(result), ex=3600)
    return result


def fetch_first_buyers(data):
    """Worker 2: Fetch first buyers"""
    from routes.wallets import get_wallet_analyzer
    
    analyzer = get_wallet_analyzer()
    token = data['token']
    
    url = f"{analyzer.st_base_url}/first-buyers/{token['address']}"
    response = analyzer.fetch_with_retry(
        url,
        analyzer._get_solanatracker_headers(),
        semaphore=analyzer.solana_tracker_semaphore
    )
    
    wallets = set()
    wallet_data = {}
    
    if response:
        buyers = response if isinstance(response, list) else response.get('buyers', [])
        first_buyer_wallets = set(b.get('wallet') for b in buyers if b.get('wallet'))
        
        # Async fetch entry prices
        import asyncio
        results = asyncio.run(analyzer._async_fetch_first_buys(first_buyer_wallets, token['address']))
        
        for buyer, first_buy_data in zip(buyers, results):
            wallet = buyer.get('wallet')
            if wallet:
                wallets.add(wallet)
                wallet_data[wallet] = {
                    'source': 'first_buyers',
                    'pnl_data': buyer,
                    'earliest_entry': buyer.get('first_buy_time', 0),
                    'entry_price': first_buy_data['price'] if first_buy_data else None
                }
    
    result = {'wallets': list(wallets), 'wallet_data': wallet_data}
    
    redis = Redis(host='localhost', port=6379)
    redis.set(f"job_result:{data.get('job_id')}", json.dumps(result), ex=3600)
    return result


def fetch_birdeye_trades(data):
    """Worker 3: Fetch Birdeye trades"""
    from routes.wallets import get_wallet_analyzer
    import time
    
    analyzer = get_wallet_analyzer()
    token = data['token']
    
    current_time = int(time.time())
    after_time = current_time - (30 * 86400)
    
    all_trades = []
    offset = 0
    
    while offset < 10000:
        params = {
            "address": token['address'],
            "offset": offset,
            "limit": 100,
            "after_time": after_time
        }
        
        response = analyzer.fetch_with_retry(
            f"{analyzer.birdeye_base_url}/defi/v3/token/txs",
            analyzer._get_birdeye_headers(),
            params,
            semaphore=analyzer.birdeye_semaphore
        )
        
        if not response or not response.get('success'):
            break
        
        trades = response.get('data', {}).get('items', [])
        if not trades:
            break
        
        all_trades.extend(trades)
        if len(trades) < 100:
            break
        
        offset += 100
        time.sleep(0.5)
    
    wallets = set()
    wallet_data = {}
    
    for trade in all_trades:
        wallet = trade.get('owner')
        if wallet:
            wallets.add(wallet)
            wallet_data[wallet] = {
                'source': 'birdeye_trades',
                'earliest_entry': trade.get('block_unix_time'),
                'entry_price': trade.get('price_pair')
            }
    
    result = {'wallets': list(wallets), 'wallet_data': wallet_data}
    
    redis = Redis(host='localhost', port=6379)
    redis.set(f"job_result:{data.get('job_id')}", json.dumps(result), ex=3600)
    return result


def fetch_recent_trades(data):
    """Worker 4: Fetch recent trades"""
    from routes.wallets import get_wallet_analyzer
    
    analyzer = get_wallet_analyzer()
    token = data['token']
    
    url = f"{analyzer.st_base_url}/trades/{token['address']}"
    params = {"sortDirection": "DESC", "limit": 100}
    
    response = analyzer.fetch_with_retry(
        url,
        analyzer._get_solanatracker_headers(),
        params,
        semaphore=analyzer.solana_tracker_semaphore
    )
    
    wallets = set()
    wallet_data = {}
    
    if response:
        trades = response.get('trades', [])[:500]
        for trade in trades:
            wallet = trade.get('wallet')
            if wallet:
                wallets.add(wallet)
                wallet_data[wallet] = {
                    'source': 'solana_recent',
                    'earliest_entry': trade.get('time', 0)
                }
    
    result = {'wallets': list(wallets), 'wallet_data': wallet_data}
    
    redis = Redis(host='localhost', port=6379)
    redis.set(f"job_result:{data.get('job_id')}", json.dumps(result), ex=3600)
    return result


def fetch_pnl_batch(data):
    """Worker 5+: Fetch PnL for wallet batch"""
    from routes.wallets import get_wallet_analyzer
    import asyncio
    
    analyzer = get_wallet_analyzer()
    wallets = data['wallets']
    token = data['token']
    wallet_data = data['wallet_data']
    
    qualified = []
    
    # Async fetch all PnLs
    async def fetch_all():
        import aiohttp
        async with aiohttp.ClientSession() as session:
            tasks = []
            for wallet in wallets:
                async def fetch(w=wallet):
                    return await analyzer.async_fetch_with_retry(
                        session,
                        f"{analyzer.st_base_url}/pnl/{w}/{token['address']}",
                        analyzer._get_solanatracker_headers(),
                        semaphore=analyzer.pnl_async_semaphore
                    )
                tasks.append(fetch())
            return await asyncio.gather(*tasks)
    
    results = asyncio.run(fetch_all())
    
    for wallet, pnl_data in zip(wallets, results):
        if pnl_data:
            realized = pnl_data.get('realized', 0)
            unrealized = pnl_data.get('unrealized', 0)
            total_invested = pnl_data.get('total_invested', 0)
            
            if total_invested >= 100:
                realized_mult = (realized + total_invested) / total_invested
                
                if realized_mult >= 3.0:
                    qualified.append({
                        'wallet': wallet,
                        'source': wallet_data.get(wallet, {}).get('source', 'unknown'),
                        'realized': realized,
                        'unrealized': unrealized,
                        'total_invested': total_invested,
                        'realized_multiplier': realized_mult,
                        'total_multiplier': (realized + unrealized + total_invested) / total_invested,
                        'earliest_entry': wallet_data.get(wallet, {}).get('earliest_entry'),
                        'entry_price': wallet_data.get(wallet, {}).get('entry_price')
                    })
    
    redis = Redis(host='localhost', port=6379)
    redis.set(f"job_result:{data.get('job_id')}", json.dumps(qualified), ex=3600)
    return qualified


def fetch_runner_history_batch(data):
    """Worker: Fetch 30-day runner history for wallet batch"""
    from routes.wallets import get_wallet_analyzer
    
    analyzer = get_wallet_analyzer()
    wallets = data['wallets']
    token = data['token']
    
    results = []
    
    for wallet_info in wallets:
        wallet = wallet_info['wallet']
        
        # Get cached runner history
        runner_history = analyzer._get_cached_other_runners(
            wallet,
            current_token=token['address'],
            min_multiplier=5.0
        )
        
        # Add entry-to-ATH if we have entry price
        if wallet_info.get('entry_price'):
            # We'll calculate this in the final scoring step
            pass
        
        wallet_info['runner_hits_30d'] = runner_history['stats'].get('total_other_runners', 0)
        wallet_info['runner_success_rate'] = runner_history['stats'].get('success_rate', 0)
        wallet_info['other_runners'] = runner_history['other_runners'][:5]
        wallet_info['other_runners_stats'] = runner_history['stats']
        
        results.append(wallet_info)
    
    redis = Redis(host='localhost', port=6379)
    redis.set(f"job_result:{data.get('job_id')}", json.dumps(results), ex=3600)
    return results


# ========================================
# CACHE WARMUP WORKERS
# ========================================

def preload_trending_cache_parallel():
    """Split cache warmup across workers"""
    from flask import current_app
    q = current_app.config['RQ_QUEUE']
    
    print("\n[CACHE WARMUP] Starting parallel cache preload...")
    
    jobs = []
    
    # Worker 1: 7-day runners
    jobs.append(q.enqueue('tasks.warm_cache_7d'))
    
    # Worker 2: 14-day runners
    jobs.append(q.enqueue('tasks.warm_cache_14d'))
    
    # Worker 3-5: Analyze top runners from each timeframe
    jobs.append(q.enqueue('tasks.analyze_top_runners', {'days': 7, 'count': 3}))
    jobs.append(q.enqueue('tasks.analyze_top_runners', {'days': 14, 'count': 3}))
    jobs.append(q.enqueue('tasks.analyze_top_runners', {'days': 30, 'count': 3}))
    
    print(f"  ✓ Queued {len(jobs)} cache warmup jobs")
    return jobs


def warm_cache_7d():
    """Warm 7-day trending cache"""
    from routes.wallets import get_wallet_analyzer
    
    analyzer = get_wallet_analyzer()
    print("[WARMUP 7D] Finding 7-day runners...")
    
    runners = analyzer.find_trending_runners_enhanced(
        days_back=7,
        min_multiplier=5.0,
        min_liquidity=50000
    )
    
    print(f"  ✓ Cached {len(runners)} 7-day runners")
    return len(runners)


def warm_cache_14d():
    """Warm 14-day trending cache"""
    from routes.wallets import get_wallet_analyzer
    
    analyzer = get_wallet_analyzer()
    print("[WARMUP 14D] Finding 14-day runners...")
    
    runners = analyzer.find_trending_runners_enhanced(
        days_back=14,
        min_multiplier=5.0,
        min_liquidity=50000
    )
    
    print(f"  ✓ Cached {len(runners)} 14-day runners")
    return len(runners)


def analyze_top_runners(data):
    """Analyze top N runners from a timeframe"""
    from routes.wallets import get_wallet_analyzer
    
    analyzer = get_wallet_analyzer()
    days = data['days']
    count = data['count']
    
    print(f"[WARMUP] Analyzing top {count} runners from {days}-day list...")
    
    runners = analyzer.find_trending_runners_enhanced(
        days_back=days,
        min_multiplier=5.0,
        min_liquidity=50000
    )
    
    for runner in runners[:count]:
        try:
            analyzer.analyze_token_professional(runner['address'])
            print(f"  ✓ Analyzed {runner['symbol']}")
        except Exception as e:
            print(f"  ⚠️ Failed {runner['symbol']}: {e}")
    
    print(f"  ✓ Warmup complete for {days}d runners")
    return count

# Add at the end of tasks.py

def monitor_wallet_activity(wallet_address):
    """Monitor a single wallet for new activity (runs every 30-60 seconds)"""
    from routes.wallets import get_wallet_analyzer
    from services.wallet_monitor import WalletActivityMonitor
    from flask import current_app
    
    monitor = WalletActivityMonitor(
        birdeye_api_key=os.environ.get('BIRDEYE_API_KEY')
,
        telegram_notifier=current_app.config.get('TELEGRAM_NOTIFIER')
    )
    
    # Check wallet and create notifications
    monitor.force_check_wallet(wallet_address)
    return {'wallet': wallet_address, 'checked': True}


def detect_multi_wallet_signals(token_address, wallets_buying):
    """Detect when multiple watchlist wallets buy the same token"""
    from db.watchlist_db import WatchlistDatabase
    
    db = WatchlistDatabase()
    
    # Calculate signal strength based on wallet tiers
    signal_strength = 0
    for wallet in wallets_buying:
        tier_weights = {'S': 4, 'A': 3, 'B': 2, 'C': 1}
        signal_strength += tier_weights.get(wallet.get('tier', 'C'), 1)
    
    # If 2+ wallets (especially high-tier) buy same token = STRONG SIGNAL
    if len(wallets_buying) >= 2 and signal_strength >= 5:
        return {
            'token': token_address,
            'signal_strength': signal_strength,
            'wallets': wallets_buying,
            'alert_type': 'multi_wallet_buy'
        }
    
    return None
# Add to tasks.py (after all existing functions)

def rerank_all_watchlists():
    """
    Daily task: Rerank all users' watchlists
    Run this via cron job at 2 AM
    """
    from services.watchlist_manager import WatchlistLeagueManager
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    
    print("\n" + "="*80)
    print("DAILY WATCHLIST RERANKING")
    print("="*80)
    
    manager = WatchlistLeagueManager()
    supabase = get_supabase_client()
    
    # Get all unique user_ids with wallets
    result = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select('user_id').execute()
    user_ids = list(set(row['user_id'] for row in result.data))
    
    print(f"\n[RERANK] Processing {len(user_ids)} users...")
    
    success_count = 0
    error_count = 0
    
    for user_id in user_ids:
        try:
            manager.rerank_user_watchlist(user_id)
            print(f"  ✓ {user_id[:8]}...")
            success_count += 1
        except Exception as e:
            print(f"  ✗ {user_id[:8]}...: {e}")
            error_count += 1
    
    print(f"\n[RERANK] Complete: {success_count} success, {error_count} errors")
    print("="*80 + "\n")
    
    # ADD THIS FUNCTION AT THE END OF tasks.py

def track_weekly_performance():
    """
    Track weekly performance for all watchlist wallets
    Run this ONCE PER WEEK (Sunday midnight)
    
    Stores each wallet's weekly performance in history table
    Used for 4-week trend detection
    """
    from services.watchlist_manager import WatchlistLeagueManager
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    from datetime import datetime, timedelta
    
    print("\n" + "="*80)
    print("WEEKLY PERFORMANCE TRACKING")
    print("="*80)
    
    manager = WatchlistLeagueManager()
    supabase = get_supabase_client()
    
    # Get all wallets from all users
    result = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select('*').execute()
    wallets = result.data
    
    week_start = datetime.utcnow() - timedelta(days=7)
    week_end = datetime.utcnow()
    
    for wallet in wallets:
        wallet_address = wallet['wallet_address']
        
        # Calculate this week's performance
        metrics = manager._refresh_wallet_metrics(wallet_address)
        
        # Store in history table
        supabase.schema(SCHEMA_NAME).table('wallet_performance_history').insert({
            'wallet_address': wallet_address,
            'user_id': wallet['user_id'],
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'runners_hit': metrics.get('runners_7d', 0),
            'avg_roi': metrics.get('roi_7d', 0),
            'position': wallet['position'],
            'zone': wallet.get('zone', 'unknown'),
            'professional_score': metrics.get('professional_score', 0),
            'created_at': datetime.utcnow().isoformat()
        }).execute()
    
    print(f"✅ Tracked {len(wallets)} wallets")
    
    
def process_telegram_update(update_data):
    """
    Background worker for processing Telegram updates
    Keeps webhook response time <100ms
    """
    from services.telegram_notifier import TelegramNotifier
    
    print(f"[TELEGRAM WORKER] Processing update...")
    
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        print("[TELEGRAM WORKER] No bot token configured")
        return
    
    notifier = TelegramNotifier(bot_token)
    
    try:
        notifier.process_bot_updates([update_data])
        print(f"[TELEGRAM WORKER] ✓ Update processed")
        return {'success': True}
    except Exception as e:
        print(f"[TELEGRAM WORKER] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


def send_telegram_alert_async(user_id, alert_type, alert_data):
    """
    Background worker for sending Telegram alerts
    Used by wallet monitor to avoid blocking
    """
    from services.telegram_notifier import TelegramNotifier
    
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        print("[TELEGRAM ALERT] No bot token configured")
        return
    
    notifier = TelegramNotifier(bot_token)
    
    try:
        if alert_type == 'trade':
            notifier.send_trade_alert(user_id, alert_data)
        elif alert_type == 'multi_wallet':
            notifier.send_multi_wallet_signal_alert(user_id, alert_data)
        elif alert_type == 'degradation':
            notifier.send_degradation_warning(user_id, alert_data)
        elif alert_type == 'replacement':
            notifier.send_replacement_complete_alert(user_id, alert_data)
        elif alert_type == 'weekly_digest':
            notifier.send_weekly_digest(user_id, alert_data)
        else:
            print(f"[TELEGRAM ALERT] Unknown alert type: {alert_type}")
            return {'success': False, 'error': 'Unknown alert type'}
        
        print(f"[TELEGRAM ALERT] ✓ Sent {alert_type} alert to {user_id[:8]}...")
        return {'success': True}
    except Exception as e:
        print(f"[TELEGRAM ALERT] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


def send_batch_telegram_alerts(alerts_batch):
    """
    Send multiple Telegram alerts in batch
    Used for daily/weekly digests to all users
    
    Args:
        alerts_batch: [
            {'user_id': 'xxx', 'type': 'weekly_digest', 'data': {...}},
            {'user_id': 'yyy', 'type': 'weekly_digest', 'data': {...}},
        ]
    """
    from services.telegram_notifier import TelegramNotifier
    import time
    
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        print("[BATCH ALERTS] No bot token configured")
        return {'success': 0, 'errors': len(alerts_batch)}
    
    notifier = TelegramNotifier(bot_token)
    
    success_count = 0
    error_count = 0
    
    print(f"[BATCH ALERTS] Processing {len(alerts_batch)} alerts...")
    
    for alert in alerts_batch:
        try:
            user_id = alert['user_id']
            alert_type = alert['type']
            alert_data = alert['data']
            
            if alert_type == 'weekly_digest':
                notifier.send_weekly_digest(user_id, alert_data)
            elif alert_type == 'trade':
                notifier.send_trade_alert(user_id, alert_data)
            elif alert_type == 'degradation':
                notifier.send_degradation_warning(user_id, alert_data)
            elif alert_type == 'replacement':
                notifier.send_replacement_complete_alert(user_id, alert_data)
            else:
                print(f"[BATCH ALERTS] Unknown type: {alert_type}")
                error_count += 1
                continue
            
            success_count += 1
            
            # Rate limit: 30 messages/second to Telegram
            # Sleep 0.04s = 25 messages/second (safe margin)
            time.sleep(0.04)
            
        except Exception as e:
            print(f"[BATCH ALERTS] ✗ Failed {user_id[:8]}...: {e}")
            error_count += 1
    
    print(f"[BATCH ALERTS] Complete: {success_count} sent, {error_count} failed")
    return {'success': success_count, 'errors': error_count}


def send_weekly_digests():
    """
    Send weekly digest to ALL users with Telegram connected
    Run this ONCE PER WEEK (Sunday night) via cron job
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    from services.watchlist_manager import WatchlistLeagueManager
    from flask import current_app
    
    print("\n" + "="*80)
    print("WEEKLY DIGEST ALERTS")
    print("="*80)
    
    supabase = get_supabase_client()
    manager = WatchlistLeagueManager()
    
    # Get all users with Telegram enabled
    result = supabase.schema(SCHEMA_NAME).table('telegram_users').select(
        'user_id, telegram_chat_id'
    ).eq('alerts_enabled', True).execute()
    
    users = result.data
    print(f"\n[WEEKLY DIGEST] Sending to {len(users)} users...")
    
    if not users:
        print("[WEEKLY DIGEST] No users with Telegram enabled")
        return
    
    # Split into batches of 100
    batch_size = 100
    alerts_batches = []
    
    for i in range(0, len(users), batch_size):
        batch = users[i:i+batch_size]
        alerts = []
        
        for user in batch:
            try:
                # Generate digest data for this user
                digest_data = manager.generate_weekly_digest(user['user_id'])
                
                alerts.append({
                    'user_id': user['user_id'],
                    'type': 'weekly_digest',
                    'data': digest_data
                })
            except Exception as e:
                print(f"[WEEKLY DIGEST] ⚠️ Failed to generate for {user['user_id'][:8]}...: {e}")
        
        if alerts:
            alerts_batches.append(alerts)
    
    # Queue batches across workers
    try:
        q = current_app.config['RQ_QUEUE']
        for batch in alerts_batches:
            q.enqueue('tasks.send_batch_telegram_alerts', batch)
        
        print(f"[WEEKLY DIGEST] ✓ Queued {len(alerts_batches)} batches")
    except Exception as e:
        print(f"[WEEKLY DIGEST] ✗ Queue failed: {e}")
        print("Falling back to direct send...")
        
        # Fallback: Send directly if queue fails
        for batch in alerts_batches:
            send_batch_telegram_alerts(batch)
    
    print("="*80 + "\n")