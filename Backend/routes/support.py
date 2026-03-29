import logging
from flask import Blueprint, request, jsonify
from auth import optional_auth
from repositories.registry import get_support_ticket_repo
from routes import anon_user_id

logger = logging.getLogger(__name__)

support_bp = Blueprint('support', __name__, url_prefix='/api/support')


@support_bp.route('/ticket', methods=['POST', 'OPTIONS'])
@optional_auth
def submit_ticket():
    """Submit support ticket"""
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.json
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            user_id = anon_user_id()
        subject = data.get('subject')
        message = data.get('message')

        if not all([user_id, subject, message]):
            return jsonify({'error': 'user_id, subject, and message required'}), 400

        repo = get_support_ticket_repo()
        repo.create_ticket(user_id, subject, message)

        return jsonify({
            'success': True,
            'message': 'Ticket submitted successfully. We\'ll respond within 24 hours.'
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500
