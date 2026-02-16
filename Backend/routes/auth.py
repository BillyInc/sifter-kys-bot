"""
Auth API Routes
"""
from flask import Blueprint, request, jsonify
from services.referral_points_manager import get_referral_manager

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@auth_bp.route('/signup', methods=['POST'])
def handle_signup():
    """Handle new user signup with referral code"""
    try:
        data = request.json
        user_id = data.get('user_id')
        email = data.get('email')
        referral_code = data.get('referral_code')
        
        if not user_id or not email:
            return jsonify({'error': 'user_id and email required'}), 400
        
        manager = get_referral_manager()
        
        # Create referral relationship if code exists
        if referral_code:
            result = manager.create_referral(referral_code, user_id, email)
            
            if result.get('success'):
                print(f"[AUTH] ✅ Referral created for {user_id[:8]}... from code {referral_code}")
            else:
                print(f"[AUTH] ⚠️ Referral creation failed: {result.get('error')}")
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"[AUTH] Signup error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500