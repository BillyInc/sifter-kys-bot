# RQ-to-Celery Migration Plan

**Status:** Completed
**Date:** 2026-03-29
**Goal:** Eliminate RQ dependency and consolidate all background work onto Celery.

---

## 1. Current State

The backend runs **two** independent job queue systems against the same Redis instance:

| System | Purpose | Workers | Queues |
|--------|---------|---------|--------|
| **RQ** | On-demand wallet analysis (user-triggered) | `rq-worker@{1..5}` (systemd template) | `high`, `batch`, `compute` |
| **Celery** | Scheduled/periodic tasks | `celery-worker` + `celery-beat` (systemd) | `default`, `stats`, `rankings`, `discovery` |

Both use Redis DB 0 (`redis://localhost:6379/0`), creating connection contention and two separate monitoring surfaces.

---

## 2. Inventory of RQ Tasks

All RQ tasks live in `services/worker_tasks.py`. They are invoked as dotted-string references via `queue.enqueue('services.worker_tasks.<func>', ...)`.

### 2.1 Entry-Point Tasks (enqueued from `routes/wallets.py`)

| # | Function | Enqueued from | Current RQ Queue | Timeout |
|---|----------|---------------|------------------|---------|
| 1 | `perform_wallet_analysis` | `POST /api/wallets/analyze` | `high` or `batch` (tier-dependent) | 120s-600s |
| 2 | `perform_trending_batch_analysis` | `POST /api/wallets/trending-batch` | `batch` | 600s |
| 3 | `perform_auto_discovery` | `POST /api/wallets/auto-discovery` | `compute` | 600s |

### 2.2 Pipeline Sub-Tasks (enqueued internally by worker_tasks.py)

These are chained within the 3-phase analysis pipeline. Many use `Dependency(jobs=[...], allow_failure=True)` for fan-out/fan-in patterns.

| # | Function | Current RQ Queue | Timeout Constant | Notes |
|---|----------|------------------|------------------|-------|
| 4 | `fetch_top_traders` | `high` | `JT_PHASE1_WORKER` (120s) | Phase 1 -- parallelized with fetch_first_buyers |
| 5 | `fetch_first_buyers` | `high` | `JT_PHASE1_WORKER` (120s) | Phase 1 -- parallelized with fetch_top_traders |
| 6 | `coordinate_pnl_phase` | `compute` | `JT_COORD` (180s) | Depends on Phase 1 jobs completing |
| 7 | `fetch_pnl_batch` | `batch` | `JT_PNL_BATCH` (600s) | Phase 2 -- multiple batches per token |
| 8 | `score_and_rank_single` | `compute` | `JT_SCORER` (600s) | Depends on PnL batches completing |
| 9 | `fetch_from_token_cache` | `compute` | `JT_CACHE_PATH` (120s) | Fast path for cached tokens |
| 10 | `fetch_runner_history_batch` | `batch` | `JT_RUNNER_BATCH` (180s) | Chunked runner history fetches |
| 11 | `merge_and_save_final` | `compute` | `JT_MERGE_FINAL` (180s) | Depends on runner history batches |
| 12 | `aggregate_cross_token` | `compute` | `JT_AGGREGATE` (600s) | Cross-token aggregation for batch jobs |
| 13 | `merge_batch_final` | `compute` | `JT_MERGE_FINAL` (180s) | Final merge for batch/discovery |
| 14 | `warm_cache_runners` | `batch` | `JT_WARMUP` (900s) | Cache warmup (also called by preload_trending_cache) |
| 15 | `preload_trending_cache` | `batch` | -- | Helper that enqueues warm_cache_runners x2 |

**Total: 15 RQ task functions** (3 entry points + 12 pipeline/internal tasks)

### 2.3 Existing Celery Tasks

Located in `services/tasks.py` and `tasks/` directory.

| # | Task name | File | Schedule |
|---|-----------|------|----------|
| 1 | `tasks.daily_stats_refresh` | `services/tasks.py` | Daily 3am UTC |
| 2 | `tasks.weekly_rerank_all` | `services/tasks.py` | Sunday 4am UTC |
| 3 | `tasks.four_week_degradation_check` | `services/tasks.py` | 1st & 29th of month |
| 4 | `tasks.warm_trending_cache` | `services/tasks.py` | Every 10 min |
| 5 | `tasks.refresh_elite_100` | `services/tasks.py` | Hourly :00 |
| 6 | `tasks.refresh_community_top_100` | `services/tasks.py` | Hourly :15 |
| 7 | `tasks.flush_redis_to_duckdb` | `services/tasks.py` | Hourly :30 |
| 8 | `tasks.invalidate_stale_ath_caches` | `services/tasks.py` | Hourly :45 |
| 9 | `tasks.purge_stale_analysis_cache` | `services/tasks.py` | (routed, no beat entry) |
| 10 | `tasks.send_telegram_alert_async` | `services/tasks.py` | On-demand |
| 11 | `tasks.purge_old_notifications` | `services/tasks.py` | Daily 2:30am UTC |
| 12 | `tasks.discover_new_tokens` | `tasks/token_discovery.py` | Every 5 min |
| 13 | `tasks.wallet_qualification_scan` | `tasks/wallet_qualification.py` | On-demand |
| 14 | `tasks.second_pass_patch` | `tasks/wallet_qualification.py` | On-demand |

**Total: 14 Celery tasks**

---

## 3. Proposed Celery Queue Mapping

Merge RQ's 3 queues into Celery's existing queue structure, adding one new queue for the on-demand analysis pipeline:

| New Celery Queue | Replaces | Tasks |
|------------------|----------|-------|
| `analysis` (NEW) | RQ `high` | `perform_wallet_analysis`, `fetch_top_traders`, `fetch_first_buyers`, `score_and_rank_single` |
| `analysis_batch` (NEW) | RQ `batch` | `perform_trending_batch_analysis`, `fetch_pnl_batch`, `fetch_runner_history_batch`, `warm_cache_runners` |
| `analysis_compute` (NEW) | RQ `compute` | `perform_auto_discovery`, `coordinate_pnl_phase`, `fetch_from_token_cache`, `merge_and_save_final`, `aggregate_cross_token`, `merge_batch_final` |
| `discovery` | (unchanged) | `discover_new_tokens`, `wallet_qualification_scan`, `second_pass_patch` |
| `stats` | (unchanged) | `daily_stats_refresh`, `weekly_rerank_all`, `flush_redis_to_duckdb`, etc. |
| `rankings` | (unchanged) | `refresh_elite_100`, `refresh_community_top_100` |

### Priority Handling

RQ uses `at_front=True` for premium users. Celery equivalent: use `task.apply_async(priority=N)` with a priority-enabled broker transport option (`broker_transport_options = {'priority_steps': list(range(10))}`) or separate high-priority queues (`analysis_priority`). Recommendation: use separate `analysis_priority` queue consumed first by workers, since Redis broker priority support is limited.

---

## 4. Code Changes Required

### 4.1 Convert `services/worker_tasks.py` to Celery Tasks

**Before (RQ pattern):**
```python
from rq import Queue
from rq.job import Job, Dependency
from rq import Retry as RQRetry

def perform_wallet_analysis(data):
    ...
    q_high.enqueue('services.worker_tasks.fetch_top_traders', {...},
                   job_timeout=JT_PHASE1_WORKER,
                   retry=RQRetry(max=3, interval=[10, 30, 60]))
```

**After (Celery pattern):**
```python
from celery import shared_task, chord, chain, group
from celery_app import celery

@celery.task(name='worker.perform_wallet_analysis', bind=True,
             time_limit=600, soft_time_limit=540)
def perform_wallet_analysis(self, data):
    ...
    fetch_top_traders.apply_async(args=[{...}],
                                  queue='analysis',
                                  retry=True,
                                  retry_policy={'max_retries': 3, 'interval_start': 10})
```

Key conversion patterns:
- `q.enqueue(func_string, data, job_timeout=N)` becomes `task.apply_async(args=[data], queue='...', time_limit=N)`
- `Dependency(jobs=[j1, j2], allow_failure=True)` becomes `chord([task1.s(...), task2.s(...)], allow_error=True)(callback.s(...))`
- `RQRetry(max=3, interval=[10, 30, 60])` becomes `retry_policy={'max_retries': 3, 'interval_start': 10, 'interval_step': 20}`
- `HeartbeatManager` can be removed -- Celery tracks task state natively
- `@timeout` decorator (SIGALRM-based) replaced by Celery's `soft_time_limit` / `time_limit`

### 4.2 Changes to `routes/wallets.py`

**Remove:**
- `get_queues()` function (lines 82-91)
- `_get_job_queue()` function (lines 94-122) -- replace with Celery queue selection logic
- All `from rq import Queue` imports
- `queue.fetch_job(job_id)` in cancel endpoint

**Replace enqueue calls (4 locations):**

1. **`analyze_wallets` route (line 181):**
   ```python
   # Before
   queue.enqueue('services.worker_tasks.perform_wallet_analysis', {...}, job_timeout=timeout, at_front=at_front)

   # After
   from services.worker_tasks import perform_wallet_analysis
   perform_wallet_analysis.apply_async(
       args=[{...}],
       queue=_get_celery_queue(user_id, job_type),
       priority=0 if tier in ('pro', 'elite') else 5,
   )
   ```

2. **`analyze_runner` route (line 692):** Same pattern as above.

3. **`trending_batch_analysis` route (line 733):**
   ```python
   perform_trending_batch_analysis.apply_async(args=[{...}], queue='analysis_batch')
   ```

4. **`auto_discovery` route (line 778):**
   ```python
   perform_auto_discovery.apply_async(args=[{...}], queue='analysis_compute')
   ```

**Replace cancel logic (line 289-300):**
```python
# Before: iterate RQ queues and fetch_job
# After:
from celery_app import celery
celery.control.revoke(job_id, terminate=True)
```

### 4.3 Changes to `celery_app.py`

- Add `'services.worker_tasks'` to the `include` list
- Add new queues to `task_routes`
- Add `broker_transport_options` for priority support (optional)

### 4.4 Changes to `services/worker_tasks.py`

This is the largest change. Every function needs:

1. **Remove all RQ imports** (`Queue`, `Job`, `Dependency`, `RQRetry`)
2. **Add `@celery.task` decorator** to each task function
3. **Replace `_get_queues()` + `q.enqueue()`** with `task.apply_async()` or Celery primitives
4. **Replace `Dependency` fan-out/fan-in** with `chord` or `group`:
   ```python
   # Before (RQ)
   job1 = q_high.enqueue('fetch_top_traders', {...})
   job2 = q_high.enqueue('fetch_first_buyers', {...})
   q_compute.enqueue('coordinate_pnl_phase', {...},
                     depends_on=Dependency(jobs=[job1, job2], allow_failure=True))

   # After (Celery)
   chord(
       group(fetch_top_traders.s({...}), fetch_first_buyers.s({...})),
       coordinate_pnl_phase.s({...})
   ).apply_async()
   ```
5. **Remove `HeartbeatManager`** -- Celery's `task_track_started=True` (already set) handles this
6. **Remove `@timeout` decorator** -- use `soft_time_limit` on the task decorator instead
7. **Remove `APICircuitBreaker`** -- can be kept as-is (it is independent of RQ)

### 4.5 Dependency Changes (`pyproject.toml`)

Remove from dependencies:
```
"rq>=1.16.0,<2.0.0"
```

---

## 5. Job Result Polling

### Current Approach (RQ)

RQ stores results in Redis automatically. However, the codebase does **not** rely on RQ's native result backend. Instead:

1. **Supabase `analysis_jobs` table** is the primary status/result store. Worker tasks write progress updates (`status`, `phase`, `progress`, `results`) directly.
2. **Redis `job_result:{key}` keys** are used as an intermediate result cache between pipeline stages (e.g., `_save_result()` / `_load_result()` in `worker_tasks.py`).
3. The **`/api/wallets/jobs/<job_id>`** endpoint reads from `analysis_jobs` in Supabase, not from RQ.

### Migration Impact: MINIMAL

Since result polling already goes through Supabase (not RQ's result backend), **no changes are needed for the polling endpoints**. The `_save_result()` / `_load_result()` helpers write to Redis with `job_result:` prefix -- these are independent of RQ and will continue to work.

The only RQ-specific result code is in the **cancel endpoint** (`queue.fetch_job(job_id)`) and the **recovery endpoint** which checks RQ job status as a fallback. Replace with:
- Cancel: `celery.control.revoke(job_id, terminate=True)` + update Supabase
- Recovery: Remove RQ fallback, rely solely on Supabase `analysis_jobs` status

---

## 6. Systemd Service Changes

### Remove

| Service | File |
|---------|------|
| `rq-worker@.service` | `Backend/systemd/rq-worker@.service` |

```bash
sudo systemctl stop rq-worker@{1..5}
sudo systemctl disable rq-worker@{1..5}
sudo rm /etc/systemd/system/rq-worker@.service
```

### Modify

**`celery-worker.service`** -- add the new analysis queues and increase concurrency:

```ini
# Before
ExecStart=... celery -A celery_app worker --loglevel=info -Q default,stats,rankings,discovery --concurrency=2

# After
ExecStart=... celery -A celery_app worker --loglevel=info \
  -Q default,stats,rankings,discovery,analysis,analysis_batch,analysis_compute \
  --concurrency=4
```

Consider splitting into two worker services for isolation:

| Service | Queues | Concurrency | Purpose |
|---------|--------|-------------|---------|
| `celery-worker-scheduled.service` | `default,stats,rankings,discovery` | 2 | Periodic/scheduled tasks |
| `celery-worker-analysis.service` | `analysis,analysis_batch,analysis_compute` | 4-8 | On-demand user analysis |

This preserves the operational isolation that separate RQ workers previously provided.

### Keep Unchanged

- `celery-beat.service` -- no changes needed
- `sifter-backend.service` -- no changes needed
- `wallet-monitor.service` -- no changes needed

### Update `Backend/systemd/README.md`

Remove all references to `rq-worker@` and document the new celery worker services.

---

## 7. Migration Sequence

### Phase 1: Dual-Write (1-2 days)

1. Convert all RQ task functions to Celery tasks (add `@celery.task` decorators)
2. Keep RQ enqueue calls working alongside Celery (both can coexist)
3. Deploy Celery workers consuming the new queues
4. Verify Celery workers pick up tasks correctly in staging

### Phase 2: Switch Traffic (1 day)

1. Update `routes/wallets.py` to use `.apply_async()` instead of `q.enqueue()`
2. Update internal pipeline chaining in `worker_tasks.py`
3. Deploy to production
4. Keep RQ workers running (idle) as hot standby

### Phase 3: Cleanup (1 day)

1. Stop and disable RQ workers
2. Remove `rq` from `pyproject.toml`
3. Remove RQ-specific code (`get_queues()`, `_get_queues()`, `HeartbeatManager`, `@timeout` decorator, `_handle_failed_job`, `_worker_handle_exception`)
4. Delete `rq-worker@.service`
5. Update documentation

---

## 8. Risk Assessment

### High Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Celery chord/group error handling differs from RQ Dependency** | Pipeline stages may not fire if upstream tasks fail | RQ uses `allow_failure=True`; Celery chord equivalent is `chord(..., allow_error=True)` (Celery 5.3+). Test thoroughly with intentional failures. |
| **Job timeout behavior change** | RQ kills the worker process on timeout; Celery raises `SoftTimeLimitExceeded` | Wrap long tasks in try/except for `SoftTimeLimitExceeded` and ensure cleanup runs. Set `time_limit` (hard kill) slightly above `soft_time_limit`. |
| **`asyncio.run()` inside Celery worker** | Several RQ tasks use `asyncio.run()` internally. Celery's prefork pool creates its own event loop context. | Test that `asyncio.run()` works in Celery prefork workers. If issues arise, switch to `--pool=solo` or `--pool=gevent` for analysis workers. |

### Medium Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Redis memory spike during migration** | Both RQ and Celery metadata in Redis simultaneously | Monitor Redis memory during Phase 1-2. Clean up RQ keys after Phase 3. |
| **Loss of `at_front` priority** | Premium users may not get faster processing | Use separate `analysis_priority` queue or Celery priority levels. Verify latency SLAs post-migration. |
| **Celery worker prefetch interferes with long tasks** | A prefetched task blocks behind a 10-min analysis | Already mitigated: `worker_prefetch_multiplier=1` is set in `celery_app.py`. |

### Low Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Result polling breaks** | Users see stale job status | Low risk because polling reads from Supabase, not RQ. No change needed. |
| **DuckDB concurrent access** | RQ workers used `read_only=True` DuckDB; Celery workers need the same | Ensure `get_worker_analyzer()` is still called with `read_only=True` in Celery context. |

---

## 9. Rollback Plan

### During Phase 1 (Dual-Write)
- No rollback needed. Both systems coexist. Remove Celery task decorators if issues arise.

### During Phase 2 (Traffic Switched)
1. Revert `routes/wallets.py` and `services/worker_tasks.py` to use RQ enqueue calls
2. Restart RQ workers: `sudo systemctl start rq-worker@{1..5}`
3. Estimated rollback time: **< 5 minutes** (git revert + service restart)

### After Phase 3 (RQ Removed)
- Revert the cleanup commit. Re-add `rq` to `pyproject.toml`, restore `rq-worker@.service`.
- Estimated rollback time: **< 15 minutes**

### Rollback Trigger Criteria
- Job completion rate drops below 90%
- Median analysis latency increases by more than 50%
- Any user-facing 500 errors on `/api/wallets/analyze`

---

## 10. Files Modified (Summary)

| File | Action |
|------|--------|
| `services/worker_tasks.py` | Major rewrite: add `@celery.task` decorators, replace `q.enqueue()` with Celery primitives, remove RQ imports/helpers |
| `routes/wallets.py` | Replace `get_queues()`, `_get_job_queue()`, all `queue.enqueue()` calls, cancel logic |
| `celery_app.py` | Add `services.worker_tasks` to `include`, add new queue routes |
| `pyproject.toml` | Remove `rq>=1.16.0,<2.0.0` |
| `systemd/rq-worker@.service` | Delete |
| `systemd/celery-worker.service` | Add new queues, increase concurrency (or split into two services) |
| `systemd/README.md` | Update documentation |
