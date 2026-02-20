"""
RQ Worker Tasks - Fixed with depends_on for true parallelism
No worker ever blocks waiting for child jobs.
RQ handles dependency resolution internally via Redis.

CACHE STRATEGY:
- Workers use get_worker_analyzer() → DuckDB read-only, writes to Redis only
- Flask uses get_wallet_analyzer()  → DuckDB read-write, writes to both
- Celery flushes Redis → DuckDB every hour via flush_redis_to_duckdb task

PHASE SUMMARY:
- Phase 1: All sources fetch in parallel.
    Worker 1 (fetch_top_traders):         PnL data, no entry price
    Worker 2 (fetch_first_buyers):        PnL data + first_buy math (price derivable, no API cost)
    Worker 3 (fetch_birdeye_trades):      entry_price from from.price, no PnL
                                          Uses launch-based 5-day window instead of rolling 30 days
    Worker 4 (coordinate_entry_prices):   Coordinator — spawns N batch workers after Worker 1
    Workers 4a..4n (fetch_entry_prices_batch): Parallel batches of ~20 wallets each
    Worker 4-merge (merge_entry_prices):  Merges all batch results, writes enriched top_traders back

- Phase 2: PnL fetching only.
    Top Traders:  PnL ✅ + entry_price ✅ (Worker 4) → skip API, go straight to qualify
    First Buyers: PnL ✅ + price derived from first_buy math → skip API, go straight to qualify
    Birdeye:      entry_price ✅ but PnL ❌ → fetch PnL only

- Phase 3: Score + rank (no runner history here).

- Phase 4: Runner history fetched in parallel workers of 5 wallets each,
           for top 20 wallets only. Final merge job saves result to Supabase.
"""
from redis import Redis
from rq import Queue
from rq.job import Job, Dependency
import json
import asyncio
import os
import time


def _get_redis():
    url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    return Redis.from_url(url)

def _get_queue():
    return Queue(connection=_get_redis(), default_timeout=1800)  # 30 min global default


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
    print(f"\n[PIPELINE] Queuing single token: {token.get('ticker')}")

    # Phase 1: Workers 1, 2, 3 start immediately in parallel
    job1 = q.enqueue('services.worker_tasks.fetch_top_traders',    {'token': token, 'job_id': job_id})
    job2 = q.enqueue('services.worker_tasks.fetch_first_buyers',   {'token': token, 'job_id': job_id})
    job3 = q.enqueue('services.worker_tasks.fetch_birdeye_trades', {'token': token, 'job_id': job_id})

    # Worker 4 coordinator: waits for Worker 1, then spawns N parallel price-fetch batches
    # coordinate_entry_prices itself queues batch workers + a merge job, then exits.
    # PnL coordinator depends on the MERGE job (stored in Redis), not just the coordinator.
    job4_coord = q.enqueue(
        'services.worker_tasks.coordinate_entry_prices',
        {'token': token, 'job_id': job_id},
        depends_on=Dependency(jobs=[job1])
    )

    print(f"  ✓ Queued Phase 1 jobs: {[j.id[:8] for j in [job1, job2, job3, job4_coord]]}")

    # PnL coordinator waits for Workers 2, 3, and the entry-price coordinator
    pnl_coordinator = q.enqueue(
        'services.worker_tasks.coordinate_pnl_phase',
        {
            'token':       token,
            'job_id':      job_id,
            'user_id':     user_id,
            'phase1_jobs': [job1.id, job2.id, job3.id, job4_coord.id]
        },
        depends_on=Dependency(jobs=[job1, job2, job3, job4_coord])
    )

    print(f"  ✓ Queued PnL coordinator: {pnl_coordinator.id[:8]}")

    r = _get_redis()
    r.set(f"pipeline:{job_id}:coordinator", pnl_coordinator.id, ex=3600)
    r.set(f"pipeline:{job_id}:token", json.dumps(token), ex=3600)

    print(f"  ✓ Pipeline queued for {token.get('ticker')} - {job_id[:8]}")


def _queue_batch_pipeline(q, tokens, user_id, job_id, supabase):
    print(f"\n[PIPELINE] Queuing batch: {len(tokens)} tokens")

    token_final_jobs = []

    for token in tokens:
        sub_job_id = f"{job_id}__{token['address'][:8]}"

        job1 = q.enqueue('services.worker_tasks.fetch_top_traders',    {'token': token, 'job_id': sub_job_id})
        job2 = q.enqueue('services.worker_tasks.fetch_first_buyers',   {'token': token, 'job_id': sub_job_id})
        job3 = q.enqueue('services.worker_tasks.fetch_birdeye_trades', {'token': token, 'job_id': sub_job_id})

        job4_coord = q.enqueue(
            'services.worker_tasks.coordinate_entry_prices',
            {'token': token, 'job_id': sub_job_id},
            depends_on=Dependency(jobs=[job1])
        )

        pnl_coordinator = q.enqueue(
            'services.worker_tasks.coordinate_pnl_phase',
            {
                'token':       token,
                'job_id':      sub_job_id,
                'user_id':     user_id,
                'phase1_jobs': [job1.id, job2.id, job3.id, job4_coord.id]
            },
            depends_on=Dependency(jobs=[job1, job2, job3, job4_coord])
        )

        final_job = q.enqueue(
            'services.worker_tasks.score_and_rank_single',
            {
                'token':         token,
                'job_id':        sub_job_id,
                'parent_job_id': job_id,
                'pnl_coord_id':  pnl_coordinator.id
            },
            depends_on=Dependency(jobs=[pnl_coordinator])
        )

        token_final_jobs.append(final_job)

        r = _get_redis()
        r.set(f"pipeline:{sub_job_id}:token", json.dumps(token), ex=3600)

        print(f"  ✓ Queued pipeline for {token.get('ticker')} [{sub_job_id[:8]}]")

    aggregate_job = q.enqueue(
        'services.worker_tasks.aggregate_cross_token',
        {
            'tokens':      tokens,
            'job_id':      job_id,
            'sub_job_ids': [f"{job_id}__{t['address'][:8]}" for t in tokens]
        },
        depends_on=Dependency(jobs=token_final_jobs)
    )

    print(f"  ✓ Queued cross-token aggregator: {aggregate_job.id[:8]} (waits for all {len(tokens)} tokens)")


# =============================================================================
# PHASE 1 WORKERS
# =============================================================================

def fetch_top_traders(data):
    """Worker 1: Fetch top 100 traders. PnL included, entry_price=None (Worker 4 fills it)."""
    from routes.wallets import get_worker_analyzer
    token  = data['token']
    job_id = data['job_id']

    analyzer = get_worker_analyzer()
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
    """
    Worker 2: Fetch first 100 buyers.
    FIX: PnL included, entry_price derived from first_buy math (volume_usd / amount).
    No API call needed for price.
    """
    from routes.wallets import get_worker_analyzer
    token  = data['token']
    job_id = data['job_id']

    analyzer = get_worker_analyzer()
    url = f"{analyzer.st_base_url}/first-buyers/{token['address']}"
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
                # FIX: Extract entry_price from first_buy math
                first_buy  = buyer.get('first_buy', {})
                amount     = first_buy.get('amount', 0)
                volume_usd = first_buy.get('volume_usd', 0)
                entry_price = (volume_usd / amount) if amount > 0 else None

                wallet_data[wallet] = {
                    'source':         'first_buyers',
                    'pnl_data':       buyer,
                    'earliest_entry': buyer.get('first_buy_time', 0),
                    'entry_price':    entry_price,  # FIX: now has value
                }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'first_buyers'}
    _save_result(f"phase1_first_buyers:{job_id}", result)
    print(f"[WORKER 2] first_buyers done: {len(wallets)} wallets")
    return result


def fetch_birdeye_trades(data):
    """
    Worker 3: Fetch early buyers from Birdeye /defi/v3/token/txs.
    Constraint: time range cannot exceed 30 days and after_time must be within last 30 days.
    If token launched >30 days ago, the launch window is out of range — skip time filter
    and just fetch the oldest available trades (default 7-day window from Birdeye).
    entry_price from from.price field (confirmed in API docs).
    """
    from routes.wallets import get_worker_analyzer
    token  = data['token']
    job_id = data['job_id']

    analyzer = get_worker_analyzer()

    # Step 1: Get token launch time
    launch_time = None
    try:
        url = f"{analyzer.st_base_url}/tokens/{token['address']}"
        token_info = analyzer.fetch_with_retry(
            url, analyzer._get_solanatracker_headers(),
            semaphore=analyzer.solana_tracker_semaphore
        )
        if token_info:
            launch_time = token_info.get('token', {}).get('creation', {}).get('created_time')
            print(f"[WORKER 3] launch_time={launch_time}")
    except Exception as e:
        print(f"[WORKER 3] Failed to fetch launch time: {e}")

    # Step 2: Build time window — Birdeye constraint: max 30 days, after_time within last 30 days
    current_time   = int(time.time())
    thirty_days_ago = current_time - (30 * 86400)
    time_params    = {}

    if launch_time and launch_time > 0:
        if launch_time >= thirty_days_ago:
            # Token launched within last 30 days — anchor to launch, fetch first 5 days
            after_time  = int(launch_time)
            before_time = min(int(launch_time) + (5 * 86400), current_time)
            time_params = {"after_time": after_time, "before_time": before_time}
            print(f"[WORKER 3] Launch window: {after_time} → {before_time} (first 5 days)")
        else:
            # Token launched >30 days ago — after_time can't go that far back.
            # Use oldest possible window Birdeye allows (30 days ago → +5 days), sorted asc
            # to still get the earliest trades within the allowed range.
            after_time  = thirty_days_ago
            before_time = thirty_days_ago + (5 * 86400)
            time_params = {"after_time": after_time, "before_time": before_time}
            print(f"[WORKER 3] Token launched >30 days ago — using oldest allowed window: {after_time} → {before_time}")
    else:
        # No launch time — fetch oldest trades in last 30 days
        after_time  = thirty_days_ago
        before_time = thirty_days_ago + (5 * 86400)
        time_params = {"after_time": after_time, "before_time": before_time}
        print(f"[WORKER 3] No launch time — using oldest 5-day window in allowed range")

    # Step 3: Fetch trades from v3 endpoint
    all_trades = []
    offset     = 0

    while offset < 10000:
        params = {
            "address":   token['address'],
            "offset":    offset,
            "limit":     100,
            "sort_by":   "block_unix_time",
            "sort_type": "asc",
            "tx_type":   "swap",
            **time_params,
        }

        response = analyzer.fetch_with_retry(
            f"{analyzer.birdeye_base_url}/defi/v3/token/txs",
            analyzer._get_birdeye_headers(),
            params,
            semaphore=analyzer.birdeye_semaphore
        )

        if offset == 0:
            print(f"[WORKER 3] First response: {list(response.keys()) if response else 'None'}")
            if response:
                items_preview = (response.get('data') or {}).get('items', [])
                print(f"[WORKER 3] success={response.get('success')}, items={len(items_preview)}")

        if not response or not response.get('success'):
            print(f"[WORKER 3] Bad response at offset {offset}: {response}")
            break

        trades = response.get('data', {}).get('items', [])
        if not trades:
            print(f"[WORKER 3] No trades at offset {offset} — done")
            break

        all_trades.extend(trades)
        print(f"[WORKER 3] offset={offset}: +{len(trades)} trades (total={len(all_trades)})")

        if len(trades) < 100:
            break
        offset += 100
        time.sleep(0.5)

    print(f"[WORKER 3] Total trades: {len(all_trades)}")

    wallets     = []
    wallet_data = {}
    for trade in all_trades:
        wallet = trade.get('owner')
        if wallet and wallet not in wallet_data:
            wallets.append(wallet)
            from_data    = trade.get('from', {}) or {}
            actual_price = from_data.get('price')  # confirmed field per API docs

            wallet_data[wallet] = {
                'source':         'birdeye_trades',
                'earliest_entry': trade.get('block_unix_time'),
                'entry_price':    actual_price,
            }

    result = {'wallets': wallets, 'wallet_data': wallet_data, 'source': 'birdeye_trades'}
    _save_result(f"phase1_birdeye:{job_id}", result)
    print(f"[WORKER 3] Done: {len(wallets)} unique wallets")
    return result


def coordinate_entry_prices(data):
    """
    Worker 4 coordinator: Reads top traders list from Redis, splits into batches of 20,
    spawns parallel fetch_entry_prices_batch workers, then queues merge_entry_prices
    to collect results. Exits immediately after queuing — RQ handles the rest.

    New pipeline for this coordinator:
        coordinate_entry_prices
            → fetch_entry_prices_batch (×N, parallel)
            → merge_entry_prices (waits for all batches, writes enriched top_traders back)
    """
    token  = data['token']
    job_id = data['job_id']

    top_traders_result = _load_result(f"phase1_top_traders:{job_id}")
    if not top_traders_result:
        print(f"[ENTRY COORD] No top traders result — skipping")
        # Write empty enriched result so coordinator doesn't stall
        _save_result(f"phase1_top_traders:{job_id}", {'wallets': [], 'wallet_data': {}, 'source': 'top_traders'})
        return {'batch_jobs': [], 'merge_job': None}

    wallets     = top_traders_result['wallets']
    batch_size  = 20
    q           = _get_queue()
    batch_jobs  = []

    print(f"[ENTRY COORD] Splitting {len(wallets)} wallets into batches of {batch_size}...")

    for i in range(0, len(wallets), batch_size):
        batch     = wallets[i:i + batch_size]
        batch_idx = i // batch_size
        bj = q.enqueue(
            'services.worker_tasks.fetch_entry_prices_batch',
            {
                'token':     token,
                'job_id':    job_id,
                'batch_idx': batch_idx,
                'wallets':   batch,
            }
        )
        batch_jobs.append(bj)

    merge_job = q.enqueue(
        'services.worker_tasks.merge_entry_prices',
        {
            'token':       token,
            'job_id':      job_id,
            'batch_count': len(batch_jobs),
            'all_wallets': wallets,
        },
        depends_on=Dependency(jobs=batch_jobs)
    )

    print(f"  ✓ Queued {len(batch_jobs)} entry-price batches + merge {merge_job.id[:8]}")
    return {'batch_jobs': [j.id for j in batch_jobs], 'merge_job': merge_job.id}


def fetch_entry_prices_batch(data):
    """
    Fetches first-buy entry prices for a batch of ~20 Top Trader wallets in parallel.
    Uses asyncio with semaphore=6 per batch.
    """
    from routes.wallets import get_worker_analyzer
    import aiohttp
    from asyncio import Semaphore as AsyncSemaphore

    token     = data['token']
    job_id    = data['job_id']
    batch_idx = data['batch_idx']
    wallets   = data['wallets']

    analyzer = get_worker_analyzer()

    print(f"[ENTRY BATCH {batch_idx}] Fetching prices for {len(wallets)} wallets...")

    async def _fetch():
        async with aiohttp.ClientSession() as session:
            sem   = AsyncSemaphore(6)
            tasks = []
            for wallet in wallets:
                async def fetch(w=wallet):
                    async with sem:
                        url  = f"{analyzer.st_base_url}/trades/{token['address']}/by-wallet/{w}"
                        resp = await analyzer.async_fetch_with_retry(
                            session, url,
                            analyzer._get_solanatracker_headers()
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
    Collects all entry-price batch results, merges into the top_traders wallet_data,
    and overwrites phase1_top_traders in Redis with the enriched data.
    The PnL coordinator reads from phase1_top_traders, so this must complete first.
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

    print(f"[ENTRY MERGE] Resolved {resolved}/{len(all_wallets)} entry prices → wrote enriched top_traders")
    return enriched




# =============================================================================
# PHASE 2 COORDINATOR
# =============================================================================

def coordinate_pnl_phase(data):
    """
    Merges Phase 1 results, dispatches parallel PnL batch jobs.
    Top Traders + First Buyers skip PnL fetch (already have it).
    Birdeye wallets fetch PnL only.
    """
    token       = data['token']
    job_id      = data['job_id']
    user_id     = data.get('user_id', 'default_user')
    phase1_jobs = data['phase1_jobs']

    print(f"\n[COORDINATOR] Phase 1 complete for {token.get('ticker')} - merging wallets...")

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

    q          = _get_queue()
    batch_size = max(1, len(all_wallets) // 5)
    pnl_jobs   = []

    for i in range(0, len(all_wallets), batch_size):
        batch         = all_wallets[i:i + batch_size]
        batch_wallets = {w: wallet_data[w] for w in batch}

        pnl_job = q.enqueue(
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

    print(f"  ✓ Queued {len(pnl_jobs)} PnL batch jobs")

    scorer_job = q.enqueue(
        'services.worker_tasks.score_and_rank_single',
        {
            'token':       token,
            'job_id':      job_id,
            'user_id':     user_id,
            'pnl_job_ids': [j.id for j in pnl_jobs],
            'batch_count': len(pnl_jobs)
        },
        depends_on=Dependency(jobs=pnl_jobs)
    )

    print(f"  ✓ Queued scorer: {scorer_job.id[:8]} (waits for {len(pnl_jobs)} PnL batches)")

    r = _get_redis()
    r.set(f"pipeline:{job_id}:final_job", scorer_job.id, ex=3600)

    return {'pnl_jobs': [j.id for j in pnl_jobs], 'final_job': scorer_job.id}


# =============================================================================
# PHASE 2 WORKERS - PnL batches run in parallel
# =============================================================================

def fetch_pnl_batch(data):
    """
    Fetch PnL for a batch of wallets.
    FIX: Categorize wallets properly:
      - Top Traders + First Buyers (have pnl_data AND entry_price) → skip API entirely
      - Birdeye wallets (have entry_price but no pnl_data) → fetch PnL only
    """
    from routes.wallets import get_worker_analyzer
    import aiohttp
    from asyncio import Semaphore as AsyncSemaphore

    token       = data['token']
    job_id      = data['job_id']
    batch_idx   = data['batch_idx']
    wallets     = data['wallets']
    wallet_data = data['wallet_data']

    analyzer  = get_worker_analyzer()
    qualified = []

    # FIX: Categorize wallets
    first_buyers_ready      = []  # Have both PnL + price → skip API
    top_traders_need_price  = []  # Have PnL, need price (shouldn't happen after Worker 4, but safety net)
    birdeye_need_pnl        = []  # Have price, need PnL

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
            first_buyers_ready.append(wallet)  # treat enriched top traders same as ready
        elif source == 'birdeye_trades':
            birdeye_need_pnl.append(wallet)
        else:
            # Fallback: if has pnl, qualify directly
            if has_pnl:
                first_buyers_ready.append(wallet)
            else:
                birdeye_need_pnl.append(wallet)

    print(f"[PNL BATCH {batch_idx}] {len(wallets)} wallets | {len(first_buyers_ready)} skip API | {len(top_traders_need_price)} need price | {len(birdeye_need_pnl)} fetch PnL")

    # FIX: First Buyers + enriched Top Traders → qualify immediately, no API
    for wallet in first_buyers_ready:
        pnl = wallet_data[wallet]['pnl_data']
        _qualify_wallet(wallet, pnl, wallet_data, token, qualified)

    # FIX: Top Traders that somehow still need price → fetch with 5 parallel workers
    if top_traders_need_price:
        async def _fetch_entry_prices():
            async with aiohttp.ClientSession() as session:
                sem   = AsyncSemaphore(5)
                tasks = []
                for wallet in top_traders_need_price:
                    async def fetch(w=wallet):
                        async with sem:
                            url = f"{analyzer.st_base_url}/trades/{token['address']}/by-wallet/{w}"
                            resp = await analyzer.async_fetch_with_retry(
                                session, url,
                                analyzer._get_solanatracker_headers()
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

    # FIX: Birdeye wallets → fetch PnL only (already have entry_price)
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
    Check ROI criteria and add to qualified list.
    Entry price resolution:
      1. wallet_data entry_price (Top Traders via Worker 4, Birdeye via from.price)
      2. Derived from pnl_data first_buy (First Buyers): volume_usd / amount
    """
    realized       = pnl_data.get('realized', 0)
    unrealized     = pnl_data.get('unrealized', 0)
    total_invested = pnl_data.get('total_invested') or pnl_data.get('totalInvested', 0)

    if total_invested < min_invested:
        return

    realized_mult = (realized + total_invested) / total_invested
    total_mult    = (realized + unrealized + total_invested) / total_invested

    if realized_mult >= min_roi_mult:
        wdata       = wallet_data.get(wallet, {})
        entry_price = wdata.get('entry_price')

        # FIX: Fallback — derive entry_price from first_buy math for First Buyers
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
# PHASE 3: SCORE + RANK
# No runner history here — that is Phase 4.
# =============================================================================

def score_and_rank_single(data):
    """
    Collect PnL batch results, score and rank all qualified wallets.
    Saves ranked top 20 to Redis, then queues Phase 4 runner history
    workers — one worker per 5 wallets — for the top 20 only.
    A final merge job waits for all runner history workers to complete
    before saving the enriched result to Supabase.
    """
    from routes.wallets import get_worker_analyzer
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    token       = data['token']
    job_id      = data['job_id']
    user_id     = data.get('user_id', 'default_user')
    batch_count = data['batch_count']
    parent_job  = data.get('parent_job_id')

    print(f"\n[SCORER] Scoring {token.get('ticker')} - collecting {batch_count} PnL batches...")

    analyzer = get_worker_analyzer()
    supabase = get_supabase_client()

    qualified_wallets = []
    for i in range(batch_count):
        batch_result = _load_result(f"pnl_batch:{job_id}:{i}")
        if batch_result:
            qualified_wallets.extend(batch_result)

    print(f"  ✓ {len(qualified_wallets)} qualified wallets to score")

    ath_data  = analyzer.get_token_ath(token['address'])
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
            # Runner history — populated by Phase 4 workers
            'runner_hits_30d':         0,
            'runner_success_rate':     0,
            'runner_avg_roi':          0,
            'other_runners':           [],
            'other_runners_stats':     {},
            'is_fresh':                True,
        })

    # Rank first, then hand off top 20 to Phase 4
    wallet_results.sort(key=lambda x: x['professional_score'], reverse=True)
    top_20 = wallet_results[:20]

    # Save ranked list (without runner history) for Phase 4 merge to enrich
    _save_result(f"ranked_wallets:{job_id}", top_20)

    print(f"  ✓ Ranked {len(wallet_results)} wallets — queuing Phase 4 runner history for top {len(top_20)}...")

    # Phase 4: one worker per 5 wallets → 4 workers for 20 wallets
    q           = _get_queue()
    runner_jobs = []
    chunk_size  = 5

    for i in range(0, len(top_20), chunk_size):
        chunk       = top_20[i:i + chunk_size]
        chunk_addrs = [w['wallet'] for w in chunk]
        batch_idx   = i // chunk_size

        rh_job = q.enqueue(
            'services.worker_tasks.fetch_runner_history_batch',
            {
                'token':     token,
                'job_id':    job_id,
                'batch_idx': batch_idx,
                'wallets':   chunk_addrs,
            }
        )
        runner_jobs.append(rh_job)

    print(f"  ✓ Queued {len(runner_jobs)} runner history workers ({chunk_size} wallets each)")

    # Merge job waits for all runner history workers
    merge_job = q.enqueue(
        'services.worker_tasks.merge_and_save_final',
        {
            'token':               token,
            'job_id':              job_id,
            'user_id':             user_id,
            'parent_job_id':       parent_job,
            'runner_batch_count':  len(runner_jobs),
            'total_qualified':     len(wallet_results),
        },
        depends_on=Dependency(jobs=runner_jobs)
    )

    print(f"  ✓ Queued merge+save: {merge_job.id[:8]} (waits for {len(runner_jobs)} runner batches)")
    return {'runner_jobs': [j.id for j in runner_jobs], 'merge_job': merge_job.id}


# =============================================================================
# PHASE 4: RUNNER HISTORY — parallel workers of 5 wallets each
# =============================================================================

def fetch_runner_history_batch(data):
    """
    Fetch 30-day runner history for a batch of 5 wallets.
    Saves enriched entries to Redis keyed by batch_idx.
    """
    from routes.wallets import get_worker_analyzer

    token     = data['token']
    job_id    = data['job_id']
    batch_idx = data['batch_idx']
    wallets   = data['wallets']   # max 5 addresses

    analyzer = get_worker_analyzer()
    enriched = []

    print(f"[RUNNER BATCH {batch_idx}] Fetching history for {len(wallets)} wallets...")

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
    print(f"[RUNNER BATCH {batch_idx}] Done: {len(enriched)} wallets enriched")
    return enriched


# =============================================================================
# PHASE 4 MERGE: Combine runner history into ranked list, save to Supabase
# =============================================================================

def merge_and_save_final(data):
    """
    Collect all runner history batches, merge into the ranked wallet list,
    then save the final enriched result to Supabase.
    FIX: Added Supabase save for single token mode.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    token              = data['token']
    job_id             = data['job_id']
    user_id            = data.get('user_id', 'default_user')
    parent_job         = data.get('parent_job_id')
    runner_batch_count = data['runner_batch_count']
    total_qualified    = data['total_qualified']

    supabase = get_supabase_client()

    print(f"\n[MERGE] Collecting {runner_batch_count} runner history batches...")

    # Load ranked list saved by scorer (no runner history yet)
    ranked_wallets = _load_result(f"ranked_wallets:{job_id}") or []

    # Build lookup from all runner history batches
    runner_lookup = {}
    for i in range(runner_batch_count):
        batch = _load_result(f"runner_batch:{job_id}:{i}") or []
        for entry in batch:
            runner_lookup[entry['wallet']] = entry

    # Merge runner history into ranked wallet list
    for wr in ranked_wallets:
        rh = runner_lookup.get(wr['wallet'])
        if rh:
            wr['runner_hits_30d']     = rh['runner_hits_30d']
            wr['runner_success_rate'] = rh['runner_success_rate']
            wr['runner_avg_roi']      = rh['runner_avg_roi']
            wr['other_runners']       = rh['other_runners']
            wr['other_runners_stats'] = rh['other_runners_stats']

    print(f"  ✓ Merged runner history for {len(runner_lookup)} wallets")

    result = {
        'success': True,
        'token':   token,
        'wallets': ranked_wallets,
        'total':   total_qualified,
    }

    _save_result(f"token_result:{job_id}", result)

    # Increment tokens_completed on parent job (batch mode)
    try:
        target_job_id = parent_job if parent_job else job_id
        current = supabase.schema(SCHEMA_NAME).table('analysis_jobs').select(
            'tokens_completed'
        ).eq('job_id', target_job_id).execute()

        current_count = current.data[0]['tokens_completed'] if current.data else 0
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
            'tokens_completed': current_count + 1
        }).eq('job_id', target_job_id).execute()
    except Exception as e:
        print(f"[MERGE] Failed to increment tokens_completed: {e}")

    # FIX: Single token mode — save final result to Supabase
    if not parent_job:
        try:
            supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
                'status':   'completed',
                'phase':    'done',
                'progress': 100,
                'results':  result
            }).eq('job_id', job_id).execute()
            print(f"  ✅ Supabase: saved final result for job {job_id[:8]}")
        except Exception as e:
            print(f"[MERGE] ⚠️ Failed to save final result: {e}")

        print(f"  ✅ Single token complete: {len(ranked_wallets)} wallets returned ({total_qualified} total qualified)")

    return result


# =============================================================================
# BATCH AGGREGATOR - Cross-token overlap ranking
# =============================================================================

def aggregate_cross_token(data):
    """
    Collect results from all token pipelines.
    Rank by cross-token appearance first, then aggregate score.
    Top 20 returned.
    FIX: Added Supabase save for batch mode.
    """
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    from collections import defaultdict

    tokens      = data['tokens']
    job_id      = data['job_id']
    sub_job_ids = data['sub_job_ids']

    supabase = get_supabase_client()

    print(f"\n[AGGREGATOR] Cross-token ranking for {len(tokens)} tokens...")

    all_token_results = []
    for sub_job_id in sub_job_ids:
        result = _load_result(f"token_result:{sub_job_id}")
        if result:
            all_token_results.append(result)

    print(f"  ✓ Loaded {len(all_token_results)}/{len(tokens)} token results")

    wallet_hits = defaultdict(lambda: {
        'wallet':                None,
        'runners_hit':           [],
        'runners_hit_addresses': set(),
        'roi_details':           [],
        'professional_scores':   [],
        'entry_to_ath_vals':     [],
        'distance_to_ath_vals':  [],
        'roi_multipliers':       [],
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
                'runner':                  sym,
                'runner_address':          token['address'],
                'roi_multiplier':          wallet.get('roi_multiplier', 0),
                'professional_score':      wallet.get('professional_score', 0),
                'professional_grade':      wallet.get('professional_grade', 'F'),
                'entry_to_ath_multiplier': wallet.get('entry_to_ath_multiplier'),
                'distance_to_ath_pct':     wallet.get('distance_to_ath_pct'),
            })

            wallet_hits[addr]['professional_scores'].append(wallet['professional_score'])
            if wallet.get('entry_to_ath_multiplier'):
                wallet_hits[addr]['entry_to_ath_vals'].append(wallet['entry_to_ath_multiplier'])
            if wallet.get('distance_to_ath_pct'):
                wallet_hits[addr]['distance_to_ath_vals'].append(wallet['distance_to_ath_pct'])
            wallet_hits[addr]['roi_multipliers'].append(wallet.get('roi_multiplier', 0))

    ranked = []
    for addr, d in wallet_hits.items():
        n         = len(d['professional_scores'])
        avg_score = sum(d['professional_scores']) / n if n else 0
        avg_dist  = sum(d['distance_to_ath_vals']) / len(d['distance_to_ath_vals']) if d['distance_to_ath_vals'] else 0
        avg_roi   = sum(d['roi_multipliers']) / len(d['roi_multipliers']) if d['roi_multipliers'] else 0
        avg_ath   = sum(d['entry_to_ath_vals']) / len(d['entry_to_ath_vals']) if d['entry_to_ath_vals'] else None

        aggregate_score = (0.60 * avg_dist) + (0.30 * (avg_roi / 10 * 100)) + (0.10 * avg_score)

        runner_count  = len(d['runners_hit'])
        participation = runner_count / len(tokens)
        if participation >= 0.8 and aggregate_score >= 85:   tier = 'S'
        elif participation >= 0.6 and aggregate_score >= 75: tier = 'A'
        elif participation >= 0.4 and aggregate_score >= 65: tier = 'B'
        else:                                                 tier = 'C'

        ranked.append({
            'wallet':                      addr,
            'runner_count':                runner_count,
            'runners_hit':                 d['runners_hit'],
            'avg_professional_score':      round(avg_score, 2),
            'avg_distance_to_ath_pct':     round(avg_dist, 2),
            'avg_roi':                     round(avg_roi, 2),
            'avg_entry_to_ath_multiplier': round(avg_ath, 2) if avg_ath else None,
            'aggregate_score':             round(aggregate_score, 2),
            'tier':                        tier,
            'professional_grade':          _calculate_grade(avg_score),
            'roi_details':                 d['roi_details'][:5],
            'is_fresh':                    True,
            'analyzed_tokens':             d['runners_hit'],
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

    ranked.sort(key=lambda x: (x['runner_count'], x['aggregate_score']), reverse=True)

    if not any(r['runner_count'] > 1 for r in ranked):
        print(f"  ⚠️ No cross-token overlap - ranking by individual score")
        ranked.sort(key=lambda x: x['aggregate_score'], reverse=True)
        for r in ranked:
            r['no_overlap_fallback'] = True

    final_result = {
        'success': True,
        'wallets': ranked[:20],
        'total':   len(ranked),
    }

    # FIX: Save batch result to Supabase
    try:
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
            'status':   'completed',
            'phase':    'done',
            'progress': 100,
            'results':  final_result
        }).eq('job_id', job_id).execute()
        print(f"  ✅ Supabase: saved batch result for job {job_id[:8]}")
    except Exception as e:
        print(f"[AGGREGATOR] ⚠️ Failed to save to Supabase: {e}")

    print(f"  ✅ Batch complete: {len(ranked)} wallets ranked, top 20 returned")
    return final_result


# =============================================================================
# CACHE WARMUP
# =============================================================================

def preload_trending_cache():
    """Queue cache warmup jobs - runner lists only, no full analysis"""
    q = _get_queue()

    job7  = q.enqueue('services.worker_tasks.warm_cache_runners', {'days_back': 7})
    job14 = q.enqueue('services.worker_tasks.warm_cache_runners', {'days_back': 14})

    print(f"[CACHE WARMUP] Queued 7d and 14d runner list warmup")
    return [job7.id, job14.id]


def warm_cache_runners(data):
    """Worker: Cache runner list only - NO full analysis"""
    from routes.wallets import get_worker_analyzer
    days_back = data['days_back']
    analyzer  = get_worker_analyzer()

    print(f"[WARMUP {days_back}D] Finding runners...")
    runners = analyzer.find_trending_runners_enhanced(
        days_back=days_back,
        min_multiplier=5.0,
        min_liquidity=50000
    )
    print(f"  ✅ Cached {len(runners)} runners for {days_back}d (lists only)")
    return len(runners)