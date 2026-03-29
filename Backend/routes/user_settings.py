import logging
from flask import Blueprint, request, jsonify
from auth import optional_auth
from repositories.registry import get_user_settings_repo
from routes import anon_user_id

logger = logging.getLogger(__name__)

user_settings_bp = Blueprint('user_settings', __name__, url_prefix='/api/user')

DEFAULT_SETTINGS = {
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


@user_settings_bp.route('/settings', methods=['POST', 'OPTIONS'])
@optional_auth
def save_user_settings():
    """Save user settings"""
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.json
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            user_id = anon_user_id()
        settings = data.get('settings', {})

        repo = get_user_settings_repo()
        repo.save_settings(user_id, settings)

        return jsonify({
            'success': True,
            'message': 'Settings saved successfully'
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


@user_settings_bp.route('/settings', methods=['GET', 'OPTIONS'])
@optional_auth
def get_user_settings():
    """Get user settings"""
    if request.method == 'OPTIONS':
        return '', 204

    try:
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            user_id = anon_user_id()

        repo = get_user_settings_repo()
        settings = repo.get_settings(user_id)

        return jsonify({
            'success': True,
            'settings': settings or DEFAULT_SETTINGS
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500
