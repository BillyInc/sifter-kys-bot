"""Wallet analysis routes - CORRECTLY FIXED for TOKEN OVERLAP ranking."""
from flask import Blueprint, request, jsonify, Response
import json

from config import Config
from auth import require_auth, optional_auth
from db.watchlist_db import WatchlistDatabase
from collections import defaultdict
from datetime import datetime
import os
import uuid

# Lazy imports
_wallet_analyzer = None
_worker_analyzer = None
_wallet_monitor = None
_watchlist_db = None


def get_watchlist_db():
    global _watchlist_db
    if _watchlist_db is None:
        _watchlist_db = WatchlistDatabase()
    return _watchlist_db


def get_wallet_analyzer():
    """
    Flask-facing analyzer: read-write DuckDB, writes to both Redis and DuckDB.
    Used by all Flask routes and the Celery flush task.
    """
    global _wallet_analyzer
    if _wallet_analyzer is None:
        from services.wallet_analyzer import WalletPumpAnalyzer
        _wallet_analyzer = WalletPumpAnalyzer(
            solanatracker_api_key=Config.SOLANATRACKER_API_KEY,
            birdeye_api_key=Config.BIRDEYE_API_KEY,
            debug_mode=True,
            read_only=False  # Flask process: full read-write access
        )
        print("[WALLET ANALYZER] ✅ Initialized (Flask - read-write)")
    return _wallet_analyzer


def get_worker_analyzer():
    """
    Worker-facing analyzer: DuckDB opened in read-only mode to avoid lock conflicts.
    Workers write to Redis only; Flask flushes Redis → DuckDB every hour via Celery.
    Use this in all RQ worker tasks (worker_tasks.py).
    """
    global _worker_analyzer
    if _worker_analyzer is None:
        from services.wallet_analyzer import WalletPumpAnalyzer
        _worker_analyzer = WalletPumpAnalyzer(
            solanatracker_api_key=Config.SOLANATRACKER_API_KEY,
            birdeye_api_key=Config.BIRDEYE_API_KEY,
            debug_mode=True,
            read_only=True  # Worker process: DuckDB read-only, writes to Redis only
        )
        print("[WORKER ANALYZER] ✅ Initialized (Worker - read-only DuckDB, Redis writes)")
    return _worker_analyzer


def get_wallet_monitor():
    global _wallet_monitor
    if _wallet_monitor is None:
        from services.wallet_monitor import WalletActivityMonitor
        from flask import current_app
        telegram_notifier = current_app.config.get('TELEGRAM_NOTIFIER')

        _wallet_monitor = WalletActivityMonitor(
            solanatracker_api_key=Config.SOLANATRACKER_API_KEY,
            poll_interval=120,
            telegram_notifier=telegram_notifier
        )
        _wallet_monitor.start()
        print("[WALLET MONITOR] Started background monitoring (Supabase)")
    return _wallet_monitor

wallets_bp = Blueprint('wallets', __name__, url_prefix='/api/wallets')


# =============================================================================
# QUEUE HELPER FUNCTIONS
# =============================================================================

def get_queues():
    """Get the three queues: high, batch, compute."""
    from redis import Redis
    from rq import Queue
    import os
    
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    redis_conn = Redis.from_url(redis_url)
    
    return (
        Queue('high', connection=redis_conn),
        Queue('batch', connection=redis_conn),
        Queue('compute', connection=redis_conn)
    )


# =============================================================================
# ASYNC JOB QUEUEING WITH PROGRESS TRACKING
# =============================================================================

@wallets_bp.route('/analyze', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_wallets():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        if not data.get('tokens'):
            return jsonify({'error': 'tokens array required'}), 400

        tokens = data['tokens']
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')

        from services.supabase_client import get_supabase_client, SCHEMA_NAME

        q_high, q_batch, q_compute = get_queues()
        supabase = get_supabase_client()

        job_id = str(uuid.uuid4())

        supabase.schema(SCHEMA_NAME).table('analysis_jobs').insert({
            'job_id': job_id,
            'user_id': user_id,
            'status': 'pending',
            'progress': 0,
            'phase': 'queued',
            'tokens_total': len(tokens),
            'tokens_completed': 0,
            'token_address': tokens[0]['address'] if len(tokens) == 1 else None
        }).execute()

        # Queue to appropriate queue based on job type
        if len(tokens) == 1:
            # Single token analysis goes to high queue
            job = q_high.enqueue('services.worker_tasks.perform_wallet_analysis', {
                'tokens': tokens,
                'user_id': user_id,
                'global_settings': data.get('global_settings', {}),
                'job_id': job_id
            })
            print(f"[ANALYZE] Queued single token job {job_id[:8]} to HIGH queue")
        else:
            # Batch token analysis goes to batch queue
            job = q_batch.enqueue('services.worker_tasks.perform_wallet_analysis', {
                'tokens': tokens,
                'user_id': user_id,
                'global_settings': data.get('global_settings', {}),
                'job_id': job_id
            })
            print(f"[ANALYZE] Queued batch job {job_id[:8]} ({len(tokens)} tokens) to BATCH queue")

        return jsonify({
            'success': True,
            'job_id': job_id,
            'status': 'pending'
        }), 202

    except Exception as e:
        print(f"\n[ANALYZE ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job_status(job_id):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME

    supabase = get_supabase_client()
    result = supabase.schema(SCHEMA_NAME).table('analysis_jobs').select('*').eq('job_id', job_id).execute()

    if not result.data:
        return jsonify({'error': 'Job not found'}), 404

    job = result.data[0]

    if job['status'] == 'completed':
        return jsonify(job.get('results', {})), 200
    elif job['status'] == 'failed':
        return jsonify({'status': 'failed', 'error': job.get('error', 'Unknown error')}), 500

    return jsonify({'status': job['status']}), 200


@wallets_bp.route('/jobs/<job_id>/progress', methods=['GET'])
def get_job_progress(job_id):
    from services.supabase_client import get_supabase_client, SCHEMA_NAME
    
    supabase = get_supabase_client()
    result = supabase.schema(SCHEMA_NAME).table('analysis_jobs').select('*').eq('job_id', job_id).execute()
    
    if not result.data:
        return jsonify({'error': 'Job not found'}), 404
    
    job = result.data[0]
    return jsonify({
        'success': True,
        'status': job['status'],
        'progress': job['progress'],
        'phase': job.get('phase', ''),
        'tokens_total': job.get('tokens_total', 0),
        'tokens_completed': job.get('tokens_completed', 0)
    })


@wallets_bp.route('/jobs/<job_id>/cancel', methods=['POST', 'OPTIONS'])
@optional_auth
def cancel_job(job_id):
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        from redis import Redis
        from rq import Queue
        import os
        
        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
        redis_conn = Redis.from_url(redis_url)
        
        # Try to cancel from all queues
        for queue_name in ['high', 'batch', 'compute']:
            queue = Queue(queue_name, connection=redis_conn)
            job = queue.fetch_job(job_id)
            if job:
                job.cancel()
                print(f"[CANCEL] Cancelled job {job_id[:8]} from {queue_name} queue")
                break
        
        # Update Supabase
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
            'status': 'cancelled',
            'phase': 'cancelled',
            'progress': 0
        }).eq('job_id', job_id).execute()
        
        return jsonify({
            'success': True,
            'message': 'Job cancelled'
        }), 200
        
    except Exception as e:
        print(f"[CANCEL ERROR] {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# ✅ NEW: JOB RECOVERY ENDPOINT
# Checks Redis for a completed result when Supabase is still stuck in 'processing'.
# This handles the case where the worker finished but died before the Supabase write,
# OR where RQ's own heartbeat/bookkeeping timed out after compute completed.
# =============================================================================

@wallets_bp.route('/jobs/<job_id>/recover', methods=['POST', 'OPTIONS'])
@optional_auth
def recover_job(job_id):
    if request.method == 'OPTIONS':
        return '', 204

    try:
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        from redis import Redis
        import os, json

        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
        r        = Redis.from_url(redis_url)
        supabase = get_supabase_client()

        # Fetch current job record
        job_record = supabase.schema(SCHEMA_NAME).table('analysis_jobs').select(
            'status, results'
        ).eq('job_id', job_id).execute()

        if not job_record.data:
            return jsonify({'error': 'Job not found'}), 404

        job = job_record.data[0]

        # Already completed — just return the stored result
        if job['status'] == 'completed' and job.get('results'):
            return jsonify({
                'recovered': False,
                'message': 'Job already completed',
                'results': job['results']
            }), 200

        # Look for the result in Redis under the two possible key patterns
        raw = r.get(f'job_result:{job_id}')
        if not raw:
            raw = r.get(f'token_result:{job_id}')
        if not raw:
            # Nothing in Redis either — job genuinely incomplete or result is lost
            return jsonify({
                'recovered': False,
                'message': 'No result found in Redis — job genuinely incomplete'
            }), 404

        result = json.loads(raw)

        # Sync the recovered result back to Supabase so future polls see it
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').update({
            'status':   'completed',
            'phase':    'done',
            'progress': 100,
            'results':  result
        }).eq('job_id', job_id).execute()

        print(f"[RECOVER] ✅ Recovered stuck job {job_id[:8]} from Redis → Supabase synced")

        return jsonify({
            'recovered': True,
            'results': result
        }), 200

    except Exception as e:
        print(f"[RECOVER ERROR] {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/analyze/stream', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_stream():
    if request.method == 'OPTIONS':
        return '', 204

    data = request.json
    tokens = data.get('tokens', [])
    user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')
    min_roi_multiplier = data.get('min_roi_multiplier', 3.0)

    def generate():
        wallet_analyzer = get_wallet_analyzer()

        yield f"data: {json.dumps({'type': 'progress', 'message': f'Starting analysis of {len(tokens)} tokens...'})}\n\n"

        all_wallets = []

        for i, token in enumerate(tokens, 1):
            try:
                yield f"data: {json.dumps({'type': 'progress', 'message': f'Analyzing {token.get(chr(39) + chr(116) + chr(105) + chr(99) + chr(107) + chr(101) + chr(114), chr(116) + chr(111) + chr(107) + chr(101) + chr(110))} ({i}/{len(tokens)})...'})}\n\n"

                wallets = wallet_analyzer.analyze_token_professional(
                    token_address=token['address'],
                    token_symbol=token.get('ticker', 'UNKNOWN'),
                    min_roi_multiplier=min_roi_multiplier,
                    user_id=user_id
                )

                for wallet in wallets:
                    wallet['analyzed_tokens'] = [token.get('ticker', 'UNKNOWN')]

                all_wallets.extend(wallets[:20])

            except Exception as e:
                yield f"data: {json.dumps({'type': 'progress', 'message': f'Error on {token.get(chr(116)+chr(105)+chr(99)+chr(107)+chr(101)+chr(114))}: {str(e)}'})}\n\n"

        yield f"data: {json.dumps({'type': 'complete', 'data': {'wallets': all_wallets, 'total': len(all_wallets)}})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


# =============================================================================
# SINGLE TOKEN ANALYSIS (SYNCHRONOUS - FOR TESTING)
# =============================================================================

@wallets_bp.route('/analyze/single', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_single_token():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        if not data.get('token'):
            return jsonify({'error': 'token object required'}), 400

        token = data['token']
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')

        wallet_analyzer = get_wallet_analyzer()

        print(f"\n{'='*80}")
        print(f"SINGLE TOKEN ANALYSIS: {token.get('ticker', 'UNKNOWN')}")
        print(f"Using TokenAnalyzer Relative Scoring")
        print(f"{'='*80}")

        wallets = wallet_analyzer.analyze_token_professional(
            token_address=token['address'],
            token_symbol=token.get('ticker', 'UNKNOWN'),
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )
        
        for wallet in wallets:
            wallet['analyzed_tokens'] = [token.get('ticker', 'UNKNOWN')]
            if 'consistency_score' in wallet:
                del wallet['consistency_score']
        
        top_wallets = wallets[:20]
        
        return jsonify({
            'success': True,
            'token': token,
            'wallets': top_wallets,
            'total_wallets': len(wallets),
            'tokens_analyzed': [token.get('ticker', 'UNKNOWN')],
            'mode': 'professional_single_6step',
            'data_source': 'TokenAnalyzer Relative Scoring',
            'summary': {
                'tokens_participated': [token.get('ticker', 'UNKNOWN')],
                'qualified_wallets': len(wallets),
                's_tier_wallets': sum(1 for w in top_wallets if w.get('professional_grade') in ['A+', 'A']),
                'top_wallets_shown': len(top_wallets),
                'avg_distance_to_ath': round(sum(w.get('entry_to_ath_multiplier', 0) for w in top_wallets) / len(top_wallets), 2) if top_wallets else 0,
                'total_roi': round(sum(w.get('roi_percent', 0) for w in top_wallets), 2) if top_wallets else 0,
                'avg_roi': round(sum(w.get('roi_percent', 0) for w in top_wallets) / len(top_wallets), 2) if top_wallets else 0,
                'avg_professional_score': round(sum(w.get('professional_score', 0) for w in top_wallets) / len(top_wallets), 2) if top_wallets else 0,
                'avg_variance': 0,
                'avg_runner_hits_30d': round(sum(w.get('runner_hits_30d', 0) for w in top_wallets) / len(top_wallets), 1) if top_wallets else 0,
                'a_plus_consistency': sum(1 for w in top_wallets if w.get('professional_grade') == 'A+')
            }
        }), 200

    except Exception as e:
        print(f"\n[SINGLE TOKEN ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# TRENDING RUNNERS ENDPOINTS
# =============================================================================

@wallets_bp.route('/trending/runners', methods=['GET','OPTIONS'])
@optional_auth
def get_trending_runners():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        timeframe = request.args.get('timeframe', '7d')
        min_liquidity = float(request.args.get('min_liquidity', 50000))
        min_multiplier = float(request.args.get('min_multiplier', 5))
        min_age_days = int(request.args.get('min_age_days', 0))
        max_age_days_raw = request.args.get('max_age_days', None)
        max_age_days = int(max_age_days_raw) if max_age_days_raw else 30

        wallet_analyzer = get_wallet_analyzer()

        days_map = {'7d': 7, '14d': 14, '30d': 30}
        days_back = days_map.get(timeframe, 7)

        # This now checks Redis/DuckDB cache first
        runners = wallet_analyzer.find_trending_runners_enhanced(
            days_back=days_back,
            min_multiplier=min_multiplier,
            min_liquidity=min_liquidity
        )

        filtered_runners = [
            r for r in runners
            if r.get('token_age_days', 0) >= min_age_days
            and r.get('token_age_days', 0) <= max_age_days
        ]

        return jsonify({
            'success': True,
            'runners': filtered_runners,
            'total': len(filtered_runners),
            'security_filtered': True,
            'security_info': 'All tokens verified: liquidity locked, mint revoked, has social'
        }), 200

    except Exception as e:
        print(f"\n[TRENDING RUNNERS ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/trending/analyze', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_trending_runner():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        if not data.get('runner'):
            return jsonify({'error': 'runner object required'}), 400

        runner = data['runner']
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')

        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        
        q_high, q_batch, q_compute = get_queues()
        supabase = get_supabase_client()
        
        job_id = str(uuid.uuid4())
        
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').insert({
            'job_id': job_id,
            'user_id': user_id,
            'status': 'pending',
            'progress': 0,
            'phase': 'queued',
            'tokens_total': 1,
            'tokens_completed': 0,
            'token_address': runner['address']
        }).execute()
        
        # Single trending analysis goes to high queue
        job = q_high.enqueue('services.worker_tasks.perform_wallet_analysis', {
            'tokens': [{
                'address': runner['address'],
                'ticker': runner.get('symbol', 'UNKNOWN'),
                'chain': runner.get('chain', 'solana')
            }],
            'user_id': user_id,
            'global_settings': {'min_roi_multiplier': min_roi_multiplier},
            'job_id': job_id
        })
        
        print(f"[TRENDING SINGLE] Queued job {job_id[:8]} for {runner.get('symbol')} to HIGH queue")
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'status': 'pending'
        }), 202

    except Exception as e:
        print(f"\n[RUNNER ANALYSIS ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/trending/analyze-batch', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_trending_runners_batch():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        if not data.get('runners'):
            return jsonify({'error': 'runners array required'}), 400

        runners = data['runners']
        min_runner_hits = data.get('min_runner_hits', 2)
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')

        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        
        q_high, q_batch, q_compute = get_queues()
        supabase = get_supabase_client()
        
        job_id = str(uuid.uuid4())
        
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').insert({
            'job_id': job_id,
            'user_id': user_id,
            'status': 'pending',
            'progress': 0,
            'phase': 'queued',
            'tokens_total': len(runners),
            'tokens_completed': 0
        }).execute()
        
        # Batch trending analysis goes to batch queue
        job = q_batch.enqueue('services.worker_tasks.perform_trending_batch_analysis', {
            'runners': runners,
            'user_id': user_id,
            'min_runner_hits': min_runner_hits,
            'min_roi_multiplier': min_roi_multiplier,
            'job_id': job_id
        })
        
        print(f"[TRENDING BATCH] Queued job {job_id[:8]} for {len(runners)} runners to BATCH queue")
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'status': 'pending'
        }), 202

    except Exception as e:
        print(f"\n[BATCH TRENDING ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# AUTO-DISCOVERY ENDPOINT
# =============================================================================

@wallets_bp.route('/discover', methods=['POST','OPTIONS'])
@optional_auth
def auto_discover_wallets():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json or {}
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')
        min_runner_hits = data.get('min_runner_hits', 2)
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)

        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        
        q_high, q_batch, q_compute = get_queues()
        supabase = get_supabase_client()
        
        job_id = str(uuid.uuid4())
        
        supabase.schema(SCHEMA_NAME).table('analysis_jobs').insert({
            'job_id': job_id,
            'user_id': user_id,
            'status': 'pending',
            'progress': 0,
            'phase': 'queued',
            'tokens_total': 10,
            'tokens_completed': 0
        }).execute()
        
        # Auto-discovery goes to compute queue (heaviest job)
        job = q_compute.enqueue('services.worker_tasks.perform_auto_discovery', {
            'user_id': user_id,
            'min_runner_hits': min_runner_hits,
            'min_roi_multiplier': min_roi_multiplier,
            'job_id': job_id
        })
        
        print(f"[AUTO DISCOVERY] Queued job {job_id[:8]} to COMPUTE queue")
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'status': 'pending'
        }), 202

    except Exception as e:
        print(f"\n[DISCOVER ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# WATCHLIST ENDPOINTS
# =============================================================================

@wallets_bp.route('/watchlist/add', methods=['POST', 'OPTIONS'])
@optional_auth
def add_wallet_to_watchlist():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')

        if not user_id or not data.get('wallet'):
            return jsonify({'error': 'user_id and wallet required'}), 400

        wallet_data = data['wallet']
        
        db_wallet = {
            'wallet_address': wallet_data.get('wallet'),
            'tier': wallet_data.get('tier', 'C'),
            'pump_count': wallet_data.get('pump_count', 0),
            'avg_distance_to_peak': wallet_data.get('avg_distance_to_ath_pct', 0),
            'avg_roi_to_peak': wallet_data.get('avg_roi_to_peak_pct', 0),
            'consistency_score': wallet_data.get('consistency_score', 0),
            'tokens_hit': wallet_data.get('token_list', [])
        }

        db = get_watchlist_db()
        success = db.add_wallet_to_watchlist(user_id, db_wallet)

        if not success:
            return jsonify({
                'success': False,
                'error': 'Wallet already in watchlist'
            }), 400

        return jsonify({
            'success': True,
            'message': f"Wallet {db_wallet['wallet_address'][:8]}... added"
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/watchlist/get', methods=['GET', 'OPTIONS'])
@optional_auth
def get_wallet_watchlist():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
        tier = request.args.get('tier')

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        query = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select(
            'wallet_address, tier, position, movement, positions_changed, '
            'form, status, degradation_alerts, roi_7d, roi_30d, '
            'runners_7d, runners_30d, win_rate_7d, last_trade_time, '
            'professional_score, consistency_score, pump_count, '
            'avg_distance_to_peak, avg_roi_to_peak, tokens_hit, '
            'tags, notes, alert_enabled, alert_threshold_usd, '
            'alert_on_buy, alert_on_sell, min_trade_usd, '
            'added_at, last_updated'
        ).eq('user_id', user_id)
        
        if tier:
            query = query.eq('tier', tier)
        
        result = query.order('position').execute()

        return jsonify({
            'success': True,
            'wallets': result.data,
            'count': len(result.data)
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/watchlist/remove', methods=['POST', 'OPTIONS'])
@optional_auth
def remove_wallet_from_watchlist():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')
        wallet_address = data.get('wallet_address')

        if not user_id or not wallet_address:
            return jsonify({
                'success': False,
                'error': 'user_id and wallet_address are required'
            }), 400

        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        check = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select(
            'wallet_address'
        ).eq('user_id', user_id).eq('wallet_address', wallet_address).execute()

        if not check.data:
            return jsonify({
                'success': False,
                'error': 'Wallet not found in your watchlist'
            }), 404

        db = get_watchlist_db()
        success = db.remove_wallet_from_watchlist(user_id, wallet_address)

        if success:
            return jsonify({
                'success': True,
                'message': 'Wallet removed from watchlist'
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to remove wallet'
            }), 500

    except Exception as e:
        print(f"[WALLET ROUTES] Error removing wallet {wallet_address}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred. Please try again.'
        }), 500


@wallets_bp.route('/watchlist/update', methods=['POST', 'OPTIONS'])
@optional_auth
def update_wallet_watchlist():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')

        if not user_id or not data.get('wallet_address'):
            return jsonify({'error': 'user_id and wallet_address required'}), 400

        db = get_watchlist_db()
        success = db.update_wallet_notes(
            user_id,
            data['wallet_address'],
            data.get('notes'),
            data.get('tags')
        )

        if success:
            return jsonify({
                'success': True,
                'message': 'Wallet updated'
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to update'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/watchlist/stats', methods=['GET', 'OPTIONS'])
@optional_auth
def get_wallet_watchlist_stats():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        db = get_watchlist_db()
        stats = db.get_wallet_watchlist_stats(user_id)

        return jsonify({
            'success': True,
            'stats': stats
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/watchlist/alerts/update', methods=['POST', 'OPTIONS'])
@optional_auth
def update_wallet_alert_settings():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')
        wallet_address = data.get('wallet_address')
        alert_enabled = data.get('alert_enabled')
        alert_threshold_usd = data.get('alert_threshold_usd')
        alert_on_buy = data.get('alert_on_buy')
        alert_on_sell = data.get('alert_on_sell')
        min_trade_usd = data.get('min_trade_usd')

        if not user_id or not wallet_address:
            return jsonify({
                'success': False,
                'error': 'user_id and wallet_address are required'
            }), 400

        update_data = {'last_updated': datetime.utcnow().isoformat()}
        if alert_enabled is not None:
            update_data['alert_enabled'] = alert_enabled
        if alert_threshold_usd is not None:
            update_data['alert_threshold_usd'] = alert_threshold_usd
        if alert_on_buy is not None:
            update_data['alert_on_buy'] = alert_on_buy
        if alert_on_sell is not None:
            update_data['alert_on_sell'] = alert_on_sell
        if min_trade_usd is not None:
            update_data['min_trade_usd'] = min_trade_usd
        
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        supabase.schema(SCHEMA_NAME).table('wallet_watchlist').update(
            update_data
        ).eq('user_id', user_id).eq('wallet_address', wallet_address).execute()

        return jsonify({
            'success': True,
            'message': 'Alert settings updated'
        }), 200

    except Exception as e:
        print(f"[WALLET ROUTES] Error updating alerts: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Failed to update alert settings'
        }), 500


@wallets_bp.route('/watchlist/rerank', methods=['POST', 'OPTIONS'])
@require_auth
def rerank_watchlist():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.json.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from services.watchlist_manager import WatchlistLeagueManager
        manager = WatchlistLeagueManager()
        
        watchlist = manager.rerank_user_watchlist(user_id)
        
        return jsonify({
            'success': True,
            'watchlist': watchlist,
            'message': 'Watchlist reranked successfully'
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/activity/recent', methods=['GET', 'OPTIONS'])
@optional_auth
def get_wallet_activity():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        from services.wallet_monitor import get_recent_wallet_activity

        wallet_address = request.args.get('wallet_address')
        limit = int(request.args.get('limit', 50))

        activities = get_recent_wallet_activity(
            wallet_address=wallet_address,
            limit=limit
        )

        return jsonify({
            'success': True,
            'activities': activities,
            'count': len(activities)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/notifications', methods=['GET', 'OPTIONS'])
@optional_auth
def get_notifications():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        from services.wallet_monitor import get_user_notifications

        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        unread_only = request.args.get('unread_only', '').lower() == 'true'
        limit = int(request.args.get('limit', 50))

        notifications = get_user_notifications(
            user_id=user_id,
            unread_only=unread_only,
            limit=limit
        )

        unread_count = len([n for n in notifications if n['read_at'] is None])

        return jsonify({
            'success': True,
            'notifications': notifications,
            'count': len(notifications),
            'unread_count': unread_count
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/notifications/mark-read', methods=['POST', 'OPTIONS'])
@optional_auth
def mark_notifications_read():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        from services.wallet_monitor import mark_notification_read, mark_all_notifications_read

        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        if data.get('mark_all'):
            count = mark_all_notifications_read(user_id)
            return jsonify({
                'success': True,
                'message': f'{count} notification(s) marked as read'
            }), 200

        elif data.get('notification_id'):
            success = mark_notification_read(
                data['notification_id'],
                user_id
            )

            if success:
                return jsonify({
                    'success': True,
                    'message': 'Notification marked as read'
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'error': 'Notification not found'
                }), 404

        else:
            return jsonify({
                'error': 'Either notification_id or mark_all required'
            }), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/alerts/update', methods=['POST', 'OPTIONS'])
@optional_auth
def update_wallet_alerts():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        from services.wallet_monitor import update_alert_settings

        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')

        if not user_id or not data.get('wallet_address'):
            return jsonify({
                'error': 'user_id and wallet_address required'
            }), 400

        if not data.get('settings'):
            return jsonify({'error': 'settings object required'}), 400

        success = update_alert_settings(
            user_id,
            data['wallet_address'],
            data['settings']
        )

        if success:
            return jsonify({
                'success': True,
                'message': 'Alert settings updated'
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': 'Wallet not found in watchlist'
            }), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/monitor/status', methods=['GET', 'OPTIONS'])
@optional_auth
def get_monitor_status():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        monitor = get_wallet_monitor()
        stats = monitor.get_monitoring_stats()

        return jsonify({
            'success': True,
            'status': stats
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/monitor/force-check', methods=['POST', 'OPTIONS'])
@optional_auth
def force_check_wallet():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        wallet_address = data.get('wallet_address')

        if not wallet_address:
            return jsonify({'error': 'wallet_address required'}), 400

        monitor = get_wallet_monitor()
        monitor.force_check_wallet(wallet_address)

        return jsonify({
            'success': True,
            'message': f'Force check completed for {wallet_address[:8]}...'
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/watchlist/table', methods=['GET', 'OPTIONS'])
@optional_auth
def get_watchlist_table():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from db.watchlist_db import WatchlistDatabase
        db = WatchlistDatabase()

        table_data = db.get_premier_league_table(user_id)
        
        return jsonify({
            'success': True,
            'table': table_data['wallets'],
            'wallets': table_data['wallets'],
            'promotion_queue': table_data['promotion_queue'],
            'stats': table_data['stats']
        }), 200
        
    except Exception as e:
        print(f"Error getting watchlist table: {e}")
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/watchlist/suggest-replacement', methods=['POST', 'OPTIONS'])
@optional_auth
def suggest_replacement():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')
        wallet_address = data.get('wallet_address')
        min_score = data.get('min_professional_score', 85)
        
        if not user_id or not wallet_address:
            return jsonify({'error': 'user_id and wallet_address required'}), 400
        
        wallet_analyzer = get_wallet_analyzer()
        
        replacements = wallet_analyzer.find_replacement_wallets(
            declining_wallet_address=wallet_address,
            user_id=user_id,
            min_professional_score=min_score,
            max_results=3
        )
        
        return jsonify({
            'success': True,
            'replacements': replacements,
            'count': len(replacements)
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/watchlist/replace', methods=['POST', 'OPTIONS'])
@optional_auth
def replace_wallet():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')
        old_wallet = data.get('old_wallet')
        new_wallet_data = data.get('new_wallet')
        
        if not all([user_id, old_wallet, new_wallet_data]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        from db.watchlist_db import WatchlistDatabase
        db = WatchlistDatabase()

        db.remove_wallet_from_watchlist(user_id, old_wallet)

        wallet_data = {
            'wallet_address': new_wallet_data['wallet'],
            'tier': new_wallet_data.get('tier', 'C'),
            'avg_distance_to_peak': new_wallet_data.get('professional_score', 0),
            'avg_roi_to_peak': new_wallet_data.get('roi_multiplier', 0) * 100,
            'pump_count': new_wallet_data.get('runner_hits_30d', 0),
            'consistency_score': new_wallet_data.get('consistency_score', 0)
        }
        db.add_wallet_to_watchlist(user_id, wallet_data)
        
        return jsonify({
            'success': True,
            'message': 'Wallet replaced successfully',
            'old_wallet': old_wallet,
            'new_wallet': new_wallet_data['wallet']
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
    
# =============================================================================
# WATCHLIST STATS ENDPOINTS
# =============================================================================

@wallets_bp.route('/watchlist/<wallet_address>/stats', methods=['GET', 'OPTIONS'])
@optional_auth
def get_wallet_stats(wallet_address):
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from services.watchlist_manager import WatchlistLeagueManager
        manager = WatchlistLeagueManager()
        
        metrics = manager._refresh_wallet_metrics(wallet_address)
        trades = manager._get_recent_trades(wallet_address, days=30, limit=10)
        
        return jsonify({
            'success': True,
            'wallet_address': wallet_address,
            'metrics': metrics,
            'recent_trades': trades
        }), 200
        
    except Exception as e:
        print(f"[WALLET STATS] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/watchlist/<wallet_address>/refresh', methods=['POST', 'OPTIONS'])
@optional_auth
def refresh_wallet_stats(wallet_address):
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json or {}
        user_id = getattr(request, 'user_id', None) or data.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from services.watchlist_manager import WatchlistLeagueManager
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        
        manager = WatchlistLeagueManager()
        supabase = get_supabase_client()
        
        metrics = manager._refresh_wallet_metrics(wallet_address)
        
        supabase.schema(SCHEMA_NAME).table('wallet_watchlist').update({
            'roi_7d': metrics.get('roi_7d', 0),
            'roi_30d': metrics.get('roi_30d', 0),
            'runners_7d': metrics.get('runners_7d', 0),
            'runners_30d': metrics.get('runners_30d', 0),
            'win_rate_7d': metrics.get('win_rate_7d', 0),
            'last_trade_time': metrics.get('last_trade_time'),
            'professional_score': metrics.get('professional_score', 0),
            'consistency_score': metrics.get('consistency_score', 0),
            'last_updated': datetime.utcnow().isoformat()
        }).eq('user_id', user_id).eq('wallet_address', wallet_address).execute()
        
        return jsonify({
            'success': True,
            'message': 'Stats refreshed',
            'metrics': metrics
        }), 200
        
    except Exception as e:
        print(f"[REFRESH WALLET] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/watchlist/add-quick', methods=['POST', 'OPTIONS'])
@optional_auth
def add_wallet_quick():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')
        wallet_address = data.get('wallet_address')
        
        if not user_id or not wallet_address:
            return jsonify({'error': 'user_id and wallet_address required'}), 400
        
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        from datetime import datetime
        
        supabase = get_supabase_client()
        
        existing = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select(
            'wallet_address'
        ).eq('user_id', user_id).eq('wallet_address', wallet_address).execute()
        
        if existing.data:
            return jsonify({
                'success': False,
                'error': 'Wallet already in watchlist'
            }), 400
        
        supabase.schema(SCHEMA_NAME).table('wallet_watchlist').insert({
            'user_id': user_id,
            'wallet_address': wallet_address,
            'tier': 'S',
            'position': 1,
            'movement': 'new',
            'positions_changed': 0,
            'form': ['neutral'] * 5,
            'status': 'healthy',
            'degradation_alerts': [],
            'roi_7d': 0,
            'roi_30d': 0,
            'runners_7d': 0,
            'runners_30d': 0,
            'win_rate_7d': 0,
            'professional_score': 0,
            'consistency_score': 0,
            'pump_count': 0,
            'avg_distance_to_peak': 0,
            'avg_roi_to_peak': 0,
            'tokens_hit': [],
            'alert_enabled': True,
            'alert_on_buy': True,
            'alert_on_sell': True,
            'min_trade_usd': 10,
            'tags': data.get('tags', ['stress-test', 'exchange']),
            'notes': data.get('notes', 'Stress test wallet - monitoring 100 transactions'),
            'added_at': datetime.utcnow().isoformat(),
            'last_updated': datetime.utcnow().isoformat(),
            'last_trade_time': None
        }).execute()
        
        print(f"[QUICK ADD] ✅ {wallet_address[:8]}... added to {user_id[:8]}... watchlist")
        
        return jsonify({
            'success': True,
            'message': f'Wallet {wallet_address[:8]}... added to watchlist',
            'alert_config': {
                'enabled': True,
                'on_buy': True,
                'on_sell': True,
                'min_usd': 10
            }
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/premium-elite-100', methods=['GET', 'OPTIONS'])
@optional_auth
def get_premium_elite_100():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
        sort_by = request.args.get('sort_by', 'score')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from services.elite_100_manager import get_elite_manager
        manager = get_elite_manager()
        
        wallets = manager.get_cached_elite_100(sort_by)
        
        return jsonify({
            'success': True,
            'wallets': wallets,
            'total': len(wallets),
            'sort_by': sort_by
        }), 200
        
    except Exception as e:
        print(f"[ELITE 100] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/premium-elite-100/export', methods=['GET', 'OPTIONS'])
@optional_auth
def export_elite_100():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from services.elite_100_manager import get_elite_manager
        import csv
        from io import StringIO
        import time
        
        manager = get_elite_manager()
        wallets = manager.get_cached_elite_100()
        
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            'Rank', 'Wallet Address', 'Tier', 'Professional Score', 
            'ROI 30d', 'Runners 30d', 'Win Rate 7d', 'Win Streak'
        ])
        
        for i, wallet in enumerate(wallets, 1):
            writer.writerow([
                i,
                wallet['wallet_address'],
                wallet['tier'],
                wallet['professional_score'],
                wallet['roi_30d'],
                wallet['runners_30d'],
                wallet['win_rate_7d'],
                wallet['win_streak']
            ])
        
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=elite-100-{int(time.time())}.csv'}
        )
        
    except Exception as e:
        print(f"[ELITE 100 EXPORT] Error: {e}")
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/top-100-community', methods=['GET', 'OPTIONS'])
@optional_auth
def get_top_100_community():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from services.elite_100_manager import get_elite_manager
        manager = get_elite_manager()
        
        wallets = manager.get_cached_community_top_100()
        
        return jsonify({
            'success': True,
            'wallets': wallets,
            'total': len(wallets)
        }), 200
        
    except Exception as e:
        print(f"[COMMUNITY TOP 100] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500