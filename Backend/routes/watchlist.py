"""Watchlist routes."""
from flask import Blueprint, request, jsonify

from auth import require_auth
from db import WatchlistDatabase
from config import Config

watchlist_bp = Blueprint('watchlist', __name__, url_prefix='/api/watchlist')

# Initialize database
watchlist_db = WatchlistDatabase(Config.WATCHLIST_DB_PATH)


def _get_user_id() -> str | None:
    """Get user ID from auth or request."""
    return getattr(request, 'user_id', None)


@watchlist_bp.route('/add', methods=['POST'])
@require_auth
def add_to_watchlist():
    """Add account to watchlist."""
    data = request.json
    user_id = _get_user_id() or data.get('user_id')
    account = data.get('account')

    if not user_id or not account:
        return jsonify({'error': 'user_id and account required'}), 400

    success = watchlist_db.add_to_watchlist(user_id, account)

    if success:
        return jsonify({'success': True, 'message': 'Account added to watchlist'}), 200
    return jsonify({'success': False, 'error': 'Failed to add account'}), 500


@watchlist_bp.route('/get', methods=['GET'])
@require_auth
def get_watchlist():
    """Get user's watchlist."""
    user_id = _get_user_id() or request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    accounts = watchlist_db.get_watchlist(user_id)
    return jsonify({'success': True, 'accounts': accounts}), 200


@watchlist_bp.route('/remove', methods=['POST'])
@require_auth
def remove_from_watchlist():
    """Remove account from watchlist."""
    data = request.json
    user_id = _get_user_id() or data.get('user_id')
    author_id = data.get('author_id')

    if not user_id or not author_id:
        return jsonify({'error': 'user_id and author_id required'}), 400

    success = watchlist_db.remove_from_watchlist(user_id, author_id)

    if success:
        return jsonify({'success': True, 'message': 'Account removed'}), 200
    return jsonify({'success': False, 'error': 'Failed to remove account'}), 500


@watchlist_bp.route('/update', methods=['POST'])
@require_auth
def update_watchlist_account():
    """Update account notes and tags."""
    data = request.json
    user_id = _get_user_id() or data.get('user_id')
    author_id = data.get('author_id')
    notes = data.get('notes')
    tags = data.get('tags')

    if not user_id or not author_id:
        return jsonify({'error': 'user_id and author_id required'}), 400

    success = watchlist_db.update_account_notes(user_id, author_id, notes, tags)

    if success:
        return jsonify({'success': True, 'message': 'Account updated'}), 200
    return jsonify({'success': False, 'error': 'Failed to update account'}), 500


@watchlist_bp.route('/groups', methods=['GET'])
@require_auth
def get_watchlist_groups():
    """Get user's watchlist groups."""
    user_id = _get_user_id() or request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    groups = watchlist_db.get_user_groups(user_id)
    return jsonify({'success': True, 'groups': groups}), 200


@watchlist_bp.route('/groups/create', methods=['POST'])
@require_auth
def create_watchlist_group():
    """Create a new watchlist group."""
    data = request.json
    user_id = _get_user_id() or data.get('user_id')
    group_name = data.get('group_name')
    description = data.get('description', '')

    if not user_id or not group_name:
        return jsonify({'error': 'user_id and group_name required'}), 400

    group_id = watchlist_db.create_group(user_id, group_name, description)

    if group_id:
        return jsonify({
            'success': True,
            'group_id': group_id,
            'group_name': group_name
        }), 201
    return jsonify({'success': False, 'error': 'Failed to create group'}), 500


@watchlist_bp.route('/stats', methods=['GET'])
@require_auth
def get_watchlist_stats():
    """Get watchlist statistics."""
    user_id = _get_user_id() or request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    stats = watchlist_db.get_watchlist_stats(user_id)
    return jsonify({'success': True, 'stats': stats}), 200
