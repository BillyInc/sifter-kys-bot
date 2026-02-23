"""
RQ Worker Tasks - Production Ready with Debug Logging
Fixes applied:
  1. Supabase cache check before queuing any pipeline (instant results for repeat searches)
  2. Queue separation: high / batch / compute (no deadlocks, priority guaranteed)
  3. Fixed batch_size = 10 (was // 5, left workers idle)
  4. Coordinators always go to compute queue (deadlock prevention)
  5. Batch workers always go to batch queue
  6. Phase 1 workers always go to high queue (except fetch_top_holders → batch)
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
  23. fetch_top_holders moved to batch queue (heavy fetch, not time-critical)
  24. aggregate_cross_token: cross-token wallets ranked first, single-token fill to 20
  25. CACHE VALIDATION: Empty/invalid cached results detected and deleted
  26. DEBUG LOGGING: Entry price failures, qualification failures, and failed wallets logged
  27. TOP HOLDERS: Limit increased to 1000, pre-filtered by holding_usd >= 100 client-side
  28. PRE-QUALIFICATION: first_buyers + top_traders qualified in coordinator, no PnL API call
  29. allow_failure=True on scorer dependency — abandoned PnL jobs no longer deadlock scorer
  30. min_roi_mult raised to 5.0 (quality > quantity for memecoins)
  31. AsyncSemaphore set to 2 per worker for PnL fetch (safe concurrency without rate limits)
  32. _save_result TTL raised to 86400 (24h) — prevents result expiry during long runs
  33. Timing logs added around slow API fetch paths in fetch_pnl_batch
  34. RQ job ID logged at start of every fetch_pnl_batch for cross-referencing abandonments
  35. Source breakdown logged in coordinate_pnl_phase (traders/buyers/holders/unique counts)
  36. Final Redis summary key written at end of score_and_rank_single for quick inspection
  37. REDIS FIX: socket_timeout raised to 60s, keepalive enabled, retry_on_timeout=True,
      ExponentialBackoff retry added, health_check_interval=30 to keep connection alive
  38. BATCH COUNTER FIX: guard against missing batch_total key after Redis restart/flush
  39. RQ RETRY: Retry(max=3, interval=[10,30,60]) added to ALL phase 1 and batch enqueues —
      transient failures (Redis drops, API timeouts, OOM) auto-retry on any free worker
  40. allow_failure=True on phase1→coordinator dependency — if a phase 1 job fails after
      saving its result but before RQ marks it succeeded, the coordinator still fires
  41. _save_result_with_retry: wraps Redis SET with exponential backoff for transient drops
  42. RATE LIMIT FIX: batch_size 10→3, countdown stagger (batch_idx*8s), sem=1, jitter 3-6s
      in both coordinate_entry_prices and coordinate_pnl_phase. All three AsyncSemaphore
      blocks in fetch_entry_prices_batch and fetch_pnl_batch reduced to 1 (fully sequential).
      Retry intervals extended to [30,60,120]. Prevents free-tier 10k credit exhaustion
      from 40+ simultaneous requests on pipeline start.
  43. COUNTDOWN FIX: countdown= removed from all enqueue() calls — it is not a valid
      enqueue kwarg in older RQ versions and was passed straight through to worker
      functions as an unexpected keyword argument, causing every batch job to fail
      instantly in an infinite failure loop. Stagger delay moved inside each worker
      function as time.sleep(batch_idx * 8) at function start.
  FIX 10: Entry price and ATH shown as market cap (ath_market_cap, entry_market_cap added)
  FIX 18: ROI scoring — log scale via _roi_to_score() replaces broken avg_total_roi/10*100
  FIX 19: aggregate_cross_token scoring uses _roi_to_score(avg_entry_to_ath_multiplier)
          for the 60% entry component instead of avg_dist (percentage). Percentages are
          display-only and never feed into any score calculation.

SUPABASE TABLE REQUIRED:
  CREATE TABLE token_qualified_wallets (
    token_address TEXT PRIMARY KEY,
    qualified_wallets JSONB,
    wallet_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );

REDIS LOG KEYS (queryable via redis-cli GET <key> or your _load_result helper):
  log:entry_prices:{job_id}:{batch_idx}
  log:pnl_entry_prices:{job_id}:{batch_idx}
  log:pnl_full_fetch:{job_id}:{batch_idx}
  log:job_fetch_summary:{job_id}
  log:job_final_summary:{job_id}
"""

from redis import Redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from rq import Queue
from rq.job import Job, Dependency
from rq import Retry as RQRetry
import json
import asyncio
import os
import time
import uuid
import statistics
from collections import defaultdict
import socket
from utils import _roi_to_score

# =============================================================================
# TTL CONSTANTS
# Two tiers:
#   LOG_TTL      = 21600  (6h)  — all debug/log/inspection keys
#   PIPELINE_TTL = 86400  (24h) — pipeline coordination keys (need full job lifetime)
#
# Rule: anything you'd query manually to debug a run → LOG_TTL
#       anything the pipeline itself reads to function correctly → PIPELINE_TTL
# =============================================================================
LOG_TTL      = 21600   # 6h  — debug logs, qualified wallets, fetch summaries, phase1 failures
PIPELINE_TTL = 86400   # 24h — job_result, batch counters, pipeline metadata

# =============================================================================
# REDIS + QUEUE SETUP
# =============================================================================

def _get_redis():
    """
    FIX 37/39: Resilient Redis connection.
    - socket_timeout=60: don't give up on slow ops (was 3s in wallet_analyzer)
    - socket_keepalive + options: detect and recover dead connections proactively
    - health_check_interval=30: most important — keeps idle connections alive so
      they don't die between RQ job handoffs (the root cause of the crash in the log)
    - ExponentialBackoff retry: if a command fails due to ConnectionError/TimeoutError,
      automatically retry up to 5 times with exponential backoff before raising
    - retry_on_timeout=True: ETIMEDOUT counts as a retryable error
    """
    url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    return Redis.from_url(
        url,
        socket_timeout=60,
        socket_connect_timeout=10,
        socket_keepalive=True,
        socket_keepalive_options={
            socket.TCP_KEEPIDLE:  30,   # start keepalive probes after 30s idle (was 60)
            socket.TCP_KEEPINTVL: 5,    # probe every 5s (was 10)
            socket.TCP_KEEPCNT:   10,   # give up after 10 failed probes (was 5)
        },
        retry_on_timeout=True,
        retry=Retry(ExponentialBackoff(cap=10, base=1), retries=5),
        health_check_interval=30,
    )


def _get_queues():
    """Return high, batch, compute queues. Always use these — never default queue."""
    r = _get_redis()
    return (
        Queue('high',    connection=r, default_timeout=1800),
        Queue('batch',   connection=r, default_timeout=1800),
        Queue('compute', connection=r, default_timeout=1800),
    )


def _save_result_with_retry(job_id, data, ttl=None, max_attempts=3):
    """
    FIX 41: Wrap Redis SET with retry logic for transient connection drops.
    The original crash happened because Redis dropped the connection AFTER the job
    completed its work but BEFORE RQ could call enqueue_dependents. By retrying
    the _save_result call we ensure the result is persisted even if the first
    attempt hits a transient drop. The underlying _get_redis() connection also
    has ExponentialBackoff, so in most cases the retry happens at the socket level
    automatically — this is a belt-and-suspenders defence for longer outages.
    """
    for attempt in range(max_attempts):
        try:
            _save_result(job_id, data, ttl)
            return
        except (ConnectionError, TimeoutError) as e:
            if attempt < max_attempts - 1:
                wait = 2 ** attempt
                print(f"[SAVE RETRY] attempt {attempt + 1}/{max_attempts} failed: {e} — retrying in {wait}s")
                time.sleep(wait)
                continue
            raise


def _save_result(job_id, data, ttl=None):
    """
    Save job result to Redis.
    Default TTL = PIPELINE_TTL (24h) — pipeline coordination data that must
    survive the full job lifetime.
    Pass ttl=LOG_TTL for debug/inspection data that only needs 6h.
    """
    r = _get_redis()
    r.set(f"job_result:{job_id}", json.dumps(data), ex=ttl or PIPELINE_TTL)


def _save_log_result(job_id, data):
    """Save a debug/inspection result that only needs 6h (LOG_TTL)."""
    r = _get_redis()
    r.set(f"job_result:{job_id}", json.dumps(data), ex=LOG_TTL)


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
# REDIS FETCH LOGGING HELPERS
# =============================================================================

def _save_fetch_log(key, entries, ex=None):
    """
    Save a list of per-request fetch log entries to Redis.
    Default TTL = LOG_TTL (6h) — manual inspection keys only.
    """
    r = _get_redis()
    r.set(key, json.dumps(entries, default=str), ex=ex or LOG_TTL)


def _build_fetch_log_entry(wallet, url, resp, outcome, reason, price_found=False,
                            error=None, failure_cause=None):
    """
    Build a single structured log entry for one HTTP fetch attempt.

    failure_cause values:
      'empty_response'      — async_fetch_with_retry returned None (429/timeout/404)
      'api_error'           — got a response but it was empty/missing expected fields
      'code_exception'      — Python exception raised during processing
      'qualification_failed'— fetched fine but wallet didn't meet threshold
      'abandoned_job'       — RQ killed the worker mid-run (result key missing)
    """
    if resp is None:
        response_type  = 'null'
        response_keys  = []
        response_len   = 0
        http_hint      = (
            "no_response — async_fetch_with_retry returned None. "
            "Most likely causes: (1) HTTP 429 rate limit, "
            "(2) request timeout, (3) HTTP 404 not found, "
            "(4) network connection dropped."
        )
        failure_cause  = failure_cause or 'empty_response'
    elif isinstance(resp, dict):
        response_type = 'empty_dict' if not resp else 'dict'
        response_keys = list(resp.keys())
        response_len  = len(resp.get('trades', resp.get('accounts', [])))
        http_hint     = None
        if not resp and not failure_cause:
            failure_cause = 'api_error'
    elif isinstance(resp, list):
        response_type = 'empty_list' if not resp else 'list'
        response_keys = []
        response_len  = len(resp)
        http_hint     = None
        if not resp and not failure_cause:
            failure_cause = 'api_error'
    else:
        response_type = str(type(resp).__name__)
        response_keys = []
        response_len  = 0
        http_hint     = None

    entry = {
        'wallet':        wallet,
        'url':           url,
        'timestamp':     time.time(),
        'response_type': response_type,
        'response_keys': response_keys,
        'response_len':  response_len,
        'outcome':       outcome,
        'reason':        reason,
        'price_found':   price_found,
    }
    if failure_cause:
        entry['failure_cause'] = failure_cause
    if http_hint:
        entry['http_hint'] = http_hint
    if error:
        entry['error'] = str(error)
    return entry


def _append_to_job_fetch_summary(job_id, batch_type, batch_idx, total, found, failure_counts, ex=None):
    key = f"log:job_fetch_summary:{job_id}"
    r   = _get_redis()
    raw = r.get(key)
    existing = json.loads(raw) if raw else []
    existing.append({
        'batch_type':       batch_type,
        'batch_idx':        batch_idx,
        'timestamp':        time.time(),
        'total_wallets':    total,
        'prices_found':     found,
        'failure_counts':   failure_counts,
        'success_rate_pct': round((found / total * 100) if total > 0 else 0, 1),
    })
    r.set(key, json.dumps(existing, default=str), ex=ex or LOG_TTL)


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
    """
    FIX 39: All phase 1 and coordinator enqueues now include RQRetry(max=3, interval=[10,30,60]).
    If a worker crashes mid-job (Redis drop, OOM, timeout), RQ automatically re-enqueues
    it after 10s on any available worker. The job saved its result before crashing in most
    cases, so the retry will re-fetch and overwrite harmlessly.

    FIX 40: allow_failure=True on the pnl_coordinator dependency — if any phase 1 job
    fails permanently (e.g., crashes after saving result but before RQ marks it succeeded),
    the coordinator still fires instead of waiting forever in DeferredJobRegistry.
    """
    print(f"\n[PIPELINE] Queuing single token: {token.get('ticker')}")
    q_high, q_batch, q_compute = _get_queues()

    # Phase 1 workers — all with retry so transient failures auto-recover
    job1 = q_high.enqueue(
        'services.worker_tasks.fetch_top_traders',
        {'token': token, 'job_id': job_id},
        retry=RQRetry(max=3, interval=[10, 30, 60])
    )
    job2 = q_high.enqueue(
        'services.worker_tasks.fetch_first_buyers',
        {'token': token, 'job_id': job_id},
        retry=RQRetry(max=3, interval=[10, 30, 60])
    )
    job3 = q_batch.enqueue(
        'services.worker_tasks.fetch_top_holders',
        {'token': token, 'job_id': job_id},
        retry=RQRetry(max=3, interval=[10, 30, 60])
    )

    job4_coord = q_compute.enqueue(
        'services.worker_tasks.coordinate_entry_prices',
        {'token': token, 'job_id': job_id},
        depends_on=Dependency(jobs=[job1], allow_failure=True),
        retry=RQRetry(max=3, interval=[10, 30, 60])
    )

    # FIX 40: allow_failure=True — if any phase 1 job ends up in FailedJobRegistry
    # (e.g., crashed after saving its result but before RQ ran enqueue_dependents),
    # the coordinator fires anyway and works with whatever data was saved.
    pnl_coordinator = q_compute.enqueue(
        'services.worker_tasks.coordinate_pnl_phase',
        {
            'token':         token,
            'job_id':        job_id,
            'user_id':       user_id,
            'parent_job_id': None,
            'phase1_jobs':   [job1.id, job2.id, job3.id, job4_coord.id]
        },
        depends_on=Dependency(jobs=[job1, job2, job3, job4_coord], allow_failure=True),
        retry=RQRetry(max=3, interval=[10, 30, 60])
    )

    r = _get_redis()
    r.set(f"pipeline:{job_id}:coordinator", pnl_coordinator.id, ex=PIPELINE_TTL)
    r.set(f"pipeline:{job_id}:token",       json.dumps(token),  ex=PIPELINE_TTL)

    print(f"  ✓ Phase 1: traders={job1.id[:8]} buyers={job2.id[:8]} holders={job3.id[:8]} (batch)")
    print(f"  ✓ Entry coord: {job4_coord.id[:8]} | PnL coord: {pnl_coordinator.id[:8]}")
    print(f"  ✓ Scorer will be queued by coordinate_pnl_phase after PnL batches complete")


def _queue_batch_pipeline(tokens, user_id, job_id, supabase, min_runner_hits=2):
    """
    FIX 39/40: Same retry and allow_failure fixes applied to batch pipeline.
    Each sub-pipeline is independent so one token's failure doesn't block others.
    """
    print(f"\n[PIPELINE] Queuing batch: {len(tokens)} tokens")
    q_high, q_batch, q_compute = _get_queues()
    r = _get_redis()

    sub_job_ids = [f"{job_id}__{t['address'][:8]}" for t in tokens]

    r.set(f"batch_total:{job_id}",           len(tokens),             ex=PIPELINE_TTL)
    r.set(f"batch_sub_jobs:{job_id}",        json.dumps(sub_job_ids), ex=PIPELINE_TTL)
    r.set(f"batch_tokens:{job_id}",          json.dumps(tokens),      ex=PIPELINE_TTL)
    r.set(f"batch_completed:{job_id}",       0,                       ex=PIPELINE_TTL)
    r.set(f"batch_min_runner_hits:{job_id}", min_runner_hits,         ex=PIPELINE_TTL)
    r.set(f"batch_user_id:{job_id}",         user_id,                 ex=PIPELINE_TTL)

    for token, sub_job_id in zip(tokens, sub_job_ids):
        r.set(f"pipeline:{sub_job_id}:token", json.dumps(token), ex=PIPELINE_TTL)

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
            job1 = q_high.enqueue(
                'services.worker_tasks.fetch_top_traders',
                {'token': token, 'job_id': sub_job_id},
                retry=RQRetry(max=3, interval=[10, 30, 60])
            )
            job2 = q_high.enqueue(
                'services.worker_tasks.fetch_first_buyers',
                {'token': token, 'job_id': sub_job_id},
                retry=RQRetry(max=3, interval=[10, 30, 60])
            )
            job3 = q_batch.enqueue(
                'services.worker_tasks.fetch_top_holders',
                {'token': token, 'job_id': sub_job_id},
                retry=RQRetry(max=3, interval=[10, 30, 60])
            )

            job4_coord = q_compute.enqueue(
                'services.worker_tasks.coordinate_entry_prices',
                {'token': token, 'job_id': sub_job_id},
                depends_on=Dependency(jobs=[job1], allow_failure=True),
                retry=RQRetry(max=3, interval=[10, 30, 60])
            )

            # FIX 40: allow_failure=True — coordinator fires even if a phase 1 job
            # ends up in FailedJobRegistry after saving its data
            q_compute.enqueue(
                'services.worker_tasks.coordinate_pnl_phase',
                {
                    'token':         token,
                    'job_id':        sub_job_id,
                    'user_id':       user_id,
                    'parent_job_id': job_id,
                    'phase1_jobs':   [job1.id, job2.id, job3.id, job4_coord.id]
                },
                depends_on=Dependency(jobs=[job1, job2, job3, job4_coord], allow_failure=True),
                retry=RQRetry(max=3, interval=[10, 30, 60])
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
    min_roi_multiplier = data.get('min_roi_multiplier', 5.0)
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
# PHASE 1 WORKERS
# =============================================================================

def fetch_top_traders(data):
    """Worker 1 [high]: Fetch top 100 traders by PnL."""
    analyzer = get_worker_analyzer()
    token    = data['token']
    job_id   = data['job_id']

    url      = f"{analyzer.st_base_url}/top-traders/{token['address']}"
    response = None
    phase1_failure = None

    try:
        response = analyzer.fetch_with_retry(
            url, analyzer._get_solanatracker_headers(),
            semaphore=analyzer.solana_tracker_semaphore
        )
        if response is None:
            phase1_failure = {
                'source':        'top_traders',
                'url':           url,
                'failure_cause': 'empty_response',
                'reason':        'fetch_with_retry returned None — likely 429, timeout, or 404',
                'timestamp':     time.time(),
            }
        elif isinstance(response, list) and len(response) == 0:
            phase1_failure = {
                'source':        'top_traders',
                'url':           url,
                'failure_cause': 'api_error',
                'reason':        'API returned empty list — token may have no traders yet',
                'timestamp':     time.time(),
            }
    except Exception as e:
        phase1_failure = {
            'source':        'top_traders',
            'url':           url,
            'failure_cause': 'code_exception',
            'reason':        str(e),
            'timestamp':     time.time(),
        }
        response = None

    if phase1_failure:
        _save_fetch_log(f"log:phase1_failures:{job_id}", [phase1_failure])

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
    # FIX 41: use _save_result_with_retry so transient Redis drops don't crash the worker
    _save_result_with_retry(f"phase1_top_traders:{job_id}", result)
    print(f"[WORKER 1] top_traders done: {len(wallets)} wallets"
          + (f" ⚠️ PHASE1 FAILURE: {phase1_failure['reason']}" if phase1_failure else ""))
    return result


def fetch_first_buyers(data):
    """Worker 2 [high]: Fetch first 100 buyers by time. Full PnL data included in response."""
    analyzer = get_worker_analyzer()
    token    = data['token']
    job_id   = data['job_id']

    url      = f"{analyzer.st_base_url}/first-buyers/{token['address']}"
    response = None
    phase1_failure = None

    try:
        response = analyzer.fetch_with_retry(
            url, analyzer._get_solanatracker_headers(),
            semaphore=analyzer.solana_tracker_semaphore
        )
        if response is None:
            phase1_failure = {
                'source':        'first_buyers',
                'url':           url,
                'failure_cause': 'empty_response',
                'reason':        'fetch_with_retry returned None — likely 429, timeout, or 404',
                'timestamp':     time.time(),
            }
        else:
            buyers = response if isinstance(response, list) else response.get('buyers', [])
            if len(buyers) == 0:
                phase1_failure = {
                    'source':        'first_buyers',
                    'url':           url,
                    'failure_cause': 'api_error',
                    'reason':        'API returned zero buyers — token may be too new or have no buy history',
                    'timestamp':     time.time(),
                }
    except Exception as e:
        phase1_failure = {
            'source':        'first_buyers',
            'url':           url,
            'failure_cause': 'code_exception',
            'reason':        str(e),
            'timestamp':     time.time(),
        }
        response = None

    if phase1_failure:
        r   = _get_redis()
        key = f"log:phase1_failures:{job_id}"
        raw = r.get(key)
        existing = json.loads(raw) if raw else []
        existing.append(phase1_failure)
        r.set(key, json.dumps(existing, default=str), ex=LOG_TTL)

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
    # FIX 41: retry on transient Redis drops
    _save_result_with_retry(f"phase1_first_buyers:{job_id}", result)
    print(f"[WORKER 2] first_buyers done: {len(wallets)} wallets"
          + (f" ⚠️ PHASE1 FAILURE: {phase1_failure['reason']}" if phase1_failure else ""))
    return result


def fetch_top_holders(data):
    """
    Worker 3 [batch]: Fetch top 1000 holders by current position size.
    Pre-filters client-side: only holders with holding_usd >= 100 are kept.
    """
    analyzer = get_worker_analyzer()
    token    = data['token']
    job_id   = data['job_id']

    MIN_HOLDING_USD = 100

    url = f"{analyzer.st_base_url}/tokens/{token['address']}/holders/paginated"
    response = analyzer.fetch_with_retry(
        url,
        analyzer._get_solanatracker_headers(),
        params={'limit': 1000},
        semaphore=analyzer.solana_tracker_semaphore
    )

    wallets      = []
    wallet_data  = {}
    total_raw    = 0
    filtered_out = 0

    if response and response.get('accounts'):
        total_raw = len(response['accounts'])
        for account in response['accounts']:
            wallet      = account.get('wallet')
            holding_usd = account.get('value', {}).get('usd', 0)

            if not wallet:
                continue

            if holding_usd < MIN_HOLDING_USD:
                filtered_out += 1
                continue

            wallets.append(wallet)
            wallet_data[wallet] = {
                'source':         'top_holders',
                'pnl_data':       None,
                'earliest_entry': None,
                'entry_price':    None,
                'holding_amount': account.get('amount', 0),
                'holding_usd':    holding_usd,
                'holding_pct':    account.get('percentage', 0),
            }

    result = {
        'wallets':       wallets,
        'wallet_data':   wallet_data,
        'source':        'top_holders',
        'total_holders': response.get('total', 0) if response else 0,
    }
    # FIX 41: retry on transient Redis drops
    _save_result_with_retry(f"phase1_holders:{job_id}", result)
    print(f"[WORKER 3] top_holders done: {len(wallets)} kept "
          f"(from {total_raw} fetched, {filtered_out} filtered <${MIN_HOLDING_USD} holding_usd, "
          f"token total={result['total_holders']})")
    return result


# =============================================================================
# PHASE 1 COORDINATOR + ENTRY PRICE BATCH WORKERS
# =============================================================================

def coordinate_entry_prices(data):
    token  = data['token']
    job_id = data['job_id']

    top_traders_result = _load_result(f"phase1_top_traders:{job_id}")
    if not top_traders_result:
        print(f"[ENTRY COORD] No top traders result — skipping")
        _save_result(f"phase1_top_traders:{job_id}", {'wallets': [], 'wallet_data': {}, 'source': 'top_traders'})
        return {'batch_jobs': [], 'merge_job': None}

    wallets    = top_traders_result['wallets']
    batch_size = 3  # FIX 42: reduced from 10 to 3 to prevent simultaneous API hammering
    _, q_batch, q_compute = _get_queues()
    batch_jobs = []

    print(f"[ENTRY COORD] {len(wallets)} wallets → batches of {batch_size}")

    for i in range(0, len(wallets), batch_size):
        batch     = wallets[i:i + batch_size]
        batch_idx = i // batch_size
        # FIX 43: stagger moved INSIDE the worker function (time.sleep at start).
        # countdown= is not a valid enqueue kwarg in older RQ versions and gets
        # passed through to the worker as an unexpected keyword argument, causing
        # an infinite failure loop. The batch_idx is already in the data dict so
        # the worker can compute its own stagger delay.
        bj = q_batch.enqueue(
            'services.worker_tasks.fetch_entry_prices_batch',
            {
                'token':     token,
                'job_id':    job_id,
                'batch_idx': batch_idx,
                'wallets':   batch,
            },
            retry=RQRetry(max=3, interval=[30, 60, 120])
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
        depends_on=Dependency(jobs=batch_jobs, allow_failure=True),
        retry=RQRetry(max=3, interval=[10, 30, 60])
    )

    print(f"  ✓ {len(batch_jobs)} entry-price batches + merge {merge_job.id[:8]}")
    return {'batch_jobs': [j.id for j in batch_jobs], 'merge_job': merge_job.id}


def fetch_entry_prices_batch(data):
    analyzer  = get_worker_analyzer()
    import aiohttp
    import random
    from asyncio import Semaphore as AsyncSemaphore

    token     = data['token']
    job_id    = data['job_id']
    batch_idx = data['batch_idx']
    wallets   = data['wallets']

    # FIX 43: stagger via sleep instead of countdown= on enqueue.
    # countdown= is not a valid enqueue kwarg in older RQ versions — it gets
    # passed straight through to the worker function as an unexpected keyword
    # argument, causing every batch job to fail instantly in an infinite loop.
    stagger_secs = batch_idx * 8
    if stagger_secs > 0:
        print(f"[ENTRY BATCH {batch_idx}] Staggering {stagger_secs}s...")
        time.sleep(stagger_secs)

    print(f"[ENTRY BATCH {batch_idx}] {len(wallets)} wallets...")

    failure_reasons  = defaultdict(int)
    detailed_results = []
    fetch_log        = []

    async def _fetch():
        async with aiohttp.ClientSession() as session:
            # FIX 42: sem=1 forces fully sequential requests within each batch.
            # Combined with countdown stagger between batches, this keeps total
            # simultaneous API requests at most 2 (one active + one just starting).
            sem   = AsyncSemaphore(1)
            tasks = []
            for wallet in wallets:
                async def fetch(w=wallet):
                    async with sem:
                        await asyncio.sleep(random.uniform(3, 6))  # FIX 42: longer jitter (was 0.5-1.5s)
                        url  = f"{analyzer.st_base_url}/trades/{token['address']}/by-wallet/{w}"
                        resp = None
                        try:
                            resp = await analyzer.async_fetch_with_retry(
                                session, url, analyzer._get_solanatracker_headers()
                            )

                            if not resp:
                                failure_reasons['no_response'] += 1
                                fetch_log.append(_build_fetch_log_entry(
                                    w, url, resp, outcome='fail', reason='no_response'
                                ))
                                return {'wallet': w, 'price': None, 'time': None, 'reason': 'no_response'}

                            if not resp.get('trades'):
                                failure_reasons['no_trades'] += 1
                                fetch_log.append(_build_fetch_log_entry(
                                    w, url, resp, outcome='fail', reason='no_trades'
                                ))
                                return {'wallet': w, 'price': None, 'time': None, 'reason': 'no_trades'}

                            buys = [t for t in resp['trades'] if t.get('type') == 'buy']
                            if not buys:
                                failure_reasons['no_buys'] += 1
                                fetch_log.append(_build_fetch_log_entry(
                                    w, url, resp, outcome='fail', reason='no_buys'
                                ))
                                return {'wallet': w, 'price': None, 'time': None, 'reason': 'no_buys'}

                            first_buy = min(buys, key=lambda x: x.get('time', float('inf')))
                            price     = first_buy.get('priceUsd')
                            fetch_log.append(_build_fetch_log_entry(
                                w, url, resp, outcome='success', reason='success', price_found=price is not None
                            ))
                            return {
                                'wallet': w,
                                'price':  price,
                                'time':   first_buy.get('time'),
                                'reason': 'success'
                            }

                        except Exception as e:
                            failure_reasons['error'] += 1
                            fetch_log.append(_build_fetch_log_entry(
                                w, url, resp, outcome='fail', reason='error', error=e
                            ))
                            return {'wallet': w, 'price': None, 'time': None, 'reason': f'error: {str(e)}'}

                tasks.append(fetch())
            return await asyncio.gather(*tasks)

    t0      = time.time()
    results = asyncio.run(_fetch())
    elapsed = time.time() - t0
    found   = 0

    for r in results:
        detailed_results.append(r)
        if r and r.get('price') is not None:
            found += 1

    print(f"[ENTRY BATCH {batch_idx}] Done: {found}/{len(wallets)} prices found in {elapsed:.1f}s")
    print(f"[ENTRY BATCH {batch_idx}] Failure breakdown: {dict(failure_reasons)}")

    _save_fetch_log(f"log:entry_prices:{job_id}:{batch_idx}", fetch_log)
    _append_to_job_fetch_summary(job_id, 'entry_prices', batch_idx, len(wallets), found, dict(failure_reasons))

    debug_log = {
        'batch_idx': batch_idx,
        'timestamp': time.time(),
        'token':     token['address'],
        'results':   detailed_results,
        'summary': {
            'total':           len(wallets),
            'found':           found,
            'failed':          len(wallets) - found,
            'failure_reasons': dict(failure_reasons),
            'elapsed_seconds': round(elapsed, 1),
        }
    }
    _save_result(f"debug_entry_prices:{job_id}:{batch_idx}", debug_log, ttl=LOG_TTL)
    # FIX 41: retry save for pipeline-critical batch result
    _save_result_with_retry(f"entry_prices_batch:{job_id}:{batch_idx}", results)

    return results


def merge_entry_prices(data):
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
    # FIX 41: retry save — this result is read by coordinate_pnl_phase
    _save_result_with_retry(f"phase1_top_traders:{job_id}", enriched)

    print(f"[ENTRY MERGE] Resolved {resolved}/{len(all_wallets)} entry prices")
    return enriched


# =============================================================================
# PHASE 2 COORDINATOR — compute queue
# =============================================================================

def coordinate_pnl_phase(data):
    token        = data['token']
    job_id       = data['job_id']
    user_id      = data.get('user_id', 'default_user')
    parent_job   = data.get('parent_job_id')
    phase1_jobs  = data['phase1_jobs']

    print(f"\n[PNL COORD] Phase 1 complete for {token.get('ticker')} — merging...")

    all_wallets  = []
    wallet_data  = {}
    source_counts = {'top_traders': 0, 'first_buyers': 0, 'top_holders': 0}

    for key_prefix in ['phase1_top_traders', 'phase1_first_buyers', 'phase1_holders']:
        result = _load_result(f"{key_prefix}:{job_id}")
        if result:
            source = result.get('source', key_prefix.replace('phase1_', ''))
            added  = 0
            for wallet in result['wallets']:
                if wallet not in wallet_data:
                    all_wallets.append(wallet)
                    wallet_data[wallet] = result['wallet_data'].get(wallet, {})
                    added += 1
                else:
                    existing = wallet_data[wallet]
                    new      = result['wallet_data'].get(wallet, {})
                    if new.get('entry_price') and not existing.get('entry_price'):
                        existing['entry_price'] = new['entry_price']
                    if new.get('pnl_data') and not existing.get('pnl_data'):
                        existing['pnl_data'] = new['pnl_data']
                    for holder_field in ['holding_amount', 'holding_usd', 'holding_pct']:
                        if new.get(holder_field) and not existing.get(holder_field):
                            existing[holder_field] = new[holder_field]

            src_key = source if source in source_counts else 'top_holders'
            source_counts[src_key] = added

    print(f"  ✓ Sources: traders={source_counts['top_traders']} "
          f"buyers={source_counts['first_buyers']} "
          f"holders={source_counts['top_holders']} "
          f"unique={len(all_wallets)}")

    _save_result(f"phase1_merged:{job_id}", {
        'wallets':     all_wallets,
        'wallet_data': wallet_data
    }, ttl=LOG_TTL)  # debug only — not read downstream by pipeline

    pre_qualified    = []
    need_pnl_fetch   = []
    pre_qual_failed  = defaultdict(int)

    for wallet in all_wallets:
        wdata = wallet_data.get(wallet, {})
        if wdata.get('pnl_data') is not None:
            if not _qualify_wallet(wallet, wdata['pnl_data'], wallet_data, token, pre_qualified, debug=True):
                invested      = wdata['pnl_data'].get('total_invested', 0)
                realized_mult = ((wdata['pnl_data'].get('realized', 0) + invested) / invested
                                 if invested > 0 else 0)
                total_mult    = ((wdata['pnl_data'].get('realized', 0) +
                                  wdata['pnl_data'].get('unrealized', 0) + invested) / invested
                                 if invested > 0 else 0)
                if invested < 100:
                    pre_qual_failed['low_invested'] += 1
                elif realized_mult < 5.0 and total_mult < 5.0:
                    pre_qual_failed['low_multiplier'] += 1
                else:
                    pre_qual_failed['other'] += 1
        else:
            need_pnl_fetch.append(wallet)

    print(f"  ✓ Pre-qualified: {len(pre_qualified)} wallets (traders+buyers, no API needed)")
    print(f"  ✓ Pre-qual failures: {dict(pre_qual_failed)}")
    print(f"  ✓ Holders queued for PnL fetch: {len(need_pnl_fetch)}")

    _save_result(f"pnl_batch:{job_id}:pre", pre_qualified)

    _, q_batch, q_compute = _get_queues()
    batch_size = 3  # FIX 42: reduced from 10 to 3, same rate-limit protection as entry prices
    pnl_jobs   = []

    for i in range(0, len(need_pnl_fetch), batch_size):
        batch         = need_pnl_fetch[i:i + batch_size]
        batch_wallets = {w: wallet_data[w] for w in batch}
        batch_idx     = i // batch_size

        # FIX 43: stagger moved INSIDE the worker (see fetch_pnl_batch).
        # countdown= removed — not a valid enqueue kwarg in older RQ versions.
        pnl_job = q_batch.enqueue(
            'services.worker_tasks.fetch_pnl_batch',
            {
                'token':       token,
                'job_id':      job_id,
                'batch_idx':   batch_idx,
                'wallets':     batch,
                'wallet_data': batch_wallets
            },
            retry=RQRetry(max=3, interval=[30, 60, 120])
        )
        pnl_jobs.append(pnl_job)

    print(f"  ✓ Queued {len(pnl_jobs)} PnL batch jobs for holders (size={batch_size})")

    r = _get_redis()
    r.set(f"pnl_batch_info:{job_id}", json.dumps({
        'batch_count': len(pnl_jobs),
        'pnl_job_ids': [j.id for j in pnl_jobs],
        'pre_qualified_count': len(pre_qualified),
    }), ex=LOG_TTL)

    scorer_job = q_compute.enqueue(
        'services.worker_tasks.score_and_rank_single',
        {
            'token':         token,
            'job_id':        job_id,
            'user_id':       user_id,
            'parent_job_id': parent_job,
            'batch_count':   len(pnl_jobs),
        },
        depends_on=Dependency(jobs=pnl_jobs, allow_failure=True) if pnl_jobs else None,
        retry=RQRetry(max=3, interval=[10, 30, 60])
    )

    print(f"  ✓ Scorer {scorer_job.id[:8]} queued — waits for {len(pnl_jobs)} PnL batches "
          f"(allow_failure=True, will not deadlock on abandoned jobs)")
    return {
        'pnl_jobs':    [j.id for j in pnl_jobs],
        'batch_count': len(pnl_jobs),
        'scorer_job':  scorer_job.id,
        'pre_qualified': len(pre_qualified),
    }


# =============================================================================
# PHASE 2 WORKERS — batch queue
# =============================================================================

def fetch_pnl_batch(data):
    from rq import get_current_job
    analyzer = get_worker_analyzer()
    import aiohttp
    import random
    from asyncio import Semaphore as AsyncSemaphore

    token       = data['token']
    job_id      = data['job_id']
    batch_idx   = data['batch_idx']
    wallets     = data['wallets']
    wallet_data = data['wallet_data']

    # FIX 43: stagger via sleep instead of countdown= on enqueue.
    # countdown= is not a valid enqueue kwarg in older RQ versions — it gets
    # passed straight through to the worker function as an unexpected keyword
    # argument, causing every batch job to fail instantly in an infinite loop.
    stagger_secs = batch_idx * 8
    if stagger_secs > 0:
        print(f"[PNL BATCH {batch_idx}] Staggering {stagger_secs}s...")
        time.sleep(stagger_secs)

    rq_job = get_current_job()
    rq_job_id = rq_job.id if rq_job else 'unknown'
    print(f"[PNL BATCH {batch_idx}] RQ job_id={rq_job_id} | {len(wallets)} wallets | "
          f"token={token.get('ticker')}")

    qualified              = []
    failed_wallets         = []
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
            need_pnl_fetch.append(wallet)

    print(f"[PNL BATCH {batch_idx}] {len(wallets)} wallets | "
          f"{len(ready_to_qualify)} ready | "
          f"{len(top_traders_need_price)} need price | "
          f"{len(need_pnl_fetch)} fetch PnL")

    for wallet in ready_to_qualify:
        pnl = wallet_data[wallet]['pnl_data']
        if not _qualify_wallet(wallet, pnl, wallet_data, token, qualified, debug=True):
            wdata         = wallet_data.get(wallet, {})
            pnl_data      = wdata.get('pnl_data', {})
            invested      = pnl_data.get('total_invested', 0)
            realized_mult = (pnl_data.get('realized', 0) + invested) / invested if invested > 0 else 0
            total_mult    = (pnl_data.get('realized', 0) + pnl_data.get('unrealized', 0) + invested) / invested if invested > 0 else 0
            failure_reason = 'missing_entry_price' if not wdata.get('entry_price') else 'low_multiplier'
            qualification_failures[failure_reason] += 1
            failed_wallets.append({
                'wallet':              wallet,
                'failure_reason':      failure_reason,
                'source':              wdata.get('source'),
                'has_pnl':             True,
                'has_entry_price':     bool(wdata.get('entry_price')),
                'invested':            invested,
                'realized_multiplier': round(realized_mult, 2),
                'total_multiplier':    round(total_mult, 2),
                'batch_idx':           batch_idx
            })

    if top_traders_need_price:
        entry_price_fetch_log = []

        async def _fetch_entry_prices():
            async with aiohttp.ClientSession() as session:
                # FIX 42: sem=1 for fully sequential, longer jitter to avoid rate limits
                sem   = AsyncSemaphore(1)
                tasks = []
                for wallet in top_traders_need_price:
                    async def fetch(w=wallet):
                        async with sem:
                            await asyncio.sleep(random.uniform(3, 6))  # FIX 42: was 0.5-1.5s
                            url  = f"{analyzer.st_base_url}/trades/{token['address']}/by-wallet/{w}"
                            resp = None
                            try:
                                resp = await analyzer.async_fetch_with_retry(
                                    session, url, analyzer._get_solanatracker_headers()
                                )
                                if resp and resp.get('trades'):
                                    buys = [t for t in resp['trades'] if t.get('type') == 'buy']
                                    if buys:
                                        first_buy = min(buys, key=lambda x: x.get('time', float('inf')))
                                        price = first_buy.get('priceUsd')
                                        entry_price_fetch_log.append(_build_fetch_log_entry(
                                            w, url, resp, outcome='success', reason='success',
                                            price_found=price is not None
                                        ))
                                        return {'price': price, 'time': first_buy.get('time')}
                                    entry_price_fetch_log.append(_build_fetch_log_entry(
                                        w, url, resp, outcome='fail', reason='no_buys'
                                    ))
                                else:
                                    reason = 'no_response' if not resp else 'no_trades'
                                    entry_price_fetch_log.append(_build_fetch_log_entry(
                                        w, url, resp, outcome='fail', reason=reason
                                    ))
                            except Exception as e:
                                entry_price_fetch_log.append(_build_fetch_log_entry(
                                    w, url, resp, outcome='fail', reason='error', error=e
                                ))
                            return None
                    tasks.append(fetch())
                return await asyncio.gather(*tasks)

        t0            = time.time()
        price_results = asyncio.run(_fetch_entry_prices())
        elapsed       = time.time() - t0

        _save_fetch_log(f"log:pnl_entry_prices:{job_id}:{batch_idx}", entry_price_fetch_log)

        ep_found    = sum(1 for p in price_results if p and p.get('price') is not None)
        ep_failures = defaultdict(int)
        for e in entry_price_fetch_log:
            if e['outcome'] == 'fail':
                ep_failures[e['reason']] += 1
        _append_to_job_fetch_summary(
            job_id, 'pnl_entry_prices', batch_idx,
            len(top_traders_need_price), ep_found, dict(ep_failures)
        )

        print(f"[PNL BATCH {batch_idx}] Entry price fetch: {ep_found}/{len(top_traders_need_price)} "
              f"found in {elapsed:.1f}s")

        for wallet, price_data in zip(top_traders_need_price, price_results):
            if price_data:
                wallet_data[wallet]['entry_price'] = price_data.get('price')
            pnl = wallet_data[wallet]['pnl_data']
            if not _qualify_wallet(wallet, pnl, wallet_data, token, qualified, debug=True):
                wdata         = wallet_data.get(wallet, {})
                pnl_data      = wdata.get('pnl_data', {})
                invested      = pnl_data.get('total_invested', 0)
                realized_mult = (pnl_data.get('realized', 0) + invested) / invested if invested > 0 else 0
                total_mult    = (pnl_data.get('realized', 0) + pnl_data.get('unrealized', 0) + invested) / invested if invested > 0 else 0
                failure_reason = 'missing_entry_price' if not price_data else 'low_multiplier'
                qualification_failures[failure_reason] += 1
                failed_wallets.append({
                    'wallet':              wallet,
                    'failure_reason':      failure_reason,
                    'source':              wdata.get('source'),
                    'has_pnl':             True,
                    'has_entry_price':     bool(price_data),
                    'invested':            invested,
                    'realized_multiplier': round(realized_mult, 2),
                    'total_multiplier':    round(total_mult, 2),
                    'batch_idx':           batch_idx
                })

    if need_pnl_fetch:
        pnl_fetch_log = []

        async def _fetch_pnls():
            async with aiohttp.ClientSession() as session:
                # FIX 42: sem=1 fully sequential + longer jitter to avoid rate limits
                sem   = AsyncSemaphore(1)
                tasks = []
                for wallet in need_pnl_fetch:
                    async def fetch(w=wallet):
                        async with sem:
                            await asyncio.sleep(random.uniform(3, 6))  # FIX 42: was 0.5-1.5s
                            url  = f"{analyzer.st_base_url}/pnl/{w}/{token['address']}"
                            resp = None
                            try:
                                resp = await analyzer.async_fetch_with_retry(
                                    session, url, analyzer._get_solanatracker_headers()
                                )
                                if resp:
                                    pnl_fetch_log.append(_build_fetch_log_entry(
                                        w, url, resp, outcome='success', reason='success'
                                    ))
                                else:
                                    pnl_fetch_log.append(_build_fetch_log_entry(
                                        w, url, resp, outcome='fail', reason='no_response'
                                    ))
                            except Exception as e:
                                pnl_fetch_log.append(_build_fetch_log_entry(
                                    w, url, resp, outcome='fail', reason='error', error=e
                                ))
                            return resp
                    tasks.append(fetch())
                return await asyncio.gather(*tasks)

        t0      = time.time()
        results = asyncio.run(_fetch_pnls())
        elapsed = time.time() - t0

        _save_fetch_log(f"log:pnl_full_fetch:{job_id}:{batch_idx}", pnl_fetch_log)

        pnl_found    = sum(1 for r in results if r)
        pnl_failures = defaultdict(int)
        for e in pnl_fetch_log:
            if e['outcome'] == 'fail':
                pnl_failures[e['reason']] += 1
        _append_to_job_fetch_summary(
            job_id, 'pnl_full_fetch', batch_idx,
            len(need_pnl_fetch), pnl_found, dict(pnl_failures)
        )

        print(f"[PNL BATCH {batch_idx}] Full PnL fetch: {pnl_found}/{len(need_pnl_fetch)} "
              f"found in {elapsed:.1f}s")

        for wallet, pnl in zip(need_pnl_fetch, results):
            if pnl:
                if _qualify_wallet(wallet, pnl, wallet_data, token, qualified, debug=True):
                    continue
                else:
                    wdata         = wallet_data.get(wallet, {})
                    invested      = pnl.get('total_invested', 0)
                    realized_mult = (pnl.get('realized', 0) + invested) / invested if invested > 0 else 0
                    total_mult    = (pnl.get('realized', 0) + pnl.get('unrealized', 0) + invested) / invested if invested > 0 else 0
                    failure_reason = 'low_invested' if invested < 100 else 'low_multiplier'
                    qualification_failures[failure_reason] += 1
                    failed_wallets.append({
                        'wallet':              wallet,
                        'failure_reason':      failure_reason,
                        'source':              wallet_data.get(wallet, {}).get('source', 'unknown'),
                        'has_pnl':             True,
                        'has_entry_price':     bool(wallet_data.get(wallet, {}).get('entry_price')),
                        'invested':            invested,
                        'realized_multiplier': round(realized_mult, 2),
                        'total_multiplier':    round(total_mult, 2),
                        'batch_idx':           batch_idx
                    })
            else:
                qualification_failures['no_pnl_data'] += 1
                failed_wallets.append({
                    'wallet':              wallet,
                    'failure_reason':      'no_pnl_data',
                    'source':              wallet_data.get(wallet, {}).get('source', 'unknown'),
                    'has_pnl':             False,
                    'has_entry_price':     False,
                    'invested':            0,
                    'realized_multiplier': 0,
                    'total_multiplier':    0,
                    'batch_idx':           batch_idx
                })

    print(f"[PNL BATCH {batch_idx}] Done: {len(qualified)} qualified, {len(failed_wallets)} failed")
    print(f"[PNL BATCH {batch_idx}] Failure breakdown: {dict(qualification_failures)}")

    if failed_wallets:
        _save_result(f"debug_failed_wallets:{job_id}:{batch_idx}", failed_wallets, ttl=LOG_TTL)

    debug_summary = {
        'batch_idx':         batch_idx,
        'rq_job_id':         rq_job_id,
        'timestamp':         time.time(),
        'total_wallets':     len(wallets),
        'qualified':         len(qualified),
        'failed':            len(failed_wallets),
        'failure_breakdown': dict(qualification_failures),
        'categories': {
            'ready':      len(ready_to_qualify),
            'need_price': len(top_traders_need_price),
            'fetch_pnl':  len(need_pnl_fetch)
        }
    }
    _save_result(f"debug_pnl_summary:{job_id}:{batch_idx}", debug_summary, ttl=LOG_TTL)
    # FIX 41: retry save — this result is read by score_and_rank_single
    _save_result_with_retry(f"pnl_batch:{job_id}:{batch_idx}", qualified)

    return qualified


def _qualify_wallet(wallet, pnl_data, wallet_data, token, qualified_list, min_invested=100, min_roi_mult=5.0, debug=False):
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
            print(f"[QUALIFY DEBUG] {wallet[:8]} FAIL: realized={realized_mult:.2f}x "
                  f"total={total_mult:.2f}x < {min_roi_mult}x")
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
        print(f"[QUALIFY DEBUG] {wallet[:8]} WARNING: No entry price, qualifies on multiplier only")

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

    for holder_field in ['holding_amount', 'holding_usd', 'holding_pct']:
        if wdata.get(holder_field):
            wallet_entry[holder_field] = wdata[holder_field]

    qualified_list.append(wallet_entry)
    if debug:
        print(f"[QUALIFY DEBUG] {wallet[:8]} PASS: invested=${total_invested:.2f}, "
              f"mult={max(realized_mult, total_mult):.2f}x")
    return True


# =============================================================================
# PHASE 3: SCORE + RANK
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

    print(f"\n[SCORER] {token.get('ticker')} — collecting pre-qualified + {batch_count} PnL batches "
          f"(mode={'batch' if is_batch else 'single'})")

    qualified_wallets = []
    total_failed      = 0
    failure_summary   = defaultdict(int)

    pre_qualified = _load_result(f"pnl_batch:{job_id}:pre")
    if pre_qualified:
        qualified_wallets.extend(pre_qualified)
        print(f"  Pre-qualified (traders+buyers): {len(pre_qualified)} wallets")

    for i in range(batch_count):
        batch_result = _load_result(f"pnl_batch:{job_id}:{i}")
        if batch_result:
            qualified_wallets.extend(batch_result)

        failed = _load_result(f"debug_failed_wallets:{job_id}:{i}")
        if failed:
            total_failed += len(failed)
            for f in failed:
                failure_summary[f.get('failure_reason', 'unknown')] += 1

        summary = _load_result(f"debug_pnl_summary:{job_id}:{i}")
        if summary:
            print(f"  Batch {i}: {summary.get('qualified', 0)} qualified, {summary.get('failed', 0)} failed")

    print(f"  ✓ Total qualified: {len(qualified_wallets)} | Total failed: {total_failed}")
    if failure_summary:
        print(f"  Failure summary: {dict(failure_summary)}")

    final_summary = {
        'job_id':             job_id,
        'token':              token.get('ticker'),
        'token_address':      token.get('address'),
        'timestamp':          time.time(),
        'mode':               'batch' if is_batch else 'single',
        'total_qualified':    len(qualified_wallets),
        'total_failed':       total_failed,
        'failure_breakdown':  dict(failure_summary),
        'pre_qualified':      len(pre_qualified) if pre_qualified else 0,
        'batch_qualified':    len(qualified_wallets) - (len(pre_qualified) if pre_qualified else 0),
        'pnl_batch_count':    batch_count,
    }
    _save_fetch_log(f"log:job_final_summary:{job_id}", final_summary)
    print(f"  \u2713 Final summary written \u2192 GET log:job_final_summary:{job_id}")

    qualified_log = [
        {
            'wallet':       w.get('wallet'),
            'source':       w.get('source'),
            'total_roi':    w.get('total_roi'),
            'invested_usd': w.get('invested_usd'),
            'realized_pnl': w.get('realized_pnl'),
        }
        for w in qualified_wallets
    ]
    _save_fetch_log(f"log:qualified_wallets:{job_id}", qualified_log)
    print(f"  \u2713 Qualified wallets written \u2192 GET log:qualified_wallets:{job_id}")

    token_address = token.get('address')
    if token_address and qualified_wallets:
        _save_qualified_wallets_cache(token_address, qualified_wallets)

    if is_batch:
        _save_result_with_retry(f"ranked_wallets:{job_id}", qualified_wallets)
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
        ath_data  = analyzer.get_token_ath(token_address)
        ath_price = ath_data.get('highest_price', 0) if ath_data else 0
        # FIX 10: ATH market cap from API
        ath_mcap  = ath_data.get('highest_market_cap', 0) if ath_data else 0

        wallet_results = []
        for wallet_info in qualified_wallets:
            wallet_addr = wallet_info['wallet']
            wallet_info['ath_price'] = ath_price
            scoring = analyzer.calculate_wallet_relative_score(wallet_info)

            if scoring['professional_score'] >= 90:   tier = 'S'
            elif scoring['professional_score'] >= 80: tier = 'A'
            elif scoring['professional_score'] >= 70: tier = 'B'
            else:                                     tier = 'C'

            entry_price = wallet_info.get('entry_price')
            # FIX 10: derive entry market cap from price ratio
            entry_mcap = None
            if entry_price and ath_price and ath_price > 0 and ath_mcap:
                entry_mcap = round((entry_price / ath_price) * ath_mcap, 0)

            wallet_result = {
                'wallet':                  wallet_addr,
                'source':                  wallet_info['source'],
                'tier':                    tier,
                'roi_percent':             round((wallet_info['realized_multiplier'] - 1) * 100, 2),
                'roi_multiplier':          round(wallet_info['realized_multiplier'], 2),
                'entry_to_ath_multiplier': scoring.get('entry_to_ath_multiplier'),
                'distance_to_ath_pct':     scoring.get('distance_to_ath_pct'),  # display only
                'realized_profit':         wallet_info['realized'],
                'unrealized_profit':       wallet_info['unrealized'],
                'total_invested':          wallet_info['total_invested'],
                'realized_multiplier':     scoring.get('realized_multiplier'),
                'total_multiplier':        scoring.get('total_multiplier'),
                'professional_score':      scoring['professional_score'],
                'professional_grade':      scoring['professional_grade'],
                'score_breakdown':         scoring['score_breakdown'],
                'first_buy_time':          wallet_info.get('earliest_entry'),
                'entry_price':             entry_price,
                'ath_price':               ath_price,
                'ath_market_cap':          ath_mcap,
                'entry_market_cap':        entry_mcap,
                'is_cross_token':          False,
                'runner_hits_30d':         0,
                'runner_success_rate':     0,
                'runner_avg_roi':          0,
                'other_runners':           [],
                'other_runners_stats':     {},
                'is_fresh':                 True,
            }

            for holder_field in ['holding_amount', 'holding_usd', 'holding_pct']:
                if wallet_info.get(holder_field):
                    wallet_result[holder_field] = wallet_info[holder_field]

            wallet_results.append(wallet_result)

        wallet_results.sort(key=lambda x: x['professional_score'], reverse=True)
        top_20 = wallet_results[:20]

        _save_result_with_retry(f"ranked_wallets:{job_id}", top_20)

        _, q_batch, q_compute = _get_queues()
        runner_jobs = []
        chunk_size  = 5

        for i in range(0, len(top_20), chunk_size):
            chunk     = top_20[i:i + chunk_size]
            batch_idx = i // chunk_size
            # FIX 39: retry on runner history workers
            rh_job = q_batch.enqueue(
                'services.worker_tasks.fetch_runner_history_batch',
                {
                    'token':     token,
                    'job_id':    job_id,
                    'batch_idx': batch_idx,
                    'wallets':   [w['wallet'] for w in chunk],
                },
                retry=RQRetry(max=3, interval=[10, 30, 60])
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
            depends_on=Dependency(jobs=runner_jobs, allow_failure=True),
            retry=RQRetry(max=3, interval=[10, 30, 60])
        )

        print(f"  ✓ Merge+save: {merge_job.id[:8]} (waits for {len(runner_jobs)} runner batches)")
        return {'mode': 'single', 'runner_jobs': [j.id for j in runner_jobs], 'merge_job': merge_job.id}


# =============================================================================
# CACHE PATH FAST TRACK
# =============================================================================

def fetch_from_token_cache(data):
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
    if not parent_job_id:
        return

    r     = _get_redis()
    count = r.incr(f"batch_completed:{parent_job_id}")
    # Re-stamp TTL after INCR: if the key expired between the initial SET and this INCR,
    # Redis creates a new key with NO TTL at all. expire() is a no-op if TTL is healthy,
    # so this is safe to call unconditionally every time.
    r.expire(f"batch_completed:{parent_job_id}", PIPELINE_TTL)
    total = r.get(f"batch_total:{parent_job_id}")

    if not total:
        print(f"[BATCH COUNTER] WARNING: batch_total key missing for {parent_job_id} "
              f"— aggregator cannot fire. Re-run or manually queue aggregate_cross_token.")
        return

    total = int(total)

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

    # FIX 41: retry save — read by merge_and_save_final
    _save_result_with_retry(f"runner_batch:{job_id}:{batch_idx}", enriched)
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
        print(f"\n[MERGE BATCH] {token.get('ticker')} — saving, incrementing counter...")

        result = {
            'success': True,
            'token':   token,
            'wallets': wallet_list,
            'total':   total_qualified,
        }

        _save_result(f"token_result:{job_id}", result, ttl=LOG_TTL)

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
# SCORING (log-scale, consistent ceiling=1000 via _roi_to_score throughout):
#   60% — _roi_to_score(avg_entry_to_ath_multiplier)  [was: 0.60 * avg_dist (percentage) — WRONG]
#   30% — _roi_to_score(avg_total_roi_multiplier)
#   10% — consistency_score
#
# avg_distance_to_ath_pct is still computed and passed through for display only.
# It does NOT feed into aggregate_score.
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

    all_token_results = []
    for sub_job_id, token in zip(sub_job_ids, tokens):
        wallets = _load_result(f"ranked_wallets:{sub_job_id}")
        if wallets:
            all_token_results.append({'token': token, 'wallets': wallets})

    print(f"  ✓ Loaded {len(all_token_results)}/{len(tokens)} token results")

    launch_prices = {}
    ath_prices    = {}
    ath_mcaps     = {}   # FIX 10: track ATH market caps per token
    for token_result in all_token_results:
        addr = token_result['token']['address']
        try:
            launch_prices[addr] = analyzer._get_token_launch_price(addr) or 0
        except Exception as e:
            print(f"  ⚠️ Launch price fetch failed for {addr[:8]}: {e}")
            launch_prices[addr] = 0
        try:
            ath_data         = analyzer.get_token_ath(addr)
            ath_prices[addr] = ath_data.get('highest_price', 0) if ath_data else 0
            ath_mcaps[addr]  = ath_data.get('highest_market_cap', 0) if ath_data else 0
        except Exception as e:
            print(f"  ⚠️ ATH fetch failed for {addr[:8]}: {e}")
            ath_prices[addr] = 0
            ath_mcaps[addr]  = 0

    wallet_hits = defaultdict(lambda: {
        'wallet':                None,
        'runners_hit':           [],
        'runners_hit_addresses': set(),
        'roi_details':           [],
        'entry_to_ath_vals':     [],
        'distance_to_ath_vals':  [],   # populated for display only
        'total_roi_multipliers': [],
        'entry_ratios':          [],
        'raw_wallet_data_list':  [],
    })

    for token_result in all_token_results:
        token        = token_result['token']
        token_addr   = token['address']
        launch_price = launch_prices.get(token_addr, 0)
        ath_price    = ath_prices.get(token_addr, 0)
        ath_mcap     = ath_mcaps.get(token_addr, 0)

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

            wallet_hits[addr]['raw_wallet_data_list'].append({
                'token_addr':  token_addr,
                'wallet_info': wallet_info,
                'ath_price':   ath_price,
                'ath_mcap':    ath_mcap,
            })

            entry_price         = wallet_info.get('entry_price')
            distance_to_ath_pct = 0
            entry_to_ath_mult   = 0

            if entry_price and entry_price > 0 and ath_price and ath_price > 0:
                distance_to_ath_pct = ((ath_price - entry_price) / ath_price) * 100  # display only
                entry_to_ath_mult   = ath_price / entry_price
                wallet_hits[addr]['distance_to_ath_vals'].append(distance_to_ath_pct)
                wallet_hits[addr]['entry_to_ath_vals'].append(entry_to_ath_mult)

            total_mult = wallet_info.get('total_multiplier', 0)
            if total_mult:
                wallet_hits[addr]['total_roi_multipliers'].append(total_mult)

            if entry_price and launch_price and launch_price > 0:
                wallet_hits[addr]['entry_ratios'].append(entry_price / launch_price)

            # FIX 10: derive entry_market_cap from price ratio
            entry_mcap = None
            if entry_price and ath_price and ath_price > 0 and ath_mcap:
                entry_mcap = round((entry_price / ath_price) * ath_mcap, 0)

            wallet_hits[addr]['roi_details'].append({
                'runner':                  sym,
                'runner_address':          token_addr,
                'roi_multiplier':          wallet_info.get('realized_multiplier', 0),
                'total_multiplier':        wallet_info.get('total_multiplier', 0),
                'entry_to_ath_multiplier': round(entry_to_ath_mult, 2) if entry_to_ath_mult else None,
                'distance_to_ath_pct':     round(distance_to_ath_pct, 2) if distance_to_ath_pct else None,  # display only
                'entry_price':             entry_price,
                'ath_market_cap':          ath_mcap,
                'entry_market_cap':        entry_mcap,
            })

    cross_token_candidates  = []
    single_token_candidates = []

    for addr, d in wallet_hits.items():
        runner_count = len(d['runners_hit'])

        # avg_dist is display-only — never used in scoring
        avg_dist = (
            sum(d['distance_to_ath_vals']) / len(d['distance_to_ath_vals'])
            if d['distance_to_ath_vals'] else 0
        )
        avg_total_roi = (
            sum(d['total_roi_multipliers']) / len(d['total_roi_multipliers'])
            if d['total_roi_multipliers'] else 0
        )
        avg_entry_to_ath = (
            sum(d['entry_to_ath_vals']) / len(d['entry_to_ath_vals'])
            if d['entry_to_ath_vals'] else None
        )

        if len(d['entry_ratios']) >= 2:
            try:
                variance          = statistics.variance(d['entry_ratios'])
                consistency_score = max(0, 100 - (variance * 10))
            except Exception:
                consistency_score = 50
        else:
            consistency_score = 50

        if runner_count >= min_runner_hits:
            # FIX 18/19: log-scale scoring for both entry timing AND total ROI.
            # avg_dist (percentage) is intentionally NOT used here — it is display-only.
            entry_score     = _roi_to_score(avg_entry_to_ath) if avg_entry_to_ath else 0
            roi_score       = _roi_to_score(avg_total_roi)
            aggregate_score = (
                0.60 * entry_score +
                0.30 * roi_score +
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
                'avg_distance_to_ath_pct':     round(avg_dist, 2),             # display only
                'avg_entry_to_ath_multiplier': round(avg_entry_to_ath, 2) if avg_entry_to_ath else None,
                'avg_total_roi':               round(avg_total_roi, 2),
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
                    'entry_score':       round(0.60 * entry_score, 2),
                    'total_roi_score':   round(0.30 * roi_score, 2),
                    'consistency_score': round(0.10 * consistency_score, 2),
                }
            })

        else:
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

            # FIX 10: pass through market cap fields for single-token candidates too
            entry_price = best_raw['wallet_info'].get('entry_price')
            ath_price   = best_raw['ath_price']
            ath_mcap    = best_raw['ath_mcap']
            entry_mcap  = None
            if entry_price and ath_price and ath_price > 0 and ath_mcap:
                entry_mcap = round((entry_price / ath_price) * ath_mcap, 0)

            single_token_candidates.append({
                'wallet':                      addr,
                'is_cross_token':              False,
                'runner_count':                runner_count,
                'runners_hit':                 d['runners_hit'],
                'analyzed_tokens':             d['runners_hit'],
                'professional_score':          scoring['professional_score'],
                'professional_grade':          scoring['professional_grade'],
                'tier':                        tier,
                'avg_distance_to_ath_pct':     round(avg_dist, 2),             # display only
                'avg_total_roi':               round(avg_total_roi, 2),
                'avg_entry_to_ath_multiplier': round(avg_entry_to_ath, 2) if avg_entry_to_ath else None,
                'entry_to_ath_multiplier':     scoring.get('entry_to_ath_multiplier'),
                'distance_to_ath_pct':         scoring.get('distance_to_ath_pct'),  # display only
                'entry_price':                 entry_price,
                'ath_price':                   ath_price,
                'ath_market_cap':              ath_mcap,
                'entry_market_cap':            entry_mcap,
                'roi_details':                 d['roi_details'][:5],
                'score_breakdown':             scoring['score_breakdown'],
                'is_fresh':                    True,
                'runner_hits_30d':             0,
                'runner_success_rate':         0,
                'runner_avg_roi':              0,
                'other_runners':               [],
                'other_runners_stats':         {},
            })

    cross_token_candidates.sort(
        key=lambda x: (x['runner_count'], x['aggregate_score']), reverse=True
    )
    single_token_candidates.sort(
        key=lambda x: x['professional_score'], reverse=True
    )

    cross_top       = cross_token_candidates[:20]
    slots_remaining = max(0, 20 - len(cross_top))
    single_fill     = single_token_candidates[:slots_remaining]
    top_20          = cross_top + single_fill

    print(f"  ✓ Cross-token: {len(cross_top)} wallets | "
          f"Single-token fill: {len(single_fill)} wallets | "
          f"Top 20 total: {len(top_20)}")

    _, q_batch, q_compute = _get_queues()
    runner_jobs = []
    chunk_size  = 5

    for i in range(0, len(top_20), chunk_size):
        chunk     = top_20[i:i + chunk_size]
        batch_idx = i // chunk_size
        # FIX 39: retry on runner history workers in aggregator path
        rh_job = q_batch.enqueue(
            'services.worker_tasks.fetch_runner_history_batch',
            {
                'token':     tokens[0] if tokens else {},
                'job_id':    job_id,
                'batch_idx': batch_idx,
                'wallets':   [w['wallet'] for w in chunk],
            },
            retry=RQRetry(max=3, interval=[10, 30, 60])
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
        depends_on=Dependency(jobs=runner_jobs, allow_failure=True) if runner_jobs else None,
        retry=RQRetry(max=3, interval=[10, 30, 60])
    )

    print(f"  ✓ {len(runner_jobs)} runner history workers → merge_batch_final")
    return {'top_20_count': len(top_20), 'runner_jobs': len(runner_jobs)}


# =============================================================================
# BATCH FINAL MERGE — compute queue
# =============================================================================

def merge_batch_final(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    job_id             = data['job_id']
    user_id            = data.get('user_id', 'default_user')
    top_20             = data['top_20']
    total              = data['total']
    cross_token_count  = data.get('cross_token_count', 0)
    single_token_count = data.get('single_token_count', 0)
    tokens_analyzed    = data.get('tokens_analyzed', 0)
    tokens             = data.get('tokens', [])
    runner_batch_count = data['runner_batch_count']

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


# =============================================================================
# MANUAL DEBUGGING UTILITY
# =============================================================================

def dump_job_logs(job_id, verbose=False):
    """
    Print a full human-readable diagnostic report for a job.

    Call from a shell / admin route:
        from services.worker_tasks import dump_job_logs
        dump_job_logs("your-job-id-here")
        dump_job_logs("your-job-id-here", verbose=True)  # include per-wallet entries

    Covers:
      - Phase 1 failures (top_traders / first_buyers API errors)
      - Entry price fetch summary (per batch)
      - PnL batch summaries (qualified / failed counts per batch)
      - Failed wallet breakdown (cause + reason per wallet)
      - Qualified wallets (source, roi, invested, pnl)
      - Abandoned job detection (pnl_batch_info present but batch result keys missing)
      - Final job summary

    All log keys expire at LOG_TTL (6h). If a key is missing, it either
    never existed or has already expired.

    failure_cause legend:
      empty_response      — async_fetch returned None (429 / timeout / 404)
      api_error           — got response but it was empty / missing expected fields
      code_exception      — Python exception raised during processing
      qualification_failed— fetched fine but wallet didn't meet threshold
      abandoned_job       — RQ killed the worker mid-run (result key present in
                            pnl_batch_info but the actual batch result key is missing)
    """
    r = _get_redis()

    def _get(key):
        raw = r.get(key)
        return json.loads(raw) if raw else None

    def _ttl(key):
        t = r.ttl(key)
        if t == -2:
            return "MISSING (expired or never written)"
        if t == -1:
            return "NO EXPIRY ⚠️"
        m, s = divmod(t, 60)
        h, m = divmod(m, 60)
        return f"{h}h {m}m {s}s remaining"

    SEP  = "=" * 70
    SEP2 = "-" * 50

    print(f"\n{SEP}")
    print(f"JOB LOG REPORT: {job_id}")
    print(SEP)

    # ── Phase 1 failures ────────────────────────────────────────────────────
    phase1_failures = _get(f"log:phase1_failures:{job_id}")
    print(f"\n{'─'*50}")
    print("PHASE 1: Top Traders / First Buyers")
    print(f"  key TTL: {_ttl(f'log:phase1_failures:{job_id}')}")
    if phase1_failures:
        for entry in phase1_failures:
            cause = entry.get('failure_cause', 'unknown')
            print(f"  ⚠️  [{entry.get('source')}] {cause}: {entry.get('reason')}")
            if verbose:
                print(f"       url: {entry.get('url')}")
    else:
        print("  ✓ No Phase 1 failures logged (or log has expired)")

    # ── Fetch summary (rolling across batches) ───────────────────────────────
    fetch_summary = _get(f"log:job_fetch_summary:{job_id}")
    print(f"\n{'─'*50}")
    print("FETCH SUMMARY (entry prices, pnl entry prices, pnl full fetch)")
    print(f"  key TTL: {_ttl(f'log:job_fetch_summary:{job_id}')}")
    if fetch_summary:
        for row in fetch_summary:
            pct  = row.get('success_rate_pct', 0)
            icon = "✓" if pct >= 70 else ("⚠️" if pct >= 40 else "❌")
            print(f"  {icon} [{row.get('batch_type')} batch {row.get('batch_idx')}] "
                  f"{row.get('prices_found')}/{row.get('total_wallets')} found "
                  f"({pct}% success)")
            if verbose and row.get('failure_counts'):
                for cause, cnt in row.get('failure_counts', {}).items():
                    print(f"       {cause}: {cnt}")
    else:
        print("  No fetch summary found (or expired)")

    # ── PnL batch summaries ──────────────────────────────────────────────────
    batch_info = _get(f"pnl_batch_info:{job_id}")
    print(f"\n{'─'*50}")
    print("PNL BATCH SUMMARIES")
    print(f"  pnl_batch_info TTL: {_ttl(f'pnl_batch_info:{job_id}')}")

    abandoned_batches = []
    if batch_info:
        batch_count   = batch_info.get('batch_count', 0)
        pnl_job_ids   = batch_info.get('pnl_job_ids', [])
        pre_qual_count = batch_info.get('pre_qualified_count', 0)
        print(f"  pre_qualified: {pre_qual_count} | pnl batches: {batch_count}")

        for i in range(batch_count):
            summary = _get(f"debug_pnl_summary:{job_id}:{i}")
            result_ttl = _ttl(f"job_result:pnl_batch:{job_id}:{i}")
            rq_job_id  = pnl_job_ids[i] if i < len(pnl_job_ids) else "unknown"

            if summary:
                icon = "✓" if summary.get('qualified', 0) > 0 else "·"
                print(f"  {icon} Batch {i}: "
                      f"{summary.get('qualified', 0)} qualified, "
                      f"{summary.get('failed', 0)} failed "
                      f"| rq_job={rq_job_id[:8] if rq_job_id != 'unknown' else 'unknown'}")
                if verbose and summary.get('failure_breakdown'):
                    for cause, cnt in summary.get('failure_breakdown', {}).items():
                        print(f"       {cause}: {cnt}")
            else:
                batch_result = _get(f"pnl_batch:{job_id}:{i}")
                if batch_result is None:
                    abandoned_batches.append({
                        'batch_idx': i,
                        'rq_job_id': rq_job_id,
                        'result_ttl': result_ttl,
                    })
                    print(f"  ❌ Batch {i}: ABANDONED — no summary and no result key "
                          f"| rq_job={rq_job_id[:8] if rq_job_id != 'unknown' else 'unknown'} "
                          f"| failure_cause=abandoned_job")
                else:
                    print(f"  ? Batch {i}: result exists but no summary (unusual) "
                          f"| {len(batch_result)} wallets")
    else:
        print("  No pnl_batch_info found — job may not have reached PnL phase, or key expired")

    # ── Abandoned job summary ────────────────────────────────────────────────
    if abandoned_batches:
        print(f"\n{'─'*50}")
        print(f"⚠️  ABANDONED JOBS DETECTED ({len(abandoned_batches)} batches)")
        print("  These batches have an RQ job ID in pnl_batch_info but no result key.")
        print("  Most likely cause: RQ worker was killed (OOM, timeout, restart) mid-run.")
        print("  With RQ Retry enabled, these should now auto-recover on next run.")
        for ab in abandoned_batches:
            print(f"  - Batch {ab['batch_idx']} | rq_job={ab['rq_job_id'][:8] if ab['rq_job_id'] != 'unknown' else 'unknown'}")

    # ── Failed wallets ───────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print("FAILED WALLETS (by cause)")

    cause_totals = defaultdict(int)
    all_failed   = []

    if batch_info:
        for i in range(batch_info.get('batch_count', 0)):
            failed = _get(f"debug_failed_wallets:{job_id}:{i}")
            if failed:
                all_failed.extend(failed)
                for w in failed:
                    cause_totals[w.get('failure_cause', w.get('failure_reason', 'unknown'))] += 1

    if all_failed:
        for cause, cnt in sorted(cause_totals.items(), key=lambda x: -x[1]):
            print(f"  {cause}: {cnt}")
        if verbose:
            print(f"\n  Per-wallet detail ({len(all_failed)} total):")
            for w in all_failed:
                cause  = w.get('failure_cause', w.get('failure_reason', 'unknown'))
                reason = w.get('reason', w.get('failure_reason', ''))
                print(f"    {w.get('wallet', 'N/A')} | {cause} | {reason}")
    else:
        print("  No failed wallet data found (or expired)")

    # ── Qualified wallets ────────────────────────────────────────────────────
    qualified_log = _get(f"log:qualified_wallets:{job_id}")
    print(f"\n{'─'*50}")
    print(f"QUALIFIED WALLETS ({len(qualified_log) if qualified_log else 0})")
    print(f"  key TTL: {_ttl(f'log:qualified_wallets:{job_id}')}")
    if qualified_log:
        for w in qualified_log:
            roi = w.get('total_roi')
            roi_str = f"{roi:.2f}x" if roi else "N/A"
            inv = w.get('invested_usd')
            inv_str = f"${inv:,.0f}" if inv else "N/A"
            pnl = w.get('realized_pnl')
            pnl_str = f"${pnl:,.0f}" if pnl else "N/A"
            print(f"  ✓ {w.get('wallet')} | src={w.get('source')} "
                  f"| roi={roi_str} | inv={inv_str} | pnl={pnl_str}")
    else:
        print("  No qualified wallet log found (or expired)")

    # ── Final summary ────────────────────────────────────────────────────────
    final = _get(f"log:job_final_summary:{job_id}")
    print(f"\n{'─'*50}")
    print("FINAL SUMMARY")
    print(f"  key TTL: {_ttl(f'log:job_final_summary:{job_id}')}")
    if final:
        for k, v in final.items():
            if k not in ('job_id', 'token_address'):
                print(f"  {k}: {v}")
    else:
        print("  No final summary found (job may still be running, or log expired)")

    # ── Key TTL overview ─────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print("KEY TTL OVERVIEW (all log keys for this job)")
    log_keys = [
        f"log:phase1_failures:{job_id}",
        f"log:job_fetch_summary:{job_id}",
        f"log:qualified_wallets:{job_id}",
        f"log:job_final_summary:{job_id}",
        f"pnl_batch_info:{job_id}",
    ]
    for key in log_keys:
        print(f"  {key.split(':')[0:2][-1]}: {_ttl(key)}")

    print(f"\n{SEP}")
    print("END OF REPORT")
    print(SEP)

    return {
        'phase1_failures':   phase1_failures or [],
        'abandoned_batches': abandoned_batches,
        'qualified_count':   len(qualified_log) if qualified_log else 0,
        'failed_count':      len(all_failed),
        'failed_by_cause':   dict(cause_totals),
        'final_summary':     final,
    }