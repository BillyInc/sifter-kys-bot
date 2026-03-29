"""
Referral & Points API Routes
"""
import logging
import os
from flask import Blueprint, request, jsonify
from auth import require_auth, optional_auth
from services.referral_points_manager import get_referral_manager
from repositories.registry import get_referral_repo

logger = logging.getLogger(__name__)

referral_points_bp = Blueprint('referral_points', __name__, url_prefix='/api/referral-points')


# =============================================================================
# REFERRAL ROUTES
# =============================================================================

@referral_points_bp.route('/referral-code', methods=['GET'])
@require_auth
def get_my_referral_code():
    """Get user's referral code"""
    try:
        user_id = getattr(request, 'user_id', None)

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        manager = get_referral_manager()
        code = manager.get_referral_code(user_id)

        if not code:
            return jsonify({'error': 'Failed to generate code'}), 500

        # Get code stats
        repo = get_referral_repo()
        code_stats = repo.get_referral_code_stats(code) or {}

        return jsonify({
            'success': True,
            'code': code,
            'referral_link': f"{os.environ.get('FRONTEND_URL', 'https://sifter-kys-web.duckdns.org')}?ref={code}",
            'stats': {
                'clicks': code_stats.get('clicks', 0),
                'signups': code_stats.get('signups', 0),
                'conversions': code_stats.get('conversions', 0)
            }
        }), 200

    except Exception as e:
        print(f"[API] Error getting referral code: {e}")
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


@referral_points_bp.route('/referral-stats', methods=['GET'])
@require_auth
def get_referral_stats():
    """Get user's referral earnings and statistics"""
    try:
        user_id = getattr(request, 'user_id', None)

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        repo = get_referral_repo()

        # Get all referrals
        referrals_data = repo.get_referrals_by_referrer(user_id)

        # Get earnings breakdown
        earnings_data = repo.get_earnings_by_referrer(user_id)

        # Calculate totals
        total_signups = len([r for r in referrals_data if r['status'] in ['signed_up', 'converted']])
        total_conversions = len([r for r in referrals_data if r['status'] == 'converted'])

        total_earnings = sum(r['total_earnings'] or 0 for r in referrals_data)
        total_pending = sum(
            e['amount'] for e in earnings_data
            if e['payment_status'] == 'pending'
        )
        total_paid = sum(
            e['amount'] for e in earnings_data
            if e['payment_status'] == 'paid'
        )

        # Active referrals (converted and not cancelled)
        active_referrals = [
            {
                'user_id': r['referee_user_id'],
                'email': r['referee_email'],
                'tier': r['referee_tier'],
                'converted_at': r['converted_at'],
                'total_earned': r['total_earnings']
            }
            for r in referrals_data if r['status'] == 'converted'
        ]

        return jsonify({
            'success': True,
            'stats': {
                'total_signups': total_signups,
                'total_conversions': total_conversions,
                'conversion_rate': (total_conversions / total_signups * 100) if total_signups > 0 else 0,
                'total_earnings': total_earnings,
                'total_pending': total_pending,
                'total_paid': total_paid
            },
            'active_referrals': active_referrals,
            'recent_earnings': earnings_data[:10]  # Last 10 earnings
        }), 200

    except Exception as e:
        print(f"[API] Error getting referral stats: {e}")
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


@referral_points_bp.route('/track-click/<code>', methods=['POST'])
def track_referral_click(code):
    """Track click on referral link"""
    try:
        manager = get_referral_manager()
        manager.track_referral_click(code)

        return jsonify({'success': True}), 200

    except Exception as e:
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


@referral_points_bp.route('/validate-code/<code>', methods=['GET'])
def validate_referral_code(code):
    """Validate referral code"""
    try:
        repo = get_referral_repo()
        result = repo.validate_referral_code(code)

        if result:
            return jsonify({
                'valid': True,
                'code': code
            }), 200
        else:
            return jsonify({
                'valid': False,
                'error': 'Invalid or inactive code'
            }), 404

    except Exception as e:
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


# =============================================================================
# POINTS ROUTES
# =============================================================================

@referral_points_bp.route('/points', methods=['GET'])
@require_auth
def get_my_points():
    """Get user's point balance and stats"""
    try:
        user_id = getattr(request, 'user_id', None)

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        manager = get_referral_manager()
        points_data = manager.get_user_points(user_id)

        return jsonify({
            'success': True,
            'points': points_data
        }), 200

    except Exception as e:
        print(f"[API] Error getting points: {e}")
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


@referral_points_bp.route('/points/award', methods=['POST'])
@require_auth
def award_points_manual():
    """Award points for an action (called by frontend)"""
    try:
        user_id = getattr(request, 'user_id', None)
        data = request.json

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        action_type = data.get('action_type')
        metadata = data.get('metadata', {})

        if not action_type:
            return jsonify({'error': 'action_type required'}), 400

        manager = get_referral_manager()

        # Update streak if login action
        if action_type == 'daily_login':
            streak = manager.update_streak(user_id)
            metadata['streak'] = streak

        points_earned = manager.award_points(user_id, action_type, metadata)

        return jsonify({
            'success': True,
            'points_earned': points_earned,
            'action_type': action_type
        }), 200

    except Exception as e:
        print(f"[API] Error awarding points: {e}")
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


@referral_points_bp.route('/points/leaderboard', methods=['GET'])
@optional_auth
def get_points_leaderboard():
    """Get points leaderboard"""
    try:
        limit = min(int(request.args.get('limit', 100)), 200)
        offset = max(int(request.args.get('offset', 0)), 0)
        leaderboard_type = request.args.get('type', 'lifetime')  # 'lifetime' or 'current'

        manager = get_referral_manager()
        leaderboard = manager.get_leaderboard(limit + offset, leaderboard_type)
        leaderboard = leaderboard[offset:offset + limit]

        # Get user's rank if authenticated
        user_id = getattr(request, 'user_id', None)
        user_rank = None

        if user_id:
            for i, entry in enumerate(leaderboard, 1):
                if entry['user_id'] == user_id:
                    user_rank = i
                    break

        return jsonify({
            'success': True,
            'leaderboard': leaderboard,
            'user_rank': user_rank,
            'type': leaderboard_type,
            'limit': limit,
            'offset': offset,
        }), 200

    except Exception as e:
        print(f"[API] Error getting leaderboard: {e}")
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


@referral_points_bp.route('/points/history', methods=['GET'])
@require_auth
def get_points_history():
    """Get user's point transaction history"""
    try:
        user_id = getattr(request, 'user_id', None)
        limit = int(request.args.get('limit', 50))

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        repo = get_referral_repo()
        transactions = repo.get_point_transactions(user_id, limit)

        return jsonify({
            'success': True,
            'transactions': transactions
        }), 200

    except Exception as e:
        print(f"[API] Error getting history: {e}")
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


# =============================================================================
# COMBINED DASHBOARD
# =============================================================================

@referral_points_bp.route('/dashboard', methods=['GET'])
@require_auth
def get_dashboard():
    """Get combined referral + points dashboard data"""
    try:
        user_id = getattr(request, 'user_id', None)

        if not user_id:
            return jsonify({'error': 'user_id required'}), 400

        manager = get_referral_manager()

        # Get referral code
        code = manager.get_referral_code(user_id)

        # Get referral stats
        repo = get_referral_repo()

        referrals_data = repo.get_referrals_by_referrer(user_id)
        code_stats = repo.get_referral_code_stats(code) if code else None

        total_conversions = len([r for r in referrals_data if r['status'] == 'converted'])
        total_earnings = sum(r['total_earnings'] or 0 for r in referrals_data)

        # Get points
        points_data = manager.get_user_points(user_id)

        # Get user's rank
        leaderboard = manager.get_leaderboard(1000, 'lifetime')
        user_rank = next(
            (i for i, entry in enumerate(leaderboard, 1) if entry['user_id'] == user_id),
            None
        )

        return jsonify({
            'success': True,
            'referrals': {
                'code': code,
                'link': f"{os.environ.get('FRONTEND_URL', 'https://sifter-kys-web.duckdns.org')}?ref={code}",
                'stats': code_stats or {},
                'conversions': total_conversions,
                'total_earnings': total_earnings
            },
            'points': {
                'total': points_data.get('total_points', 0),
                'lifetime': points_data.get('lifetime_points', 0),
                'streak': points_data.get('daily_streak', 0),
                'level': points_data.get('level', 1),
                'rank': user_rank
            }
        }), 200

    except Exception as e:
        print(f"[API] Error getting dashboard: {e}")
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500
