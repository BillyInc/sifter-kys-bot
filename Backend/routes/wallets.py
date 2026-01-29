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
    """Get or create watchlist database instance."""
    global _watchlist_db
    if _watchlist_db is None:
        _watchlist_db = WatchlistDatabase(db_path='watchlists.db')
    return _watchlist_db


def get_wallet_analyzer():
    """Get or create wallet analyzer instance."""
    global _wallet_analyzer
    if _wallet_analyzer is None:
        from services.wallet_analyzer import WalletPumpAnalyzer
        _wallet_analyzer = WalletPumpAnalyzer(
            birdeye_api_key=Config.BIRDEYE_API_KEY
        )
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
        stats = db.get_wallet_stats(user_id)

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
