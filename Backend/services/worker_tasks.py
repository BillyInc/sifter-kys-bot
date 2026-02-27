"""
RQ Worker Tasks - Hardened Against Timeout & Work-Horse Death
=============================================================
All fixes applied:

CRITICAL BUG FIXES:
  1. Stagger sleep was inside @timeout window — SIGALRM fired mid-sleep for high batch indices.
     Fixed by pulling stagger out before timeout context / removing SIGALRM from batch funcs.
  2. @timeout decorator used SIGALRM which is not safe inside asyncio event loop.
     Batch async functions now use asyncio.wait_for() internally instead.
  3. warm_cache_runners had no heartbeat and was enqueued with default_timeout=300 (5 min),
     but took ~6 min in production. Fixed with job_timeout=900 and HeartbeatManager.
  4. coordinate_pnl_phase, merge_and_save_final, aggregate_cross_token, merge_batch_final,
     fetch_runner_history_batch, fetch_from_token_cache all had no heartbeat — added to all.
  5. All enqueue() calls now carry explicit job_timeout to override the queue default of 300s.
  6. Worker.handle_exception classmethod assignment was wrong (lambda ignored args incorrectly).
  7. HeartbeatManager now uses a safe try/except on every heartbeat attempt.
  8. Added _safe_heartbeat_job() helper to get current job without crashing if unavailable.
  9. score_and_rank_single heartbeat was never stopped on the batch code-path early return — fixed.
  10. asyncio.run() inside @timeout(SIGALRM) context could leave event loop in broken state on
      timeout — batch workers converted to internal asyncio timeout pattern.
  11. aggregate_cross_token now accumulates total_invested, realized, unrealized per wallet
      and outputs them correctly for both cross-token (summed) and single-token (direct) candidates.
      Single-token candidates now include all PnL fields identical to single-token mode.

PIPELINE SIMPLIFICATION:
  - Removed coordinate_entry_prices, fetch_entry_prices_batch, merge_entry_prices entirely.
  - Entry price now extracted from first_buy field in /pnl/{wallet}/{token} response.
  - Runner history now uses /pnl/{wallet} (all positions) instead of /wallet/{wallet}/trades.
  - Runner results bucketed into 7d/14d/30d windows by first_buy_time.
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
import signal
import threading
import traceback
from utils import _roi_to_score

# =============================================================================
# TTL CONSTANTS
# =============================================================================
LOG_TTL = 21600          # 6h
PIPELINE_TTL = 86400     # 24h
DEAD_LETTER_TTL = 604800 # 7 days

# =============================================================================
# JOB TIMEOUT CONSTANTS
# =============================================================================
TIMEOUT_PHASE1_WORKER  = 50
TIMEOUT_PNL_BATCH      = 120

JT_PHASE1_WORKER       = 120
JT_COORD               = 180
JT_PNL_BATCH           = 600
JT_MERGE               = 180
JT_SCORER              = 600
JT_RUNNER_BATCH        = 180
JT_MERGE_FINAL         = 180
JT_AGGREGATE           = 600
JT_CACHE_PATH          = 120
JT_WARMUP              = 900

# =============================================================================
# CIRCUIT BREAKER
# =============================================================================
class APICircuitBreaker:
    def __init__(self, name, failure_threshold=3, recovery_timeout=60):
        self.name = name
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = 0
        self.is_open = False
        self._lock = threading.Lock()

    def call(self, func, *args, **kwargs):
        with self._lock:
            if self.is_open:
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    print(f"[CIRCUIT BREAKER] {self.name} attempting recovery — closing circuit")
                    self.is_open = False
                    self.failure_count = 0
                else:
                    raise Exception(f"Circuit breaker {self.name} is open (failed {self.failure_count} times)")
        try:
            result = func(*args, **kwargs)
            with self._lock:
                self.failure_count = 0
            return result
        except Exception as e:
            with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.failure_threshold:
                    print(f"[CIRCUIT BREAKER] {self.name} opened after {self.failure_count} failures")
                    self.is_open = True
            raise e

pnl_circuit_breaker     = APICircuitBreaker("pnl_api",     failure_threshold=3, recovery_timeout=120)
holders_circuit_breaker = APICircuitBreaker("holders_api", failure_threshold=3, recovery_timeout=60)

# =============================================================================
# DEAD LETTER QUEUE HANDLER
# =============================================================================
def _handle_failed_job(job, connection, exc_type, exc_value, tb):
    try:
        r = _get_redis()
        failed_info = {
            'job_id':      job.id,
            'queue':       job.origin,
            'function':    job.func_name,
            'args':        str(job.args),
            'kwargs':      str(job.kwargs),
            'error':       str(exc_value),
            'traceback':   str(tb),
            'timestamp':   time.time(),
            'created_at':  job.created_at.isoformat()  if job.created_at  else None,
            'enqueued_at': job.enqueued_at.isoformat() if job.enqueued_at else None,
            'started_at':  job.started_at.isoformat()  if job.started_at  else None,
        }
        r.lpush(f"dead_letter:{job.origin}", json.dumps(failed_info, default=str))
        r.ltrim(f"dead_letter:{job.origin}", 0, 99)
        r.expire(f"dead_letter:{job.origin}", DEAD_LETTER_TTL)
        print(f"\n{'='*70}")
        print(f"[DEAD LETTER] Job {job.id[:8]} failed in {job.origin} queue")
        print(f"  Function: {job.func_name}")
        print(f"  Error: {str(exc_value)[:200]}")
        print(f"{'='*70}\n")
    except Exception as e:
        print(f"[DEAD LETTER] Error handling failed job: {e}")

from rq.worker import Worker as _RQWorker

def _worker_handle_exception(self, job, *exc_info):
    _handle_failed_job(job, self.connection, *exc_info)

_RQWorker.handle_exception = _worker_handle_exception

# =============================================================================
# TIMEOUT DECORATOR
# =============================================================================
class SoftTimeoutError(Exception):
    pass

def timeout(seconds=30):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if threading.current_thread() is not threading.main_thread():
                return func(*args, **kwargs)

            def _handler(signum, frame):
                raise SoftTimeoutError(
                    f"{func.__name__} soft-timed-out after {seconds}s "
                    f"(RQ hard-kill in ~{max(0, seconds - 5)}s more)"
                )

            original = signal.signal(signal.SIGALRM, _handler)
            signal.alarm(seconds)
            try:
                result = func(*args, **kwargs)
                signal.alarm(0)
                return result
            except SoftTimeoutError as e:
                signal.alarm(0)
                print(f"[SOFT TIMEOUT] {e}")
                job_id   = args[0].get('job_id')   if args and isinstance(args[0], dict) else None
                if job_id:
                    if func.__name__ == 'fetch_top_traders':
                        _save_result_with_retry(f"phase1_top_traders:{job_id}",
                                                {'wallets': [], 'wallet_data': {}, 'source': 'top_traders', 'error': str(e)})
                    elif func.__name__ == 'fetch_first_buyers':
                        _save_result_with_retry(f"phase1_first_buyers:{job_id}",
                                                {'wallets': [], 'wallet_data': {}, 'source': 'first_buyers', 'error': str(e)})
                    elif func.__name__ == 'fetch_top_holders':
                        _save_result_with_retry(f"phase1_holders:{job_id}",
                                                {'wallets': [], 'wallet_data': {}, 'source': 'top_holders', 'error': str(e)})
                raise
            except Exception:
                signal.alarm(0)
                raise
            finally:
                signal.signal(signal.SIGALRM, original)

        wrapper.__name__ = func.__name__
        return wrapper
    return decorator

# =============================================================================
# HEARTBEAT MANAGER
# =============================================================================
class HeartbeatManager:
    def __init__(self, job, interval=15):
        self.job      = job
        self.interval = interval
        self.running  = False
        self.thread   = None

    def start(self):
        if not self.job:
            return
        self.running = True
        self.thread  = threading.Thread(target=self._loop, daemon=True, name="heartbeat")
        self.thread.start()

    def stop(self):
        self.running = False

    def _loop(self):
        while self.running:
            try:
                try:
                    self.job.heartbeat()
                except TypeError:
                    self.job.heartbeat(self.interval * 3)
                time.sleep(self.interval)
            except Exception:
                break


def _safe_heartbeat_job():
    try:
        from rq import get_current_job
        return get_current_job()
    except Exception:
        return None

# =============================================================================
# REDIS + QUEUE SETUP
# =============================================================================

def _get_redis():
    url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    return Redis.from_url(
        url,
        socket_timeout=60,
        socket_connect_timeout=10,
        socket_keepalive=True,
        socket_keepalive_options={
            socket.TCP_KEEPIDLE:  30,
            socket.TCP_KEEPINTVL: 5,
            socket.TCP_KEEPCNT:   10,
        },
        retry_on_timeout=True,
        retry=Retry(ExponentialBackoff(cap=10, base=1), retries=5),
        health_check_interval=30,
    )

def _get_queues():
    r = _get_redis()
    return (
        Queue('high',    connection=r, default_timeout=JT_PHASE1_WORKER),
        Queue('batch',   connection=r, default_timeout=JT_PNL_BATCH),
        Queue('compute', connection=r, default_timeout=JT_SCORER),
    )

def _save_result_with_retry(key, data, ttl=None, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            _save_result(key, data, ttl)
            return
        except Exception as e:
            if attempt < max_attempts - 1:
                wait = 2 ** attempt
                print(f"[SAVE RETRY] attempt {attempt+1}/{max_attempts} failed: {e} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"[SAVE RETRY] all attempts exhausted for key={key}: {e}")

def _save_result(key, data, ttl=None):
    r = _get_redis()
    r.set(f"job_result:{key}", json.dumps(data), ex=ttl or PIPELINE_TTL)

def _load_result(key):
    r = _get_redis()
    raw = r.get(f"job_result:{key}")
    return json.loads(raw) if raw else None

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
    r = _get_redis()
    r.set(key, json.dumps(entries, default=str), ex=ex or LOG_TTL)

def _build_fetch_log_entry(wallet, url, resp, outcome, reason, price_found=False,
                           error=None, failure_cause=None):
    if resp is None:
        response_type  = 'null'
        response_keys  = []
        response_len   = 0
        failure_cause  = failure_cause or 'empty_response'
    elif isinstance(resp, dict):
        response_type  = 'empty_dict' if not resp else 'dict'
        response_keys  = list(resp.keys())
        response_len   = len(resp.get('trades', resp.get('accounts', [])))
        if not resp and not failure_cause:
            failure_cause = 'api_error'
    elif isinstance(resp, list):
        response_type  = 'empty_list' if not resp else 'list'
        response_keys  = []
        response_len   = len(resp)
        if not resp and not failure_cause:
            failure_cause = 'api_error'
    else:
        response_type  = str(type(resp).__name__)
        response_keys  = []
        response_len   = 0

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
    if error:
        entry['error'] = str(error)
    return entry

def _append_to_job_fetch_summary(job_id, batch_type, batch_idx, total, found,
                                 failure_counts, ex=None):
    key = f"log:job_fetch_summary:{job_id}"
    r   = _get_redis()
    raw = r.get(key)
    existing = json.loads(raw) if raw else []
    existing.append({
        'batch_type':      batch_type,
        'batch_idx':       batch_idx,
        'timestamp':       time.time(),
        'total_wallets':   total,
        'prices_found':    found,
        'failure_counts':  failure_counts,
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
    except Exception as e:
        print(f"[CACHE] Failed to read qualified wallets for {token_address[:8]}: {e}")
    return None

# =============================================================================
# WORKER ANALYZER GETTER
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

    tokens    = data.get('tokens', [])
    user_id   = data.get('user_id', 'default_user')
    job_id    = data.get('job_id')
    supabase  = get_supabase_client()
    r         = _get_redis()

    if len(tokens) == 1:
        token         = tokens[0]
        token_address = token['address']

        cached = r.get(f"cache:token:{token_address}")
        if cached:
            cached_result = json.loads(cached)
            skip_cache    = False
            if not cached_result.get('wallets') or len(cached_result.get('wallets', [])) == 0:
                print(f"[CACHE INVALID] Redis cache empty for {token.get('ticker')} — deleting")
                r.delete(f"cache:token:{token_address}")
                skip_cache = True
            else:
                try:
                    current_ath_raw = r.get(f"token_ath:{token_address}")
                    if current_ath_raw:
                        current_ath_price = json.loads(current_ath_raw).get('highest_price', 0)
                        cached_wallets    = cached_result.get('wallets', [])
                        cached_ath        = next(
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


# =============================================================================
# PIPELINE QUEUING — entry prices now come from PnL first_buy, no job4_coord
# =============================================================================

def _queue_single_token_pipeline(token, user_id, job_id, supabase):
    print(f"\n[PIPELINE] Queuing single token: {token.get('ticker')}")
    q_high, q_batch, q_compute = _get_queues()

    job1 = q_high.enqueue(
        'services.worker_tasks.fetch_top_traders',
        {'token': token, 'job_id': job_id},
        job_timeout=JT_PHASE1_WORKER,
        retry=RQRetry(max=3, interval=[10, 30, 60]),
        failure_ttl=86400,
    )
    job2 = q_high.enqueue(
        'services.worker_tasks.fetch_first_buyers',
        {'token': token, 'job_id': job_id},
        job_timeout=JT_PHASE1_WORKER,
        retry=RQRetry(max=3, interval=[10, 30, 60]),
        failure_ttl=86400,
    )
    job3 = q_batch.enqueue(
        'services.worker_tasks.fetch_top_holders',
        {'token': token, 'job_id': job_id},
        job_timeout=JT_PHASE1_WORKER,
        retry=RQRetry(max=3, interval=[10, 30, 60]),
        failure_ttl=86400,
    )
    # NOTE: No job4_coord — entry prices now extracted from /pnl/{wallet}/{token} first_buy field
    pnl_coordinator = q_compute.enqueue(
        'services.worker_tasks.coordinate_pnl_phase',
        {
            'token': token, 'job_id': job_id,
            'user_id': user_id, 'parent_job_id': None,
            'phase1_jobs': [job1.id, job2.id, job3.id],
        },
        depends_on=Dependency(jobs=[job1, job2, job3], allow_failure=True),
        job_timeout=JT_COORD,
        retry=RQRetry(max=3, interval=[10, 30, 60]),
        failure_ttl=86400,
    )

    r = _get_redis()
    r.set(f"pipeline:{job_id}:coordinator", pnl_coordinator.id, ex=PIPELINE_TTL)
    r.set(f"pipeline:{job_id}:token",       json.dumps(token),  ex=PIPELINE_TTL)

    print(f"  ✓ Phase 1: traders={job1.id[:8]} buyers={job2.id[:8]} holders={job3.id[:8]}")
    print(f"  ✓ PnL coord: {pnl_coordinator.id[:8]} (entry prices from PnL first_buy)")


def _queue_batch_pipeline(tokens, user_id, job_id, supabase, min_runner_hits=2):
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
            print(f"  ✓ CACHE HIT for {token.get('ticker')} — skipping Phases 1-3")
            q_compute.enqueue(
                'services.worker_tasks.fetch_from_token_cache',
                {'token': token, 'job_id': sub_job_id,
                 'parent_job_id': job_id, 'user_id': user_id},
                job_timeout=JT_CACHE_PATH,
            )
        else:
            job1 = q_high.enqueue(
                'services.worker_tasks.fetch_top_traders',
                {'token': token, 'job_id': sub_job_id},
                job_timeout=JT_PHASE1_WORKER,
                retry=RQRetry(max=3, interval=[10, 30, 60]),
                failure_ttl=86400,
            )
            job2 = q_high.enqueue(
                'services.worker_tasks.fetch_first_buyers',
                {'token': token, 'job_id': sub_job_id},
                job_timeout=JT_PHASE1_WORKER,
                retry=RQRetry(max=3, interval=[10, 30, 60]),
                failure_ttl=86400,
            )
            job3 = q_batch.enqueue(
                'services.worker_tasks.fetch_top_holders',
                {'token': token, 'job_id': sub_job_id},
                job_timeout=JT_PHASE1_WORKER,
                retry=RQRetry(max=3, interval=[10, 30, 60]),
                failure_ttl=86400,
            )
            # NOTE: No job4_coord — entry prices from PnL first_buy
            q_compute.enqueue(
                'services.worker_tasks.coordinate_pnl_phase',
                {
                    'token': token, 'job_id': sub_job_id,
                    'user_id': user_id, 'parent_job_id': job_id,
                    'phase1_jobs': [job1.id, job2.id, job3.id],
                },
                depends_on=Dependency(jobs=[job1, job2, job3], allow_failure=True),
                job_timeout=JT_COORD,
                retry=RQRetry(max=3, interval=[10, 30, 60]),
                failure_ttl=86400,
            )
            print(f"  ✓ Full pipeline for {token.get('ticker')} [{sub_job_id[:8]}]")

    print(f"  ✓ Aggregator triggers automatically when all {len(tokens)} tokens complete")

# =============================================================================
# TRENDING BATCH ANALYSIS
# =============================================================================

def perform_trending_batch_analysis(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    runners         = data.get('runners', [])
    user_id         = data.get('user_id', 'default_user')
    min_runner_hits = data.get('min_runner_hits', 2)
    job_id          = data.get('job_id')
    supabase        = get_supabase_client()

    print(f"\n[TRENDING BATCH] Starting distributed analysis of {len(runners)} runners")
    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
        'status': 'processing', 'phase': 'queuing_pipeline', 'progress': 10,
        'tokens_total': len(runners), 'tokens_completed': 0,
    }).eq('job_id', job_id).execute()

    tokens = [
        {'address': r['address'],
         'ticker':  r.get('symbol', r.get('ticker', 'UNKNOWN')),
         'symbol':  r.get('symbol', r.get('ticker', 'UNKNOWN'))}
        for r in runners
    ]
    _queue_batch_pipeline(tokens, user_id, job_id, supabase, min_runner_hits=min_runner_hits)
    print(f"[TRENDING BATCH] Distributed pipeline queued for {len(tokens)} runners")

# =============================================================================
# AUTO-DISCOVERY
# =============================================================================

def perform_auto_discovery(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    user_id         = data.get('user_id', 'default_user')
    min_runner_hits = data.get('min_runner_hits', 2)
    job_id          = data.get('job_id')
    analyzer        = get_worker_analyzer()
    supabase        = get_supabase_client()

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
        'phase': 'queuing_pipeline', 'progress': 25, 'tokens_total': len(selected),
    }).eq('job_id', job_id).execute()

    tokens = [
        {'address': r['address'],
         'ticker':  r.get('symbol', r.get('ticker', 'UNKNOWN')),
         'symbol':  r.get('symbol', r.get('ticker', 'UNKNOWN'))}
        for r in selected
    ]
    _queue_batch_pipeline(tokens, user_id, job_id, supabase, min_runner_hits=min_runner_hits)
    print(f"[AUTO DISCOVERY] Distributed pipeline queued for {len(tokens)} runners")

# =============================================================================
# PHASE 1 WORKERS
# =============================================================================

@timeout(TIMEOUT_PHASE1_WORKER)
def fetch_top_traders(data):
    analyzer        = get_worker_analyzer()
    token           = data['token']
    job_id          = data['job_id']
    heartbeat       = HeartbeatManager(_safe_heartbeat_job())
    heartbeat.start()

    url            = f"{analyzer.st_base_url}/top-traders/{token['address']}"
    response       = None
    phase1_failure = None

    try:
        for attempt in range(3):
            try:
                response = analyzer.fetch_with_retry(
                    url, analyzer._get_solanatracker_headers(),
                    semaphore=analyzer.solana_tracker_semaphore,
                )
                if response is not None:
                    break
                print(f"[WORKER 1] attempt {attempt+1}/3 returned None")
            except Exception as e:
                print(f"[WORKER 1] attempt {attempt+1}/3 failed: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise

        if response is None:
            phase1_failure = {'source': 'top_traders', 'url': url,
                              'failure_cause': 'empty_response', 'timestamp': time.time(),
                              'reason': 'fetch_with_retry returned None after retries'}
        elif isinstance(response, list) and len(response) == 0:
            phase1_failure = {'source': 'top_traders', 'url': url,
                              'failure_cause': 'api_error', 'timestamp': time.time(),
                              'reason': 'API returned empty list'}
    except Exception as e:
        phase1_failure = {'source': 'top_traders', 'url': url, 'failure_cause': 'code_exception',
                          'reason': str(e), 'timestamp': time.time(),
                          'traceback': traceback.format_exc()}
        response = None
        print(f"[WORKER 1] ERROR: {e}")

    if phase1_failure:
        _save_fetch_log(f"log:phase1_failures:{job_id}", [phase1_failure])

    wallets     = []
    wallet_data = {}
    if response:
        for trader in (response if isinstance(response, list) else []):
            wallet = trader.get('wallet')
            if wallet:
                wallets.append(wallet)
                wallet_data[wallet] = {
                    'source': 'top_traders', 'pnl_data': trader,
                    'earliest_entry': None, 'entry_price': None,
                }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'top_traders'}
    if phase1_failure:
        result['error'] = phase1_failure
    _save_result_with_retry(f"phase1_top_traders:{job_id}", result)

    print(f"[WORKER 1] top_traders done: {len(wallets)} wallets"
          + (f" ⚠️ {phase1_failure['reason']}" if phase1_failure else ""))
    heartbeat.stop()
    return result


@timeout(TIMEOUT_PHASE1_WORKER)
def fetch_first_buyers(data):
    analyzer        = get_worker_analyzer()
    token           = data['token']
    job_id          = data['job_id']
    heartbeat       = HeartbeatManager(_safe_heartbeat_job())
    heartbeat.start()

    url            = f"{analyzer.st_base_url}/first-buyers/{token['address']}"
    response       = None
    phase1_failure = None

    try:
        for attempt in range(3):
            try:
                response = analyzer.fetch_with_retry(
                    url, analyzer._get_solanatracker_headers(),
                    semaphore=analyzer.solana_tracker_semaphore,
                )
                if response is not None:
                    break
            except Exception as e:
                print(f"[WORKER 2] attempt {attempt+1}/3 failed: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise

        if response is None:
            phase1_failure = {'source': 'first_buyers', 'url': url,
                              'failure_cause': 'empty_response', 'timestamp': time.time(),
                              'reason': 'fetch_with_retry returned None'}
        else:
            buyers = response if isinstance(response, list) else response.get('buyers', [])
            if len(buyers) == 0:
                phase1_failure = {'source': 'first_buyers', 'url': url,
                                  'failure_cause': 'api_error', 'timestamp': time.time(),
                                  'reason': 'API returned zero buyers'}
    except Exception as e:
        phase1_failure = {'source': 'first_buyers', 'url': url,
                          'failure_cause': 'code_exception', 'reason': str(e),
                          'timestamp': time.time(), 'traceback': traceback.format_exc()}
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
                    'source': 'first_buyers', 'pnl_data': buyer,
                    'earliest_entry': buyer.get('first_buy_time', 0),
                    'entry_price': entry_price,
                }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'first_buyers'}
    if phase1_failure:
        result['error'] = phase1_failure
    _save_result_with_retry(f"phase1_first_buyers:{job_id}", result)

    print(f"[WORKER 2] first_buyers done: {len(wallets)} wallets"
          + (f" ⚠️ {phase1_failure['reason']}" if phase1_failure else ""))
    heartbeat.stop()
    return result


@timeout(TIMEOUT_PHASE1_WORKER)
def fetch_top_holders(data):
    analyzer        = get_worker_analyzer()
    token           = data['token']
    job_id          = data['job_id']
    heartbeat       = HeartbeatManager(_safe_heartbeat_job())
    heartbeat.start()

    MIN_HOLDING_USD = 100
    url             = f"{analyzer.st_base_url}/tokens/{token['address']}/holders/paginated"

    try:
        response = holders_circuit_breaker.call(
            analyzer.fetch_with_retry,
            url, analyzer._get_solanatracker_headers(),
            params={'limit': 1000},
            semaphore=analyzer.solana_tracker_semaphore,
        )
    except Exception as e:
        print(f"[WORKER 3] Circuit breaker / error: {e}")
        result = {'wallets': [], 'wallet_data': {}, 'source': 'top_holders',
                  'total_holders': 0, 'error': str(e)}
        _save_result_with_retry(f"phase1_holders:{job_id}", result)
        heartbeat.stop()
        return result

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
                'source': 'top_holders', 'pnl_data': None,
                'earliest_entry': None, 'entry_price': None,
                'holding_amount': account.get('amount', 0),
                'holding_usd':    holding_usd,
                'holding_pct':    account.get('percentage', 0),
            }

    result = {
        'wallets': wallets, 'wallet_data': wallet_data, 'source': 'top_holders',
        'total_holders': response.get('total', 0) if response else 0,
    }
    _save_result_with_retry(f"phase1_holders:{job_id}", result)
    print(f"[WORKER 3] top_holders done: {len(wallets)} kept "
          f"(from {total_raw} fetched, {filtered_out} filtered <${MIN_HOLDING_USD} USD, "
          f"total={result['total_holders']})")
    heartbeat.stop()
    return result

# =============================================================================
# PHASE 2 COORDINATOR — everyone goes to PnL fetch, entry price from first_buy
# =============================================================================

def coordinate_pnl_phase(data):
    token      = data['token']
    job_id     = data['job_id']
    user_id    = data.get('user_id', 'default_user')
    parent_job = data.get('parent_job_id')
    heartbeat  = HeartbeatManager(_safe_heartbeat_job())
    heartbeat.start()

    try:
        print(f"\n[PNL COORD] Phase 1 complete for {token.get('ticker')} — merging…")

        all_wallets   = []
        wallet_data   = {}
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
                        # first_buyers data takes priority for entry_price
                        if new.get('entry_price') and not existing.get('entry_price'):
                            existing['entry_price'] = new['entry_price']
                        if new.get('earliest_entry') and not existing.get('earliest_entry'):
                            existing['earliest_entry'] = new['earliest_entry']
                        if new.get('pnl_data') and not existing.get('pnl_data'):
                            existing['pnl_data'] = new['pnl_data']
                        for hf in ['holding_amount', 'holding_usd', 'holding_pct']:
                            if new.get(hf) and not existing.get(hf):
                                existing[hf] = new[hf]
                src_key = source if source in source_counts else 'top_holders'
                source_counts[src_key] = added
            else:
                print(f"[PNL COORD] Warning: No result for {key_prefix}:{job_id}")

        print(f"  ✓ Sources: traders={source_counts['top_traders']} "
              f"buyers={source_counts['first_buyers']} "
              f"holders={source_counts['top_holders']} unique={len(all_wallets)}")

        _save_result(f"phase1_merged:{job_id}",
                     {'wallets': all_wallets, 'wallet_data': wallet_data}, ttl=LOG_TTL)

        # ── Pre-qualify wallets that have BOTH pnl_data AND entry_price ──────────
        # This covers first_buyers (entry_price from first_buy.volume_usd/amount)
        # All others go to PnL fetch — entry_price extracted from first_buy in PnL response
        pre_qualified  = []
        need_pnl_fetch = []
        pre_qual_failed = defaultdict(int)

        for wallet in all_wallets:
            wdata       = wallet_data.get(wallet, {})
            has_pnl     = wdata.get('pnl_data') is not None
            has_price   = wdata.get('entry_price') is not None

            if has_pnl and has_price:
                # first_buyers with entry_price already computed — try to qualify directly
                if not _qualify_wallet(wallet, wdata['pnl_data'], wallet_data,
                                       token, pre_qualified, debug=True):
                    invested = wdata['pnl_data'].get('total_invested', 0)
                    if invested < 100:
                        pre_qual_failed['low_invested'] += 1
                    else:
                        pre_qual_failed['low_multiplier'] += 1
            else:
                # top_traders (no entry_price) and top_holders (no pnl_data) both go here
                # PnL fetch will get us: realized, unrealized, total_invested, first_buy (→ entry_price)
                need_pnl_fetch.append(wallet)

        print(f"  ✓ Pre-qualified: {len(pre_qualified)} | "
              f"Pre-qual failures: {dict(pre_qual_failed)} | "
              f"Queued for PnL fetch: {len(need_pnl_fetch)}")

        _save_result(f"pnl_batch:{job_id}:pre", pre_qualified)

        _, q_batch, q_compute = _get_queues()
        batch_size = 8
        pnl_jobs   = []

        for i in range(0, len(need_pnl_fetch), batch_size):
            batch      = need_pnl_fetch[i:i + batch_size]
            batch_idx  = i // batch_size
            dynamic_jt = max(JT_PNL_BATCH, batch_idx * 10 + 180)
            pnl_job = q_batch.enqueue(
                'services.worker_tasks.fetch_pnl_batch',
                {
                    'token': token, 'job_id': job_id,
                    'batch_idx': batch_idx, 'wallets': batch,
                    'wallet_data': {w: wallet_data[w] for w in batch},
                },
                job_timeout=dynamic_jt,
                retry=RQRetry(max=3, interval=[30, 60, 120]),
                failure_ttl=86400,
            )
            pnl_jobs.append(pnl_job)

        print(f"  ✓ Queued {len(pnl_jobs)} PnL batch jobs (size={batch_size})")

        r = _get_redis()
        r.set(f"pnl_batch_info:{job_id}", json.dumps({
            'batch_count':         len(pnl_jobs),
            'pnl_job_ids':         [j.id for j in pnl_jobs],
            'pre_qualified_count': len(pre_qualified),
        }), ex=LOG_TTL)

        scorer_job = q_compute.enqueue(
            'services.worker_tasks.score_and_rank_single',
            {
                'token': token, 'job_id': job_id,
                'user_id': user_id, 'parent_job_id': parent_job,
                'batch_count': len(pnl_jobs),
            },
            depends_on=Dependency(jobs=pnl_jobs, allow_failure=True) if pnl_jobs else None,
            job_timeout=JT_SCORER,
            retry=RQRetry(max=3, interval=[10, 30, 60]),
            failure_ttl=86400,
        )
        print(f"  ✓ Scorer {scorer_job.id[:8]} queued — waits for {len(pnl_jobs)} PnL batches")
        return {
            'pnl_jobs':      [j.id for j in pnl_jobs],
            'batch_count':   len(pnl_jobs),
            'scorer_job':    scorer_job.id,
            'pre_qualified': len(pre_qualified),
        }
    finally:
        heartbeat.stop()

# =============================================================================
# PHASE 2 WORKERS — simplified, entry price from first_buy in PnL response
# =============================================================================

def fetch_pnl_batch(data):
    import aiohttp
    import random

    analyzer    = get_worker_analyzer()
    token       = data['token']
    job_id      = data['job_id']
    batch_idx   = data['batch_idx']
    wallets     = data['wallets']
    wallet_data = data['wallet_data']

    heartbeat = HeartbeatManager(_safe_heartbeat_job(), interval=10)
    heartbeat.start()

    rq_job    = _safe_heartbeat_job()
    rq_job_id = rq_job.id if rq_job else 'unknown'
    print(f"[PNL BATCH {batch_idx}] {len(wallets)} wallets | token={token.get('ticker')}")

    qualified              = []
    failed_wallets         = []
    qualification_failures = defaultdict(int)
    pnl_fetch_log          = []

    async def _fetch_pnls():
        async def fetch_one(session, w):
            url  = f"{analyzer.st_base_url}/pnl/{w}/{token['address']}"
            resp = None
            try:
                await asyncio.sleep(random.uniform(3, 6))
                resp = await asyncio.wait_for(
                    pnl_circuit_breaker.call(
                        analyzer.async_fetch_with_retry,
                        session, url, analyzer._get_solanatracker_headers(),
                    ),
                    timeout=TIMEOUT_PNL_BATCH,
                )
                if resp:
                    pnl_fetch_log.append(_build_fetch_log_entry(
                        w, url, resp, outcome='success', reason='success'))
                else:
                    pnl_fetch_log.append(_build_fetch_log_entry(
                        w, url, resp, outcome='fail', reason='no_response'))
            except asyncio.TimeoutError:
                pnl_fetch_log.append(_build_fetch_log_entry(
                    w, url, resp, outcome='fail', reason='timeout'))
                resp = None
            except Exception as e:
                pnl_fetch_log.append(_build_fetch_log_entry(
                    w, url, None, outcome='fail', reason='circuit_breaker', error=e))
                resp = None
            return resp

        async with aiohttp.ClientSession() as session:
            sem = asyncio.Semaphore(1)
            async def guarded(w):
                async with sem:
                    return await fetch_one(session, w)
            return await asyncio.gather(*[guarded(w) for w in wallets])

    t0 = time.time()
    try:
        results = asyncio.run(_fetch_pnls())
    except Exception as e:
        print(f"[PNL BATCH {batch_idx}] asyncio.run() failed: {e}")
        traceback.print_exc()
        results = [None] * len(wallets)

    elapsed   = time.time() - t0
    pnl_found = sum(1 for r in results if r)
    pnl_fails = defaultdict(int)
    for entry in pnl_fetch_log:
        if entry['outcome'] == 'fail':
            pnl_fails[entry['reason']] += 1

    _save_fetch_log(f"log:pnl_full_fetch:{job_id}:{batch_idx}", pnl_fetch_log)
    _append_to_job_fetch_summary(job_id, 'pnl_full_fetch', batch_idx,
                                 len(wallets), pnl_found, dict(pnl_fails))
    print(f"[PNL BATCH {batch_idx}] PnL fetch: {pnl_found}/{len(wallets)} in {elapsed:.1f}s")

    for wallet, pnl in zip(wallets, results):
        wdata = wallet_data.get(wallet, {})

        if not pnl:
            qualification_failures['no_pnl_data'] += 1
            failed_wallets.append({
                'wallet': wallet, 'failure_reason': 'no_pnl_data',
                'source': wdata.get('source', 'unknown'),
                'has_pnl': False, 'has_entry_price': False,
                'invested': 0, 'realized_multiplier': 0, 'total_multiplier': 0,
                'batch_idx': batch_idx,
            })
            continue

        # ── Extract entry_price from first_buy in PnL response ────────────────
        # This works for top_traders AND top_holders — no separate trades fetch needed
        if not wdata.get('entry_price'):
            first_buy  = pnl.get('first_buy', {})
            amount     = first_buy.get('amount', 0)
            volume_usd = first_buy.get('volume_usd', 0)
            if amount > 0:
                wdata['entry_price']    = volume_usd / amount
                wdata['earliest_entry'] = first_buy.get('time')
                # Push back into wallet_data so _qualify_wallet sees it
                wallet_data[wallet] = wdata

        if not _qualify_wallet(wallet, pnl, wallet_data, token, qualified, debug=True):
            invested = pnl.get('total_invested', 0)
            r_mult   = (pnl.get('realized', 0) + invested) / invested if invested > 0 else 0
            t_mult   = (pnl.get('realized', 0) + pnl.get('unrealized', 0) + invested) / invested \
                       if invested > 0 else 0

            if invested < 100:
                reason = 'low_invested'
            elif not wdata.get('entry_price'):
                reason = 'missing_entry_price'
            else:
                reason = 'low_multiplier'

            qualification_failures[reason] += 1
            failed_wallets.append({
                'wallet': wallet, 'failure_reason': reason,
                'source': wdata.get('source', 'unknown'),
                'has_pnl': True,
                'has_entry_price': bool(wdata.get('entry_price')),
                'invested': invested,
                'realized_multiplier': round(r_mult, 2),
                'total_multiplier': round(t_mult, 2),
                'batch_idx': batch_idx,
            })

    print(f"[PNL BATCH {batch_idx}] Done: {len(qualified)} qualified, {len(failed_wallets)} failed")
    print(f"[PNL BATCH {batch_idx}] Failure breakdown: {dict(qualification_failures)}")

    if failed_wallets:
        _save_result(f"debug_failed_wallets:{job_id}:{batch_idx}", failed_wallets, ttl=LOG_TTL)

    _save_result(f"debug_pnl_summary:{job_id}:{batch_idx}", {
        'batch_idx': batch_idx, 'rq_job_id': rq_job_id, 'timestamp': time.time(),
        'total_wallets': len(wallets), 'qualified': len(qualified),
        'failed': len(failed_wallets), 'failure_breakdown': dict(qualification_failures),
    }, ttl=LOG_TTL)

    _save_result_with_retry(f"pnl_batch:{job_id}:{batch_idx}", qualified)
    heartbeat.stop()
    return qualified

# =============================================================================
# QUALIFY WALLET
# =============================================================================

def _qualify_wallet(wallet, pnl_data, wallet_data, token, qualified_list,
                    min_invested=100, min_roi_mult=5.0, debug=False):
    realized       = pnl_data.get('realized', 0)
    unrealized     = pnl_data.get('unrealized', 0)
    total_invested = pnl_data.get('total_invested') or pnl_data.get('totalInvested', 0)

    if total_invested < min_invested:
        if debug:
            print(f"[QUALIFY] {wallet[:8]} FAIL: invested=${total_invested:.2f} < ${min_invested}")
        return False

    realized_mult = (realized + total_invested) / total_invested
    total_mult    = (realized + unrealized + total_invested) / total_invested

    if realized_mult < min_roi_mult and total_mult < min_roi_mult:
        if debug:
            print(f"[QUALIFY] {wallet[:8]} FAIL: realized={realized_mult:.2f}x "
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

    if entry_price is None:
        if debug:
            print(f"[QUALIFY] {wallet[:8]} FAIL: No entry price — cannot qualify")
        return False

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
    for hf in ['holding_amount', 'holding_usd', 'holding_pct']:
        if wdata.get(hf):
            wallet_entry[hf] = wdata[hf]

    qualified_list.append(wallet_entry)
    if debug:
        print(f"[QUALIFY] {wallet[:8]} PASS: inv=${total_invested:.2f} "
              f"ep=${entry_price:.8f} mult={max(realized_mult, total_mult):.2f}x")
    return True

# =============================================================================
# PHASE 3: SCORE + RANK
# =============================================================================

def score_and_rank_single(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    token       = data['token']
    job_id      = data['job_id']
    user_id     = data.get('user_id', 'default_user')
    parent_job  = data.get('parent_job_id')
    is_batch    = parent_job is not None
    batch_count = data.get('batch_count', 0)

    heartbeat = HeartbeatManager(_safe_heartbeat_job(), interval=10)
    heartbeat.start()

    try:
        analyzer = get_worker_analyzer()
        supabase = get_supabase_client()

        print(f"\n[SCORER] {token.get('ticker')} — collecting pre-qualified + "
              f"{batch_count} PnL batches (mode={'batch' if is_batch else 'single'})")

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
                print(f"  Batch {i}: {summary.get('qualified', 0)} qualified, "
                      f"{summary.get('failed', 0)} failed")

        print(f"  ✓ Total qualified: {len(qualified_wallets)} | Total failed: {total_failed}")
        if failure_summary:
            print(f"  Failure summary: {dict(failure_summary)}")

        final_summary = {
            'job_id': job_id, 'token': token.get('ticker'),
            'token_address': token.get('address'), 'timestamp': time.time(),
            'mode': 'batch' if is_batch else 'single',
            'total_qualified': len(qualified_wallets), 'total_failed': total_failed,
            'failure_breakdown': dict(failure_summary),
            'pre_qualified': len(pre_qualified) if pre_qualified else 0,
            'batch_qualified': len(qualified_wallets) - (len(pre_qualified) if pre_qualified else 0),
            'pnl_batch_count': batch_count,
        }
        _save_fetch_log(f"log:job_final_summary:{job_id}", final_summary)

        qualified_log = [
            {'wallet': w.get('wallet'), 'source': w.get('source'),
             'total_roi': w.get('total_multiplier', 0),
             'invested_usd': w.get('total_invested', 0),
             'realized_pnl': w.get('realized', 0)}
            for w in qualified_wallets
        ]
        _save_fetch_log(f"log:qualified_wallets:{job_id}", qualified_log)

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
                    'token': token, 'job_id': job_id,
                    'user_id': user_id, 'parent_job_id': parent_job,
                    'total_qualified': len(qualified_wallets), 'is_batch_mode': True,
                },
                job_timeout=JT_MERGE_FINAL,
            )
            print(f"  ✓ Queued merge {merge_job.id[:8]}")
            return {'mode': 'batch', 'qualified': len(qualified_wallets), 'merge_job': merge_job.id}

        else:
            ath_data  = analyzer.get_token_ath(token_address)
            ath_price = ath_data.get('highest_price', 0)      if ath_data else 0
            ath_mcap  = ath_data.get('highest_market_cap', 0) if ath_data else 0

            wallet_results = []
            for wallet_info in qualified_wallets:
                wallet_addr          = wallet_info['wallet']
                wallet_info['ath_price'] = ath_price
                scoring              = analyzer.calculate_wallet_relative_score(wallet_info)

                if   scoring['professional_score'] >= 90: tier = 'S'
                elif scoring['professional_score'] >= 80: tier = 'A'
                elif scoring['professional_score'] >= 70: tier = 'B'
                else:                                     tier = 'C'

                entry_price = wallet_info.get('entry_price')
                entry_mcap  = None
                if entry_price and ath_price and ath_price > 0 and ath_mcap:
                    entry_mcap = round((entry_price / ath_price) * ath_mcap, 0)

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
                    'entry_price':             entry_price,
                    'ath_price':               ath_price,
                    'ath_market_cap':          ath_mcap,
                    'entry_market_cap':        entry_mcap,
                    'is_cross_token':          False,
                    # Runner fields — populated by merge_and_save_final after runner history
                    'runner_hits_30d':         0,
                    'runner_hits_7d':          0,
                    'runner_success_rate':     0,
                    'runner_avg_roi':          0,
                    'other_runners':           [],
                    'other_runners_stats':     {},
                    'runners_7d':              [],
                    'runners_14d':             [],
                    'runners_30d':             [],
                    'stats_7d':                {},
                    'stats_14d':               {},
                    'stats_30d':               {},
                    'is_fresh':                True,
                }
                for hf in ['holding_amount', 'holding_usd', 'holding_pct']:
                    if wallet_info.get(hf):
                        wallet_result[hf] = wallet_info[hf]
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
                rh_job    = q_batch.enqueue(
                    'services.worker_tasks.fetch_runner_history_batch',
                    {'token': token, 'job_id': job_id,
                     'batch_idx': batch_idx, 'wallets': [w['wallet'] for w in chunk]},
                    job_timeout=JT_RUNNER_BATCH,
                    retry=RQRetry(max=3, interval=[10, 30, 60]),
                    failure_ttl=86400,
                )
                runner_jobs.append(rh_job)

            merge_job = q_compute.enqueue(
                'services.worker_tasks.merge_and_save_final',
                {
                    'token': token, 'job_id': job_id,
                    'user_id': user_id, 'parent_job_id': None,
                    'runner_batch_count': len(runner_jobs),
                    'total_qualified': len(wallet_results), 'is_batch_mode': False,
                },
                depends_on=Dependency(jobs=runner_jobs, allow_failure=True),
                job_timeout=JT_MERGE_FINAL,
                retry=RQRetry(max=3, interval=[10, 30, 60]),
                failure_ttl=86400,
            )
            print(f"  ✓ Merge {merge_job.id[:8]} (waits for {len(runner_jobs)} runner batches)")
            return {'mode': 'single', 'runner_jobs': [j.id for j in runner_jobs],
                    'merge_job': merge_job.id}
    finally:
        heartbeat.stop()

# =============================================================================
# CACHE PATH FAST TRACK
# =============================================================================

def fetch_from_token_cache(data):
    token      = data['token']
    job_id     = data['job_id']
    parent_job = data.get('parent_job_id')
    user_id    = data.get('user_id', 'default_user')
    heartbeat  = HeartbeatManager(_safe_heartbeat_job())
    heartbeat.start()

    try:
        print(f"\n[TOKEN CACHE] Fast path for {token.get('ticker')} [{job_id[:8]}]…")
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
                'token': token, 'job_id': job_id,
                'user_id': user_id, 'parent_job_id': parent_job,
                'total_qualified': len(qualified_wallets), 'is_batch_mode': True,
            },
            job_timeout=JT_MERGE_FINAL,
        )
        print(f"  ✓ Cache path: merge {merge_job.id[:8]} queued")
        return {'merge_job': merge_job.id}
    finally:
        heartbeat.stop()


def _trigger_aggregate_if_complete(parent_job_id, sub_job_id):
    if not parent_job_id:
        return

    r     = _get_redis()
    count = r.incr(f"batch_completed:{parent_job_id}")
    r.expire(f"batch_completed:{parent_job_id}", PIPELINE_TTL)
    total = r.get(f"batch_total:{parent_job_id}")

    if not total:
        print(f"[BATCH COUNTER] WARNING: batch_total key missing for {parent_job_id}")
        return

    total = int(total)
    print(f"[BATCH COUNTER] {count}/{total} tokens complete for parent {parent_job_id[:8]}")

    if total > 0 and count >= total:
        sub_job_ids     = json.loads(r.get(f"batch_sub_jobs:{parent_job_id}") or '[]')
        tokens          = json.loads(r.get(f"batch_tokens:{parent_job_id}") or '[]')
        min_runner_hits = int(r.get(f"batch_min_runner_hits:{parent_job_id}") or 2)
        user_id_raw     = r.get(f"batch_user_id:{parent_job_id}")
        user_id         = user_id_raw.decode() if user_id_raw else 'default_user'

        _, _, q_compute = _get_queues()
        q_compute.enqueue(
            'services.worker_tasks.aggregate_cross_token',
            {
                'tokens':          tokens,
                'job_id':          parent_job_id,
                'sub_job_ids':     sub_job_ids,
                'min_runner_hits': min_runner_hits,
                'user_id':         user_id,
            },
            job_timeout=JT_AGGREGATE,
        )
        print(f"[BATCH COUNTER] All {total} done — aggregator queued for {parent_job_id[:8]}")

# =============================================================================
# PHASE 4: RUNNER HISTORY — returns 7d/14d/30d bucketed data
# =============================================================================

def fetch_runner_history_batch(data):
    analyzer  = get_worker_analyzer()
    token     = data['token']
    job_id    = data['job_id']
    batch_idx = data['batch_idx']
    wallets   = data['wallets']
    heartbeat = HeartbeatManager(_safe_heartbeat_job())
    heartbeat.start()

    enriched = []
    print(f"[RUNNER BATCH {batch_idx}] {len(wallets)} wallets…")

    try:
        for wallet_addr in wallets:
            try:
                runner_history = analyzer._get_cached_other_runners(
                    wallet_addr,
                    current_token=token.get('address'),
                    min_multiplier=10.0,
                )
                enriched.append({
                    'wallet':              wallet_addr,
                    # 7/14/30d bucketed data for watchlist
                    'runners_7d':          runner_history.get('runners_7d', []),
                    'runners_14d':         runner_history.get('runners_14d', []),
                    'runners_30d':         runner_history.get('runners_30d', []),
                    'stats_7d':            runner_history.get('stats_7d', {}),
                    'stats_14d':           runner_history.get('stats_14d', {}),
                    'stats_30d':           runner_history.get('stats_30d', {}),
                    # Backward compat flat fields
                    'runner_hits_30d':     runner_history['stats_30d'].get('total_other_runners', 0),
                    'runner_hits_7d':      runner_history['stats_7d'].get('total_other_runners', 0),
                    'runner_success_rate': runner_history['stats_30d'].get('success_rate', 0),
                    'runner_avg_roi':      runner_history['stats_30d'].get('avg_roi', 0),
                    'other_runners':       runner_history.get('runners_30d', [])[:5],
                    'other_runners_stats': runner_history.get('stats_30d', {}),
                })
            except Exception as e:
                print(f"  ⚠️ Runner history failed for {wallet_addr[:8]}: {e}")
                empty = {
                    'total_other_runners': 0, 'success_rate': 0,
                    'avg_roi': 0, 'avg_entry_to_ath': 0,
                    'total_invested': 0, 'total_realized': 0,
                }
                enriched.append({
                    'wallet':              wallet_addr,
                    'runners_7d':          [],
                    'runners_14d':         [],
                    'runners_30d':         [],
                    'stats_7d':            empty,
                    'stats_14d':           empty,
                    'stats_30d':           empty,
                    'runner_hits_30d':     0,
                    'runner_hits_7d':      0,
                    'runner_success_rate': 0,
                    'runner_avg_roi':      0,
                    'other_runners':       [],
                    'other_runners_stats': {},
                })

        _save_result_with_retry(f"runner_batch:{job_id}:{batch_idx}", enriched)
        print(f"[RUNNER BATCH {batch_idx}] Done: {len(enriched)} enriched")
        return enriched
    finally:
        heartbeat.stop()

# =============================================================================
# RUNNER HISTORY MERGE HELPER — used by both merge_and_save_final and merge_batch_final
# =============================================================================

def _merge_runner_history_into_wallets(wallet_list, runner_lookup):
    """
    Merges runner history (7d/14d/30d) into wallet result dicts.
    Called by both merge_and_save_final (single) and merge_batch_final (batch).
    """
    empty_stats = {
        'total_other_runners': 0, 'success_rate': 0,
        'avg_roi': 0, 'avg_entry_to_ath': 0,
        'total_invested': 0, 'total_realized': 0,
    }
    for w in wallet_list:
        rh = runner_lookup.get(w.get('wallet'))
        if rh:
            w['runners_7d']          = rh.get('runners_7d', [])
            w['runners_14d']         = rh.get('runners_14d', [])
            w['runners_30d']         = rh.get('runners_30d', [])
            w['stats_7d']            = rh.get('stats_7d', {})
            w['stats_14d']           = rh.get('stats_14d', {})
            w['stats_30d']           = rh.get('stats_30d', {})
            w['runner_hits_30d']     = rh.get('runner_hits_30d', 0)
            w['runner_hits_7d']      = rh.get('runner_hits_7d', 0)
            w['runner_success_rate'] = rh.get('runner_success_rate', 0)
            w['runner_avg_roi']      = rh.get('runner_avg_roi', 0)
            w['other_runners']       = rh.get('other_runners', [])
            w['other_runners_stats'] = rh.get('other_runners_stats', {})
        else:
            # Defaults — runner history job may have timed out
            w.setdefault('runners_7d',          [])
            w.setdefault('runners_14d',         [])
            w.setdefault('runners_30d',         [])
            w.setdefault('stats_7d',            empty_stats)
            w.setdefault('stats_14d',           empty_stats)
            w.setdefault('stats_30d',           empty_stats)
            w.setdefault('runner_hits_30d',     0)
            w.setdefault('runner_hits_7d',      0)
            w.setdefault('runner_success_rate', 0)
            w.setdefault('runner_avg_roi',      0)
            w.setdefault('other_runners',       [])
            w.setdefault('other_runners_stats', {})
    return wallet_list

# =============================================================================
# PHASE 4 MERGE
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

    heartbeat = HeartbeatManager(_safe_heartbeat_job())
    heartbeat.start()

    try:
        supabase      = get_supabase_client()
        r             = _get_redis()
        wallet_list   = _load_result(f"ranked_wallets:{job_id}") or []
        token_address = token.get('address')

        if not is_batch_mode:
            print(f"\n[MERGE] {token.get('ticker')} — {runner_batch_count} runner batches…")

            runner_lookup = {}
            for i in range(runner_batch_count):
                batch = _load_result(f"runner_batch:{job_id}:{i}") or []
                for entry in batch:
                    runner_lookup[entry['wallet']] = entry

            _merge_runner_history_into_wallets(wallet_list, runner_lookup)

            result = {'success': True, 'token': token,
                      'wallets': wallet_list, 'total': total_qualified}

            warm_redis_cache = True
            try:
                current_ath_raw = r.get(f"token_ath:{token_address}")
                if current_ath_raw:
                    current_ath_price = json.loads(current_ath_raw).get('highest_price', 0)
                    analysis_ath      = next(
                        (w.get('ath_price', 0) for w in wallet_list if w.get('ath_price')), 0)
                    if analysis_ath > 0 and current_ath_price > analysis_ath * 1.10:
                        print(f"  ⚠️ ATH moved — skipping Redis warm for {token.get('ticker')}")
                        warm_redis_cache = False
            except Exception as e:
                print(f"[MERGE] ATH check failed: {e}")

            if warm_redis_cache:
                r.set(f"cache:token:{token_address}", json.dumps(result), ex=21600)

            for attempt in range(3):
                try:
                    supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                        'status': 'completed', 'phase': 'done', 'progress': 100,
                        'results': result, 'token_address': token_address,
                    }).eq('job_id', job_id).execute()
                    print(f"  ✅ Saved final result for job {job_id[:8]}")
                    break
                except Exception as e:
                    if attempt < 2:
                        wait = 5 * (attempt + 1)
                        print(f"  ⚠️ Save attempt {attempt+1}/3 failed: {e} — retrying in {wait}s")
                        time.sleep(wait)
                    else:
                        r.set(f"UNSAVED_RESULT:{job_id}", json.dumps(result), ex=PIPELINE_TTL)
                        print(f"  ❌ All save attempts failed — preserved in Redis as UNSAVED_RESULT:{job_id}")

            return result

        else:
            print(f"\n[MERGE BATCH] {token.get('ticker')} — saving, incrementing counter…")

            result = {'success': True, 'token': token,
                      'wallets': wallet_list, 'total': total_qualified}
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
    finally:
        heartbeat.stop()

# =============================================================================
# BATCH AGGREGATOR
# =============================================================================

def aggregate_cross_token(data):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    tokens          = data['tokens']
    job_id          = data['job_id']
    sub_job_ids     = data['sub_job_ids']
    min_runner_hits = data.get('min_runner_hits', 2)

    heartbeat = HeartbeatManager(_safe_heartbeat_job(), interval=10)
    heartbeat.start()

    try:
        supabase = get_supabase_client()
        analyzer = get_worker_analyzer()

        print(f"\n[AGGREGATOR] Cross-token ranking for {len(tokens)} tokens "
              f"(min_runner_hits={min_runner_hits})…")

        all_token_results = []
        for sub_job_id, token in zip(sub_job_ids, tokens):
            wallets = _load_result(f"ranked_wallets:{sub_job_id}")
            if wallets:
                all_token_results.append({'token': token, 'wallets': wallets})

        print(f"  ✓ Loaded {len(all_token_results)}/{len(tokens)} token results")

        launch_prices = {}
        ath_prices    = {}
        ath_mcaps     = {}
        for token_result in all_token_results:
            addr = token_result['token']['address']
            try:
                launch_prices[addr] = analyzer._get_token_launch_price(addr) or 0
            except Exception as e:
                print(f"  ⚠️ Launch price fetch failed for {addr[:8]}: {e}")
                launch_prices[addr] = 0
            try:
                ath_data         = analyzer.get_token_ath(addr)
                ath_prices[addr] = ath_data.get('highest_price', 0)      if ath_data else 0
                ath_mcaps[addr]  = ath_data.get('highest_market_cap', 0) if ath_data else 0
            except Exception as e:
                print(f"  ⚠️ ATH fetch failed for {addr[:8]}: {e}")
                ath_prices[addr] = 0
                ath_mcaps[addr]  = 0

        wallet_hits = defaultdict(lambda: {
            'wallet':               None,
            'runners_hit':          [],
            'runners_hit_addresses': set(),
            'roi_details':          [],
            'entry_to_ath_vals':    [],
            'distance_to_ath_vals': [],
            'total_roi_multipliers': [],
            'entry_ratios':         [],
            'raw_wallet_data_list': [],
            'total_invested_list':  [],
            'realized_list':        [],
            'unrealized_list':      [],
        })

        for token_result in all_token_results:
            token       = token_result['token']
            token_addr  = token['address']
            ath_price   = ath_prices.get(token_addr, 0)
            ath_mcap    = ath_mcaps.get(token_addr, 0)
            launch_price= launch_prices.get(token_addr, 0)

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

                wallet_hits[addr]['total_invested_list'].append(
                    wallet_info.get('total_invested', 0)
                )
                wallet_hits[addr]['realized_list'].append(
                    wallet_info.get('realized', 0)
                )
                wallet_hits[addr]['unrealized_list'].append(
                    wallet_info.get('unrealized', 0)
                )

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

                entry_mcap = None
                if entry_price and ath_price and ath_price > 0 and ath_mcap:
                    entry_mcap = round((entry_price / ath_price) * ath_mcap, 0)

                wallet_hits[addr]['roi_details'].append({
                    'runner':                   sym,
                    'runner_address':           token_addr,
                    'roi_multiplier':           wallet_info.get('realized_multiplier', 0),
                    'total_multiplier':         wallet_info.get('total_multiplier', 0),
                    'entry_to_ath_multiplier':  round(entry_to_ath_mult, 2) if entry_to_ath_mult else None,
                    'distance_to_ath_pct':      round(distance_to_ath_pct, 2) if distance_to_ath_pct else None,
                    'entry_price':              entry_price,
                    'ath_market_cap':           ath_mcap,
                    'entry_market_cap':         entry_mcap,
                })

        cross_token_candidates  = []
        single_token_candidates = []

        for addr, d in wallet_hits.items():
            runner_count = len(d['runners_hit'])

            avg_dist = (sum(d['distance_to_ath_vals']) / len(d['distance_to_ath_vals'])
                        if d['distance_to_ath_vals'] else 0)
            avg_total_roi = (sum(d['total_roi_multipliers']) / len(d['total_roi_multipliers'])
                             if d['total_roi_multipliers'] else 0)
            avg_entry_to_ath = (sum(d['entry_to_ath_vals']) / len(d['entry_to_ath_vals'])
                                if d['entry_to_ath_vals'] else None)

            total_invested_sum   = sum(d['total_invested_list'])
            total_realized_sum   = sum(d['realized_list'])
            total_unrealized_sum = sum(d['unrealized_list'])
            avg_invested = (total_invested_sum / len(d['total_invested_list'])
                            if d['total_invested_list'] else 0)
            avg_realized = (total_realized_sum / len(d['realized_list'])
                            if d['realized_list'] else 0)

            if len(d['entry_ratios']) >= 2:
                try:
                    variance          = statistics.variance(d['entry_ratios'])
                    consistency_score = max(0, 100 - (variance * 10))
                except Exception:
                    consistency_score = 50
            else:
                consistency_score = 50

            if runner_count >= min_runner_hits:
                entry_score    = _roi_to_score(avg_entry_to_ath) if avg_entry_to_ath else 0
                roi_score      = _roi_to_score(avg_total_roi)
                aggregate_score= 0.60 * entry_score + 0.30 * roi_score + 0.10 * consistency_score
                participation  = runner_count / len(tokens) if tokens else 0

                if   participation >= 0.8 and aggregate_score >= 85: tier = 'S'
                elif participation >= 0.6 and aggregate_score >= 75: tier = 'A'
                elif participation >= 0.4 and aggregate_score >= 65: tier = 'B'
                else:                                                 tier = 'C'

                cross_token_candidates.append({
                    'wallet':                      addr,
                    'is_cross_token':              True,
                    'runner_count':                runner_count,
                    'runners_hit':                 d['runners_hit'],
                    'analyzed_tokens':             d['runners_hit'],
                    'avg_distance_to_ath_pct':     round(avg_dist, 2),
                    'avg_entry_to_ath_multiplier': round(avg_entry_to_ath, 2) if avg_entry_to_ath else None,
                    'avg_total_roi':               round(avg_total_roi, 2),
                    'consistency_score':           round(consistency_score, 2),
                    'aggregate_score':             round(aggregate_score, 2),
                    'tier':                        tier,
                    'professional_grade':          _calculate_grade(aggregate_score),
                    'roi_details':                 d['roi_details'][:5],
                    'is_fresh':                    True,
                    'runner_hits_30d':             0,
                    'runner_hits_7d':              0,
                    'runner_success_rate':         0,
                    'runner_avg_roi':              0,
                    'other_runners':               [],
                    'other_runners_stats':         {},
                    'runners_7d':                  [],
                    'runners_14d':                 [],
                    'runners_30d':                 [],
                    'stats_7d':                    {},
                    'stats_14d':                   {},
                    'stats_30d':                   {},
                    'total_invested':              round(total_invested_sum, 2),
                    'total_invested_sum':          round(total_invested_sum, 2),
                    'total_realized_sum':          round(total_realized_sum, 2),
                    'avg_invested':                round(avg_invested, 2),
                    'avg_realized':                round(avg_realized, 2),
                    'score_breakdown': {
                        'entry_score':       round(0.60 * entry_score, 2),
                        'total_roi_score':   round(0.30 * roi_score, 2),
                        'consistency_score': round(0.10 * consistency_score, 2),
                    },
                })

            else:
                best_raw = max(d['raw_wallet_data_list'],
                               key=lambda x: x['wallet_info'].get('total_multiplier', 0))
                wi       = best_raw['wallet_info']
                ath_price_best = best_raw['ath_price']
                ath_mcap_best  = best_raw['ath_mcap']

                wallet_info_for_scoring = {**wi, 'ath_price': ath_price_best}
                scoring = analyzer.calculate_wallet_relative_score(wallet_info_for_scoring)

                if   scoring['professional_score'] >= 90: tier = 'S'
                elif scoring['professional_score'] >= 80: tier = 'A'
                elif scoring['professional_score'] >= 70: tier = 'B'
                else:                                     tier = 'C'

                entry_price = wi.get('entry_price')
                entry_mcap  = None
                if entry_price and ath_price_best and ath_price_best > 0 and ath_mcap_best:
                    entry_mcap = round((entry_price / ath_price_best) * ath_mcap_best, 0)

                realized_mult = wi.get('realized_multiplier', 1)

                single_token_candidates.append({
                    'wallet':                  addr,
                    'is_cross_token':          False,
                    'runner_count':            runner_count,
                    'runners_hit':             d['runners_hit'],
                    'analyzed_tokens':         d['runners_hit'],
                    'source':                  wi.get('source', 'unknown'),
                    'realized_profit':         wi.get('realized', 0),
                    'unrealized_profit':       wi.get('unrealized', 0),
                    'total_invested':          wi.get('total_invested', 0),
                    'realized_multiplier':     scoring.get('realized_multiplier', realized_mult),
                    'total_multiplier':        scoring.get('total_multiplier', wi.get('total_multiplier', 0)),
                    'roi_percent':             round((realized_mult - 1) * 100, 2),
                    'professional_score':      scoring['professional_score'],
                    'professional_grade':      scoring['professional_grade'],
                    'tier':                    tier,
                    'entry_to_ath_multiplier': scoring.get('entry_to_ath_multiplier'),
                    'distance_to_ath_pct':     scoring.get('distance_to_ath_pct'),
                    'avg_distance_to_ath_pct': round(avg_dist, 2),
                    'avg_total_roi':           round(avg_total_roi, 2),
                    'entry_price':             entry_price,
                    'ath_price':               ath_price_best,
                    'ath_market_cap':          ath_mcap_best,
                    'entry_market_cap':        entry_mcap,
                    'first_buy_time':          wi.get('earliest_entry'),
                    'roi_details':             d['roi_details'][:5],
                    'score_breakdown':         scoring['score_breakdown'],
                    'is_fresh':                True,
                    'runner_hits_30d':         0,
                    'runner_hits_7d':          0,
                    'runner_success_rate':     0,
                    'runner_avg_roi':          0,
                    'other_runners':           [],
                    'other_runners_stats':     {},
                    'runners_7d':              [],
                    'runners_14d':             [],
                    'runners_30d':             [],
                    'stats_7d':                {},
                    'stats_14d':               {},
                    'stats_30d':               {},
                })

        cross_token_candidates.sort(key=lambda x: (x['runner_count'], x['aggregate_score']),
                                    reverse=True)
        single_token_candidates.sort(key=lambda x: x['professional_score'], reverse=True)

        cross_top      = cross_token_candidates[:20]
        slots_remaining= max(0, 20 - len(cross_top))
        single_fill    = single_token_candidates[:slots_remaining]
        top_20         = cross_top + single_fill

        print(f"  ✓ Cross-token: {len(cross_top)} | Single-token fill: {len(single_fill)} | "
              f"Top 20 total: {len(top_20)}")

        _, q_batch, q_compute = _get_queues()
        runner_jobs = []
        chunk_size  = 5
        for i in range(0, len(top_20), chunk_size):
            chunk     = top_20[i:i + chunk_size]
            batch_idx = i // chunk_size
            rh_job    = q_batch.enqueue(
                'services.worker_tasks.fetch_runner_history_batch',
                {'token': tokens[0] if tokens else {}, 'job_id': job_id,
                 'batch_idx': batch_idx, 'wallets': [w['wallet'] for w in chunk]},
                job_timeout=JT_RUNNER_BATCH,
                retry=RQRetry(max=3, interval=[10, 30, 60]),
                failure_ttl=86400,
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
            job_timeout=JT_MERGE_FINAL,
            retry=RQRetry(max=3, interval=[10, 30, 60]),
            failure_ttl=86400,
        )
        print(f"  ✓ {len(runner_jobs)} runner history workers → merge_batch_final")
        return {'top_20_count': len(top_20), 'runner_jobs': len(runner_jobs)}
    finally:
        heartbeat.stop()

# =============================================================================
# BATCH FINAL MERGE
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

    heartbeat = HeartbeatManager(_safe_heartbeat_job())
    heartbeat.start()

    try:
        supabase = get_supabase_client()
        print(f"\n[BATCH FINAL] Attaching runner history for {len(top_20)} wallets…")

        runner_lookup = {}
        for i in range(runner_batch_count):
            batch = _load_result(f"runner_batch:{job_id}:{i}") or []
            for entry in batch:
                runner_lookup[entry['wallet']] = entry

        _merge_runner_history_into_wallets(top_20, runner_lookup)

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

        for attempt in range(3):
            try:
                supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                    'status': 'completed', 'phase': 'done', 'progress': 100,
                    'results': final_result,
                }).eq('job_id', job_id).execute()
                print(f"  ✅ Saved final batch result for job {job_id[:8]}")
                tokens_list  = final_result.get('tokens_analyzed_list', [])
                wallets_list = final_result.get('wallets', [])
                label        = ', '.join(tokens_list) if tokens_list else 'Batch Analysis'
                sublabel     = f"{len(wallets_list)} smart money wallets across {len(tokens_list)} tokens"
                try:
                    supabase.schema(SCHEMA_NAME).table('user_analysis_history').insert({
                        'user_id':     user_id,
                        'result_type': 'batch',
                        'label':       label,
                        'sublabel':    sublabel,
                        'data':        final_result,
                    }).execute()
                    print(f"  ✅ Saved to user_analysis_history for {user_id[:8]}")
                except Exception as he:
                    print(f"  ⚠️ Failed to save history entry: {he}")
                break
            except Exception as e:
                if attempt < 2:
                    wait = 5 * (attempt + 1)
                    print(f"  ⚠️ Save attempt {attempt+1}/3 failed: {e} — retrying in {wait}s")
                    time.sleep(wait)
                else:
                    r = _get_redis()
                    r.set(f"UNSAVED_RESULT:{job_id}", json.dumps(final_result), ex=PIPELINE_TTL)
                    print(f"  ❌ All save attempts failed — preserved in Redis as UNSAVED_RESULT:{job_id}")

        print(f"  ✅ Batch complete: {len(top_20)} wallets "
              f"({cross_token_count} cross-token + {single_token_count} single-token fill)")
        return final_result
    finally:
        heartbeat.stop()

# =============================================================================
# CACHE WARMUP
# =============================================================================

def preload_trending_cache():
    _, q_batch, _ = _get_queues()
    job7  = q_batch.enqueue('services.worker_tasks.warm_cache_runners',
                            {'days_back': 7},  job_timeout=JT_WARMUP)
    job14 = q_batch.enqueue('services.worker_tasks.warm_cache_runners',
                            {'days_back': 14}, job_timeout=JT_WARMUP)
    print(f"[CACHE WARMUP] Queued 7d ({job7.id[:8]}) and 14d ({job14.id[:8]}) warmup "
          f"(job_timeout={JT_WARMUP}s each)")
    return [job7.id, job14.id]


def warm_cache_runners(data):
    from routes.wallets import get_worker_analyzer
    days_back = data['days_back']
    heartbeat = HeartbeatManager(_safe_heartbeat_job(), interval=15)
    heartbeat.start()

    try:
        print(f"[WARMUP {days_back}D] Finding runners…")
        analyzer = get_worker_analyzer()
        runners  = analyzer.find_trending_runners_enhanced(
            days_back=days_back, min_multiplier=5.0, min_liquidity=50000
        )
        print(f"  ✅ Cached {len(runners)} runners for {days_back}d in Redis")
        return len(runners)
    except Exception as e:
        print(f"[WARMUP {days_back}D] ERROR: {e}")
        traceback.print_exc()
        return 0
    finally:
        heartbeat.stop()

# =============================================================================
# MANUAL DEBUGGING UTILITY
# =============================================================================

def dump_job_logs(job_id, verbose=False):
    r = _get_redis()

    def _get(key):
        raw = r.get(key)
        return json.loads(raw) if raw else None

    def _ttl(key):
        t = r.ttl(key)
        if t == -2: return "MISSING (expired or never written)"
        if t == -1: return "NO EXPIRY ⚠️"
        m, s = divmod(t, 60)
        h, m = divmod(m, 60)
        return f"{h}h {m}m {s}s remaining"

    SEP = "=" * 70
    print(f"\n{SEP}")
    print(f"JOB LOG REPORT: {job_id}")
    print(SEP)

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

    fetch_summary = _get(f"log:job_fetch_summary:{job_id}")
    print(f"\n{'─'*50}")
    print("FETCH SUMMARY")
    print(f"  key TTL: {_ttl(f'log:job_fetch_summary:{job_id}')}")
    if fetch_summary:
        for row in fetch_summary:
            pct  = row.get('success_rate_pct', 0)
            icon = "✓" if pct >= 70 else ("⚠️" if pct >= 40 else "❌")
            print(f"  {icon} [{row.get('batch_type')} batch {row.get('batch_idx')}] "
                  f"{row.get('prices_found')}/{row.get('total_wallets')} found ({pct}% success)")
            if verbose and row.get('failure_counts'):
                for cause, cnt in row.get('failure_counts', {}).items():
                    print(f"       {cause}: {cnt}")
    else:
        print("  No fetch summary found (or expired)")

    batch_info = _get(f"pnl_batch_info:{job_id}")
    print(f"\n{'─'*50}")
    print("PNL BATCH SUMMARIES")
    print(f"  pnl_batch_info TTL: {_ttl(f'pnl_batch_info:{job_id}')}")

    abandoned_batches = []
    if batch_info:
        batch_count    = batch_info.get('batch_count', 0)
        pnl_job_ids    = batch_info.get('pnl_job_ids', [])
        pre_qual_count = batch_info.get('pre_qualified_count', 0)
        print(f"  pre_qualified: {pre_qual_count} | pnl batches: {batch_count}")

        for i in range(batch_count):
            summary    = _get(f"debug_pnl_summary:{job_id}:{i}")
            result_ttl = _ttl(f"job_result:pnl_batch:{job_id}:{i}")
            rq_job_id  = pnl_job_ids[i] if i < len(pnl_job_ids) else "unknown"

            if summary:
                icon = "✓" if summary.get('qualified', 0) > 0 else "·"
                print(f"  {icon} Batch {i}: {summary.get('qualified', 0)} qualified, "
                      f"{summary.get('failed', 0)} failed "
                      f"| rq_job={rq_job_id[:8] if rq_job_id != 'unknown' else 'unknown'}")
                if verbose and summary.get('failure_breakdown'):
                    for cause, cnt in summary.get('failure_breakdown', {}).items():
                        print(f"       {cause}: {cnt}")
            else:
                batch_result = _get(f"pnl_batch:{job_id}:{i}")
                if batch_result is None:
                    abandoned_batches.append({'batch_idx': i, 'rq_job_id': rq_job_id,
                                              'result_ttl': result_ttl})
                    print(f"  ❌ Batch {i}: ABANDONED — no summary and no result key "
                          f"| rq_job={rq_job_id[:8] if rq_job_id != 'unknown' else 'unknown'} "
                          f"| failure_cause=abandoned_job")
                else:
                    print(f"  ? Batch {i}: result exists but no summary (unusual) "
                          f"| {len(batch_result)} wallets")
    else:
        print("  No pnl_batch_info found (job may not have reached PnL phase, or key expired)")

    if abandoned_batches:
        print(f"\n{'─'*50}")
        print(f"⚠️  ABANDONED JOBS DETECTED ({len(abandoned_batches)} batches)")
        for ab in abandoned_batches:
            print(f"  - Batch {ab['batch_idx']} | "
                  f"rq_job={ab['rq_job_id'][:8] if ab['rq_job_id'] != 'unknown' else 'unknown'}")

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

    qualified_log = _get(f"log:qualified_wallets:{job_id}")
    print(f"\n{'─'*50}")
    print(f"QUALIFIED WALLETS ({len(qualified_log) if qualified_log else 0})")
    print(f"  key TTL: {_ttl(f'log:qualified_wallets:{job_id}')}")
    if qualified_log:
        for w in qualified_log:
            roi     = w.get('total_roi')
            roi_str = f"{roi:.2f}x" if roi else "N/A"
            inv     = w.get('invested_usd')
            inv_str = f"${inv:,.0f}" if inv else "N/A"
            pnl     = w.get('realized_pnl')
            pnl_str = f"${pnl:,.0f}" if pnl else "N/A"
            print(f"  ✓ {w.get('wallet')} | src={w.get('source')} "
                  f"| roi={roi_str} | inv={inv_str} | pnl={pnl_str}")
    else:
        print("  No qualified wallet log found (or expired)")

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

    dead_letter = r.lrange("dead_letter:batch", 0, 4)
    if dead_letter:
        print(f"\n{'─'*50}")
        print("DEAD LETTER QUEUE (recent batch failures)")
        for dl in dead_letter:
            dldata = json.loads(dl)
            print(f"  {dldata['job_id'][:8]}: {dldata['function']} - {dldata['error'][:100]}")

    print(f"\n{'─'*50}")
    print("KEY TTL OVERVIEW")
    for key in [
        f"log:phase1_failures:{job_id}",
        f"log:job_fetch_summary:{job_id}",
        f"log:qualified_wallets:{job_id}",
        f"log:job_final_summary:{job_id}",
        f"pnl_batch_info:{job_id}",
    ]:
        print(f"  {':'.join(key.split(':')[:2])}: {_ttl(key)}")

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