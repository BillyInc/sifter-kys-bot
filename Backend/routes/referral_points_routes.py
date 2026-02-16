"""
Referral & Points API Routes
"""
from flask import Blueprint, request, jsonify
from auth import require_auth, optional_auth
from services.referral_points_manager import get_referral_manager

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
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        stats = supabase.schema(SCHEMA_NAME).table('referral_codes').select(
            'clicks, signups, conversions'
        ).eq('code', code).limit(1).execute()
        
        code_stats = stats.data[0] if stats.data else {}
        
        return jsonify({
            'success': True,
            'code': code,
            'referral_link': f"https://your-app.com/signup?ref={code}",
            'stats': {
                'clicks': code_stats.get('clicks', 0),
                'signups': code_stats.get('signups', 0),
                'conversions': code_stats.get('conversions', 0)
            }
        }), 200
        
    except Exception as e:
        print(f"[API] Error getting referral code: {e}")
        return jsonify({'error': str(e)}), 500


@referral_points_bp.route('/referral-stats', methods=['GET'])
@require_auth
def get_referral_stats():
    """Get user's referral earnings and statistics"""
    try:
        user_id = getattr(request, 'user_id', None)
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        # Get all referrals
        referrals = supabase.schema(SCHEMA_NAME).table('referrals').select(
            '*'
        ).eq('referrer_user_id', user_id).execute()
        
        # Get earnings breakdown
        earnings = supabase.schema(SCHEMA_NAME).table('referral_earnings').select(
            '*'
        ).eq('referrer_user_id', user_id).order('created_at', desc=True).execute()
        
        # Calculate totals
        total_signups = len([r for r in referrals.data if r['status'] in ['signed_up', 'converted']])
        total_conversions = len([r for r in referrals.data if r['status'] == 'converted'])
        
        total_earnings = sum(r['total_earnings'] or 0 for r in referrals.data)
        total_pending = sum(
            e['amount'] for e in earnings.data 
            if e['payment_status'] == 'pending'
        )
        total_paid = sum(
            e['amount'] for e in earnings.data 
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
            for r in referrals.data if r['status'] == 'converted'
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
            'recent_earnings': earnings.data[:10]  # Last 10 earnings
        }), 200
        
    except Exception as e:
        print(f"[API] Error getting referral stats: {e}")
        return jsonify({'error': str(e)}), 500


@referral_points_bp.route('/track-click/<code>', methods=['POST'])
def track_referral_click(code):
    """Track click on referral link"""
    try:
        manager = get_referral_manager()
        manager.track_referral_click(code)
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@referral_points_bp.route('/validate-code/<code>', methods=['GET'])
def validate_referral_code(code):
    """Validate referral code"""
    try:
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        result = supabase.schema(SCHEMA_NAME).table('referral_codes').select(
            'code, user_id, active'
        ).eq('code', code).eq('active', True).limit(1).execute()
        
        if result.data:
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
        return jsonify({'error': str(e)}), 500


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
        return jsonify({'error': str(e)}), 500


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
        return jsonify({'error': str(e)}), 500


@referral_points_bp.route('/points/leaderboard', methods=['GET'])
@optional_auth
def get_points_leaderboard():
    """Get points leaderboard"""
    try:
        limit = int(request.args.get('limit', 100))
        leaderboard_type = request.args.get('type', 'lifetime')  # 'lifetime' or 'current'
        
        manager = get_referral_manager()
        leaderboard = manager.get_leaderboard(limit, leaderboard_type)
        
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
            'type': leaderboard_type
        }), 200
        
    except Exception as e:
        print(f"[API] Error getting leaderboard: {e}")
        return jsonify({'error': str(e)}), 500


@referral_points_bp.route('/points/history', methods=['GET'])
@require_auth
def get_points_history():
    """Get user's point transaction history"""
    try:
        user_id = getattr(request, 'user_id', None)
        limit = int(request.args.get('limit', 50))
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        result = supabase.schema(SCHEMA_NAME).table('point_transactions').select(
            '*'
        ).eq('user_id', user_id).order('created_at', desc=True).limit(limit).execute()
        
        return jsonify({
            'success': True,
            'transactions': result.data
        }), 200
        
    except Exception as e:
        print(f"[API] Error getting history: {e}")
        return jsonify({'error': str(e)}), 500


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
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()
        
        referrals = supabase.schema(SCHEMA_NAME).table('referrals').select(
            '*'
        ).eq('referrer_user_id', user_id).execute()
        
        code_stats = supabase.schema(SCHEMA_NAME).table('referral_codes').select(
            'clicks, signups, conversions'
        ).eq('code', code).limit(1).execute()
        
        total_conversions = len([r for r in referrals.data if r['status'] == 'converted'])
        total_earnings = sum(r['total_earnings'] or 0 for r in referrals.data)
        
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
                'link': f"https://your-app.com/signup?ref={code}",
                'stats': code_stats.data[0] if code_stats.data else {},
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
        return jsonify({'error': str(e)}), 500