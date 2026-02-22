"""
RQ Worker Tasks - Production Ready with Debug Logging
Fixes applied:
  1. Supabase cache check before queuing any pipeline (instant results for repeat searches)
  2. Queue separation: high / batch / compute (no deadlocks, priority guaranteed)
  3. Fixed batch_size = 10 (was // 5, left workers idle)
  4. Coordinators always go to compute queue (deadlock prevention)
  5. Batch workers always go to batch queue
  6. Phase 1 workers always go to high queue
  7. Qualification accepts realized OR total multiplier >= threshold (holders qualify)
  8. Batch mode caches each token individually to Supabase for future single-token lookups
  9. Cache warming writes to Redis, not just memory
  10. Workers now use Redis ONLY - DuckDB disabled via WORKER_MODE env var
  11. Per-token qualified wallet cache in Supabase (saves ALL qualifying wallets before scoring)
  12. Batch pipeline checks Supabase cache per token — skips Phases 1-4 for cached tokens
  13. aggregate_cross_token triggered by counter in merge_and_save_final (fixes race condition)
  14. min_runner_hits filter applied in aggregate_cross_token (mirrors wallet_analyzer.py)
  15. Batch aggregate scoring: 60% entry timing | 30% total ROI | 10% entry consistency
  16. Ranking: cross-token wallets first, single-token wallets fill remaining slots to 20
  17. perform_trending_batch_analysis now uses _queue_batch_pipeline (parallel distributed)
  18. perform_auto_discovery now fetches runners then uses _queue_batch_pipeline (parallel)
  19. score_and_rank_single in batch mode: saves ALL qualified wallets to Supabase
  20. Sample size preserved: no per-token top-20 cut in batch mode
  21. Runner history fetched AFTER cross-token correlation for final top 20 wallets
  22. RACE CONDITION FIX: score_and_rank_single queued INSIDE coordinate_pnl_phase
  23. Birdeye removed — Worker 3 replaced with fetch_top_holders
  24. aggregate_cross_token: cross-token wallets ranked first, single-token fill to 20
  25. CACHE VALIDATION: Empty/invalid cached results detected and deleted
  26. DEBUG LOGGING: Entry price failures, qualification failures, and failed wallets logged

SUPABASE TABLE REQUIRED:
  CREATE TABLE token_qualified_wallets (
    token_address TEXT PRIMARY KEY,
    qualified_wallets JSONB,
    wallet_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
"""

from redis import Redis
from rq import Queue
from rq.job import Job, Dependency
import json
import asyncio
import os
import time
import uuid
import statistics
from collections import defaultdict


# =============================================================================
# REDIS + QUEUE SETUP
# =============================================================================

def _get_redis():
    url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    return Redis.from_url(url, socket_timeout=10, socket_connect_timeout=10)


def _get_queues():
    """Return high, batch, compute queues. Always use these — never default queue."""
    r = _get_redis()
    return (
        Queue('high',    connection=r, default_timeout=1800),
        Queue('batch',   connection=r, default_timeout=1800),
        Queue('compute', connection=r, default_timeout=1800),
    )


def _save_result(job_id, data):
    """Save job result to Redis with 1 hour TTL."""
    r = _get_redis()
    r.set(f"job_result:{job_id}", json.dumps(data), ex=3600)


def _load_result(job_id):
    """Load job result from Redis."""
    r = _get_redis()
    raw = r.get(f"job_result:{job_id}")
    return json.loads(raw) if raw else None


def _update_job_progress(supabase, job_id, phase, progress, tokens_completed=None, tokens_total=None):
    from services.supabase_client import SCHEMA_NAME
    try:
        update_data = {'phase': phase, 'progress': progress}
        if tokens_completed is not None:
            update_data['tokens_completed'] = tokens_completed
        if tokens_total is not None:
            update_data['tokens_total'] = tokens_total
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update(
            update_data
        ).eq('job_id', job_id).execute()
    except Exception as e:
        print(f"[PROGRESS] Failed to update: {e}")


def _calculate_grade(score):
    if score >= 90: return 'A+'
    if score >= 85: return 'A'
    if score >= 80: return 'A-'
    if score >= 75: return 'B+'
    if score >= 70: return 'B'
    if score >= 65: return 'B-'
    return 'C'


# =============================================================================
# SUPABASE PER-TOKEN QUALIFIED WALLET CACHE
# =============================================================================

def _save_qualified_wallets_cache(token_address, qualified_wallets):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    supabase = get_supabase_client()
    try:
        supabase.schema(SCHEMA_NAME).table('token_qualified_wallets').upsert({
            'token_address':     token_address,
            'qualified_wallets': qualified_wallets,
            'wallet_count':      len(qualified_wallets),
            'created_at':        time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }).execute()
        print(f"[CACHE] Saved {len(qualified_wallets)} qualified wallets for {token_address[:8]}")
    except Exception as e:
        print(f"[CACHE] Failed to save qualified wallets for {token_address[:8]}: {e}")


def _get_qualified_wallets_cache(token_address):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    supabase = get_supabase_client()
    try:
        result = supabase.schema(SCHEMA_NAME).table('token_qualified_wallets').select(
            'qualified_wallets, created_at'
        ).eq('token_address', token_address).execute()
        if result.data and result.data[0].get('qualified_wallets'):
            wallets = result.data[0]['qualified_wallets']
            # Validate that cached wallets have data
            if wallets and len(wallets) > 0:
                print(f"[CACHE HIT] {len(wallets)} qualified wallets for {token_address[:8]}")
                return wallets
            else:
                print(f"[CACHE INVALID] Empty wallets for {token_address[:8]} — deleting")
                supabase.schema(SCHEMA_NAME).table('token_qualified_wallets').delete().eq(
                    'token_address', token_address
                ).execute()
                return None
    except Exception as e:
        print(f"[CACHE] Failed to read qualified wallets for {token_address[:8]}: {e}")
    return None


# =============================================================================
# WORKER ANALYZER GETTER - Redis-only mode
# =============================================================================

def get_worker_analyzer():
    from routes.wallets import get_worker_analyzer as get_analyzer
    os.environ['WORKER_MODE'] = 'true'
    return get_analyzer()


# =============================================================================
# ENTRY POINT
# =============================================================================

def perform_wallet_analysis(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    tokens  = data.get('tokens', [])
    user_id = data.get('user_id', 'default_user')
    job_id  = data.get('job_id')

    supabase = get_supabase_client()
    r        = _get_redis()
    q_high, q_batch, q_compute = _get_queues()

    if len(tokens) == 1:
        token         = tokens[0]
        token_address = token['address']

        cached = r.get(f"cache:token:{token_address}")
        if cached:
            cached_result = json.loads(cached)
            skip_cache = False
            
            # Validate cached result has actual wallet data
            if not cached_result.get('wallets') or len(cached_result.get('wallets', [])) == 0:
                print(f"[CACHE INVALID] Redis cache empty for {token.get('ticker')} — deleting")
                r.delete(f"cache:token:{token_address}")
                skip_cache = True
            else:
                try:
                    current_ath_raw = r.get(f"token_ath:{token_address}")
                    if current_ath_raw:
                        current_ath_price = json.loads(current_ath_raw).get('highest_price', 0)
                        cached_wallets = cached_result.get('wallets', [])
                        cached_ath = next(
                            (w.get('ath_price', 0) for w in cached_wallets if w.get('ath_price')), 0
                        )
                        if cached_ath > 0 and current_ath_price > cached_ath * 1.10:
                            print(f"[CACHE INVALIDATED] ATH moved for {token.get('ticker')} — running fresh")
                            skip_cache = True
                            r.delete(f"cache:token:{token_address}")
                except Exception as e:
                    print(f"[CACHE] ATH check failed — serving cached result: {e}")

            if not skip_cache:
                print(f"[CACHE HIT] Redis — instant return for {token.get('ticker')}")
                try:
                    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                        'status': 'completed', 'phase': 'done', 'progress': 100,
                        'results': cached_result
                    }).eq('job_id', job_id).execute()
                except Exception as e:
                    print(f"[CACHE] Failed to update job: {e}")
                return

        if not (cached and skip_cache):
            try:
                existing = supabase.schema(SCHEMA_NAME).table('analysis_jobs').select(
                    'results'
                ).eq('token_address', token_address).eq(
                    'status', 'completed'
                ).order('created_at', desc=True).limit(1).execute()

                if existing.data and existing.data[0].get('results'):
                    result = existing.data[0]['results']
                    
                    # Validate Supabase result has actual wallet data
                    if result.get('wallets') and len(result.get('wallets', [])) > 0:
                        print(f"[CACHE HIT] Supabase — returning saved result for {token.get('ticker')}")
                        r.set(f"cache:token:{token_address}", json.dumps(result), ex=21600)
                        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                            'status': 'completed', 'phase': 'done', 'progress': 100,
                            'results': result
                        }).eq('job_id', job_id).execute()
                        return
                    else:
                        print(f"[CACHE INVALID] Supabase result empty for {token.get('ticker')} — deleting")
                        supabase.schema(SCHEMA_NAME).table('token_qualified_wallets').delete().eq(
                            'token_address', token_address
                        ).execute()
            except Exception as e:
                print(f"[CACHE CHECK] Supabase lookup failed — running fresh: {e}")

    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
        'status': 'processing', 'phase': 'queuing', 'progress': 5
    }).eq('job_id', job_id).execute()

    if len(tokens) == 1:
        _queue_single_token_pipeline(tokens[0], user_id, job_id, supabase)
    else:
        _queue_batch_pipeline(tokens, user_id, job_id, supabase)


def _queue_single_token_pipeline(token, user_id, job_id, supabase):
    print(f"\n[PIPELINE] Queuing single token: {token.get('ticker')}")
    q_high, q_batch, q_compute = _get_queues()

    job1 = q_high.enqueue('services.worker_tasks.fetch_top_traders',  {'token': token, 'job_id': job_id})
    job2 = q_high.enqueue('services.worker_tasks.fetch_first_buyers', {'token': token, 'job_id': job_id})
    job3 = q_high.enqueue('services.worker_tasks.fetch_top_holders',  {'token': token, 'job_id': job_id})

    job4_coord = q_compute.enqueue(
        'services.worker_tasks.coordinate_entry_prices',
        {'token': token, 'job_id': job_id},
        depends_on=Dependency(jobs=[job1])
    )

    # NOTE: score_and_rank_single is NOT queued here.
    # coordinate_pnl_phase queues it internally with depends_on=pnl_jobs
    # so it correctly waits for all PnL batch workers to finish.
    pnl_coordinator = q_compute.enqueue(
        'services.worker_tasks.coordinate_pnl_phase',
        {
            'token':         token,
            'job_id':        job_id,
            'user_id':       user_id,
            'parent_job_id': None,   # single token mode
            'phase1_jobs':   [job1.id, job2.id, job3.id, job4_coord.id]
        },
        depends_on=Dependency(jobs=[job1, job2, job3, job4_coord])
    )

    r = _get_redis()
    r.set(f"pipeline:{job_id}:coordinator", pnl_coordinator.id, ex=3600)
    r.set(f"pipeline:{job_id}:token",       json.dumps(token),  ex=3600)

    print(f"  ✓ Phase 1: {[j.id[:8] for j in [job1, job2, job3]]}")
    print(f"  ✓ Entry coord: {job4_coord.id[:8]} | PnL coord: {pnl_coordinator.id[:8]}")
    print(f"  ✓ Scorer will be queued by coordinate_pnl_phase after PnL batches complete")


def _queue_batch_pipeline(tokens, user_id, job_id, supabase, min_runner_hits=2):
    """
    Queue full pipeline per token in parallel across all workers.

    RACE CONDITION FIX:
      score_and_rank_single is now queued INSIDE coordinate_pnl_phase with
      depends_on=pnl_jobs (the actual PnL batch workers), not the coordinator.
      parent_job_id is passed through so batch mode is preserved.

    BATCH MODE SCORING FLOW:
      Phase 1-3: fetch wallets per token (parallel across workers)
      score_and_rank_single (batch mode):
        - saves ALL qualified wallets to Supabase
        - saves raw qualified wallet data to Redis for aggregator
        - does NOT score or rank
      aggregate_cross_token:
        - loads raw qualified wallets per token from Redis
        - finds cross-token wallets, scores with 60/30/10 (aggregate score)
        - scores remaining single-token wallets individually (professional_score)
        - merges: cross-token first, fill to 20 with best single-token
        - tags each wallet with is_cross_token for frontend display
    """
    print(f"\n[PIPELINE] Queuing batch: {len(tokens)} tokens")
    q_high, q_batch, q_compute = _get_queues()
    r = _get_redis()

    sub_job_ids = [f"{job_id}__{t['address'][:8]}" for t in tokens]

    r.set(f"batch_total:{job_id}",           len(tokens),             ex=7200)
    r.set(f"batch_sub_jobs:{job_id}",        json.dumps(sub_job_ids), ex=7200)
    r.set(f"batch_tokens:{job_id}",          json.dumps(tokens),      ex=7200)
    r.set(f"batch_completed:{job_id}",       0,                       ex=7200)
    r.set(f"batch_min_runner_hits:{job_id}", min_runner_hits,         ex=7200)
    r.set(f"batch_user_id:{job_id}",         user_id,                 ex=7200)

    for token, sub_job_id in zip(tokens, sub_job_ids):
        r.set(f"pipeline:{sub_job_id}:token", json.dumps(token), ex=3600)

        cached_wallets = _get_qualified_wallets_cache(token['address'])

        if cached_wallets:
            print(f"  ✓ CACHE HIT for {token.get('ticker')} — skipping Phases 1-4")
            q_compute.enqueue(
                'services.worker_tasks.fetch_from_token_cache',
                {
                    'token':         token,
                    'job_id':        sub_job_id,
                    'parent_job_id': job_id,
                    'user_id':       user_id,
                }
            )
        else:
            job1 = q_high.enqueue('services.worker_tasks.fetch_top_traders',  {'token': token, 'job_id': sub_job_id})
            job2 = q_high.enqueue('services.worker_tasks.fetch_first_buyers', {'token': token, 'job_id': sub_job_id})
            job3 = q_high.enqueue('services.worker_tasks.fetch_top_holders',  {'token': token, 'job_id': sub_job_id})

            job4_coord = q_compute.enqueue(
                'services.worker_tasks.coordinate_entry_prices',
                {'token': token, 'job_id': sub_job_id},
                depends_on=Dependency(jobs=[job1])
            )

            # score_and_rank_single queued inside coordinate_pnl_phase — see fix note above
            q_compute.enqueue(
                'services.worker_tasks.coordinate_pnl_phase',
                {
                    'token':         token,
                    'job_id':        sub_job_id,
                    'user_id':       user_id,
                    'parent_job_id': job_id,   # ← threaded through for batch mode
                    'phase1_jobs':   [job1.id, job2.id, job3.id, job4_coord.id]
                },
                depends_on=Dependency(jobs=[job1, job2, job3, job4_coord])
            )

            print(f"  ✓ Full pipeline for {token.get('ticker')} [{sub_job_id[:8]}]")

    print(f"  ✓ Aggregator will trigger automatically when all {len(tokens)} tokens complete")


# =============================================================================
# TRENDING BATCH ANALYSIS
# =============================================================================

def perform_trending_batch_analysis(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    runners         = data.get('runners', [])
    user_id         = data.get('user_id', 'default_user')
    min_runner_hits = data.get('min_runner_hits', 2)
    job_id          = data.get('job_id')

    supabase = get_supabase_client()

    print(f"\n[TRENDING BATCH] Starting distributed analysis of {len(runners)} runners")

    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
        'status':           'processing',
        'phase':            'queuing_pipeline',
        'progress':         10,
        'tokens_total':     len(runners),
        'tokens_completed': 0
    }).eq('job_id', job_id).execute()

    tokens = [
        {
            'address': r['address'],
            'ticker':  r.get('symbol', r.get('ticker', 'UNKNOWN')),
            'symbol':  r.get('symbol', r.get('ticker', 'UNKNOWN')),
        }
        for r in runners
    ]

    _queue_batch_pipeline(tokens, user_id, job_id, supabase, min_runner_hits=min_runner_hits)
    print(f"[TRENDING BATCH] Distributed pipeline queued for {len(tokens)} runners")


# =============================================================================
# AUTO-DISCOVERY
# =============================================================================

def perform_auto_discovery(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    user_id            = data.get('user_id', 'default_user')
    min_runner_hits    = data.get('min_runner_hits', 2)
    min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
    job_id             = data.get('job_id')

    analyzer = get_worker_analyzer()
    supabase = get_supabase_client()

    print(f"\n[AUTO DISCOVERY] Finding runners...")

    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
        'phase': 'fetching_trending', 'progress': 15
    }).eq('job_id', job_id).execute()

    runners = analyzer.find_trending_runners_enhanced(
        days_back=30, min_multiplier=5.0, min_liquidity=50000
    )

    if not runners:
        result = {'success': False, 'error': 'No secure trending runners found'}
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
            'status': 'completed', 'phase': 'done', 'progress': 100, 'results': result
        }).eq('job_id', job_id).execute()
        return result

    selected = runners[:10]

    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
        'phase':        'queuing_pipeline',
        'progress':     25,
        'tokens_total': len(selected),
    }).eq('job_id', job_id).execute()

    tokens = [
        {
            'address': r['address'],
            'ticker':  r.get('symbol', r.get('ticker', 'UNKNOWN')),
            'symbol':  r.get('symbol', r.get('ticker', 'UNKNOWN')),
        }
        for r in selected
    ]

    _queue_batch_pipeline(tokens, user_id, job_id, supabase, min_runner_hits=min_runner_hits)
    print(f"[AUTO DISCOVERY] Distributed pipeline queued for {len(tokens)} runners")


# =============================================================================
# PHASE 1 WORKERS — high queue
# job1: top traders | job2: first buyers | job3: top holders (parallel)
# =============================================================================

def fetch_top_traders(data):
    """Worker 1 [high]: Fetch top 100 traders by PnL. Covers active traders who realized gains."""
    analyzer = get_worker_analyzer()
    token    = data['token']
    job_id   = data['job_id']

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
                wallet_data[wallet] = {
                    'source':         'top_traders',
                    'pnl_data':       trader,
                    'earliest_entry': None,
                    'entry_price':    None,
                }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'top_traders'}
    _save_result(f"phase1_top_traders:{job_id}", result)
    print(f"[WORKER 1] top_traders done: {len(wallets)} wallets")
    return result


def fetch_first_buyers(data):
    """Worker 2 [high]: Fetch first 100 buyers by time. Covers earliest entries."""
    analyzer = get_worker_analyzer()
    token    = data['token']
    job_id   = data['job_id']

    url      = f"{analyzer.st_base_url}/first-buyers/{token['address']}"
    response = analyzer.fetch_with_retry(
        url, analyzer._get_solanatracker_headers(),
        semaphore=analyzer.solana_tracker_semaphore
    )

    wallets     = []
    wallet_data = {}

    if response:
        buyers = response if isinstance(response, list) else response.get('buyers', [])
        for buyer in buyers:
            wallet = buyer.get('wallet')
            if wallet:
                wallets.append(wallet)
                first_buy   = buyer.get('first_buy', {})
                amount      = first_buy.get('amount', 0)
                volume_usd  = first_buy.get('volume_usd', 0)
                entry_price = (volume_usd / amount) if amount > 0 else None

                wallet_data[wallet] = {
                    'source':         'first_buyers',
                    'pnl_data':       buyer,
                    'earliest_entry': buyer.get('first_buy_time', 0),
                    'entry_price':    entry_price,
                }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'first_buyers'}
    _save_result(f"phase1_first_buyers:{job_id}", result)
    print(f"[WORKER 2] first_buyers done: {len(wallets)} wallets")
    return result


def fetch_top_holders(data):
    """
    Worker 3 [high]: Fetch top 500 holders by current position size.

    Covers the gap left by top_traders and first_buyers:
      - Wallets that bought early and never sold (unrealized PnL, realized=0)
      - Wallets that took partials and are still holding a significant position
      - Conviction holders who would be invisible in top_traders (low realized PnL)

    These wallets qualify via total_multiplier (realized + unrealized >= 3x),
    not realized_multiplier alone. Their entry_price comes from the PnL fetch
    in fetch_pnl_batch, same as any other wallet without pre-existing entry data.

    No pagination needed — top 500 sorted by amount descending is sufficient.
    Holders outside top 500 by position size are not meaningful cross-reference candidates.
    """
    analyzer = get_worker_analyzer()
    token    = data['token']
    job_id   = data['job_id']

    url = f"{analyzer.st_base_url}/tokens/{token['address']}/holders/paginated"
    response = analyzer.fetch_with_retry(
        url,
        analyzer._get_solanatracker_headers(),
        params={'limit': 500},
        semaphore=analyzer.solana_tracker_semaphore
    )

    wallets     = []
    wallet_data = {}

    if response and response.get('accounts'):
        for account in response['accounts']:
            wallet = account.get('wallet')
            if wallet:
                wallets.append(wallet)
                wallet_data[wallet] = {
                    'source':            'top_holders',
                    'pnl_data':          None,   # fetched in PnL phase
                    'earliest_entry':    None,   # fetched in PnL phase
                    'entry_price':       None,   # fetched in PnL phase
                    'holding_amount':    account.get('amount', 0),
                    'holding_usd':       account.get('value', {}).get('usd', 0),
                    'holding_pct':       account.get('percentage', 0),
                }

    result = {
        'wallets':       wallets,
        'wallet_data':   wallet_data,
        'source':        'top_holders',
        'total_holders': response.get('total', 0) if response else 0,
    }
    _save_result(f"phase1_holders:{job_id}", result)
    print(f"[WORKER 3] top_holders done: {len(wallets)} holders "
          f"(token total={result['total_holders']})")
    return result


# =============================================================================
# PHASE 1 COORDINATOR + ENTRY PRICE BATCH WORKERS
# =============================================================================

def coordinate_entry_prices(data):
    """
    [compute queue] Reads top traders from Redis, splits into batches of 10,
    spawns parallel fetch_entry_prices_batch on batch queue, then queues
    merge_entry_prices on compute queue. Exits immediately.
    """
    token  = data['token']
    job_id = data['job_id']

    top_traders_result = _load_result(f"phase1_top_traders:{job_id}")
    if not top_traders_result:
        print(f"[ENTRY COORD] No top traders result — skipping")
        _save_result(f"phase1_top_traders:{job_id}", {'wallets': [], 'wallet_data': {}, 'source': 'top_traders'})
        return {'batch_jobs': [], 'merge_job': None}

    wallets    = top_traders_result['wallets']
    batch_size = 10
    _, q_batch, q_compute = _get_queues()
    batch_jobs = []

    print(f"[ENTRY COORD] {len(wallets)} wallets → batches of {batch_size}")

    for i in range(0, len(wallets), batch_size):
        batch     = wallets[i:i + batch_size]
        batch_idx = i // batch_size
        bj = q_batch.enqueue(
            'services.worker_tasks.fetch_entry_prices_batch',
            {
                'token':     token,
                'job_id':    job_id,
                'batch_idx': batch_idx,
                'wallets':   batch,
            }
        )
        batch_jobs.append(bj)

    merge_job = q_compute.enqueue(
        'services.worker_tasks.merge_entry_prices',
        {
            'token':       token,
            'job_id':      job_id,
            'batch_count': len(batch_jobs),
            'all_wallets': wallets,
        },
        depends_on=Dependency(jobs=batch_jobs)
    )

    print(f"  ✓ {len(batch_jobs)} entry-price batches + merge {merge_job.id[:8]}")
    return {'batch_jobs': [j.id for j in batch_jobs], 'merge_job': merge_job.id}


def fetch_entry_prices_batch(data):
    """[batch queue] Fetch first-buy entry prices for a batch of ~10 wallets with debug logging."""
    analyzer  = get_worker_analyzer()
    import aiohttp
    from asyncio import Semaphore as AsyncSemaphore

    token     = data['token']
    job_id    = data['job_id']
    batch_idx = data['batch_idx']
    wallets   = data['wallets']

    print(f"[ENTRY BATCH {batch_idx}] {len(wallets)} wallets...")

    failure_reasons = defaultdict(int)
    detailed_results = []

    async def _fetch():
        async with aiohttp.ClientSession() as session:
            sem   = AsyncSemaphore(6)
            tasks = []
            for wallet in wallets:
                async def fetch(w=wallet):
                    async with sem:
                        try:
                            url  = f"{analyzer.st_base_url}/trades/{token['address']}/by-wallet/{w}"
                            resp = await analyzer.async_fetch_with_retry(
                                session, url, analyzer._get_solanatracker_headers()
                            )
                            
                            if not resp:
                                failure_reasons['no_response'] += 1
                                return {'wallet': w, 'price': None, 'time': None, 'reason': 'no_response'}
                                
                            if not resp.get('trades'):
                                failure_reasons['no_trades'] += 1
                                return {'wallet': w, 'price': None, 'time': None, 'reason': 'no_trades'}
                                
                            buys = [t for t in resp['trades'] if t.get('type') == 'buy']
                            if not buys:
                                failure_reasons['no_buys'] += 1
                                return {'wallet': w, 'price': None, 'time': None, 'reason': 'no_buys'}
                                
                            first_buy = min(buys, key=lambda x: x.get('time', float('inf')))
                            return {
                                'wallet': w, 
                                'price': first_buy.get('priceUsd'), 
                                'time': first_buy.get('time'),
                                'reason': 'success'
                            }
                        except Exception as e:
                            failure_reasons['error'] += 1
                            return {'wallet': w, 'price': None, 'time': None, 'reason': f'error: {str(e)}'}
                tasks.append(fetch())
            return await asyncio.gather(*tasks)

    results = asyncio.run(_fetch())
    found = 0
    
    for r in results:
        detailed_results.append(r)
        if r and r.get('price') is not None:
            found += 1

    print(f"[ENTRY BATCH {batch_idx}] Done: {found}/{len(wallets)} prices found")
    print(f"[ENTRY BATCH {batch_idx}] Failure breakdown: {dict(failure_reasons)}")

    # Save detailed debug log
    debug_log = {
        'batch_idx': batch_idx,
        'timestamp': time.time(),
        'token': token['address'],
        'results': detailed_results,
        'summary': {
            'total': len(wallets),
            'found': found,
            'failed': len(wallets) - found,
            'failure_reasons': dict(failure_reasons)
        }
    }
    _save_result(f"debug_entry_prices:{job_id}:{batch_idx}", debug_log)
    _save_result(f"entry_prices_batch:{job_id}:{batch_idx}", results)
    
    return results


def merge_entry_prices(data):
    """[compute queue] Merge entry-price batch results into top_traders wallet_data."""
    token       = data['token']
    job_id      = data['job_id']
    batch_count = data['batch_count']
    all_wallets = data['all_wallets']

    top_traders_result = _load_result(f"phase1_top_traders:{job_id}") or {}
    wallet_data        = top_traders_result.get('wallet_data', {})

    resolved = 0
    for i in range(batch_count):
        batch = _load_result(f"entry_prices_batch:{job_id}:{i}") or []
        for entry in batch:
            if not entry:
                continue
            w = entry.get('wallet')
            if w and w in wallet_data:
                if entry.get('price') is not None:
                    wallet_data[w]['entry_price']    = entry['price']
                    wallet_data[w]['earliest_entry'] = entry.get('time') or wallet_data[w].get('earliest_entry')
                    resolved += 1

    enriched = {'wallets': all_wallets, 'wallet_data': wallet_data, 'source': 'top_traders'}
    _save_result(f"phase1_top_traders:{job_id}", enriched)

    print(f"[ENTRY MERGE] Resolved {resolved}/{len(all_wallets)} entry prices")
    return enriched


# =============================================================================
# PHASE 2 COORDINATOR — compute queue
#
# RACE CONDITION FIX:
#   score_and_rank_single is now queued HERE with depends_on=pnl_jobs.
#   Previously it was queued externally with depends_on=pnl_coordinator,
#   which returned immediately after spawning PnL batch workers — meaning
#   the scorer ran before any PnL results were written to Redis.
#
#   Now the scorer correctly waits for all actual PnL batch workers to finish.
#   parent_job_id is passed through from _queue_batch_pipeline so batch mode works.
# =============================================================================

def coordinate_pnl_phase(data):
    """
    [compute queue] Merges Phase 1 results, dispatches parallel PnL batch jobs,
    then queues score_and_rank_single with depends_on=pnl_jobs.

    Sources merged: top_traders | first_buyers | top_holders
    Deduplication: first source wins; entry_price and pnl_data backfilled where missing.
    Holder-specific fields (holding_usd, holding_pct) preserved on wallet_data.
    """
    token        = data['token']
    job_id       = data['job_id']
    user_id      = data.get('user_id', 'default_user')
    parent_job   = data.get('parent_job_id')   # None for single token, set for batch
    phase1_jobs  = data['phase1_jobs']

    print(f"\n[PNL COORD] Phase 1 complete for {token.get('ticker')} — merging...")

    all_wallets = []
    wallet_data = {}

    # Merge all three Phase 1 sources — deduplication preserves first-seen source
    for key_prefix in ['phase1_top_traders', 'phase1_first_buyers', 'phase1_holders']:
        result = _load_result(f"{key_prefix}:{job_id}")
        if result:
            for wallet in result['wallets']:
                if wallet not in wallet_data:
                    all_wallets.append(wallet)
                    wallet_data[wallet] = result['wallet_data'].get(wallet, {})
                else:
                    # Backfill missing data from secondary sources
                    existing = wallet_data[wallet]
                    new      = result['wallet_data'].get(wallet, {})
                    if new.get('entry_price') and not existing.get('entry_price'):
                        existing['entry_price'] = new['entry_price']
                    if new.get('pnl_data') and not existing.get('pnl_data'):
                        existing['pnl_data'] = new['pnl_data']
                    # Preserve holder position data if present
                    for holder_field in ['holding_amount', 'holding_usd', 'holding_pct']:
                        if new.get(holder_field) and not existing.get(holder_field):
                            existing[holder_field] = new[holder_field]

    print(f"  ✓ Merged: {len(all_wallets)} unique wallets")

    _save_result(f"phase1_merged:{job_id}", {
        'wallets':     all_wallets,
        'wallet_data': wallet_data
    })

    _, q_batch, q_compute = _get_queues()
    batch_size = 10
    pnl_jobs   = []

    for i in range(0, len(all_wallets), batch_size):
        batch         = all_wallets[i:i + batch_size]
        batch_wallets = {w: wallet_data[w] for w in batch}

        pnl_job = q_batch.enqueue(
            'services.worker_tasks.fetch_pnl_batch',
            {
                'token':       token,
                'job_id':      job_id,
                'batch_idx':   i // batch_size,
                'wallets':     batch,
                'wallet_data': batch_wallets
            }
        )
        pnl_jobs.append(pnl_job)

    print(f"  ✓ Queued {len(pnl_jobs)} PnL batch jobs (size={batch_size})")

    # Save batch info to Redis (used as fallback reference)
    r = _get_redis()
    r.set(f"pnl_batch_info:{job_id}", json.dumps({
        'batch_count': len(pnl_jobs),
        'pnl_job_ids': [j.id for j in pnl_jobs]
    }), ex=3600)

    # FIX: Queue scorer here with depends_on=pnl_jobs (actual batch workers),
    # not externally with depends_on=pnl_coordinator (which exits immediately).
    scorer_job = q_compute.enqueue(
        'services.worker_tasks.score_and_rank_single',
        {
            'token':         token,
            'job_id':        job_id,
            'user_id':       user_id,
            'parent_job_id': parent_job,   # None = single mode, set = batch mode
            'batch_count':   len(pnl_jobs),
        },
        depends_on=Dependency(jobs=pnl_jobs) if pnl_jobs else None
    )

    print(f"  ✓ Scorer {scorer_job.id[:8]} queued — waits for all {len(pnl_jobs)} PnL batches")
    return {'pnl_jobs': [j.id for j in pnl_jobs], 'batch_count': len(pnl_jobs), 'scorer_job': scorer_job.id}


# =============================================================================
# PHASE 2 WORKERS — batch queue
# =============================================================================

def fetch_pnl_batch(data):
    """
    [batch queue] Fetch PnL for a batch of wallets with debug logging.

    Sources:
      first_buyers / top_traders with pnl_data + entry_price → skip API, qualify directly
      top_traders with pnl_data but no entry_price             → fetch entry price only
      top_holders / others with no pnl_data                   → fetch full PnL
    """
    analyzer = get_worker_analyzer()
    import aiohttp
    from asyncio import Semaphore as AsyncSemaphore

    token       = data['token']
    job_id      = data['job_id']
    batch_idx   = data['batch_idx']
    wallets     = data['wallets']
    wallet_data = data['wallet_data']

    qualified = []
    failed_wallets = []
    qualification_failures = defaultdict(int)

    ready_to_qualify       = []
    top_traders_need_price = []
    need_pnl_fetch         = []

    for wallet in wallets:
        wdata     = wallet_data.get(wallet, {})
        source    = wdata.get('source', '')
        has_pnl   = wdata.get('pnl_data') is not None
        has_price = wdata.get('entry_price') is not None

        if has_pnl and has_price:
            ready_to_qualify.append(wallet)
        elif source == 'top_traders' and has_pnl and not has_price:
            top_traders_need_price.append(wallet)
        elif has_pnl and not has_price:
            ready_to_qualify.append(wallet)
        else:
            # top_holders and any wallet without pnl_data
            need_pnl_fetch.append(wallet)

    print(f"[PNL BATCH {batch_idx}] {len(wallets)} wallets | "
          f"{len(ready_to_qualify)} ready | "
          f"{len(top_traders_need_price)} need price | "
          f"{len(need_pnl_fetch)} fetch PnL")

    # Process ready_to_qualify wallets
    for wallet in ready_to_qualify:
        pnl = wallet_data[wallet]['pnl_data']
        if not _qualify_wallet(wallet, pnl, wallet_data, token, qualified, debug=True):
            wdata = wallet_data.get(wallet, {})
            pnl_data = wdata.get('pnl_data', {})
            invested = pnl_data.get('total_invested', 0)
            realized_mult = (pnl_data.get('realized', 0) + invested) / invested if invested > 0 else 0
            total_mult = (pnl_data.get('realized', 0) + pnl_data.get('unrealized', 0) + invested) / invested if invested > 0 else 0
            
            failure_reason = 'missing_entry_price' if not wdata.get('entry_price') else 'low_multiplier'
            qualification_failures[failure_reason] += 1
            
            failed_wallets.append({
                'wallet': wallet,
                'failure_reason': failure_reason,
                'source': wdata.get('source'),
                'has_pnl': True,
                'has_entry_price': bool(wdata.get('entry_price')),
                'invested': invested,
                'realized_multiplier': round(realized_mult, 2),
                'total_multiplier': round(total_mult, 2),
                'batch_idx': batch_idx
            })

    # Fetch entry prices for top_traders that need them
    if top_traders_need_price:
        async def _fetch_entry_prices():
            async with aiohttp.ClientSession() as session:
                sem   = AsyncSemaphore(5)
                tasks = []
                for wallet in top_traders_need_price:
                    async def fetch(w=wallet):
                        async with sem:
                            url  = f"{analyzer.st_base_url}/trades/{token['address']}/by-wallet/{w}"
                            resp = await analyzer.async_fetch_with_retry(
                                session, url, analyzer._get_solanatracker_headers()
                            )
                            if resp and resp.get('trades'):
                                buys = [t for t in resp['trades'] if t.get('type') == 'buy']
                                if buys:
                                    first_buy = min(buys, key=lambda x: x.get('time', float('inf')))
                                    return {'price': first_buy.get('priceUsd'), 'time': first_buy.get('time')}
                            return None
                    tasks.append(fetch())
                return await asyncio.gather(*tasks)

        price_results = asyncio.run(_fetch_entry_prices())
        for wallet, price_data in zip(top_traders_need_price, price_results):
            if price_data:
                wallet_data[wallet]['entry_price'] = price_data.get('price')
            pnl = wallet_data[wallet]['pnl_data']
            if not _qualify_wallet(wallet, pnl, wallet_data, token, qualified, debug=True):
                wdata = wallet_data.get(wallet, {})
                pnl_data = wdata.get('pnl_data', {})
                invested = pnl_data.get('total_invested', 0)
                realized_mult = (pnl_data.get('realized', 0) + invested) / invested if invested > 0 else 0
                total_mult = (pnl_data.get('realized', 0) + pnl_data.get('unrealized', 0) + invested) / invested if invested > 0 else 0
                
                failure_reason = 'missing_entry_price' if not price_data else 'low_multiplier'
                qualification_failures[failure_reason] += 1
                
                failed_wallets.append({
                    'wallet': wallet,
                    'failure_reason': failure_reason,
                    'source': wdata.get('source'),
                    'has_pnl': True,
                    'has_entry_price': bool(price_data),
                    'invested': invested,
                    'realized_multiplier': round(realized_mult, 2),
                    'total_multiplier': round(total_mult, 2),
                    'batch_idx': batch_idx
                })

    # Fetch full PnL for wallets without it
    async def _fetch_pnls():
        async with aiohttp.ClientSession() as session:
            sem   = AsyncSemaphore(2)
            tasks = []
            for wallet in need_pnl_fetch:
                async def fetch(w=wallet):
                    async with sem:
                        return await analyzer.async_fetch_with_retry(
                            session,
                            f"{analyzer.st_base_url}/pnl/{w}/{token['address']}",
                            analyzer._get_solanatracker_headers()
                        )
                tasks.append(fetch())
            return await asyncio.gather(*tasks)

    if need_pnl_fetch:
        results = asyncio.run(_fetch_pnls())
        for wallet, pnl in zip(need_pnl_fetch, results):
            if pnl:
                if _qualify_wallet(wallet, pnl, wallet_data, token, qualified, debug=True):
                    continue
                else:
                    wdata = wallet_data.get(wallet, {})
                    invested = pnl.get('total_invested', 0)
                    realized_mult = (pnl.get('realized', 0) + invested) / invested if invested > 0 else 0
                    total_mult = (pnl.get('realized', 0) + pnl.get('unrealized', 0) + invested) / invested if invested > 0 else 0
                    
                    failure_reason = 'low_invested' if invested < 100 else 'low_multiplier'
                    qualification_failures[failure_reason] += 1
                    
                    failed_wallets.append({
                        'wallet': wallet,
                        'failure_reason': failure_reason,
                        'source': wdata.get('source', 'unknown'),
                        'has_pnl': True,
                        'has_entry_price': bool(wdata.get('entry_price')),
                        'invested': invested,
                        'realized_multiplier': round(realized_mult, 2),
                        'total_multiplier': round(total_mult, 2),
                        'batch_idx': batch_idx
                    })
            else:
                qualification_failures['no_pnl_data'] += 1
                failed_wallets.append({
                    'wallet': wallet,
                    'failure_reason': 'no_pnl_data',
                    'source': wallet_data.get(wallet, {}).get('source', 'unknown'),
                    'has_pnl': False,
                    'has_entry_price': False,
                    'invested': 0,
                    'realized_multiplier': 0,
                    'total_multiplier': 0,
                    'batch_idx': batch_idx
                })

    print(f"[PNL BATCH {batch_idx}] Done: {len(qualified)} qualified, {len(failed_wallets)} failed")
    print(f"[PNL BATCH {batch_idx}] Failure breakdown: {dict(qualification_failures)}")

    # Save debug logs
    if failed_wallets:
        _save_result(f"debug_failed_wallets:{job_id}:{batch_idx}", failed_wallets)
    
    debug_summary = {
        'batch_idx': batch_idx,
        'timestamp': time.time(),
        'total_wallets': len(wallets),
        'qualified': len(qualified),
        'failed': len(failed_wallets),
        'failure_breakdown': dict(qualification_failures),
        'categories': {
            'ready': len(ready_to_qualify),
            'need_price': len(top_traders_need_price),
            'fetch_pnl': len(need_pnl_fetch)
        }
    }
    _save_result(f"debug_pnl_summary:{job_id}:{batch_idx}", debug_summary)
    _save_result(f"pnl_batch:{job_id}:{batch_idx}", qualified)
    
    return qualified


def _qualify_wallet(wallet, pnl_data, wallet_data, token, qualified_list, min_invested=100, min_roi_mult=3.0, debug=False):
    """
    Qualification: realized OR total multiplier >= threshold.
    Holders sitting on unrealized gains qualify the same as sellers.
    Min invested: $100.
    Holder-specific fields (holding_usd, holding_pct) carried through if present.
    """
    realized       = pnl_data.get('realized', 0)
    unrealized     = pnl_data.get('unrealized', 0)
    total_invested = pnl_data.get('total_invested') or pnl_data.get('totalInvested', 0)

    if total_invested < min_invested:
        if debug:
            print(f"[QUALIFY DEBUG] {wallet[:8]} FAIL: invested=${total_invested:.2f} < ${min_invested}")
        return False

    realized_mult = (realized + total_invested) / total_invested
    total_mult    = (realized + unrealized + total_invested) / total_invested

    if realized_mult < min_roi_mult and total_mult < min_roi_mult:
        if debug:
            print(f"[QUALIFY DEBUG] {wallet[:8]} FAIL: realized={realized_mult:.2f}x total={total_mult:.2f}x < {min_roi_mult}x")
        return False

    wdata       = wallet_data.get(wallet, {})
    entry_price = wdata.get('entry_price')

    if entry_price is None:
        first_buy  = pnl_data.get('first_buy', {})
        amount     = first_buy.get('amount', 0)
        volume_usd = first_buy.get('volume_usd', 0)
        if amount > 0:
            entry_price = volume_usd / amount
    
    if entry_price is None and debug:
        print(f"[QUALIFY DEBUG] {wallet[:8]} WARNING: No entry price, but qualifies on multiplier")

    wallet_entry = {
        'wallet':              wallet,
        'source':              wdata.get('source', 'unknown'),
        'realized':            realized,
        'unrealized':          unrealized,
        'total_invested':      total_invested,
        'realized_multiplier': realized_mult,
        'total_multiplier':    total_mult,
        'earliest_entry':      wdata.get('earliest_entry'),
        'entry_price':         entry_price,
    }

    # Carry through holder position data for frontend conviction display
    for holder_field in ['holding_amount', 'holding_usd', 'holding_pct']:
        if wdata.get(holder_field):
            wallet_entry[holder_field] = wdata[holder_field]

    qualified_list.append(wallet_entry)
    if debug:
        print(f"[QUALIFY DEBUG] {wallet[:8]} PASS: invested=${total_invested:.2f}, mult={max(realized_mult, total_mult):.2f}x")
    return True


# =============================================================================
# PHASE 3: SCORE + RANK
#
# SINGLE MODE: score immediately, queue runner history, save final result
# BATCH MODE:  save raw qualified wallets to Redis + Supabase cache,
#              queue merge_and_save_final to increment batch counter
#              aggregate_cross_token handles all scoring after all tokens complete
# =============================================================================

def score_and_rank_single(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    token        = data['token']
    job_id       = data['job_id']
    user_id      = data.get('user_id', 'default_user')
    parent_job   = data.get('parent_job_id')
    is_batch     = parent_job is not None
    batch_count  = data.get('batch_count', 0)

    analyzer = get_worker_analyzer()
    supabase = get_supabase_client()

    print(f"\n[SCORER] {token.get('ticker')} — collecting {batch_count} PnL batches "
          f"(mode={'batch' if is_batch else 'single'})")

    qualified_wallets = []
    total_failed = 0
    failure_summary = defaultdict(int)

    for i in range(batch_count):
        batch_result = _load_result(f"pnl_batch:{job_id}:{i}")
        if batch_result:
            qualified_wallets.extend(batch_result)
        
        # Load debug info if available
        failed = _load_result(f"debug_failed_wallets:{job_id}:{i}")
        if failed:
            total_failed += len(failed)
            for f in failed:
                failure_summary[f.get('failure_reason', 'unknown')] += 1

        summary = _load_result(f"debug_pnl_summary:{job_id}:{i}")
        if summary:
            print(f"  Batch {i}: {summary.get('qualified', 0)} qualified, {summary.get('failed', 0)} failed")

    print(f"  ✓ {len(qualified_wallets)} qualified wallets, {total_failed} failed wallets")
    if failure_summary:
        print(f"  Failure summary: {dict(failure_summary)}")

    token_address = token.get('address')
    if token_address and qualified_wallets:
        _save_qualified_wallets_cache(token_address, qualified_wallets)

    if is_batch:
        # BATCH MODE: save raw unscored wallets to Redis for aggregator
        # aggregate_cross_token scores cross-token wallets with aggregate score
        # and single-token wallets with individual professional_score
        _save_result(f"ranked_wallets:{job_id}", qualified_wallets)

        print(f"  ✓ Batch mode: {len(qualified_wallets)} raw wallets saved for aggregator")

        _, q_batch, q_compute = _get_queues()
        merge_job = q_compute.enqueue(
            'services.worker_tasks.merge_and_save_final',
            {
                'token':           token,
                'job_id':          job_id,
                'user_id':         user_id,
                'parent_job_id':   parent_job,
                'total_qualified': len(qualified_wallets),
                'is_batch_mode':   True,
            }
        )

        print(f"  ✓ Queued merge {merge_job.id[:8]} — will increment batch counter")
        return {'mode': 'batch', 'qualified': len(qualified_wallets), 'merge_job': merge_job.id}

    else:
        # SINGLE MODE: score and rank immediately
        ath_data  = analyzer.get_token_ath(token_address)
        ath_price = ath_data.get('highest_price', 0) if ath_data else 0

        wallet_results = []
        for wallet_info in qualified_wallets:
            wallet_addr = wallet_info['wallet']
            wallet_info['ath_price'] = ath_price
            scoring = analyzer.calculate_wallet_relative_score(wallet_info)

            if scoring['professional_score'] >= 90:   tier = 'S'
            elif scoring['professional_score'] >= 80: tier = 'A'
            elif scoring['professional_score'] >= 70: tier = 'B'
            else:                                     tier = 'C'

            wallet_result = {
                'wallet':                  wallet_addr,
                'source':                  wallet_info['source'],
                'tier':                    tier,
                'roi_percent':             round((wallet_info['realized_multiplier'] - 1) * 100, 2),
                'roi_multiplier':          round(wallet_info['realized_multiplier'], 2),
                'entry_to_ath_multiplier': scoring.get('entry_to_ath_multiplier'),
                'distance_to_ath_pct':     scoring.get('distance_to_ath_pct'),
                'realized_profit':         wallet_info['realized'],
                'unrealized_profit':       wallet_info['unrealized'],
                'total_invested':          wallet_info['total_invested'],
                'realized_multiplier':     scoring.get('realized_multiplier'),
                'total_multiplier':        scoring.get('total_multiplier'),
                'professional_score':      scoring['professional_score'],
                'professional_grade':      scoring['professional_grade'],
                'score_breakdown':         scoring['score_breakdown'],
                'first_buy_time':          wallet_info.get('earliest_entry'),
                'entry_price':             wallet_info.get('entry_price'),
                'ath_price':               ath_price,
                'is_cross_token':          False,  # single token — never cross-token
                'runner_hits_30d':         0,
                'runner_success_rate':     0,
                'runner_avg_roi':          0,
                'other_runners':           [],
                'other_runners_stats':     {},
                'is_fresh':                True,
            }

            # Carry through holder conviction fields if present
            for holder_field in ['holding_amount', 'holding_usd', 'holding_pct']:
                if wallet_info.get(holder_field):
                    wallet_result[holder_field] = wallet_info[holder_field]

            wallet_results.append(wallet_result)

        wallet_results.sort(key=lambda x: x['professional_score'], reverse=True)
        top_20 = wallet_results[:20]

        _save_result(f"ranked_wallets:{job_id}", top_20)

        _, q_batch, q_compute = _get_queues()
        runner_jobs = []
        chunk_size  = 5

        for i in range(0, len(top_20), chunk_size):
            chunk     = top_20[i:i + chunk_size]
            batch_idx = i // chunk_size
            rh_job = q_batch.enqueue(
                'services.worker_tasks.fetch_runner_history_batch',
                {
                    'token':     token,
                    'job_id':    job_id,
                    'batch_idx': batch_idx,
                    'wallets':   [w['wallet'] for w in chunk],
                }
            )
            runner_jobs.append(rh_job)

        merge_job = q_compute.enqueue(
            'services.worker_tasks.merge_and_save_final',
            {
                'token':              token,
                'job_id':             job_id,
                'user_id':            user_id,
                'parent_job_id':      None,
                'runner_batch_count': len(runner_jobs),
                'total_qualified':    len(wallet_results),
                'is_batch_mode':      False,
            },
            depends_on=Dependency(jobs=runner_jobs)
        )

        print(f"  ✓ Merge+save: {merge_job.id[:8]} (waits for {len(runner_jobs)} runner batches)")
        return {'mode': 'single', 'runner_jobs': [j.id for j in runner_jobs], 'merge_job': merge_job.id}


# =============================================================================
# CACHE PATH FAST TRACK
# =============================================================================

def fetch_from_token_cache(data):
    """[compute queue] Fast path for batch when a token's qualified wallets are cached."""
    token      = data['token']
    job_id     = data['job_id']
    parent_job = data.get('parent_job_id')
    user_id    = data.get('user_id', 'default_user')

    print(f"\n[TOKEN CACHE] Fast path for {token.get('ticker')} [{job_id[:8]}]...")

    qualified_wallets = _get_qualified_wallets_cache(token['address'])
    if not qualified_wallets:
        print(f"[TOKEN CACHE] Cache miss for {token['address'][:8]} — returning empty")
        _save_result(f"ranked_wallets:{job_id}", [])
        _trigger_aggregate_if_complete(parent_job, job_id)
        return {'success': True, 'token': token, 'wallets': [], 'total': 0}

    print(f"  ✓ Loaded {len(qualified_wallets)} cached wallets")
    _save_result(f"ranked_wallets:{job_id}", qualified_wallets)

    _, q_batch, q_compute = _get_queues()
    merge_job = q_compute.enqueue(
        'services.worker_tasks.merge_and_save_final',
        {
            'token':           token,
            'job_id':          job_id,
            'user_id':         user_id,
            'parent_job_id':   parent_job,
            'total_qualified': len(qualified_wallets),
            'is_batch_mode':   True,
        }
    )

    print(f"  ✓ Cache path: merge {merge_job.id[:8]} queued")
    return {'merge_job': merge_job.id}


def _trigger_aggregate_if_complete(parent_job_id, sub_job_id):
    """Increment batch counter. Queue aggregate_cross_token when last token completes."""
    if not parent_job_id:
        return

    r     = _get_redis()
    count = r.incr(f"batch_completed:{parent_job_id}")
    total = r.get(f"batch_total:{parent_job_id}")
    total = int(total) if total else 0

    print(f"[BATCH COUNTER] {count}/{total} tokens complete for parent {parent_job_id[:8]}")

    if total > 0 and count >= total:
        sub_job_ids     = json.loads(r.get(f"batch_sub_jobs:{parent_job_id}") or '[]')
        tokens          = json.loads(r.get(f"batch_tokens:{parent_job_id}") or '[]')
        min_runner_hits = int(r.get(f"batch_min_runner_hits:{parent_job_id}") or 2)

        _, _, q_compute = _get_queues()
        q_compute.enqueue(
            'services.worker_tasks.aggregate_cross_token',
            {
                'tokens':          tokens,
                'job_id':          parent_job_id,
                'sub_job_ids':     sub_job_ids,
                'min_runner_hits': min_runner_hits,
            }
        )
        print(f"[BATCH COUNTER] All {total} tokens done — aggregator queued for {parent_job_id[:8]}")


# =============================================================================
# PHASE 4: RUNNER HISTORY — batch queue
# =============================================================================

def fetch_runner_history_batch(data):
    """[batch queue] Fetch 30-day runner history for a batch of 5 wallets."""
    analyzer  = get_worker_analyzer()
    token     = data['token']
    job_id    = data['job_id']
    batch_idx = data['batch_idx']
    wallets   = data['wallets']

    enriched = []
    print(f"[RUNNER BATCH {batch_idx}] {len(wallets)} wallets...")

    for wallet_addr in wallets:
        try:
            runner_history = analyzer._get_cached_other_runners(
                wallet_addr,
                current_token=token.get('address'),
                min_multiplier=10.0
            )
            enriched.append({
                'wallet':              wallet_addr,
                'runner_hits_30d':     runner_history['stats'].get('total_other_runners', 0),
                'runner_success_rate': runner_history['stats'].get('success_rate', 0),
                'runner_avg_roi':      runner_history['stats'].get('avg_roi', 0),
                'other_runners':       runner_history['other_runners'][:5],
                'other_runners_stats': runner_history['stats'],
            })
        except Exception as e:
            print(f"  ⚠️ Runner history failed for {wallet_addr[:8]}: {e}")
            enriched.append({
                'wallet':              wallet_addr,
                'runner_hits_30d':     0,
                'runner_success_rate': 0,
                'runner_avg_roi':      0,
                'other_runners':       [],
                'other_runners_stats': {},
            })

    _save_result(f"runner_batch:{job_id}:{batch_idx}", enriched)
    print(f"[RUNNER BATCH {batch_idx}] Done: {len(enriched)} enriched")
    return enriched


# =============================================================================
# PHASE 4 MERGE — compute queue
# =============================================================================

def merge_and_save_final(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    token              = data['token']
    job_id             = data['job_id']
    user_id            = data.get('user_id', 'default_user')
    parent_job         = data.get('parent_job_id')
    total_qualified    = data['total_qualified']
    is_batch_mode      = data.get('is_batch_mode', parent_job is not None)
    runner_batch_count = data.get('runner_batch_count', 0)

    supabase      = get_supabase_client()
    r             = _get_redis()
    wallet_list   = _load_result(f"ranked_wallets:{job_id}") or []
    token_address = token.get('address')

    if not is_batch_mode:
        # SINGLE MODE: attach runner history, save final result to Supabase
        print(f"\n[MERGE] {token.get('ticker')} — {runner_batch_count} runner history batches...")

        runner_lookup = {}
        for i in range(runner_batch_count):
            batch = _load_result(f"runner_batch:{job_id}:{i}") or []
            for entry in batch:
                runner_lookup[entry['wallet']] = entry

        for w in wallet_list:
            rh = runner_lookup.get(w.get('wallet'))
            if rh:
                w['runner_hits_30d']     = rh['runner_hits_30d']
                w['runner_success_rate'] = rh['runner_success_rate']
                w['runner_avg_roi']      = rh['runner_avg_roi']
                w['other_runners']       = rh['other_runners']
                w['other_runners_stats'] = rh['other_runners_stats']

        result = {
            'success': True,
            'token':   token,
            'wallets': wallet_list,
            'total':   total_qualified,
        }

        warm_redis_cache = True
        try:
            current_ath_raw = r.get(f"token_ath:{token_address}")
            if current_ath_raw:
                current_ath_price = json.loads(current_ath_raw).get('highest_price', 0)
                analysis_ath = next(
                    (w.get('ath_price', 0) for w in wallet_list if w.get('ath_price')), 0
                )
                if analysis_ath > 0 and current_ath_price > analysis_ath * 1.10:
                    print(f"  ⚠️ ATH moved — skipping Redis warm for {token.get('ticker')}")
                    warm_redis_cache = False
        except Exception as e:
            print(f"[MERGE] ATH check failed: {e}")

        if warm_redis_cache:
            r.set(f"cache:token:{token_address}", json.dumps(result), ex=21600)

        try:
            supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                'status':        'completed',
                'phase':         'done',
                'progress':      100,
                'results':       result,
                'token_address': token_address,
            }).eq('job_id', job_id).execute()
            print(f"  ✅ Saved final result for job {job_id[:8]}")
        except Exception as e:
            print(f"[MERGE] ⚠️ Failed to save: {e}")

        return result

    else:
        # BATCH MODE: save raw token result, increment parent counter
        print(f"\n[MERGE BATCH] {token.get('ticker')} — saving, incrementing counter...")

        result = {
            'success': True,
            'token':   token,
            'wallets': wallet_list,
            'total':   total_qualified,
        }

        _save_result(f"token_result:{job_id}", result)

        try:
            supabase.schema(SCHEMA_NAME).table('analysis_jobs').insert({
                'job_id':           str(uuid.uuid4()),
                'user_id':          user_id,
                'status':           'completed',
                'phase':            'done',
                'progress':         100,
                'token_address':    token_address,
                'tokens_total':     1,
                'tokens_completed': 1,
                'results':          result,
            }).execute()
        except Exception as e:
            print(f"[MERGE BATCH] ⚠️ Failed to insert token cache row: {e}")

        try:
            current = supabase.schema(SCHEMA_NAME).table('analysis_jobs').select(
                'tokens_completed'
            ).eq('job_id', parent_job).execute()
            current_count = current.data[0]['tokens_completed'] if current.data else 0
            supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                'tokens_completed': current_count + 1
            }).eq('job_id', parent_job).execute()
        except Exception as e:
            print(f"[MERGE BATCH] Failed to increment tokens_completed: {e}")

        _trigger_aggregate_if_complete(parent_job, job_id)
        return result


# =============================================================================
# BATCH AGGREGATOR — compute queue
#
# Triggered when all tokens complete (counter-based via _trigger_aggregate_if_complete).
#
# SCORING:
#   Cross-token wallets (runner_count >= min_runner_hits):
#     60% avg distance to ATH | 30% avg total ROI | 10% entry consistency
#   Single-token wallets (runner_count < min_runner_hits):
#     Scored individually using calculate_wallet_relative_score (professional_score)
#     Same scoring as single-token mode — entry timing, total ROI, realized ROI
#
# RANKING:
#   1. Cross-token wallets first (by token count DESC, aggregate score DESC)
#   2. Single-token wallets fill remaining slots to 20 (by professional_score DESC)
#   3. All wallets tagged with is_cross_token for frontend badge/separator display
#
# This approach:
#   - Never discards wallets just because there's no cross-token overlap
#   - Always returns up to 20 wallets with clear signal differentiation
#   - Scores each group by the method appropriate to their data
# =============================================================================

def aggregate_cross_token(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    from collections import defaultdict

    tokens          = data['tokens']
    job_id          = data['job_id']
    sub_job_ids     = data['sub_job_ids']
    min_runner_hits = data.get('min_runner_hits', 2)

    supabase = get_supabase_client()
    analyzer = get_worker_analyzer()

    print(f"\n[AGGREGATOR] Cross-token ranking for {len(tokens)} tokens "
          f"(min_runner_hits={min_runner_hits})...")

    # Load raw qualified wallets per token from Redis
    all_token_results = []
    for sub_job_id, token in zip(sub_job_ids, tokens):
        wallets = _load_result(f"ranked_wallets:{sub_job_id}")
        if wallets:
            all_token_results.append({'token': token, 'wallets': wallets})

    print(f"  ✓ Loaded {len(all_token_results)}/{len(tokens)} token results")

    # Pre-fetch launch and ATH prices for scoring
    launch_prices = {}
    ath_prices    = {}
    for token_result in all_token_results:
        addr = token_result['token']['address']
        try:
            launch_prices[addr] = analyzer._get_token_launch_price(addr) or 0
        except Exception as e:
            print(f"  ⚠️ Launch price fetch failed for {addr[:8]}: {e}")
            launch_prices[addr] = 0
        try:
            ath_data       = analyzer.get_token_ath(addr)
            ath_prices[addr] = ath_data.get('highest_price', 0) if ath_data else 0
        except Exception as e:
            print(f"  ⚠️ ATH fetch failed for {addr[:8]}: {e}")
            ath_prices[addr] = 0

    # Build wallet_hits — aggregate each wallet's data across all tokens
    # Raw wallet dicts are stored as-is; scoring happens after correlation
    wallet_hits = defaultdict(lambda: {
        'wallet':                None,
        'runners_hit':           [],
        'runners_hit_addresses': set(),
        'roi_details':           [],
        'entry_to_ath_vals':     [],
        'distance_to_ath_vals':  [],
        'total_roi_multipliers': [],
        'entry_ratios':          [],
        # Store raw wallet data per token for individual scoring fallback
        'raw_wallet_data_list':  [],
    })

    for token_result in all_token_results:
        token        = token_result['token']
        token_addr   = token['address']
        launch_price = launch_prices.get(token_addr, 0)
        ath_price    = ath_prices.get(token_addr, 0)

        for wallet_info in token_result['wallets']:
            addr = wallet_info.get('wallet')
            if not addr:
                continue

            if wallet_hits[addr]['wallet'] is None:
                wallet_hits[addr]['wallet'] = addr

            sym = token.get('ticker', token.get('symbol', '?'))
            if sym not in wallet_hits[addr]['runners_hit']:
                wallet_hits[addr]['runners_hit'].append(sym)
                wallet_hits[addr]['runners_hit_addresses'].add(token_addr)

            # Store raw wallet data for individual scoring if needed
            wallet_hits[addr]['raw_wallet_data_list'].append({
                'token_addr':   token_addr,
                'wallet_info':  wallet_info,
                'ath_price':    ath_price,
            })

            # Entry timing
            entry_price         = wallet_info.get('entry_price')
            distance_to_ath_pct = 0
            entry_to_ath_mult   = 0

            if entry_price and entry_price > 0 and ath_price and ath_price > 0:
                distance_to_ath_pct = ((ath_price - entry_price) / ath_price) * 100
                entry_to_ath_mult   = ath_price / entry_price
                wallet_hits[addr]['distance_to_ath_vals'].append(distance_to_ath_pct)
                wallet_hits[addr]['entry_to_ath_vals'].append(entry_to_ath_mult)

            total_mult = wallet_info.get('total_multiplier', 0)
            if total_mult:
                wallet_hits[addr]['total_roi_multipliers'].append(total_mult)

            if entry_price and launch_price and launch_price > 0:
                wallet_hits[addr]['entry_ratios'].append(entry_price / launch_price)

            wallet_hits[addr]['roi_details'].append({
                'runner':                  sym,
                'runner_address':          token_addr,
                'roi_multiplier':          wallet_info.get('realized_multiplier', 0),
                'total_multiplier':        wallet_info.get('total_multiplier', 0),
                'entry_to_ath_multiplier': round(entry_to_ath_mult, 2) if entry_to_ath_mult else None,
                'distance_to_ath_pct':     round(distance_to_ath_pct, 2) if distance_to_ath_pct else None,
                'entry_price':             entry_price,
            })

    # Separate cross-token from single-token wallets
    cross_token_candidates  = []
    single_token_candidates = []

    for addr, d in wallet_hits.items():
        runner_count = len(d['runners_hit'])

        avg_dist = (
            sum(d['distance_to_ath_vals']) / len(d['distance_to_ath_vals'])
            if d['distance_to_ath_vals'] else 0
        )
        avg_total_roi = (
            sum(d['total_roi_multipliers']) / len(d['total_roi_multipliers'])
            if d['total_roi_multipliers'] else 0
        )
        avg_ath = (
            sum(d['entry_to_ath_vals']) / len(d['entry_to_ath_vals'])
            if d['entry_to_ath_vals'] else None
        )

        # Entry consistency (10% of aggregate score — cross-token wallets only)
        if len(d['entry_ratios']) >= 2:
            try:
                variance          = statistics.variance(d['entry_ratios'])
                consistency_score = max(0, 100 - (variance * 10))
            except Exception:
                consistency_score = 50
        else:
            consistency_score = 50

        if runner_count >= min_runner_hits:
            # CROSS-TOKEN: score with aggregate formula 60/30/10
            aggregate_score = (
                0.60 * avg_dist +
                0.30 * (avg_total_roi / 10 * 100) +
                0.10 * consistency_score
            )
            participation = runner_count / len(tokens) if tokens else 0
            if participation >= 0.8 and aggregate_score >= 85:   tier = 'S'
            elif participation >= 0.6 and aggregate_score >= 75: tier = 'A'
            elif participation >= 0.4 and aggregate_score >= 65: tier = 'B'
            else:                                                 tier = 'C'

            cross_token_candidates.append({
                'wallet':                      addr,
                'is_cross_token':              True,
                'runner_count':                runner_count,
                'runners_hit':                 d['runners_hit'],
                'avg_distance_to_ath_pct':     round(avg_dist, 2),
                'avg_total_roi':               round(avg_total_roi, 2),
                'avg_entry_to_ath_multiplier': round(avg_ath, 2) if avg_ath else None,
                'consistency_score':           round(consistency_score, 2),
                'aggregate_score':             round(aggregate_score, 2),
                'tier':                        tier,
                'professional_grade':          _calculate_grade(aggregate_score),
                'roi_details':                 d['roi_details'][:5],
                'is_fresh':                    True,
                'analyzed_tokens':             d['runners_hit'],
                'runner_hits_30d':             0,
                'runner_success_rate':         0,
                'runner_avg_roi':              0,
                'other_runners':               [],
                'other_runners_stats':         {},
                'score_breakdown': {
                    'entry_score':       round(0.60 * avg_dist, 2),
                    'total_roi_score':   round(0.30 * (avg_total_roi / 10 * 100), 2),
                    'consistency_score': round(0.10 * consistency_score, 2),
                }
            })

        else:
            # SINGLE-TOKEN: score individually using professional_score
            # Use the best token's data for scoring (highest total_multiplier)
            best_raw = max(
                d['raw_wallet_data_list'],
                key=lambda x: x['wallet_info'].get('total_multiplier', 0)
            )
            wallet_info_for_scoring = {**best_raw['wallet_info'], 'ath_price': best_raw['ath_price']}
            scoring = analyzer.calculate_wallet_relative_score(wallet_info_for_scoring)

            if scoring['professional_score'] >= 90:   tier = 'S'
            elif scoring['professional_score'] >= 80: tier = 'A'
            elif scoring['professional_score'] >= 70: tier = 'B'
            else:                                     tier = 'C'

            token_sym = d['runners_hit'][0] if d['runners_hit'] else '?'

            single_token_candidates.append({
                'wallet':                      addr,
                'is_cross_token':              False,
                'runner_count':                runner_count,
                'runners_hit':                 d['runners_hit'],
                'analyzed_tokens':             d['runners_hit'],
                'professional_score':          scoring['professional_score'],
                'professional_grade':          scoring['professional_grade'],
                'tier':                        tier,
                'avg_distance_to_ath_pct':     round(avg_dist, 2),
                'avg_total_roi':               round(avg_total_roi, 2),
                'avg_entry_to_ath_multiplier': round(avg_ath, 2) if avg_ath else None,
                'entry_to_ath_multiplier':     scoring.get('entry_to_ath_multiplier'),
                'distance_to_ath_pct':         scoring.get('distance_to_ath_pct'),
                'roi_details':                 d['roi_details'][:5],
                'score_breakdown':             scoring['score_breakdown'],
                'is_fresh':                    True,
                'runner_hits_30d':             0,
                'runner_success_rate':         0,
                'runner_avg_roi':              0,
                'other_runners':               [],
                'other_runners_stats':         {},
            })

    # Sort each group
    cross_token_candidates.sort(
        key=lambda x: (x['runner_count'], x['aggregate_score']), reverse=True
    )
    single_token_candidates.sort(
        key=lambda x: x['professional_score'], reverse=True
    )

    # Merge: cross-token first, fill remaining slots with best single-token
    cross_top     = cross_token_candidates[:20]
    slots_remaining = max(0, 20 - len(cross_top))
    single_fill   = single_token_candidates[:slots_remaining]
    top_20        = cross_top + single_fill

    print(f"  ✓ Cross-token: {len(cross_top)} wallets | "
          f"Single-token fill: {len(single_fill)} wallets | "
          f"Top 20 total: {len(top_20)}")

    # Runner history for final top 20 only
    _, q_batch, q_compute = _get_queues()
    runner_jobs = []
    chunk_size  = 5

    for i in range(0, len(top_20), chunk_size):
        chunk     = top_20[i:i + chunk_size]
        batch_idx = i // chunk_size
        rh_job = q_batch.enqueue(
            'services.worker_tasks.fetch_runner_history_batch',
            {
                'token':     tokens[0] if tokens else {},
                'job_id':    job_id,
                'batch_idx': batch_idx,
                'wallets':   [w['wallet'] for w in chunk],
            }
        )
        runner_jobs.append(rh_job)

    q_compute.enqueue(
        'services.worker_tasks.merge_batch_final',
        {
            'job_id':             job_id,
            'user_id':            data.get('user_id', 'default_user'),
            'top_20':             top_20,
            'total':              len(cross_token_candidates) + len(single_token_candidates),
            'cross_token_count':  len(cross_token_candidates),
            'single_token_count': len(single_token_candidates),
            'tokens_analyzed':    len(all_token_results),
            'tokens':             tokens,
            'runner_batch_count': len(runner_jobs),
        },
        depends_on=Dependency(jobs=runner_jobs) if runner_jobs else None
    )

    print(f"  ✓ {len(runner_jobs)} runner history workers → merge_batch_final")
    return {'top_20_count': len(top_20), 'runner_jobs': len(runner_jobs)}


# =============================================================================
# BATCH FINAL MERGE — compute queue
# =============================================================================

def merge_batch_final(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    job_id              = data['job_id']
    user_id             = data.get('user_id', 'default_user')
    top_20              = data['top_20']
    total               = data['total']
    cross_token_count   = data.get('cross_token_count', 0)
    single_token_count  = data.get('single_token_count', 0)
    tokens_analyzed     = data.get('tokens_analyzed', 0)
    tokens              = data.get('tokens', [])
    runner_batch_count  = data['runner_batch_count']

    supabase = get_supabase_client()

    print(f"\n[BATCH FINAL] Attaching runner history for {len(top_20)} wallets...")

    runner_lookup = {}
    for i in range(runner_batch_count):
        batch = _load_result(f"runner_batch:{job_id}:{i}") or []
        for entry in batch:
            runner_lookup[entry['wallet']] = entry

    for w in top_20:
        rh = runner_lookup.get(w['wallet'])
        if rh:
            w['runner_hits_30d']     = rh['runner_hits_30d']
            w['runner_success_rate'] = rh['runner_success_rate']
            w['runner_avg_roi']      = rh['runner_avg_roi']
            w['other_runners']       = rh['other_runners']
            w['other_runners_stats'] = rh['other_runners_stats']
        else:
            w.setdefault('runner_hits_30d', 0)
            w.setdefault('runner_success_rate', 0)
            w.setdefault('runner_avg_roi', 0)
            w.setdefault('other_runners', [])
            w.setdefault('other_runners_stats', {})

    final_result = {
        'success':              True,
        'wallets':              top_20,
        'total':                total,
        'cross_token_count':    cross_token_count,
        'single_token_count':   single_token_count,
        'tokens_analyzed':      tokens_analyzed,
        'smart_money_wallets':  top_20,
        'wallets_discovered':   len(top_20),
        'runners_analyzed':     len(tokens),
        'tokens_analyzed_list': [t.get('ticker', t.get('symbol', '?')) for t in tokens],
        'mode':                 'distributed_batch_cross_token_overlap',
    }

    try:
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
            'status':   'completed',
            'phase':    'done',
            'progress': 100,
            'results':  final_result
        }).eq('job_id', job_id).execute()
        print(f"  ✅ Saved final batch result for job {job_id[:8]}")
    except Exception as e:
        print(f"[BATCH FINAL] ⚠️ Failed to save: {e}")

    print(f"  ✅ Batch complete: {len(top_20)} wallets "
          f"({cross_token_count} cross-token + {single_token_count} single-token fill)")
    return final_result


# =============================================================================
# CACHE WARMUP
# =============================================================================

def preload_trending_cache():
    _, q_batch, _ = _get_queues()
    job7  = q_batch.enqueue('services.worker_tasks.warm_cache_runners', {'days_back': 7})
    job14 = q_batch.enqueue('services.worker_tasks.warm_cache_runners', {'days_back': 14})
    print(f"[CACHE WARMUP] Queued 7d and 14d runner list warmup")
    return [job7.id, job14.id]


def warm_cache_runners(data):
    """[batch queue] Cache runner list in Redis."""
    from routes.wallets import get_worker_analyzer
    days_back = data['days_back']
    analyzer  = get_worker_analyzer()
    print(f"[WARMUP {days_back}D] Finding runners...")
    runners = analyzer.find_trending_runners_enhanced(
        days_back=days_back, min_multiplier=5.0, min_liquidity=50000
    )
    print(f"  ✅ Cached {len(runners)} runners for {days_back}d in Redis")
    return len(runners)