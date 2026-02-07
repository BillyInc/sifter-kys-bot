"""Wallet analysis and watchlist API routes."""
from flask import Blueprint, request, jsonify

from config import Config
from auth import require_auth, optional_auth
from db.watchlist_db import WatchlistDatabase

# Lazy imports to avoid circular dependencies
_wallet_analyzer = None
_wallet_monitor = None
_watchlist_db = None


def get_watchlist_db():
    """Get or create watchlist database instance (now uses Supabase)."""
    global _watchlist_db
    if _watchlist_db is None:
        _watchlist_db = WatchlistDatabase()
    return _watchlist_db


def get_wallet_analyzer():
    """Get or create wallet analyzer instance (enhanced with 6-step professional analysis)."""
    global _wallet_analyzer
    if _wallet_analyzer is None:
        from services.wallet_analyzer import WalletPumpAnalyzer
        _wallet_analyzer = WalletPumpAnalyzer(
            solanatracker_api_key=Config.SOLANATRACKER_API_KEY,
            birdeye_api_key=Config.BIRDEYE_API_KEY,
            debug_mode=True
        )
        print("[WALLET ANALYZER] Initialized with 6-step professional analysis")
    return _wallet_analyzer


def get_wallet_monitor():
    """Get or create wallet monitor instance."""
    global _wallet_monitor
    if _wallet_monitor is None:
        from services.wallet_monitor import WalletActivityMonitor
        from flask import current_app  # ← ADD THIS
        telegram_notifier = current_app.config.get('TELEGRAM_NOTIFIER')  # ← ADD THIS

        _wallet_monitor = WalletActivityMonitor(
            birdeye_api_key=Config.BIRDEYE_API_KEY,
            db_path='watchlists.db',
            poll_interval=120,
            telegram_notifier=telegram_notifier  # ← ADD THIS
        )
        _wallet_monitor.start()
        print("[WALLET MONITOR] Started background monitoring")
        if telegram_notifier:  # ← ADD THIS
            print("[WALLET MONITOR] ✅ Telegram alerts ENABLED")
        else:
            print("[WALLET MONITOR] ⚠️ Telegram alerts DISABLED")
    return _wallet_monitor

wallets_bp = Blueprint('wallets', __name__, url_prefix='/api/wallets')


# =============================================================================
# WALLET ANALYSIS ENDPOINT (FIXED - NOW USES 6-STEP ANALYSIS)
# =============================================================================

@wallets_bp.route('/analyze', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_wallets():
    """
    ✅ FIXED: General wallet analysis using 6-step professional method.
    
    FIXES:
    1. Cross-token deduplication (keep highest professional_score)
    2. Remove pump-related fields from response
    3. Track which tokens were analyzed
    """
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        if not data.get('tokens'):
            return jsonify({'error': 'tokens array required'}), 400

        tokens = data['tokens']
        min_roi_multiplier = data.get('global_settings', {}).get('min_roi_multiplier', 3.0)
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')

        print(f"\n{'='*80}")
        print(f"GENERAL WALLET ANALYSIS: {len(tokens)} tokens")
        print(f"Using 6-Step Professional Analysis")
        print(f"Min ROI: {min_roi_multiplier}x")
        print(f"{'='*80}\n")

        wallet_analyzer = get_wallet_analyzer()
        
        # ✅ STEP 1: Collect ALL wallets from ALL selected tokens
        wallet_map = {}  # {wallet_address: wallet_data}
        
        for idx, token in enumerate(tokens, 1):
            print(f"\n[{idx}/{len(tokens)}] ANALYZING: {token['ticker']}")
            
            # Run 6-step analysis
            wallets = wallet_analyzer.analyze_token_professional(
                token_address=token['address'],
                token_symbol=token.get('ticker', 'UNKNOWN'),
                min_roi_multiplier=min_roi_multiplier,
                user_id=user_id
            )
            
            # ✅ STEP 2: Deduplicate - keep highest professional_score per wallet
            for wallet in wallets:
                addr = wallet['wallet']
                
                if addr not in wallet_map:
                    # First time seeing this wallet
                    wallet_map[addr] = wallet
                    wallet_map[addr]['analyzed_tokens'] = [token['ticker']]
                else:
                    # Wallet already exists - compare scores
                    if wallet['professional_score'] > wallet_map[addr]['professional_score']:
                        # This token gave better score - replace
                        wallet_map[addr] = wallet
                        wallet_map[addr]['analyzed_tokens'] = [token['ticker']]
                    else:
                        # Keep existing score, but track this token too
                        if token['ticker'] not in wallet_map[addr]['analyzed_tokens']:
                            wallet_map[addr]['analyzed_tokens'].append(token['ticker'])

        # ✅ STEP 3: Rank by professional score (cross-token)
        all_wallets = list(wallet_map.values())
        all_wallets.sort(key=lambda x: x['professional_score'], reverse=True)
        
        # ✅ STEP 4: Top 20 only
        top_wallets = all_wallets[:20]

        # ✅ STEP 5: Remove pump-related fields from response
        for wallet in top_wallets:
            # ❌ REMOVE these fields (pump-based, not in general mode)
            wallet.pop('pump_count', None)
            wallet.pop('in_window_count', None)
            wallet.pop('avg_distance_to_ath_pct', None)
            wallet.pop('rally_history', None)

        return jsonify({
            'success': True,
            'summary': {
                'tokens_analyzed': len(tokens),
                'qualified_wallets': len(top_wallets),
                'a_plus_tier': len([w for w in top_wallets if w.get('professional_grade') == 'A+']),
            },
            'top_wallets': top_wallets,
            'mode': 'general_6step_cross_token',
            'data_source': '6-Step Professional Analysis (Cross-Token Ranking)'
        }), 200

    except Exception as e:
        print(f"\n[ANALYSIS ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# =============================================================================
# WALLET WATCHLIST ENDPOINTS
# =============================================================================

@wallets_bp.route('/watchlist/add', methods=['POST', 'OPTIONS'])
@optional_auth
def add_wallet_to_watchlist():
    """✅ FIXED: Add wallet to watchlist with correct schema."""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')

        if not user_id or not data.get('wallet'):
            return jsonify({'error': 'user_id and wallet required'}), 400

        wallet_data = data['wallet']
        
        # ✅ FIX: Map frontend fields to correct DB schema
        db_wallet = {
            'wallet_address': wallet_data.get('wallet'),  # ✅ 'wallet' → 'wallet_address'
            'tier': wallet_data.get('tier', 'C'),
            'pump_count': wallet_data.get('pump_count', 0),
            'avg_distance_to_peak': wallet_data.get('avg_distance_to_ath_pct', 0),
            'avg_roi_to_peak': wallet_data.get('avg_roi_to_peak_pct', 0),
            'consistency_score': wallet_data.get('consistency_score', 0),
            'tokens_hit': wallet_data.get('token_list', [])  # ✅ 'token_list' → 'tokens_hit'
        }

        db = get_watchlist_db()
        success = db.add_wallet_to_watchlist(user_id, db_wallet)

        if not success:
            return jsonify({
                'success': False,
                'error': 'Wallet already in watchlist'
            }), 400

        # Update alert settings if provided
        if data.get('alert_settings'):
            from services.wallet_monitor import update_alert_settings
            update_alert_settings(
                'watchlists.db',
                user_id,
                db_wallet['wallet_address'],
                data['alert_settings']
            )

        return jsonify({
            'success': True,
            'message': f"Wallet {db_wallet['wallet_address'][:8]}... added with alerts"
        }), 200

    except Exception as e:
        print(f"[WATCHLIST ADD ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@wallets_bp.route('/watchlist/get', methods=['GET', 'OPTIONS'])
@optional_auth
def get_wallet_watchlist():
    """Get user's watched wallets."""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
        tier = request.args.get('tier')

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        db = get_watchlist_db()
        wallets = db.get_wallet_watchlist(user_id, tier)

        return jsonify({
            'success': True,
            'wallets': wallets,
            'count': len(wallets)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/watchlist/remove', methods=['POST', 'OPTIONS'])
@optional_auth
def remove_wallet_from_watchlist():
    """Remove wallet from watchlist."""
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
    """Update wallet notes/tags."""
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
    """Get wallet watchlist statistics."""
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


# =============================================================================
# WALLET ACTIVITY & NOTIFICATION ENDPOINTS
# =============================================================================

@wallets_bp.route('/activity/recent', methods=['GET', 'OPTIONS'])
@optional_auth
def get_wallet_activity():
    """Get recent wallet activity."""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        from services.wallet_monitor import get_recent_wallet_activity

        wallet_address = request.args.get('wallet_address')
        limit = int(request.args.get('limit', 50))

        activities = get_recent_wallet_activity(
            db_path='watchlists.db',
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
    """Get notifications for a user."""
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
            db_path='watchlists.db',
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
    """Mark notification(s) as read."""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        from services.wallet_monitor import mark_notification_read, mark_all_notifications_read

        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        if data.get('mark_all'):
            count = mark_all_notifications_read('watchlists.db', user_id)
            return jsonify({
                'success': True,
                'message': f'{count} notification(s) marked as read'
            }), 200

        elif data.get('notification_id'):
            success = mark_notification_read(
                'watchlists.db',
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
    """Update alert settings for a wallet."""
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
            'watchlists.db',
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
    """Get wallet monitor status and statistics."""
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
    """Force an immediate check of a specific wallet (for testing)."""
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


# =============================================================================
# WATCHLIST TABLE & REPLACEMENT ENDPOINTS
# =============================================================================

@wallets_bp.route('/watchlist/table', methods=['GET', 'OPTIONS'])
@optional_auth
def get_watchlist_table():
    """Get Premier League-style watchlist table"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from db.watchlist_db import WatchlistDatabase
        db = WatchlistDatabase(db_path='watchlists.db')
        
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
    """Find replacement wallets for degrading wallet"""
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
        print(f"[REPLACEMENT FINDER ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/watchlist/replace', methods=['POST', 'OPTIONS'])
@optional_auth
def replace_wallet():
    """Replace degrading wallet with new one"""
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
        db = WatchlistDatabase(db_path='watchlists.db')
        
        # Remove old wallet
        db.remove_wallet_from_watchlist(user_id, old_wallet)
        
        # Add new wallet
        db.add_wallet_to_watchlist(
            user_id=user_id,
            wallet_address=new_wallet_data['wallet'],
            tier=new_wallet_data.get('tier', 'C'),
            avg_professional_score=new_wallet_data.get('professional_score', 0),
            avg_roi_to_peak=new_wallet_data.get('roi_multiplier', 0) * 100,
            pump_count=new_wallet_data.get('runner_hits_30d', 0),
            consistency_score=new_wallet_data.get('consistency_score', 0)
        )
        
        return jsonify({
            'success': True,
            'message': 'Wallet replaced successfully',
            'old_wallet': old_wallet,
            'new_wallet': new_wallet_data['wallet']
        }), 200
        
    except Exception as e:
        print(f"Error replacing wallet: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# PROFESSIONAL 6-STEP ANALYSIS ENDPOINTS (ENHANCED)
# =============================================================================

@wallets_bp.route('/analyze/single', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_single_token():
    """Single token with professional 6-step analysis + 30-day dropdown."""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        import traceback

        data = request.json
        if not data.get('token'):
            return jsonify({'error': 'token object required'}), 400

        token = data['token']
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')

        wallet_analyzer = get_wallet_analyzer()

        print(f"\n{'='*80}")
        print(f"SINGLE TOKEN ANALYSIS (6-STEP): {token.get('ticker', 'UNKNOWN')}")
        print(f"{'='*80}")

        wallets = wallet_analyzer.analyze_token_professional(
            token_address=token['address'],
            token_symbol=token.get('ticker', 'UNKNOWN'),
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )

        return jsonify({
            'success': True,
            'token': token,
            'wallets': wallets[:50],
            'total_wallets': len(wallets),
            'mode': 'professional_general_6step',
            'data_source': '6-Step Professional Analyzer',
            'features': {
                'professional_scoring': '60% Timing, 30% Profit, 10% Overall',
                '30day_runner_tracking': True,
                'dropdown_data': True,
                'birdeye_depth': True
            },
            'professional_summary': {
                'avg_professional_score': round(sum(w.get('professional_score', 0) for w in wallets)/len(wallets) if wallets else 0, 2),
                'a_plus_wallets': sum(1 for w in wallets if w.get('professional_grade') == 'A+'),
                'avg_runner_hits': round(sum(w.get('runner_hits_30d', 0) for w in wallets)/len(wallets) if wallets else 0, 1)
            }
        }), 200

    except Exception as e:
        print(f"\n[SINGLE TOKEN ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# TRENDING RUNNERS ENDPOINT (FIXED)
# =============================================================================

@wallets_bp.route('/trending/runners', methods=['GET','OPTIONS'])
@optional_auth
def get_trending_runners():
    """
    ✅ FIXED: Enhanced trending runners with 7d/14d/30d timeframes.
    
    Changes from original:
    1. Changed timeframe mapping from 24h/7d/30d to 7d/14d/30d
    2. Default changed from 24h to 7d
    3. Added OPTIONS method for CORS
    4. Removed candle_timeframe parameter (not needed - auto-selected)
    """
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        import traceback

        # ✅ NEW: 7d/14d/30d only (no 24h)
        timeframe = request.args.get('timeframe', '7d')
        min_liquidity = float(request.args.get('min_liquidity', 50000))
        min_multiplier = float(request.args.get('min_multiplier', 5))
        min_age_days = int(request.args.get('min_age_days', 0))
        max_age_days_raw = request.args.get('max_age_days', None)
        max_age_days = int(max_age_days_raw) if max_age_days_raw else 30

        wallet_analyzer = get_wallet_analyzer()

        print(f"\n{'='*80}")
        print(f"TRENDING RUNNERS DISCOVERY")
        print(f"Timeframe: {timeframe} | Min: {min_multiplier}x")
        print(f"{'='*80}")

        # ✅ NEW MAPPING: 7d/14d/30d only
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

        print(f"Found {len(filtered_runners)} trending runners")

        return jsonify({
            'success': True,
            'runners': filtered_runners,
            'total': len(filtered_runners),
            'data_source': 'Professional Trending Discovery',
            'filters_applied': {
                'timeframe': timeframe,
                'min_liquidity': min_liquidity,
                'min_multiplier': min_multiplier,
                'min_age_days': min_age_days,
                'max_age_days': max_age_days
            }
        }), 200

    except Exception as e:
        print(f"\n[TRENDING RUNNERS ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/trending/analyze', methods=['POST', 'OPTIONS'])
@optional_auth
def analyze_trending_runner():
    """Analyze a single trending runner using 6-step professional analysis."""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        import traceback

        data = request.json
        if not data.get('runner'):
            return jsonify({'error': 'runner object required'}), 400

        runner = data['runner']
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')

        wallet_analyzer = get_wallet_analyzer()

        print(f"\n{'='*80}")
        print(f"RUNNER ANALYSIS (6-STEP): {runner.get('symbol', 'UNKNOWN')}")
        print(f"{'='*80}")

        wallets = wallet_analyzer.analyze_token_professional(
            token_address=runner['address'],
            token_symbol=runner.get('symbol', 'UNKNOWN'),
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )

        return jsonify({
            'success': True,
            'runner': runner,
            'wallets': wallets[:50],
            'total_wallets': len(wallets),
            'mode': 'professional_runner_6step',
            'professional_summary': {
                'avg_professional_score': round(sum(w.get('professional_score', 0) for w in wallets)/len(wallets) if wallets else 0, 2),
                'a_plus_wallets': sum(1 for w in wallets if w.get('professional_grade') == 'A+'),
            }
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
    ✅ NEW: Batch analyze multiple trending runners at once
    Accepts array of runners and returns combined smart money analysis
    """
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        import traceback

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
        print(f"{'='*80}")

        # Use batch analysis for cross-runner consistency
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
            'mode': 'batch_trending_analysis',
            'consistency_summary': {
                'avg_runner_hits': round(sum(w['runner_count'] for w in smart_money) / len(smart_money) if smart_money else 0, 1),
                'a_plus_consistency': sum(1 for w in smart_money if w.get('consistency_grade') == 'A+'),
                'high_variance_wallets': sum(1 for w in smart_money if w.get('variance', 0) > 30)
            }
        }), 200

    except Exception as e:
        print(f"\n[BATCH TRENDING ANALYSIS ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# AUTO-DISCOVERY ENDPOINT (FIXED)
# =============================================================================

@wallets_bp.route('/discover', methods=['POST','OPTIONS'])
@optional_auth
def auto_discover_wallets():
    """
    ✅ FIXED: Auto-discover professional wallets using trending runners (ALWAYS 30 days).
    
    Changes from original:
    1. Forced days_back = 30 (always 30 days for auto-discovery)
    2. Added OPTIONS method for CORS
    3. Added smart_money_wallets alias for frontend compatibility
    """
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        import traceback

        data = request.json or {}
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')
        min_runner_hits = data.get('min_runner_hits', 2)
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
        
        # ✅ FORCE 30 DAYS for auto-discovery
        days_back = 30

        wallet_analyzer = get_wallet_analyzer()

        print(f"\n{'='*80}")
        print(f"AUTO-DISCOVER WALLETS (Professional)")
        print(f"Days: {days_back} (FIXED) | Min Hits: {min_runner_hits}")
        print(f"{'='*80}")

        # Step 1: Find trending runners (30 days)
        runners = wallet_analyzer.find_trending_runners_enhanced(
            days_back=30,  # ✅ Always 30
            min_multiplier=5.0,
            min_liquidity=50000
        )

        if not runners:
            return jsonify({
                'success': False,
                'error': 'No trending runners found'
            }), 200

        print(f"Found {len(runners)} trending runners, analyzing...")

        # Step 2: Batch analyze runners
        smart_money = wallet_analyzer.batch_analyze_runners_professional(
            runners_list=runners[:10],  # Top 10 hottest runners
            min_runner_hits=min_runner_hits,
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )

        return jsonify({
            'success': True,
            'runners_analyzed': min(len(runners), 10),
            'wallets_discovered': len(smart_money),
            'top_wallets': smart_money[:50],
            'smart_money_wallets': smart_money[:50],  # ✅ Alias for frontend compatibility
            'discovery_settings': {
                'days_back': 30,  # ✅ Always 30
                'min_runner_hits': min_runner_hits,
                'min_roi_multiplier': min_roi_multiplier
            }
        }), 200

    except Exception as e:
        print(f"\n[DISCOVER ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500