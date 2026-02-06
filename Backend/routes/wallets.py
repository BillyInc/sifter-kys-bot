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
        _wallet_monitor = WalletActivityMonitor(
            birdeye_api_key=Config.BIRDEYE_API_KEY,
            db_path='watchlists.db',
            poll_interval=120
        )
        _wallet_monitor.start()
        print("[WALLET MONITOR] Started background monitoring")
    return _wallet_monitor


wallets_bp = Blueprint('wallets', __name__, url_prefix='/api/wallets')


# =============================================================================
# WALLET ANALYSIS ENDPOINT
# =============================================================================

@wallets_bp.route('/analyze', methods=['POST'])
@optional_auth
def analyze_wallets():
    """
    Wallet analysis endpoint with ALL-TIME HIGH scoring.
    """
    try:
        from analyzers import PrecisionRallyDetector

        data = request.json
        if not data.get('tokens'):
            return jsonify({'error': 'tokens array required'}), 400

        tokens = data['tokens']
        global_settings = data.get('global_settings', {})

        default_window_before = global_settings.get('wallet_window_before', 35)
        default_window_after = global_settings.get('wallet_window_after', 0)
        min_pump_count = global_settings.get('min_pump_count', 3)

        print(f"\n{'='*100}")
        print(f"WALLET ANALYSIS: {len(tokens)} tokens")
        print(f"Scoring: ALL-TIME HIGH")
        print(f"Window: T-{default_window_before}min to T+{default_window_after}min")
        print(f"Min Pump Count: {min_pump_count}")
        print(f"{'='*100}\n")

        detector = PrecisionRallyDetector(birdeye_api_key=Config.BIRDEYE_API_KEY)
        token_rally_data = []

        for idx, token in enumerate(tokens, 1):
            print(f"\n[{idx}/{len(tokens)}] RALLY DETECTION: {token['ticker']}")

            settings = token.get('settings', {})
            days_back = settings.get('days_back', 7)
            candle_size = settings.get('candle_size', '5m')

            pair_address = token.get('pair_address', token['address'])

            print(f"  Token mint: {token['address'][:8]}...")
            print(f"  Pair address: {pair_address[:8]}...")

            ohlcv_data = detector.get_ohlcv_data(
                pair_address=pair_address,
                chain=token.get('chain', 'solana'),
                days_back=days_back,
                candle_size=candle_size
            )

            if not ohlcv_data:
                print(f"  ❌ No price data")
                continue

            rallies = detector.detect_all_rallies(ohlcv_data)

            if rallies:
                window_before = settings.get('wallet_window_before', default_window_before)
                window_after = settings.get('wallet_window_after', default_window_after)

                token_rally_data.append({
                    'token': {
                        'ticker': token['ticker'],
                        'name': token['name'],
                        'address': token['address'],
                        'pair_address': pair_address,
                        'chain': token.get('chain', 'solana')
                    },
                    'rallies': rallies,
                    'ohlcv_data': ohlcv_data,
                    'window_before': window_before,
                    'window_after': window_after
                })

                print(f"  ✓ Found {len(rallies)} rallies")

        if not token_rally_data:
            return jsonify({
                'success': False,
                'error': 'No rallies detected across any tokens'
            }), 200

        wallet_analyzer = get_wallet_analyzer()

        # Determine window settings
        unique_windows = set(
            (t['window_before'], t['window_after'])
            for t in token_rally_data
        )

        if len(unique_windows) == 1:
            window_before = token_rally_data[0]['window_before']
            window_after = token_rally_data[0]['window_after']
        else:
            from collections import Counter
            most_common_window = Counter(unique_windows).most_common(1)[0][0]
            window_before, window_after = most_common_window
            print(f"\n⚠️ Multiple window configurations detected")
            print(f"   Using most common: T-{window_before}min to T+{window_after}min")

        top_wallets = wallet_analyzer.analyze_multi_token_wallets(
            token_rally_data,
            window_minutes_before=window_before,
            window_minutes_after=window_after,
            min_pump_count=min_pump_count
        )

        wallet_analyzer.display_top_wallets(top_wallets, top_n=50)

        return jsonify({
            'success': True,
            'summary': {
                'tokens_analyzed': len(token_rally_data),
                'total_rallies': sum(len(t['rallies']) for t in token_rally_data),
                'qualified_wallets': len(top_wallets),
                's_tier': len([w for w in top_wallets if w['tier'] == 'S']),
                'a_tier': len([w for w in top_wallets if w['tier'] == 'A']),
                'b_tier': len([w for w in top_wallets if w['tier'] == 'B'])
            },
            'top_wallets': top_wallets,
            'settings': {
                'window_before': window_before,
                'window_after': window_after,
                'min_pump_count': min_pump_count,
                'scoring_method': 'ALL-TIME HIGH',
                'data_source': 'Birdeye /defi/v3/token/txs'
            }
        }), 200

    except Exception as e:
        print(f"\n[WALLET ANALYSIS ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# WALLET WATCHLIST ENDPOINTS
# =============================================================================

@wallets_bp.route('/watchlist/add', methods=['POST'])
@optional_auth
def add_wallet_to_watchlist():
    """Add wallet to watchlist with alert settings."""
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')

        if not user_id or not data.get('wallet'):
            return jsonify({'error': 'user_id and wallet required'}), 400

        db = get_watchlist_db()
        success = db.add_wallet_to_watchlist(user_id, data['wallet'])

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
                data['wallet']['wallet_address'],
                data['alert_settings']
            )

        return jsonify({
            'success': True,
            'message': f"Wallet {data['wallet']['wallet_address'][:8]}... added with alerts"
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/watchlist/get', methods=['GET'])
@optional_auth
def get_wallet_watchlist():
    """Get user's watched wallets."""
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


@wallets_bp.route('/watchlist/remove', methods=['POST'])
@optional_auth
def remove_wallet_from_watchlist():
    """Remove wallet from watchlist."""
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


@wallets_bp.route('/watchlist/update', methods=['POST'])
@optional_auth
def update_wallet_watchlist():
    """Update wallet notes/tags."""
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


@wallets_bp.route('/watchlist/stats', methods=['GET'])
@optional_auth
def get_wallet_watchlist_stats():
    """Get wallet watchlist statistics."""
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

@wallets_bp.route('/activity/recent', methods=['GET'])
@optional_auth
def get_wallet_activity():
    """Get recent wallet activity."""
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


@wallets_bp.route('/notifications', methods=['GET'])
@optional_auth
def get_notifications():
    """Get notifications for a user."""
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


@wallets_bp.route('/notifications/mark-read', methods=['POST'])
@optional_auth
def mark_notifications_read():
    """Mark notification(s) as read."""
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


@wallets_bp.route('/alerts/update', methods=['POST'])
@optional_auth
def update_wallet_alerts():
    """Update alert settings for a wallet."""
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


@wallets_bp.route('/monitor/status', methods=['GET'])
@optional_auth
def get_monitor_status():
    """Get wallet monitor status and statistics."""
    try:
        monitor = get_wallet_monitor()
        stats = monitor.get_monitoring_stats()

        return jsonify({
            'success': True,
            'status': stats
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/monitor/force-check', methods=['POST'])
@optional_auth
def force_check_wallet():
    """Force an immediate check of a specific wallet (for testing)."""
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

# ==========================================
# NEW ENDPOINTS - ADD TO routes/wallets.py
# ==========================================

@wallets_bp.route('/watchlist/table', methods=['GET'])
@optional_auth
def get_watchlist_table():
    """Get Premier League-style watchlist table"""
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
            'promotion_queue': table_data['promotion_queue'],
            'stats': table_data['stats']
        }), 200
        
    except Exception as e:
        print(f"Error getting watchlist table: {e}")
        return jsonify({'error': str(e)}), 500


@wallets_bp.route('/watchlist/suggest-replacement', methods=['POST'])
@optional_auth
def suggest_replacement():
    """Find replacement wallets for degrading wallet"""
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')
        wallet_address = data.get('wallet_address')
        min_score = data.get('min_professional_score', 85)
        
        if not user_id or not wallet_address:
            return jsonify({'error': 'user_id and wallet_address required'}), 400
        
        from services.wallet_analyzer import WalletPumpAnalyzer
        analyzer = WalletPumpAnalyzer()
        
        replacements = analyzer.find_replacement_wallets(
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

# =============================================================================
# PROFESSIONAL 6-STEP ANALYSIS ENDPOINTS (Enhanced)
# =============================================================================

@wallets_bp.route('/analyze/single', methods=['POST'])
@optional_auth
def analyze_single_token():
    """Single token with professional 6-step analysis + 30-day dropdown."""
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


@wallets_bp.route('/trending/runners', methods=['GET'])
@optional_auth
def get_trending_runners():
    """Enhanced trending runners with professional discovery."""
    try:
        import traceback

        timeframe = request.args.get('timeframe', '24h')
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

        days_map = {'24h': 1, '7d': 7, '30d': 30}
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


@wallets_bp.route('/watchlist/replace', methods=['POST'])
@optional_auth
def replace_wallet():
    """Replace degrading wallet with new one"""
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
        return jsonify({'error': str(e)}), 500
@wallets_bp.route('/trending/analyze', methods=['POST'])
@optional_auth
def analyze_trending_runner():
    """Analyze a single trending runner using 6-step professional analysis."""
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


@wallets_bp.route('/discover', methods=['POST'])
@optional_auth
def auto_discover_wallets():
    """Auto-discover professional wallets using trending runners."""
    try:
        import traceback

        data = request.json or {}
        user_id = getattr(request, 'user_id', None) or data.get('user_id', 'default_user')
        min_runner_hits = data.get('min_runner_hits', 2)
        days_back = data.get('days_back', 7)
        min_roi_multiplier = data.get('min_roi_multiplier', 3.0)

        wallet_analyzer = get_wallet_analyzer()

        print(f"\n{'='*80}")
        print(f"AUTO-DISCOVER WALLETS (Professional)")
        print(f"Days: {days_back} | Min Hits: {min_runner_hits}")
        print(f"{'='*80}")

        # Step 1: Find trending runners
        runners = wallet_analyzer.find_trending_runners_enhanced(
            days_back=days_back,
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
            runners_list=runners[:10],  # Limit to top 10 runners
            min_runner_hits=min_runner_hits,
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )

        return jsonify({
            'success': True,
            'runners_analyzed': min(len(runners), 10),
            'wallets_discovered': len(smart_money),
            'top_wallets': smart_money[:50],
            'discovery_settings': {
                'days_back': days_back,
                'min_runner_hits': min_runner_hits,
                'min_roi_multiplier': min_roi_multiplier
            }
        }), 200

    except Exception as e:
        print(f"\n[DISCOVER ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
