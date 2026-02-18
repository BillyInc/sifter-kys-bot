"""
RQ Worker Tasks - Fixed with depends_on for true parallelism
No worker ever blocks waiting for child jobs.
RQ handles dependency resolution internally via Redis.
"""
from redis import Redis
from rq import Queue
from rq.job import Job, Dependency
import json
import asyncio
import os
import time


def _get_redis():
    return Redis(host='localhost', port=6379)


def _get_queue():
    return Queue(connection=_get_redis(), default_timeout=600)


def _save_result(job_id, data):
    """Save job result to Redis with 1 hour TTL"""
    r = _get_redis()
    r.set(f"job_result:{job_id}", json.dumps(data), ex=3600)


def _load_result(job_id):
    """Load job result from Redis"""
    r = _get_redis()
    raw = r.get(f"job_result:{job_id}")
    return json.loads(raw) if raw else None


def _update_job_progress(supabase, job_id, phase, progress):
    from services.supabase_client import SCHEMA_NAME
    try:
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
            'phase': phase,
            'progress': progress
        }).eq('job_id', job_id).execute()
    except Exception as e:
        print(f"[PROGRESS] Failed to update progress: {e}")


def _calculate_grade(score):
    if score >= 90: return 'A+'
    if score >= 85: return 'A'
    if score >= 80: return 'A-'
    if score >= 75: return 'B+'
    if score >= 70: return 'B'
    if score >= 65: return 'B-'
    return 'C'


# =============================================================================
# ENTRY POINT - Called by Flask route, returns immediately
# =============================================================================

def perform_wallet_analysis(data):
    """
    Entry point. Does NOT run on a worker itself.
    Just queues the pipeline and returns job IDs immediately.
    Flask gets instant response, frontend polls for progress.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    tokens  = data.get('tokens', [])
    user_id = data.get('user_id', 'default_user')
    job_id  = data.get('job_id')

    supabase = get_supabase_client()
    q = _get_queue()

    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
        'status': 'processing',
        'phase': 'queuing',
        'progress': 5
    }).eq('job_id', job_id).execute()

    if len(tokens) == 1:
        _queue_single_token_pipeline(q, tokens[0], user_id, job_id, supabase)
    else:
        _queue_batch_pipeline(q, tokens, user_id, job_id, supabase)


def _queue_single_token_pipeline(q, token, user_id, job_id, supabase):
    """
    Queue single token 6-step pipeline using depends_on.
    No worker blocked. RQ triggers each phase automatically.

    Phase 1: Steps 1-4 run in parallel (4 workers)
    Phase 2: PnL batches run in parallel (depends on phase 1)
    Phase 3: Score + rank (depends on phase 2)
    """
    print(f"\n[PIPELINE] Queuing single token: {token.get('ticker')}")

    # ── PHASE 1: fetch data (4 parallel workers, no blocking) ────────────────
    job1 = q.enqueue('worker_tasks.fetch_top_traders',   {'token': token, 'job_id': job_id})
    job2 = q.enqueue('worker_tasks.fetch_first_buyers',  {'token': token, 'job_id': job_id})
    job3 = q.enqueue('worker_tasks.fetch_birdeye_trades',{'token': token, 'job_id': job_id})
    job4 = q.enqueue('worker_tasks.fetch_recent_trades', {'token': token, 'job_id': job_id})

    print(f"  ✓ Queued Phase 1 jobs: {[j.id[:8] for j in [job1,job2,job3,job4]]}")

    # ── PHASE 2: aggregate phase 1, then split PnL across workers ────────────
    # This job only starts when ALL 4 phase 1 jobs finish
    pnl_coordinator = q.enqueue(
        'worker_tasks.coordinate_pnl_phase',
        {
            'token':       token,
            'job_id':      job_id,
            'user_id':     user_id,
            'phase1_jobs': [job1.id, job2.id, job3.id, job4.id]
        },
        depends_on=Dependency(jobs=[job1, job2, job3, job4])
    )

    print(f"  ✓ Queued PnL coordinator: {pnl_coordinator.id[:8]} (waits for phase 1)")

    # ── PHASE 3: final scoring depends on PnL coordinator ────────────────────
    # coordinate_pnl_phase itself queues PnL batch jobs and then
    # queues the final scorer with depends_on those batches.
    # We store the pnl_coordinator job_id so the scorer can find it.

    # Store pipeline metadata in Redis so phases can find each other
    r = _get_redis()
    r.set(f"pipeline:{job_id}:coordinator", pnl_coordinator.id, ex=3600)
    r.set(f"pipeline:{job_id}:token", json.dumps(token), ex=3600)

    print(f"  ✓ Pipeline queued for {token.get('ticker')} - {job_id[:8]}")


def _queue_batch_pipeline(q, tokens, user_id, job_id, supabase):
    """
    Batch: each token gets its own full pipeline in parallel.
    Aggregation job depends on ALL token pipelines finishing.
    """
    print(f"\n[PIPELINE] Queuing batch: {len(tokens)} tokens")

    token_final_jobs = []

    for token in tokens:
        sub_job_id = f"{job_id}__{token['address'][:8]}"

        # Queue each token's full 6-step pipeline
        job1 = q.enqueue('worker_tasks.fetch_top_traders',    {'token': token, 'job_id': sub_job_id})
        job2 = q.enqueue('worker_tasks.fetch_first_buyers',   {'token': token, 'job_id': sub_job_id})
        job3 = q.enqueue('worker_tasks.fetch_birdeye_trades', {'token': token, 'job_id': sub_job_id})
        job4 = q.enqueue('worker_tasks.fetch_recent_trades',  {'token': token, 'job_id': sub_job_id})

        pnl_coordinator = q.enqueue(
            'worker_tasks.coordinate_pnl_phase',
            {
                'token':       token,
                'job_id':      sub_job_id,
                'user_id':     user_id,
                'phase1_jobs': [job1.id, job2.id, job3.id, job4.id]
            },
            depends_on=Dependency(jobs=[job1, job2, job3, job4])
        )

        # Final scorer for this token
        final_job = q.enqueue(
            'worker_tasks.score_and_rank_single',
            {
                'token':           token,
                'job_id':          sub_job_id,
                'parent_job_id':   job_id,
                'pnl_coord_id':    pnl_coordinator.id
            },
            depends_on=Dependency(jobs=[pnl_coordinator])
        )

        token_final_jobs.append(final_job)

        r = _get_redis()
        r.set(f"pipeline:{sub_job_id}:token", json.dumps(token), ex=3600)

        print(f"  ✓ Queued pipeline for {token.get('ticker')} [{sub_job_id[:8]}]")

    # Aggregate cross-token overlap - runs after ALL tokens finish
    aggregate_job = q.enqueue(
        'worker_tasks.aggregate_cross_token',
        {
            'tokens':        tokens,
            'job_id':        job_id,
            'sub_job_ids':   [f"{job_id}__{t['address'][:8]}" for t in tokens]
        },
        depends_on=Dependency(jobs=token_final_jobs)
    )

    print(f"  ✓ Queued cross-token aggregator: {aggregate_job.id[:8]} (waits for all {len(tokens)} tokens)")


# =============================================================================
# PHASE 1 WORKERS - All run simultaneously
# =============================================================================

def fetch_top_traders(data):
    """Worker: Fetch top 100 traders for token"""
    from routes.wallets import get_wallet_analyzer
    token  = data['token']
    job_id = data['job_id']

    analyzer = get_wallet_analyzer()
    url = f"{analyzer.st_base_url}/top-traders/{token['address']}"
    response = analyzer.fetch_with_retry(
        url, analyzer._get_solanatracker_headers(),
        semaphore=analyzer.solana_tracker_semaphore
    )

    wallets     = []
    wallet_data = {}

    if response:
        traders = response if isinstance(response, list) else []
        for trader in traders:
            wallet = trader.get('wallet')
            if wallet:
                wallets.append(wallet)
                # Use 6h cached PnL - won't burn credits if cached
                cached = analyzer._get_cached_pnl_and_entry(wallet, token['address'])
                wallet_data[wallet] = {
                    'source':         'top_traders',
                    'pnl_data':       trader,
                    'earliest_entry': cached['first_buy_time'] if cached else None,
                    'entry_price':    cached['entry_price']    if cached else None,
                }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'top_traders'}
    _save_result(f"phase1_top_traders:{job_id}", result)
    print(f"[WORKER] top_traders done: {len(wallets)} wallets")
    return result


def fetch_first_buyers(data):
    """Worker: Fetch first buyers for token"""
    from routes.wallets import get_wallet_analyzer
    token  = data['token']
    job_id = data['job_id']

    analyzer = get_wallet_analyzer()
    url = f"{analyzer.st_base_url}/first-buyers/{token['address']}"
    response = analyzer.fetch_with_retry(
        url, analyzer._get_solanatracker_headers(),
        semaphore=analyzer.solana_tracker_semaphore
    )

    wallets     = []
    wallet_data = {}

    if response:
        buyers = response if isinstance(response, list) else response.get('buyers', [])
        first_buyer_wallets = [b.get('wallet') for b in buyers if b.get('wallet')]

        # Async fetch entry prices
        results = asyncio.run(
            analyzer._async_fetch_first_buys(first_buyer_wallets, token['address'])
        )

        for buyer, first_buy in zip(buyers, results):
            wallet = buyer.get('wallet')
            if wallet:
                wallets.append(wallet)
                wallet_data[wallet] = {
                    'source':         'first_buyers',
                    'pnl_data':       buyer,
                    'earliest_entry': buyer.get('first_buy_time', 0),
                    'entry_price':    first_buy['price'] if first_buy else None,
                }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'first_buyers'}
    _save_result(f"phase1_first_buyers:{job_id}", result)
    print(f"[WORKER] first_buyers done: {len(wallets)} wallets")
    return result


def fetch_birdeye_trades(data):
    """Worker: Fetch 30-day Birdeye trades"""
    from routes.wallets import get_wallet_analyzer
    token  = data['token']
    job_id = data['job_id']

    analyzer    = get_wallet_analyzer()
    current_time = int(time.time())
    after_time   = current_time - (30 * 86400)
    all_trades   = []
    offset       = 0

    while offset < 10000:
        params   = {"address": token['address'], "offset": offset, "limit": 100, "after_time": after_time}
        response = analyzer.fetch_with_retry(
            f"{analyzer.birdeye_base_url}/defi/v3/token/txs",
            analyzer._get_birdeye_headers(), params,
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

    wallets     = []
    wallet_data = {}
    for trade in all_trades:
        wallet = trade.get('owner')
        if wallet and wallet not in wallet_data:
            wallets.append(wallet)
            wallet_data[wallet] = {
                'source':         'birdeye_trades',
                'earliest_entry': trade.get('block_unix_time'),
                'entry_price':    trade.get('price_pair'),
            }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'birdeye_trades'}
    _save_result(f"phase1_birdeye:{job_id}", result)
    print(f"[WORKER] birdeye_trades done: {len(wallets)} wallets")
    return result


def fetch_recent_trades(data):
    """Worker: Fetch recent trades from SolanaTracker"""
    from routes.wallets import get_wallet_analyzer
    token  = data['token']
    job_id = data['job_id']

    analyzer = get_wallet_analyzer()
    url    = f"{analyzer.st_base_url}/trades/{token['address']}"
    params = {"sortDirection": "DESC", "limit": 100}
    response = analyzer.fetch_with_retry(
        url, analyzer._get_solanatracker_headers(), params,
        semaphore=analyzer.solana_tracker_semaphore
    )

    wallets     = []
    wallet_data = {}
    if response:
        for trade in response.get('trades', [])[:500]:
            wallet = trade.get('wallet')
            if wallet and wallet not in wallet_data:
                wallets.append(wallet)
                wallet_data[wallet] = {
                    'source':         'solana_recent',
                    'earliest_entry': trade.get('time', 0),
                    'entry_price':    None,
                }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'recent_trades'}
    _save_result(f"phase1_recent:{job_id}", result)
    print(f"[WORKER] recent_trades done: {len(wallets)} wallets")
    return result


# =============================================================================
# PHASE 2 COORDINATOR - Triggered by RQ when phase 1 finishes
# No worker blocked - it just merges results and queues PnL jobs
# =============================================================================

def coordinate_pnl_phase(data):
    """
    Runs ONCE when all 4 phase 1 jobs finish.
    Merges wallet lists, queues PnL batches with depends_on,
    then queues final scorer.
    No polling loop - this job runs fast and exits.
    """
    token        = data['token']
    job_id       = data['job_id']
    user_id      = data.get('user_id', 'default_user')
    phase1_jobs  = data['phase1_jobs']

    print(f"\n[COORDINATOR] Phase 1 complete for {token.get('ticker')} - merging wallets...")

    # Load all phase 1 results
    all_wallets = []
    wallet_data = {}

    for key_prefix in ['phase1_top_traders', 'phase1_first_buyers', 'phase1_birdeye', 'phase1_recent']:
        result = _load_result(f"{key_prefix}:{job_id}")
        if result:
            for wallet in result['wallets']:
                if wallet not in wallet_data:
                    all_wallets.append(wallet)
                    wallet_data[wallet] = result['wallet_data'].get(wallet, {})
                else:
                    # Merge: prefer richer source
                    existing = wallet_data[wallet]
                    new      = result['wallet_data'].get(wallet, {})
                    if new.get('entry_price') and not existing.get('entry_price'):
                        existing['entry_price'] = new['entry_price']
                    if new.get('pnl_data') and not existing.get('pnl_data'):
                        existing['pnl_data'] = new['pnl_data']

    print(f"  ✓ Merged: {len(all_wallets)} unique wallets")

    # Save merged wallet list for PnL workers
    _save_result(f"phase1_merged:{job_id}", {
        'wallets':     all_wallets,
        'wallet_data': wallet_data
    })

    # Split wallets across PnL batch workers
    q          = _get_queue()
    batch_size = max(1, len(all_wallets) // 5)  # 5 workers
    pnl_jobs   = []

    for i in range(0, len(all_wallets), batch_size):
        batch        = all_wallets[i:i + batch_size]
        batch_wallets = {w: wallet_data[w] for w in batch}

        pnl_job = q.enqueue(
            'worker_tasks.fetch_pnl_batch',
            {
                'token':      token,
                'job_id':     job_id,
                'batch_idx':  i // batch_size,
                'wallets':    batch,
                'wallet_data': batch_wallets
            }
        )
        pnl_jobs.append(pnl_job)

    print(f"  ✓ Queued {len(pnl_jobs)} PnL batch jobs")

    # Queue final scorer - depends on ALL PnL batches
    final_job = q.enqueue(
        'worker_tasks.score_and_rank_single',
        {
            'token':        token,
            'job_id':       job_id,
            'user_id':      user_id,
            'pnl_job_ids':  [j.id for j in pnl_jobs],
            'batch_count':  len(pnl_jobs)
        },
        depends_on=Dependency(jobs=pnl_jobs)
    )

    print(f"  ✓ Queued scorer: {final_job.id[:8]} (waits for {len(pnl_jobs)} PnL batches)")

    # Store final job ID so batch aggregator can find it
    r = _get_redis()
    r.set(f"pipeline:{job_id}:final_job", final_job.id, ex=3600)

    return {'pnl_jobs': [j.id for j in pnl_jobs], 'final_job': final_job.id}


# =============================================================================
# PHASE 2 WORKERS - PnL batches run in parallel
# =============================================================================

def fetch_pnl_batch(data):
    """Worker: Fetch PnL for a batch of wallets"""
    from routes.wallets import get_wallet_analyzer
    import aiohttp
    from asyncio import Semaphore as AsyncSemaphore

    token      = data['token']
    job_id     = data['job_id']
    batch_idx  = data['batch_idx']
    wallets    = data['wallets']
    wallet_data = data['wallet_data']

    analyzer  = get_wallet_analyzer()
    qualified = []

    # Wallets that already have PnL data (from top_traders source)
    already_have_pnl = []
    need_fetch       = []

    for wallet in wallets:
        wdata = wallet_data.get(wallet, {})
        if wdata.get('pnl_data') and wdata['pnl_data'].get('realized') is not None:
            already_have_pnl.append(wallet)
        else:
            need_fetch.append(wallet)

    print(f"[PNL BATCH {batch_idx}] {len(wallets)} wallets | {len(already_have_pnl)} cached | {len(need_fetch)} to fetch")

    # Process wallets that already have PnL
    for wallet in already_have_pnl:
        pnl = wallet_data[wallet]['pnl_data']
        _qualify_wallet(wallet, pnl, wallet_data, token, qualified)

    # Async fetch remaining PnLs in parallel
    async def _fetch_all():
        async with aiohttp.ClientSession() as session:
            sem   = AsyncSemaphore(2)  # Free tier: 2 concurrent max
            tasks = []
            for wallet in need_fetch:
                async def fetch(w=wallet):
                    async with sem:
                        return await analyzer.async_fetch_with_retry(
                            session,
                            f"{analyzer.st_base_url}/pnl/{w}/{token['address']}",
                            analyzer._get_solanatracker_headers()
                        )
                tasks.append(fetch())
            return await asyncio.gather(*tasks)

    if need_fetch:
        results = asyncio.run(_fetch_all())
        for wallet, pnl in zip(need_fetch, results):
            if pnl:
                _qualify_wallet(wallet, pnl, wallet_data, token, qualified)

    _save_result(f"pnl_batch:{job_id}:{batch_idx}", qualified)
    print(f"[PNL BATCH {batch_idx}] Done: {len(qualified)} qualified")
    return qualified


def _qualify_wallet(wallet, pnl_data, wallet_data, token, qualified_list, min_invested=100, min_roi_mult=3.0):
    """Helper: check if wallet meets criteria and add to qualified list"""
    realized      = pnl_data.get('realized', 0)
    unrealized    = pnl_data.get('unrealized', 0)
    total_invested = pnl_data.get('total_invested') or pnl_data.get('totalInvested', 0)

    if total_invested < min_invested:
        return

    realized_mult = (realized + total_invested) / total_invested
    total_mult    = (realized + unrealized + total_invested) / total_invested

    if realized_mult >= min_roi_mult:
        wdata = wallet_data.get(wallet, {})
        qualified_list.append({
            'wallet':             wallet,
            'source':             wdata.get('source', 'unknown'),
            'realized':           realized,
            'unrealized':         unrealized,
            'total_invested':     total_invested,
            'realized_multiplier': realized_mult,
            'total_multiplier':   total_mult,
            'earliest_entry':     wdata.get('earliest_entry'),
            'entry_price':        wdata.get('entry_price'),
        })


# =============================================================================
# PHASE 3: SCORE + RANK - Triggered when all PnL batches finish
# =============================================================================

def score_and_rank_single(data):
    """
    Final step for single token.
    Collects all PnL batch results, scores, ranks, saves to Supabase.
    """
    from routes.wallets import get_wallet_analyzer
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    token       = data['token']
    job_id      = data['job_id']
    user_id     = data.get('user_id', 'default_user')
    batch_count = data['batch_count']
    parent_job  = data.get('parent_job_id')  # Only set in batch mode

    print(f"\n[SCORER] Scoring {token.get('ticker')} - collecting {batch_count} PnL batches...")

    analyzer = get_wallet_analyzer()
    supabase = get_supabase_client()

    # Collect all qualified wallets from PnL batches
    qualified_wallets = []
    for i in range(batch_count):
        batch_result = _load_result(f"pnl_batch:{job_id}:{i}")
        if batch_result:
            qualified_wallets.extend(batch_result)

    print(f"  ✓ {len(qualified_wallets)} qualified wallets to score")

    # Get ATH (24h cached - won't burn credits)
    ath_data  = analyzer.get_token_ath(token['address'])
    ath_price = ath_data.get('highest_price', 0) if ath_data else 0

    wallet_results = []

    for wallet_info in qualified_wallets:
        wallet_addr = wallet_info['wallet']

        # 12h cached runner history
        runner_history = analyzer._get_cached_other_runners(
            wallet_addr,
            current_token=token['address'],
            min_multiplier=10.0
        )

        wallet_info['ath_price'] = ath_price
        scoring = analyzer.calculate_wallet_relative_score(wallet_info)

        if scoring['professional_score'] >= 90:   tier = 'S'
        elif scoring['professional_score'] >= 80: tier = 'A'
        elif scoring['professional_score'] >= 70: tier = 'B'
        else:                                     tier = 'C'

        wallet_results.append({
            'wallet':                wallet_addr,
            'source':                wallet_info['source'],
            'tier':                  tier,
            'roi_percent':           round((wallet_info['realized_multiplier'] - 1) * 100, 2),
            'roi_multiplier':        round(wallet_info['realized_multiplier'], 2),
            'entry_to_ath_multiplier': scoring.get('entry_to_ath_multiplier'),
            'distance_to_ath_pct':   scoring.get('distance_to_ath_pct'),
            'realized_profit':       wallet_info['realized'],
            'unrealized_profit':     wallet_info['unrealized'],
            'total_invested':        wallet_info['total_invested'],
            'realized_multiplier':   scoring.get('realized_multiplier'),
            'total_multiplier':      scoring.get('total_multiplier'),
            'professional_score':    scoring['professional_score'],
            'professional_grade':    scoring['professional_grade'],
            'score_breakdown':       scoring['score_breakdown'],
            'runner_hits_30d':       runner_history['stats'].get('total_other_runners', 0),
            'runner_success_rate':   runner_history['stats'].get('success_rate', 0),
            'runner_avg_roi':        runner_history['stats'].get('avg_roi', 0),
            'other_runners':         runner_history['other_runners'][:5],
            'other_runners_stats':   runner_history['stats'],
            'first_buy_time':        wallet_info.get('earliest_entry'),
            'entry_price':           wallet_info.get('entry_price'),
            'ath_price':             ath_price,
            'is_fresh':              True,
        })

    wallet_results.sort(key=lambda x: x['professional_score'], reverse=True)

    result = {
        'success': True,
        'token':   token,
        'wallets': wallet_results[:50],
        'total':   len(wallet_results),
    }

    # Save for batch aggregator to collect
    _save_result(f"token_result:{job_id}", result)

    # If this is a standalone single-token analysis, update Supabase now
    if not parent_job:
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
            'status':   'completed',
            'phase':    'done',
            'progress': 100,
            'results':  result
        }).eq('job_id', job_id).execute()
        print(f"  ✅ Single token analysis complete: {len(wallet_results)} wallets")

    return result


# =============================================================================
# BATCH AGGREGATOR - Cross-token overlap ranking
# Triggered by RQ when ALL token pipelines finish
# =============================================================================

def aggregate_cross_token(data):
    """
    Collect results from all token pipelines.
    Rank by cross-token appearance first, then aggregate score.
    Triggered automatically by RQ when all token final jobs finish.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    from collections import defaultdict

    tokens      = data['tokens']
    job_id      = data['job_id']
    sub_job_ids = data['sub_job_ids']

    supabase = get_supabase_client()

    print(f"\n[AGGREGATOR] Cross-token ranking for {len(tokens)} tokens...")

    # Collect all per-token results
    all_token_results = []
    for sub_job_id in sub_job_ids:
        result = _load_result(f"token_result:{sub_job_id}")
        if result:
            all_token_results.append(result)

    print(f"  ✓ Loaded {len(all_token_results)}/{len(tokens)} token results")

    # Build cross-token wallet map
    wallet_hits = defaultdict(lambda: {
        'wallet':              None,
        'runners_hit':         [],
        'runners_hit_addresses': set(),
        'roi_details':         [],
        'professional_scores': [],
        'entry_to_ath_vals':   [],
        'distance_to_ath_vals':[],
        'roi_multipliers':     [],
    })

    for token_result in all_token_results:
        token = token_result['token']
        for wallet in token_result['wallets']:
            addr = wallet['wallet']
            if wallet_hits[addr]['wallet'] is None:
                wallet_hits[addr]['wallet'] = addr

            sym = token.get('ticker', token.get('symbol', '?'))
            if sym not in wallet_hits[addr]['runners_hit']:
                wallet_hits[addr]['runners_hit'].append(sym)
                wallet_hits[addr]['runners_hit_addresses'].add(token['address'])

            wallet_hits[addr]['roi_details'].append({
                'runner':             sym,
                'runner_address':     token['address'],
                'roi_multiplier':     wallet.get('roi_multiplier', 0),
                'professional_score': wallet.get('professional_score', 0),
                'professional_grade': wallet.get('professional_grade', 'F'),
                'entry_to_ath_multiplier': wallet.get('entry_to_ath_multiplier'),
                'distance_to_ath_pct':    wallet.get('distance_to_ath_pct'),
            })

            wallet_hits[addr]['professional_scores'].append(wallet['professional_score'])
            if wallet.get('entry_to_ath_multiplier'):
                wallet_hits[addr]['entry_to_ath_vals'].append(wallet['entry_to_ath_multiplier'])
            if wallet.get('distance_to_ath_pct'):
                wallet_hits[addr]['distance_to_ath_vals'].append(wallet['distance_to_ath_pct'])
            wallet_hits[addr]['roi_multipliers'].append(wallet.get('roi_multiplier', 0))

    # Rank: cross-token first, then aggregate score
    ranked = []
    for addr, d in wallet_hits.items():
        n        = len(d['professional_scores'])
        avg_score = sum(d['professional_scores']) / n if n else 0
        avg_dist  = sum(d['distance_to_ath_vals']) / len(d['distance_to_ath_vals']) if d['distance_to_ath_vals'] else 0
        avg_roi   = sum(d['roi_multipliers']) / len(d['roi_multipliers']) if d['roi_multipliers'] else 0
        avg_ath   = sum(d['entry_to_ath_vals']) / len(d['entry_to_ath_vals']) if d['entry_to_ath_vals'] else None

        aggregate_score = (0.60 * avg_dist) + (0.30 * (avg_roi / 10 * 100)) + (0.10 * avg_score)

        runner_count = len(d['runners_hit'])
        participation = runner_count / len(tokens)
        if participation >= 0.8 and aggregate_score >= 85:   tier = 'S'
        elif participation >= 0.6 and aggregate_score >= 75: tier = 'A'
        elif participation >= 0.4 and aggregate_score >= 65: tier = 'B'
        else:                                                 tier = 'C'

        ranked.append({
            'wallet':                  addr,
            'runner_count':            runner_count,
            'runners_hit':             d['runners_hit'],
            'avg_professional_score':  round(avg_score, 2),
            'avg_distance_to_ath_pct': round(avg_dist, 2),
            'avg_roi':                 round(avg_roi, 2),
            'avg_entry_to_ath_multiplier': round(avg_ath, 2) if avg_ath else None,
            'aggregate_score':         round(aggregate_score, 2),
            'tier':                    tier,
            'professional_grade':      _calculate_grade(avg_score),
            'roi_details':             d['roi_details'][:5],
            'is_fresh':                True,

            # Frontend compatibility
            'analyzed_tokens':  d['runners_hit'],
            'other_runners': [
                {
                    'symbol':             p['runner'],
                    'multiplier':         p.get('roi_multiplier', 0),
                    'roi_multiplier':     p.get('roi_multiplier', 0),
                    'professional_score': p['professional_score'],
                }
                for p in d['roi_details']
            ],
        })

    # Primary sort: cross-token appearance count, then aggregate score
    ranked.sort(key=lambda x: (x['runner_count'], x['aggregate_score']), reverse=True)

    # Fallback if no overlap
    if not any(r['runner_count'] > 1 for r in ranked):
        print(f"  ⚠️ No cross-token overlap - ranking by individual score")
        ranked.sort(key=lambda x: x['aggregate_score'], reverse=True)
        for r in ranked:
            r['no_overlap_fallback'] = True

    final_result = {
        'success': True,
        'wallets': ranked[:50],
        'total':   len(ranked),
    }

    # Update Supabase - job complete
    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
        'status':   'completed',
        'phase':    'done',
        'progress': 100,
        'results':  final_result
    }).eq('job_id', job_id).execute()

    print(f"  ✅ Batch complete: {len(ranked)} wallets ranked by cross-token overlap")
    return final_result


# =============================================================================
# CACHE WARMUP - Startup only, runner LISTS not full analysis
# =============================================================================

def preload_trending_cache():
    """Queue cache warmup jobs - runner lists only, no full analysis"""
    q = _get_queue()

    job7  = q.enqueue('worker_tasks.warm_cache_runners', {'days_back': 7})
    job14 = q.enqueue('worker_tasks.warm_cache_runners', {'days_back': 14})

    print(f"[CACHE WARMUP] Queued 7d and 14d runner list warmup")
    return [job7.id, job14.id]


def warm_cache_runners(data):
    """Worker: Cache runner list only - NO full analysis"""
    from routes.wallets import get_wallet_analyzer
    days_back = data['days_back']
    analyzer  = get_wallet_analyzer()

    print(f"[WARMUP {days_back}D] Finding runners...")
    runners = analyzer.find_trending_runners_enhanced(
        days_back=days_back,
        min_multiplier=5.0,
        min_liquidity=50000
    )
    print(f"  ✅ Cached {len(runners)} runners for {days_back}d (lists only)")
    return len(runners)