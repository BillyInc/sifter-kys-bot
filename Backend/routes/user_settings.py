from flask import Blueprint, request, jsonify
from auth import optional_auth
from services.supabase_client import get_supabase_client, SCHEMA_NAME

user_settings_bp = Blueprint('user_settings', __name__, url_prefix='/api/user')


@user_settings_bp.route('/settings', methods=['POST', 'OPTIONS'])
@optional_auth
def save_user_settings():
    """Save user settings"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')
        settings = data.get('settings', {})
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        supabase = get_supabase_client()
        
        # Upsert user settings
        supabase.schema(SCHEMA_NAME).table('user_settings').upsert({
            'user_id': user_id,
            'email': settings.get('email'),
            'timezone': settings.get('timezone', 'UTC'),
            'language': settings.get('language', 'English'),
            'email_alerts': settings.get('emailAlerts', True),
            'browser_notifications': settings.get('browserNotifications', True),
            'alert_threshold': settings.get('alertThreshold', 100),
            'default_timeframe': settings.get('defaultTimeframe', '7d'),
            'default_candle': settings.get('defaultCandle', '5m'),
            'min_roi_multiplier': settings.get('minRoiMultiplier', 3.0),
            'theme': settings.get('theme', 'dark'),
            'compact_mode': settings.get('compactMode', False),
            'data_refresh_rate': settings.get('dataRefreshRate', 30),
            'updated_at': 'now()'
        }, on_conflict='user_id').execute()
        
        return jsonify({
            'success': True,
            'message': 'Settings saved successfully'
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@user_settings_bp.route('/settings', methods=['GET', 'OPTIONS'])
@optional_auth
def get_user_settings():
    """Get user settings"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        supabase = get_supabase_client()
        
        result = supabase.schema(SCHEMA_NAME).table('user_settings').select('*').eq(
            'user_id', user_id
        ).limit(1).execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'settings': result.data[0]
            }), 200
        else:
            # Return defaults
            return jsonify({
                'success': True,
                'settings': {
                    'timezone': 'UTC',
                    'language': 'English',
                    'email_alerts': True,
                    'browser_notifications': True,
                    'alert_threshold': 100,
                    'default_timeframe': '7d',
                    'default_candle': '5m',
                    'min_roi_multiplier': 3.0,
                    'theme': 'dark',
                    'compact_mode': False,
                    'data_refresh_rate': 30
                }
            }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500