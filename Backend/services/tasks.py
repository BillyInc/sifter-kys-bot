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