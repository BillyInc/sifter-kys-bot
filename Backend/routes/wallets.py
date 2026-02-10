"""Wallet analysis routes - CORRECTLY FIXED for TOKEN OVERLAP ranking."""
from flask import Blueprint, request, jsonify

from config import Config
from auth import require_auth, optional_auth
from db.watchlist_db import WatchlistDatabase
from collections import defaultdict

# Lazy imports
_wallet_analyzer = None
_wallet_monitor = None
_watchlist_db = None


def get_watchlist_db():
    global _watchlist_db
    if _watchlist_db is None:
        _watchlist_db = WatchlistDatabase()
    return _watchlist_db


def get_wallet_analyzer():
    global _wallet_analyzer
    if _wallet_analyzer is None:
        from services.wallet_analyzer import WalletPumpAnalyzer
        _wallet_analyzer = WalletPumpAnalyzer(
            solanatracker_api_key=Config.SOLANATRACKER_API_KEY,
            birdeye_api_key=Config.BIRDEYE_API_KEY,
            debug_mode=True
        )
        print("[WALLET ANALYZER] ✅ Initialized with TokenAnalyzer relative scoring")
    return _wallet_analyzer


def get_wallet_monitor():
    global _wallet_monitor
    if _wallet_monitor is None:
        from services.wallet_monitor import WalletActivityMonitor
        from flask import current_app
        telegram_notifier = current_app.config.get('TELEGRAM_NOTIFIER')

        _wallet_monitor = WalletActivityMonitor(
            birdeye_api_key=Config.BIRDEYE_API_KEY,
            poll_interval=120,
            telegram_notifier=telegram_notifier
        )
        _wallet_monitor.start()
        print("[WALLET MONITOR] Started background monitoring (Supabase)")
    return _wallet_monitor

wallets_bp = Blueprint('wallets', __name__, url_prefix='/api/wallets')


# =============================================================================
# ✅ CORRECTLY FIXED: TOKEN OVERLAP BATCH ANALYSIS
# =============================================================================

@wallets_bp.route('/analyze', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_wallets():
    if request.method == 'OPTIONS':
        return '', 204
    
    data = request.json
    # ... (your validation)
    
    from flask import current_app
    q = current_app.config['RQ_QUEUE']
    job = q.enqueue('tasks.perform_wallet_analysis', data, job_timeout=600)  # tasks.py function
    return jsonify({'job_id': job.id, 'status': 'queued'}), 202

@wallets_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job_status(job_id):
    from flask import current_app
    q = current_app.config['RQ_QUEUE']
    job = q.fetch_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    if job.is_finished:
        # Get result from Redis
        from redis import Redis
        redis = Redis(host='localhost', port=6379)
        import json
        result = redis.get(f"job_result:{job_id}")
        if result:
            return jsonify(json.loads(result)), 200
        return jsonify({'error': 'Result expired'}), 404
    elif job.is_failed:
        return jsonify({'status': 'failed', 'error': str(job.exc_info)}), 500
    return jsonify({'status': job.get_status()}), 200


# =============================================================================
# SINGLE TOKEN ANALYSIS (NO TOKEN OVERLAP - JUST RELATIVE SCORING)
# =============================================================================

@wallets_bp.route('/analyze/single', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_single_token():
    """
    Single token analysis - Just relative scoring within that token
    (No token overlap needed - only 1 token)
    """
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
        top_wallets = wallets[:20]
        return jsonify({
            'success': True,
            'token': token,
            'wallets': top_wallets,
            'total_wallets': len(wallets),
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
                'avg_variance': 0,  # Single token has no variance
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
    """Get trending runners list"""
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
        }), 200

    except Exception as e:
        print(f"\n[TRENDING RUNNERS ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/trending/analyze', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_trending_runner():
    """Analyze single trending runner"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        if not data.get('runner'):
            return jsonify({'error': 'runner object required'}), 400

        runner = data['runner']
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')

        wallet_analyzer = get_wallet_analyzer()

        wallets = wallet_analyzer.analyze_token_professional(
            token_address=runner['address'],
            token_symbol=runner.get('symbol', 'UNKNOWN'),
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )

        return jsonify({
            'success': True,
            'runner': runner,
            'wallets': wallets[:20],
            'total_wallets': len(wallets),
        }), 200

    except Exception as e:
        print(f"\n[RUNNER ANALYSIS ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/trending/analyze-batch', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_trending_runners_batch():
    """
    ✅ CORRECT: Batch trending analysis with TOKEN OVERLAP ranking
    """
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        if not data.get('runners'):
            return jsonify({'error': 'runners array required'}), 400

        runners = data['runners']
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        min_runner_hits = data.get('min_runner_hits', 2)
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')

        wallet_analyzer = get_wallet_analyzer()

        print(f"\n{'='*80}")
        print(f"BATCH TRENDING ANALYSIS: {len(runners)} runners")
        print(f"Using TokenAnalyzer Token Overlap Method")
        print(f"{'='*80}")

        # Use built-in batch analysis (already has token overlap logic)
        smart_money = wallet_analyzer.batch_analyze_runners_professional(
            runners_list=runners,
            min_runner_hits=min_runner_hits,
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )

        return jsonify({
            'success': True,
            'runners_analyzed': len(runners),
            'wallets_discovered': len(smart_money),
            'smart_money_wallets': smart_money[:50],
            'mode': 'batch_trending_token_overlap',
        }), 200

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
    """Auto-discover using trending runners (30 days)"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json or {}
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')
        min_runner_hits = data.get('min_runner_hits', 2)
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)

        wallet_analyzer = get_wallet_analyzer()

        runners = wallet_analyzer.find_trending_runners_enhanced(
            days_back=30,
            min_multiplier=5.0,
            min_liquidity=50000
        )

        if not runners:
            return jsonify({
                'success': False,
                'error': 'No trending runners found'
            }), 200

        smart_money = wallet_analyzer.batch_analyze_runners_professional(
            runners_list=runners[:10],
            min_runner_hits=min_runner_hits,
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )

        return jsonify({
            'success': True,
            'runners_analyzed': min(len(runners), 10),
            'wallets_discovered': len(smart_money),
            'top_wallets': smart_money[:50],
            'smart_money_wallets': smart_money[:50],
        }), 200

    except Exception as e:
        print(f"\n[DISCOVER ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# WATCHLIST ENDPOINTS (unchanged from before)
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

# Find this function in routes/wallets.py and REPLACE it:

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
        
        # SELECT with ALL new columns
        query = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select(
            'wallet_address, tier, position, movement, positions_changed, '
            'form, status, degradation_alerts, roi_7d, roi_30d, '
            'runners_7d, runners_30d, win_rate_7d, last_trade_time, '
            'professional_score, consistency_score, pump_count, '
            'avg_distance_to_peak, avg_roi_to_peak, tokens_hit, '
            'tags, notes, alert_enabled, alert_threshold_usd, '
            'added_at, last_updated'
        ).eq('user_id', user_id)
        
        if tier:
            query = query.eq('tier', tier)
        
        # ORDER BY position
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

        if not user_id or not data.get('wallet_address'):
            return jsonify({'error': 'user_id and wallet_address required'}), 400

        db = get_watchlist_db()
        success = db.remove_wallet_from_watchlist(user_id, data['wallet_address'])

        if success:
            return jsonify({
                'success': True,
                'message': 'Wallet removed from watchlist'
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to remove wallet'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
    
# Add to routes/wallets.py (around line 400, after other watchlist routes)

@wallets_bp.route('/watchlist/rerank', methods=['POST', 'OPTIONS'])
@require_auth
def rerank_watchlist():
    """Manually trigger watchlist rerank"""
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

# Activity/notification endpoints continue...
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

        # Build wallet_data dict for add_wallet_to_watchlist
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