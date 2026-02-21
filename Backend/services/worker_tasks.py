"""
RQ Worker Tasks - Production Ready
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
      Entry consistency = variance of entry_price/launch_price across tokens (lower = better)
  16. Ranking: most tokens participated first, then aggregate score, top 20 returned
  17. perform_trending_batch_analysis now uses _queue_batch_pipeline (parallel distributed)
      run_trending_batch_analysis (synchronous single-worker) removed
  18. perform_auto_discovery now fetches runners then uses _queue_batch_pipeline (parallel)
      run_auto_discovery (synchronous single-worker) removed
  19. score_and_rank_single in batch mode: saves ALL qualified wallets to Supabase,
      does NOT score or rank — leaves all scoring to aggregate_cross_token
  20. Sample size preserved: no per-token top-20 cut in batch mode
  21. Runner history fetched AFTER cross-token correlation (aggregate_cross_token),
      only for the final top 20 wallets — not for every qualified wallet per token.
      This avoids fetching runner history for wallets that won't make the final cut.

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
# Saves ALL wallets that passed qualification (min $100, 3x) before scoring.
# Allows future batch jobs to skip Phases 1-4 entirely for known tokens.
# =============================================================================

def _save_qualified_wallets_cache(token_address, qualified_wallets):
    """
    Save all qualified wallets for a token to Supabase.
    Called from score_and_rank_single before any scoring/runner history.
    Table: token_qualified_wallets (token_address PK, qualified_wallets JSONB)
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    supabase = get_supabase_client()
    try:
        supabase.schema(SCHEMA_NAME).table('token_qualified_wallets').upsert({
            'token_address':    token_address,
            'qualified_wallets': qualified_wallets,
            'wallet_count':     len(qualified_wallets),
            'created_at':       time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }).execute()
        print(f"[CACHE] Saved {len(qualified_wallets)} qualified wallets for {token_address[:8]}")
    except Exception as e:
        print(f"[CACHE] Failed to save qualified wallets for {token_address[:8]}: {e}")


def _get_qualified_wallets_cache(token_address):
    """
    Retrieve cached qualified wallets for a token from Supabase.
    Returns list of wallet dicts or None if not cached.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    supabase = get_supabase_client()
    try:
        result = supabase.schema(SCHEMA_NAME).table('token_qualified_wallets').select(
            'qualified_wallets, created_at'
        ).eq('token_address', token_address).execute()
        if result.data and result.data[0].get('qualified_wallets'):
            wallets = result.data[0]['qualified_wallets']
            print(f"[CACHE HIT] {len(wallets)} qualified wallets for {token_address[:8]}")
            return wallets
    except Exception as e:
        print(f"[CACHE] Failed to read qualified wallets for {token_address[:8]}: {e}")
    return None


# =============================================================================
# WORKER ANALYZER GETTER - Redis-only mode
# =============================================================================

def get_worker_analyzer():
    """
    Get worker analyzer instance in Redis-only mode.
    Sets WORKER_MODE environment variable to tell WalletPumpAnalyzer to skip DuckDB.
    """
    from routes.wallets import get_worker_analyzer as get_analyzer
    os.environ['WORKER_MODE'] = 'true'
    return get_analyzer()


# =============================================================================
# ENTRY POINT — Supabase + Redis cache check before any pipeline work
# =============================================================================

def perform_wallet_analysis(data):
    """
    Entry point. Checks Redis → Supabase before queuing any work.
    Returns immediately in all cases. Frontend polls for progress.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    tokens  = data.get('tokens', [])
    user_id = data.get('user_id', 'default_user')
    job_id  = data.get('job_id')

    supabase = get_supabase_client()
    r        = _get_redis()
    q_high, q_batch, q_compute = _get_queues()

    # -------------------------------------------------------------------------
    # CACHE CHECK: Single token only (batch always runs fresh pipeline)
    # -------------------------------------------------------------------------
    if len(tokens) == 1:
        token         = tokens[0]
        token_address = token['address']

        # 1. Redis cache — fastest path
        cached = r.get(f"cache:token:{token_address}")
        if cached:
            cached_result = json.loads(cached)
            skip_cache = False
            try:
                current_ath_raw = r.get(f"token_ath:{token_address}")
                if current_ath_raw:
                    current_ath_price = json.loads(current_ath_raw).get('highest_price', 0)
                    cached_wallets = cached_result.get('wallets', [])
                    cached_ath = next(
                        (w.get('ath_price', 0) for w in cached_wallets if w.get('ath_price')), 0
                    )
                    if cached_ath > 0 and current_ath_price > cached_ath * 1.10:
                        print(f"[CACHE INVALIDATED] ATH moved since last analysis for {token.get('ticker')} — running fresh")
                        skip_cache = True
                        r.delete(f"cache:token:{token_address}")
            except Exception as e:
                print(f"[CACHE] ATH check failed — serving cached result anyway: {e}")

            if not skip_cache:
                print(f"[CACHE HIT] Redis — instant return for {token.get('ticker')}")
                try:
                    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                        'status': 'completed', 'phase': 'done', 'progress': 100,
                        'results': cached_result
                    }).eq('job_id', job_id).execute()
                except Exception as e:
                    print(f"[CACHE] Failed to update job with cached result: {e}")
                return

        # 2. Supabase — find previous completed analysis for this token
        if not (cached and skip_cache):
            try:
                existing = supabase.schema(SCHEMA_NAME).table('analysis_jobs').select(
                    'results'
                ).eq('token_address', token_address).eq(
                    'status', 'completed'
                ).order('created_at', desc=True).limit(1).execute()

                if existing.data and existing.data[0].get('results'):
                    result = existing.data[0]['results']
                    print(f"[CACHE HIT] Supabase — returning saved result for {token.get('ticker')}")
                    r.set(f"cache:token:{token_address}", json.dumps(result), ex=21600)
                    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                        'status': 'completed', 'phase': 'done', 'progress': 100,
                        'results': result
                    }).eq('job_id', job_id).execute()
                    return
            except Exception as e:
                print(f"[CACHE CHECK] Supabase lookup failed — running fresh pipeline: {e}")

    # -------------------------------------------------------------------------
    # NO CACHE — queue the full pipeline
    # -------------------------------------------------------------------------
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

    job1 = q_high.enqueue('services.worker_tasks.fetch_top_traders',    {'token': token, 'job_id': job_id})
    job2 = q_high.enqueue('services.worker_tasks.fetch_first_buyers',   {'token': token, 'job_id': job_id})
    job3 = q_high.enqueue('services.worker_tasks.fetch_birdeye_trades', {'token': token, 'job_id': job_id})

    job4_coord = q_compute.enqueue(
        'services.worker_tasks.coordinate_entry_prices',
        {'token': token, 'job_id': job_id},
        depends_on=Dependency(jobs=[job1])
    )

    pnl_coordinator = q_compute.enqueue(
        'services.worker_tasks.coordinate_pnl_phase',
        {
            'token':       token,
            'job_id':      job_id,
            'user_id':     user_id,
            'phase1_jobs': [job1.id, job2.id, job3.id, job4_coord.id]
        },
        depends_on=Dependency(jobs=[job1, job2, job3, job4_coord])
    )

    # Explicitly queue scorer here — coordinate_pnl_phase no longer does this
    scorer_job = q_compute.enqueue(
        'services.worker_tasks.score_and_rank_single',
        {
            'token':   token,
            'job_id':  job_id,
            'user_id': user_id,
            # No parent_job_id = single token mode → scores and ranks immediately
        },
        depends_on=Dependency(jobs=[pnl_coordinator])
    )

    r = _get_redis()
    r.set(f"pipeline:{job_id}:coordinator", pnl_coordinator.id, ex=3600)
    r.set(f"pipeline:{job_id}:token",       json.dumps(token),  ex=3600)

    print(f"  ✓ Phase 1: {[j.id[:8] for j in [job1, job2, job3]]}")
    print(f"  ✓ Entry coord: {job4_coord.id[:8]} | PnL coord: {pnl_coordinator.id[:8]} | Scorer: {scorer_job.id[:8]}")


def _queue_batch_pipeline(tokens, user_id, job_id, supabase, min_runner_hits=2):
    """
    Queue full pipeline per token in parallel across all workers.

    BATCH MODE SCORING FLOW:
      Phase 1-4: fetch wallets + qualify per token (parallel across workers)
      score_and_rank_single (batch mode):
        - saves ALL qualified wallets to Supabase
        - does NOT score or rank (no per-token top-20 cut)
        - passes raw qualified wallet data to aggregator
      aggregate_cross_token:
        - loads ALL qualified wallets from Redis per token
        - finds cross-token wallets
        - scores using 60/30/10 (entry timing / total ROI / consistency)
        - ranks by token count then aggregate score
        - returns top 20

    This preserves full sample size — no wallet is excluded from cross-token
    correlation due to per-token ranking cutoffs.

    aggregate_cross_token is NOT queued here — it's triggered automatically
    by merge_and_save_final when the last token completes (counter-based).
    """
    print(f"\n[PIPELINE] Queuing batch: {len(tokens)} tokens")
    q_high, q_batch, q_compute = _get_queues()
    r = _get_redis()

    sub_job_ids = [f"{job_id}__{t['address'][:8]}" for t in tokens]

    # Store batch metadata in Redis for merge_and_save_final to trigger aggregator
    r.set(f"batch_total:{job_id}",           len(tokens),             ex=7200)
    r.set(f"batch_sub_jobs:{job_id}",        json.dumps(sub_job_ids), ex=7200)
    r.set(f"batch_tokens:{job_id}",          json.dumps(tokens),      ex=7200)
    r.set(f"batch_completed:{job_id}",       0,                       ex=7200)
    r.set(f"batch_min_runner_hits:{job_id}", min_runner_hits,         ex=7200)
    r.set(f"batch_user_id:{job_id}",         user_id,                 ex=7200)

    for token, sub_job_id in zip(tokens, sub_job_ids):
        r.set(f"pipeline:{sub_job_id}:token", json.dumps(token), ex=3600)

        # Check Supabase cache for this token's qualified wallets
        cached_wallets = _get_qualified_wallets_cache(token['address'])

        if cached_wallets:
            # Fast path: skip Phases 1-4, go straight to aggregator contribution
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
            # Full pipeline path: Phases 1-4 then save qualified wallets
            job1 = q_high.enqueue('services.worker_tasks.fetch_top_traders',    {'token': token, 'job_id': sub_job_id})
            job2 = q_high.enqueue('services.worker_tasks.fetch_first_buyers',   {'token': token, 'job_id': sub_job_id})
            job3 = q_high.enqueue('services.worker_tasks.fetch_birdeye_trades', {'token': token, 'job_id': sub_job_id})

            job4_coord = q_compute.enqueue(
                'services.worker_tasks.coordinate_entry_prices',
                {'token': token, 'job_id': sub_job_id},
                depends_on=Dependency(jobs=[job1])
            )

            pnl_coordinator = q_compute.enqueue(
                'services.worker_tasks.coordinate_pnl_phase',
                {
                    'token':       token,
                    'job_id':      sub_job_id,
                    'user_id':     user_id,
                    'phase1_jobs': [job1.id, job2.id, job3.id, job4_coord.id]
                },
                depends_on=Dependency(jobs=[job1, job2, job3, job4_coord])
            )

            q_compute.enqueue(
                'services.worker_tasks.score_and_rank_single',
                {
                    'token':         token,
                    'job_id':        sub_job_id,
                    'parent_job_id': job_id,   # batch mode flag
                    'user_id':       user_id,
                },
                depends_on=Dependency(jobs=[pnl_coordinator])
            )

            print(f"  ✓ Full pipeline for {token.get('ticker')} [{sub_job_id[:8]}]")

    print(f"  ✓ Aggregator will trigger automatically when all {len(tokens)} tokens complete")


# =============================================================================
# TRENDING BATCH ANALYSIS — uses distributed pipeline
# Replaces the old synchronous run_trending_batch_analysis (removed).
# Runners are converted to token format and fanned out via _queue_batch_pipeline.
# Cross-token correlation happens in aggregate_cross_token after all tokens complete.
# =============================================================================

def perform_trending_batch_analysis(data):
    """
    Entry point for trending batch analysis.

    Converts runners to token format and routes through _queue_batch_pipeline
    so all tokens are analyzed in parallel across workers.

    Cross-token correlation (finding wallets that appear across multiple tokens)
    happens in aggregate_cross_token after ALL tokens complete — not per-token.
    This preserves the full wallet pool for cross-token ranking.

    Previously used run_trending_batch_analysis (synchronous single compute worker).
    That function has been removed — all batch analysis now uses the distributed pipeline.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    runners            = data.get('runners', [])
    user_id            = data.get('user_id', 'default_user')
    min_runner_hits    = data.get('min_runner_hits', 2)
    job_id             = data.get('job_id')

    supabase = get_supabase_client()

    print(f"\n[TRENDING BATCH] Starting distributed analysis of {len(runners)} runners")

    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
        'status':           'processing',
        'phase':            'queuing_pipeline',
        'progress':         10,
        'tokens_total':     len(runners),
        'tokens_completed': 0
    }).eq('job_id', job_id).execute()

    # Convert runner format to token format expected by _queue_batch_pipeline
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
    print(f"  ✓ Cross-token correlation will run in aggregate_cross_token after all tokens complete")


# =============================================================================
# AUTO-DISCOVERY — finds runners then uses distributed pipeline
# Replaces the old synchronous run_auto_discovery (removed).
# Phase 1: find_trending_runners_enhanced (this worker)
# Phase 2: fan out to _queue_batch_pipeline for parallel analysis
# =============================================================================

def perform_auto_discovery(data):
    """
    Entry point for auto-discovery.

    Phase 1 (this worker): fetches trending runners via find_trending_runners_enhanced.
    Phase 2: fans out to _queue_batch_pipeline for fully parallel analysis.

    Cross-token correlation happens in aggregate_cross_token after all tokens complete.

    Previously used run_auto_discovery (synchronous single compute worker).
    That function has been removed — auto-discovery now uses the distributed pipeline.
    """
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

    # Take top 10 runners
    selected = runners[:10]

    print(f"[AUTO DISCOVERY] Found {len(runners)} runners — analyzing top {len(selected)}")

    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
        'phase':        'queuing_pipeline',
        'progress':     25,
        'tokens_total': len(selected),
    }).eq('job_id', job_id).execute()

    # Convert to token format and fan out
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
    print(f"  ✓ Cross-token correlation will run in aggregate_cross_token after all tokens complete")


# =============================================================================
# PHASE 1 WORKERS — high queue
# =============================================================================

def fetch_top_traders(data):
    """Worker 1 [high]: Fetch top 100 traders. PnL included, entry_price filled by Phase 2."""
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
    """Worker 2 [high]: Fetch first 100 buyers. Entry price derived from first_buy math."""
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


def fetch_birdeye_trades(data):
    """
    Worker 3 [high]: Fetch early buyers from Birdeye.
    Time window anchored to token launch (max 30-day API constraint).
    entry_price from from.price field. Uses tx_type=all (matches single-token path).
    """
    analyzer = get_worker_analyzer()
    token    = data['token']
    job_id   = data['job_id']

    launch_time = None
    try:
        url        = f"{analyzer.st_base_url}/tokens/{token['address']}"
        token_info = analyzer.fetch_with_retry(
            url, analyzer._get_solanatracker_headers(),
            semaphore=analyzer.solana_tracker_semaphore
        )
        if token_info:
            launch_time = token_info.get('token', {}).get('creation', {}).get('created_time')
    except Exception as e:
        print(f"[WORKER 3] Failed to fetch launch time: {e}")

    current_time    = int(time.time())
    thirty_days_ago = current_time - (30 * 86400)
    time_params     = {}

    if launch_time and launch_time > 0:
        if launch_time >= thirty_days_ago:
            after_time  = int(launch_time)
            before_time = min(int(launch_time) + (5 * 86400), current_time)
            time_params = {"after_time": after_time, "before_time": before_time}
            print(f"[WORKER 3] Launch window: {after_time} → {before_time}")
        else:
            after_time  = thirty_days_ago
            before_time = thirty_days_ago + (5 * 86400)
            time_params = {"after_time": after_time, "before_time": before_time}
            print(f"[WORKER 3] Token >30d old — oldest allowed window")
    else:
        after_time  = thirty_days_ago
        before_time = thirty_days_ago + (5 * 86400)
        time_params = {"after_time": after_time, "before_time": before_time}

    all_trades = []
    offset     = 0

    while offset < 10000:
        params = {
            "address":   token['address'],
            "offset":    offset,
            "limit":     100,
            "sort_by":   "block_unix_time",
            "sort_type": "asc",
            "tx_type":   "all",
            **time_params,
        }

        response = analyzer.fetch_with_retry(
            f"{analyzer.birdeye_base_url}/defi/v3/token/txs",
            analyzer._get_birdeye_headers(),
            params,
            semaphore=analyzer.birdeye_semaphore
        )

        if not response or not response.get('success'):
            print(f"[WORKER 3] Bad response at offset {offset}")
            break

        trades = response.get('data', {}).get('items', [])
        if not trades:
            break

        all_trades.extend(trades)
        print(f"[WORKER 3] offset={offset}: +{len(trades)} (total={len(all_trades)})")

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
            from_data    = trade.get('from', {}) or {}
            actual_price = from_data.get('price')

            wallet_data[wallet] = {
                'source':         'birdeye_trades',
                'earliest_entry': trade.get('block_unix_time'),
                'entry_price':    actual_price,
            }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'birdeye_trades'}
    _save_result(f"phase1_birdeye:{job_id}", result)
    print(f"[WORKER 3] Done: {len(wallets)} unique wallets")
    return result


# =============================================================================
# PHASE 1 COORDINATOR + BATCH WORKERS — compute spawns batch
# =============================================================================

def coordinate_entry_prices(data):
    """
    [compute queue] Reads top traders from Redis, splits into fixed batches of 10,
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
    """
    [batch queue] Fetches first-buy entry prices for a batch of ~10 wallets.
    asyncio with semaphore=6 per batch.
    """
    analyzer  = get_worker_analyzer()
    import aiohttp
    from asyncio import Semaphore as AsyncSemaphore

    token     = data['token']
    job_id    = data['job_id']
    batch_idx = data['batch_idx']
    wallets   = data['wallets']

    print(f"[ENTRY BATCH {batch_idx}] {len(wallets)} wallets...")

    async def _fetch():
        async with aiohttp.ClientSession() as session:
            sem   = AsyncSemaphore(6)
            tasks = []
            for wallet in wallets:
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
                                return {'wallet': w, 'price': first_buy.get('priceUsd'), 'time': first_buy.get('time')}
                        return {'wallet': w, 'price': None, 'time': None}
                tasks.append(fetch())
            return await asyncio.gather(*tasks)

    results = asyncio.run(_fetch())
    found   = sum(1 for r in results if r and r.get('price') is not None)
    print(f"[ENTRY BATCH {batch_idx}] Done: {found}/{len(wallets)} prices found")

    _save_result(f"entry_prices_batch:{job_id}:{batch_idx}", results)
    return results


def merge_entry_prices(data):
    """
    [compute queue] Collects all entry-price batch results, merges into top_traders
    wallet_data, overwrites phase1_top_traders in Redis with enriched data.
    """
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
# Does NOT queue score_and_rank_single — that is done by the pipeline queuer.
# Saves batch_count to Redis for score_and_rank_single to read.
# =============================================================================

def coordinate_pnl_phase(data):
    """
    [compute queue] Merges Phase 1 results, dispatches parallel PnL batch jobs.
    Top Traders + First Buyers skip PnL fetch (already have it).
    Birdeye wallets fetch PnL only.

    NOTE: Does NOT queue score_and_rank_single — the pipeline queuer
    (_queue_single_token_pipeline / _queue_batch_pipeline) handles that externally.
    Saves batch_count to Redis key pnl_batch_info:{job_id} for the scorer to read.
    """
    token       = data['token']
    job_id      = data['job_id']
    user_id     = data.get('user_id', 'default_user')
    phase1_jobs = data['phase1_jobs']

    print(f"\n[PNL COORD] Phase 1 complete for {token.get('ticker')} — merging...")

    all_wallets = []
    wallet_data = {}

    for key_prefix in ['phase1_top_traders', 'phase1_first_buyers', 'phase1_birdeye']:
        result = _load_result(f"{key_prefix}:{job_id}")
        if result:
            for wallet in result['wallets']:
                if wallet not in wallet_data:
                    all_wallets.append(wallet)
                    wallet_data[wallet] = result['wallet_data'].get(wallet, {})
                else:
                    existing = wallet_data[wallet]
                    new      = result['wallet_data'].get(wallet, {})
                    if new.get('entry_price') and not existing.get('entry_price'):
                        existing['entry_price'] = new['entry_price']
                    if new.get('pnl_data') and not existing.get('pnl_data'):
                        existing['pnl_data'] = new['pnl_data']

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

    # Save batch info to Redis for score_and_rank_single to read
    r = _get_redis()
    r.set(f"pnl_batch_info:{job_id}", json.dumps({
        'batch_count': len(pnl_jobs),
        'pnl_job_ids': [j.id for j in pnl_jobs]
    }), ex=3600)

    return {'pnl_jobs': [j.id for j in pnl_jobs], 'batch_count': len(pnl_jobs)}


# =============================================================================
# PHASE 2 WORKERS — batch queue
# =============================================================================

def fetch_pnl_batch(data):
    """
    [batch queue] Fetch PnL for a batch of wallets.
    Top Traders + First Buyers (have pnl_data + entry_price) → skip API entirely.
    Birdeye wallets (have entry_price, no pnl_data) → fetch PnL only.
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

    first_buyers_ready     = []
    top_traders_need_price = []
    birdeye_need_pnl       = []

    for wallet in wallets:
        wdata     = wallet_data.get(wallet, {})
        source    = wdata.get('source', '')
        has_pnl   = wdata.get('pnl_data') is not None
        has_price = wdata.get('entry_price') is not None

        if source == 'first_buyers' and has_pnl and has_price:
            first_buyers_ready.append(wallet)
        elif source == 'top_traders' and has_pnl and not has_price:
            top_traders_need_price.append(wallet)
        elif source == 'top_traders' and has_pnl and has_price:
            first_buyers_ready.append(wallet)
        elif source == 'birdeye_trades':
            birdeye_need_pnl.append(wallet)
        else:
            if has_pnl:
                first_buyers_ready.append(wallet)
            else:
                birdeye_need_pnl.append(wallet)

    print(f"[PNL BATCH {batch_idx}] {len(wallets)} wallets | "
          f"{len(first_buyers_ready)} skip | "
          f"{len(top_traders_need_price)} need price | "
          f"{len(birdeye_need_pnl)} fetch PnL")

    for wallet in first_buyers_ready:
        pnl = wallet_data[wallet]['pnl_data']
        _qualify_wallet(wallet, pnl, wallet_data, token, qualified)

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
            _qualify_wallet(wallet, pnl, wallet_data, token, qualified)

    async def _fetch_birdeye_pnls():
        async with aiohttp.ClientSession() as session:
            sem   = AsyncSemaphore(2)
            tasks = []
            for wallet in birdeye_need_pnl:
                async def fetch(w=wallet):
                    async with sem:
                        return await analyzer.async_fetch_with_retry(
                            session,
                            f"{analyzer.st_base_url}/pnl/{w}/{token['address']}",
                            analyzer._get_solanatracker_headers()
                        )
                tasks.append(fetch())
            return await asyncio.gather(*tasks)

    if birdeye_need_pnl:
        results = asyncio.run(_fetch_birdeye_pnls())
        for wallet, pnl in zip(birdeye_need_pnl, results):
            if pnl:
                _qualify_wallet(wallet, pnl, wallet_data, token, qualified)

    _save_result(f"pnl_batch:{job_id}:{batch_idx}", qualified)
    print(f"[PNL BATCH {batch_idx}] Done: {len(qualified)} qualified")
    return qualified


def _qualify_wallet(wallet, pnl_data, wallet_data, token, qualified_list, min_invested=100, min_roi_mult=3.0):
    """
    Check qualification criteria and add to qualified list.
    Passes if realized OR total multiplier >= threshold.
    A holder sitting on 3x unrealized is just as valid as someone who sold at 3x.
    """
    realized       = pnl_data.get('realized', 0)
    unrealized     = pnl_data.get('unrealized', 0)
    total_invested = pnl_data.get('total_invested') or pnl_data.get('totalInvested', 0)

    if total_invested < min_invested:
        return

    realized_mult = (realized + total_invested) / total_invested
    total_mult    = (realized + unrealized + total_invested) / total_invested

    if realized_mult < min_roi_mult and total_mult < min_roi_mult:
        return

    wdata       = wallet_data.get(wallet, {})
    entry_price = wdata.get('entry_price')

    if entry_price is None:
        first_buy  = pnl_data.get('first_buy', {})
        amount     = first_buy.get('amount', 0)
        volume_usd = first_buy.get('volume_usd', 0)
        if amount > 0:
            entry_price = volume_usd / amount

    qualified_list.append({
        'wallet':              wallet,
        'source':              wdata.get('source', 'unknown'),
        'realized':            realized,
        'unrealized':          unrealized,
        'total_invested':      total_invested,
        'realized_multiplier': realized_mult,
        'total_multiplier':    total_mult,
        'earliest_entry':      wdata.get('earliest_entry'),
        'entry_price':         entry_price,
    })


# =============================================================================
# PHASE 3: SCORE + RANK — compute queue
#
# SINGLE MODE (no parent_job_id):
#   - Saves ALL qualified wallets to Supabase cache
#   - Scores using 60/30/10 (entry timing / total ROI / realized ROI)
#   - Cuts to top 20
#   - Queues runner history → merge_and_save_final → saves result to job
#
# BATCH MODE (parent_job_id present):
#   - Saves ALL qualified wallets to Supabase cache
#   - Saves raw qualified wallet list to Redis (no scoring, no ranking)
#   - Queues merge_and_save_final which triggers aggregate_cross_token
#   - aggregate_cross_token handles all scoring and cross-token ranking
#   - Full wallet pool preserved — no per-token top-20 cut
# =============================================================================

def score_and_rank_single(data):
    """
    [compute queue] Collect PnL batch results, save to Supabase cache.

    SINGLE mode (no parent_job_id):
      Score and rank immediately. Queues runner history. Saves final result to job.

    BATCH mode (parent_job_id present):
      Save ALL qualified wallets to Redis and Supabase cache.
      Do NOT score or rank — aggregate_cross_token handles that after all tokens complete.
      Trigger merge_and_save_final to increment batch counter.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    token        = data['token']
    job_id       = data['job_id']
    user_id      = data.get('user_id', 'default_user')
    parent_job   = data.get('parent_job_id')
    is_batch     = parent_job is not None

    analyzer = get_worker_analyzer()
    supabase = get_supabase_client()

    # Read batch_count from Redis (set by coordinate_pnl_phase)
    r = _get_redis()
    batch_info_raw = r.get(f"pnl_batch_info:{job_id}")
    if batch_info_raw:
        batch_info  = json.loads(batch_info_raw)
        batch_count = batch_info['batch_count']
    else:
        batch_count = data.get('batch_count', 0)

    print(f"\n[SCORER] {token.get('ticker')} — collecting {batch_count} PnL batches... (mode={'batch' if is_batch else 'single'})")

    qualified_wallets = []
    for i in range(batch_count):
        batch_result = _load_result(f"pnl_batch:{job_id}:{i}")
        if batch_result:
            qualified_wallets.extend(batch_result)

    print(f"  ✓ {len(qualified_wallets)} qualified wallets")

    # Save ALL qualified wallets to Supabase cache (both modes)
    token_address = token.get('address')
    if token_address and qualified_wallets:
        _save_qualified_wallets_cache(token_address, qualified_wallets)

    if is_batch:
        # BATCH MODE: save raw data to Redis for aggregator, skip scoring
        # aggregate_cross_token will score and rank after all tokens complete
        _save_result(f"ranked_wallets:{job_id}", qualified_wallets)  # raw, not scored/ranked

        print(f"  ✓ Batch mode: saved {len(qualified_wallets)} raw wallets for aggregator (no per-token ranking)")

        _, q_batch, q_compute = _get_queues()

        # Runner history is fetched AFTER aggregate_cross_token identifies the final top 20.
        # No point fetching it here for wallets that won't make the cross-token cut.
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
            # Single token: no consistency_score → uses realized ROI for 10%
            scoring = analyzer.calculate_wallet_relative_score(wallet_info)

            if scoring['professional_score'] >= 90:   tier = 'S'
            elif scoring['professional_score'] >= 80: tier = 'A'
            elif scoring['professional_score'] >= 70: tier = 'B'
            else:                                     tier = 'C'

            wallet_results.append({
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
                'runner_hits_30d':         0,
                'runner_success_rate':     0,
                'runner_avg_roi':          0,
                'other_runners':           [],
                'other_runners_stats':     {},
                'is_fresh':                True,
            })

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

        print(f"  ✓ {len(runner_jobs)} runner history workers (5 wallets each)")

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
# CACHE PATH FAST TRACK — compute queue
# Used by _queue_batch_pipeline when a token has cached qualified wallets.
# Skips Phases 1-4 entirely. Reads from Supabase, saves to Redis for aggregator.
# =============================================================================

def fetch_from_token_cache(data):
    """
    [compute queue] Fast path for batch analysis when a token's qualified wallets
    are already cached in Supabase.

    BATCH MODE ONLY (always has parent_job_id).
    Loads cached wallets → saves raw to Redis → queues merge_and_save_final.
    Runner history is NOT fetched here — aggregate_cross_token fetches it for
    the final top 20 only after cross-token correlation is complete.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    token      = data['token']
    job_id     = data['job_id']
    parent_job = data.get('parent_job_id')
    user_id    = data.get('user_id', 'default_user')

    print(f"\n[TOKEN CACHE] Fast path for {token.get('ticker')} [{job_id[:8]}]...")

    qualified_wallets = _get_qualified_wallets_cache(token['address'])
    if not qualified_wallets:
        print(f"[TOKEN CACHE] Cache miss for {token['address'][:8]} — returning empty result")
        _save_result(f"ranked_wallets:{job_id}", [])
        result = {'success': True, 'token': token, 'wallets': [], 'total': 0}
        _save_result(f"token_result:{job_id}", result)
        _trigger_aggregate_if_complete(parent_job, job_id)
        return result

    print(f"  ✓ Loaded {len(qualified_wallets)} cached wallets — saving for aggregator")

    # Save raw qualified wallets to Redis for aggregator (no scoring, no runner history)
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

    print(f"  ✓ Cache path: merge {merge_job.id[:8]} queued — will increment batch counter")
    return {'merge_job': merge_job.id}


def _trigger_aggregate_if_complete(parent_job_id, sub_job_id):
    """
    Increment the batch completion counter. If all tokens are done,
    queue aggregate_cross_token. Called by merge_and_save_final.
    """
    if not parent_job_id:
        return

    r = _get_redis()
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
                current_token=token['address'],
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
#
# SINGLE mode: merges runner history into scored/ranked wallets, saves final result.
# BATCH mode:  saves raw token result with runner history attached.
#              aggregate_cross_token uses ranked_wallets:{sub_job_id} (raw qualified
#              wallets) for cross-token correlation and scoring.
# =============================================================================

def merge_and_save_final(data):
    """
    [compute queue] Save token result and trigger batch counter.

    SINGLE mode:
      Collects runner history batches, merges into scored/ranked wallet list,
      saves final result directly to job record.

    BATCH mode:
      Saves raw token result (no runner history — that happens after aggregation).
      Increments Redis counter. When last token fires, queues aggregate_cross_token.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    token           = data['token']
    job_id          = data['job_id']
    user_id         = data.get('user_id', 'default_user')
    parent_job      = data.get('parent_job_id')
    total_qualified = data['total_qualified']
    is_batch_mode   = data.get('is_batch_mode', parent_job is not None)

    # Single mode only
    runner_batch_count = data.get('runner_batch_count', 0)

    supabase = get_supabase_client()
    r        = _get_redis()

    # ranked_wallets: scored list (single) or raw qualified list (batch)
    wallet_list = _load_result(f"ranked_wallets:{job_id}") or []
    token_address = token.get('address')

    if not is_batch_mode:
        # SINGLE MODE: collect runner history and attach to scored wallets
        print(f"\n[MERGE] {token.get('ticker')} — collecting {runner_batch_count} runner history batches...")

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

        # ATH cache validity check before warming Redis
        warm_redis_cache = True
        try:
            current_ath_raw = r.get(f"token_ath:{token_address}")
            if current_ath_raw:
                current_ath_price = json.loads(current_ath_raw).get('highest_price', 0)
                analysis_ath = next(
                    (w.get('ath_price', 0) for w in wallet_list if w.get('ath_price')), 0
                )
                if analysis_ath > 0 and current_ath_price > analysis_ath * 1.10:
                    print(f"  ⚠️ ATH moved during analysis for {token.get('ticker')} — skipping Redis warm")
                    warm_redis_cache = False
        except Exception as e:
            print(f"[MERGE] ATH check failed — proceeding with cache warm: {e}")

        if warm_redis_cache:
            r.set(f"cache:token:{token_address}", json.dumps(result), ex=21600)
            print(f"  ✓ Redis cache warmed for {token.get('ticker')} (6hr TTL)")

        try:
            supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                'status':        'completed',
                'phase':         'done',
                'progress':      100,
                'results':       result,
                'token_address': token_address,
            }).eq('job_id', job_id).execute()
            print(f"  ✅ Supabase: saved final result for job {job_id[:8]}")
        except Exception as e:
            print(f"[MERGE] ⚠️ Failed to save final result: {e}")

        print(f"  ✅ Complete: {len(wallet_list)} wallets ({total_qualified} qualified)")
        return result

    else:
        # BATCH MODE: save raw token result, increment parent counter.
        # Runner history will be fetched by merge_batch_final after aggregation.
        print(f"\n[MERGE BATCH] {token.get('ticker')} — saving token result, incrementing counter...")

        result = {
            'success': True,
            'token':   token,
            'wallets': wallet_list,   # raw qualified wallets, no runner history yet
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
            print(f"  ✅ Supabase: cached individual token row for {token.get('ticker')}")
        except Exception as e:
            print(f"[MERGE BATCH] ⚠️ Failed to insert individual token cache row: {e}")

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
# Triggered by _trigger_aggregate_if_complete after last merge_and_save_final.
#
# Reads ranked_wallets:{sub_job_id} for each token.
# In batch mode these contain RAW qualified wallets (not scored/ranked per-token).
# This is the only place batch scoring and ranking happens.
#
# Scoring:
#   60% — avg distance to ATH (entry timing)
#   30% — avg total ROI (realized + unrealized)
#   10% — entry consistency (variance of entry_price/launch_price across tokens)
#
# Ranking:
#   1. Filter: min_runner_hits gate
#   2. Primary: most tokens participated
#   3. Secondary: aggregate score
#   4. Return top 20
# =============================================================================

def aggregate_cross_token(data):
    """
    [compute queue] Cross-token correlation and scoring for batch analysis.

    Reads the raw qualified wallet lists saved by score_and_rank_single (batch mode).
    No per-token ranking has occurred — full wallet pool is available here.

    Ranking:
      1. Filter: min_runner_hits gate (wallets below threshold excluded)
      2. Primary sort: most tokens participated
      3. Secondary sort: aggregate score
         - 60% avg distance to ATH (entry timing)
         - 30% avg total ROI (realized + unrealized)
         - 10% entry consistency (variance of entry_price/launch_price multiplier)
      4. Return top 20

    Fallback: if no cross-token overlap, rank all wallets individually.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    from collections import defaultdict

    tokens          = data['tokens']
    job_id          = data['job_id']
    sub_job_ids     = data['sub_job_ids']
    min_runner_hits = data.get('min_runner_hits', 2)

    supabase = get_supabase_client()
    analyzer = get_worker_analyzer()

    print(f"\n[AGGREGATOR] Cross-token ranking for {len(tokens)} tokens (min_runner_hits={min_runner_hits})...")

    # Load all token results (ranked_wallets = raw qualified wallets in batch mode)
    all_token_results = []
    for sub_job_id, token in zip(sub_job_ids, tokens):
        wallets = _load_result(f"ranked_wallets:{sub_job_id}")
        if wallets:
            all_token_results.append({'token': token, 'wallets': wallets})

    print(f"  ✓ Loaded {len(all_token_results)}/{len(tokens)} token results")

    # Pre-fetch launch prices for entry consistency calculation
    launch_prices = {}
    for token_result in all_token_results:
        addr = token_result['token']['address']
        try:
            launch_price = analyzer._get_token_launch_price(addr)
            launch_prices[addr] = launch_price or 0
        except Exception as e:
            print(f"  ⚠️ Could not fetch launch price for {addr[:8]}: {e}")
            launch_prices[addr] = 0

    # Pre-fetch ATH prices for entry timing scoring
    ath_prices = {}
    for token_result in all_token_results:
        addr = token_result['token']['address']
        try:
            ath_data = analyzer.get_token_ath(addr)
            ath_prices[addr] = ath_data.get('highest_price', 0) if ath_data else 0
        except Exception as e:
            print(f"  ⚠️ Could not fetch ATH for {addr[:8]}: {e}")
            ath_prices[addr] = 0

    # Build wallet_hits — aggregate each wallet's data across all tokens
    wallet_hits = defaultdict(lambda: {
        'wallet':                None,
        'runners_hit':           [],
        'runners_hit_addresses': set(),
        'roi_details':           [],
        'entry_to_ath_vals':     [],
        'distance_to_ath_vals':  [],
        'total_roi_multipliers': [],
        'entry_ratios':          [],
    })

    for token_result in all_token_results:
        token        = token_result['token']
        token_addr   = token['address']
        launch_price = launch_prices.get(token_addr, 0)
        ath_price    = ath_prices.get(token_addr, 0)

        for wallet_info in token_result['wallets']:
            # wallet_info is a raw qualified wallet dict in batch mode
            addr = wallet_info.get('wallet')
            if not addr:
                continue

            if wallet_hits[addr]['wallet'] is None:
                wallet_hits[addr]['wallet'] = addr

            sym = token.get('ticker', token.get('symbol', '?'))
            if sym not in wallet_hits[addr]['runners_hit']:
                wallet_hits[addr]['runners_hit'].append(sym)
                wallet_hits[addr]['runners_hit_addresses'].add(token_addr)

            # Compute entry timing for this token
            entry_price = wallet_info.get('entry_price')
            distance_to_ath_pct = 0
            entry_to_ath_mult   = 0

            if entry_price and entry_price > 0 and ath_price and ath_price > 0:
                distance_to_ath_pct   = ((ath_price - entry_price) / ath_price) * 100
                entry_to_ath_mult     = ath_price / entry_price
                wallet_hits[addr]['distance_to_ath_vals'].append(distance_to_ath_pct)
                wallet_hits[addr]['entry_to_ath_vals'].append(entry_to_ath_mult)

            # Total ROI for 30%
            total_mult = wallet_info.get('total_multiplier', 0)
            if total_mult:
                wallet_hits[addr]['total_roi_multipliers'].append(total_mult)

            # Entry consistency: entry_price / launch_price ratio
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

    # Build ranked candidates
    all_candidates = []
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

        # Entry consistency score (10%):
        # Variance of entry_price/launch_price multiplier — lower variance = more consistent
        if len(d['entry_ratios']) >= 2:
            try:
                variance          = statistics.variance(d['entry_ratios'])
                consistency_score = max(0, 100 - (variance * 10))
            except Exception:
                consistency_score = 50
        else:
            consistency_score = 50  # neutral — single data point

        # Aggregate score: 60% entry timing | 30% total ROI | 10% entry consistency
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

        all_candidates.append({
            'wallet':                      addr,
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
            # runner_hits_30d / other_runners filled by merge_batch_final after aggregation
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

    # Apply min_runner_hits filter
    ranked = [c for c in all_candidates if c['runner_count'] >= min_runner_hits]

    no_overlap_fallback = False
    if not ranked:
        print(f"  ⚠️ No cross-token overlap (min={min_runner_hits}) — ranking individually")
        ranked = all_candidates
        no_overlap_fallback = True
        for r in ranked:
            r['no_overlap_fallback'] = True
        ranked.sort(key=lambda x: x['aggregate_score'], reverse=True)
    else:
        # Primary: most tokens → Secondary: aggregate score
        ranked.sort(key=lambda x: (x['runner_count'], x['aggregate_score']), reverse=True)

    top_20 = ranked[:20]

    print(f"  ✓ Cross-token ranking complete: {len(top_20)} wallets in top 20")
    print(f"  ✓ Fetching runner history for top {len(top_20)} wallets only...")

    # Queue runner history for the final top 20 only
    _, q_batch, q_compute = _get_queues()
    runner_jobs = []
    chunk_size  = 5

    for i in range(0, len(top_20), chunk_size):
        chunk     = top_20[i:i + chunk_size]
        batch_idx = i // chunk_size
        rh_job = q_batch.enqueue(
            'services.worker_tasks.fetch_runner_history_batch',
            {
                # No specific token context for batch runner history —
                # pass first token just for current_token exclusion
                'token':     tokens[0] if tokens else {},
                'job_id':    job_id,
                'batch_idx': batch_idx,
                'wallets':   [w['wallet'] for w in chunk],
            }
        )
        runner_jobs.append(rh_job)

    # merge_batch_final attaches runner history and saves the real final result
    q_compute.enqueue(
        'services.worker_tasks.merge_batch_final',
        {
            'job_id':              job_id,
            'user_id':             data.get('user_id', 'default_user'),
            'top_20':              top_20,
            'total':               len(ranked),
            'no_overlap_fallback': no_overlap_fallback,
            'tokens_analyzed':     len(all_token_results),
            'tokens':              tokens,
            'runner_batch_count':  len(runner_jobs),
        },
        depends_on=Dependency(jobs=runner_jobs) if runner_jobs else None
    )

    print(f"  ✓ {len(runner_jobs)} runner history workers queued → merge_batch_final")
    return {'top_20_count': len(top_20), 'runner_jobs': len(runner_jobs)}


# =============================================================================
# BATCH FINAL MERGE — compute queue
# Triggered by aggregate_cross_token after runner history is fetched for top 20.
# Attaches runner history, builds final result, saves to Supabase.
# =============================================================================

def merge_batch_final(data):
    """
    [compute queue] Final step for batch analysis.

    Collects runner history for the top 20 wallets identified by aggregate_cross_token,
    attaches it to each wallet, and saves the complete final result to Supabase.

    This is the only place runner history is fetched in batch mode — after cross-token
    correlation has already identified which wallets made the final cut.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    job_id              = data['job_id']
    user_id             = data.get('user_id', 'default_user')
    top_20              = data['top_20']
    total               = data['total']
    no_overlap_fallback = data.get('no_overlap_fallback', False)
    tokens_analyzed     = data.get('tokens_analyzed', 0)
    tokens              = data.get('tokens', [])
    runner_batch_count  = data['runner_batch_count']

    supabase = get_supabase_client()

    print(f"\n[BATCH FINAL] Attaching runner history for {len(top_20)} wallets...")

    # Collect runner history
    runner_lookup = {}
    for i in range(runner_batch_count):
        batch = _load_result(f"runner_batch:{job_id}:{i}") or []
        for entry in batch:
            runner_lookup[entry['wallet']] = entry

    # Attach runner history to each top 20 wallet
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
        'no_overlap_fallback':  no_overlap_fallback,
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
        print(f"  ✅ Supabase: saved final batch result for job {job_id[:8]}")
    except Exception as e:
        print(f"[BATCH FINAL] ⚠️ Failed to save: {e}")

    print(f"  ✅ Batch complete: {len(top_20)} wallets with runner history ({total} total qualified)")
    return final_result


# =============================================================================
# CACHE WARMUP
# =============================================================================

def preload_trending_cache():
    """Queue cache warmup jobs."""
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