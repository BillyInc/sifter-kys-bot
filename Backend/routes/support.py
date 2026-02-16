from flask import Blueprint, request, jsonify
from auth import optional_auth
from services.supabase_client import get_supabase_client, SCHEMA_NAME
from datetime import datetime

support_bp = Blueprint('support', __name__, url_prefix='/api/support')


@support_bp.route('/ticket', methods=['POST', 'OPTIONS'])
@optional_auth
def submit_ticket():
    """Submit support ticket"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        user_id = getattr(request, 'user_id', None) or data.get('user_id')
        subject = data.get('subject')
        message = data.get('message')
        
        if not all([user_id, subject, message]):
            return jsonify({'error': 'user_id, subject, and message required'}), 400
        
        supabase = get_supabase_client()
        
        # Insert ticket
        supabase.schema(SCHEMA_NAME).table('support_tickets').insert({
            'user_id': user_id,
            'subject': subject,
            'message': message,
            'status': 'open',
            'created_at': datetime.utcnow().isoformat()
        }).execute()
        
        # TODO: Send email notification to support@sifter.io
        
        return jsonify({
            'success': True,
            'message': 'Ticket submitted successfully. We\'ll respond within 24 hours.'
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500