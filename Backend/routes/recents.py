"""
User recent analysis results — stored in Redis with 6-hour TTL.

Key:   user_recents:{user_id}
Value: JSON array of up to MAX_RECENTS entries, newest first.
TTL:   6 hours, refreshed on every write.

Each entry:
  {
    "id":         str,          # unique, client-generated
    "resultType": str,          # single-token | batch-token | trending-single | trending-batch | discovery
    "label":      str,          # human-readable title, e.g. "📊 BONK"
    "sublabel":   str,          # e.g. "Single token"
    "timestamp":  int (ms),     # Date.now() from client
    "data":       dict          # full result payload (wallets, token, etc.)
  }

Storage note:
  Each entry can be 50–200 KB (20 wallets with full data). At MAX_RECENTS=20 that
  is up to ~4 MB per user — well within Redis limits.
  If you later want to reduce memory usage, store only metadata + job_id here and
  re-fetch the full result on demand via GET /api/wallets/jobs/<job_id>.
"""

from flask import Blueprint, request, jsonify
from auth import optional_auth
from redis import Redis
import json
import os

recents_bp = Blueprint('recents', __name__, url_prefix='/api/user/recents')

MAX_RECENTS  = 20
RECENTS_TTL  = 21_600   # 6 hours — matches analysis cache TTL in worker_tasks.py


def _get_redis():
    """Same pattern used everywhere in the codebase."""
    url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    return Redis.from_url(url, socket_timeout=10, socket_connect_timeout=10)


def _recents_key(user_id: str) -> str:
    return f"user_recents:{user_id}"


def _load_recents(r, user_id: str) -> list:
    raw = r.get(_recents_key(user_id))
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return []


def _save_recents(r, user_id: str, recents: list):
    """Save recents list and refresh the 6-hour TTL."""
    r.set(
        _recents_key(user_id),
        json.dumps(recents, separators=(',', ':')),
        ex=RECENTS_TTL
    )


# =============================================================================
# GET /api/user/recents
# Load all recent entries for the authenticated user.
# =============================================================================

@recents_bp.route('', methods=['GET', 'OPTIONS'])
@optional_auth
def get_recents():
    if request.method == 'OPTIONS':
        return '', 204

    user_id = getattr(request, 'user_id', None) or request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    try:
        r       = _get_redis()
        recents = _load_recents(r, user_id)
        return jsonify({'success': True, 'recents': recents, 'count': len(recents)}), 200
    except Exception as e:
        print(f"[RECENTS GET] Error for {str(user_id)[:8]}: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# POST /api/user/recents
# Add a new entry. Prepends to list, enforces MAX_RECENTS cap.
# Body: { entry: { id, resultType, label, sublabel, timestamp, data } }
# =============================================================================

@recents_bp.route('', methods=['POST', 'OPTIONS'])
@optional_auth
def add_recent():
    if request.method == 'OPTIONS':
        return '', 204

    data    = request.json or {}
    user_id = getattr(request, 'user_id', None) or data.get('user_id')
    entry   = data.get('entry')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    if not entry or not isinstance(entry, dict):
        return jsonify({'error': 'entry object required'}), 400
    if not entry.get('id') or not entry.get('resultType'):
        return jsonify({'error': 'entry.id and entry.resultType required'}), 400

    try:
        r       = _get_redis()
        recents = _load_recents(r, user_id)

        # Remove any existing entry with the same id (idempotent)
        recents = [r_entry for r_entry in recents if r_entry.get('id') != entry['id']]

        # Prepend new entry, enforce cap
        recents = [entry, *recents][:MAX_RECENTS]

        _save_recents(r, user_id, recents)

        return jsonify({'success': True, 'count': len(recents)}), 200

    except Exception as e:
        print(f"[RECENTS ADD] Error for {str(user_id)[:8]}: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# DELETE /api/user/recents/<entry_id>
# Remove a single entry by id.
# =============================================================================

@recents_bp.route('/<entry_id>', methods=['DELETE', 'OPTIONS'])
@optional_auth
def remove_recent(entry_id):
    if request.method == 'OPTIONS':
        return '', 204

    data    = request.json or {}
    user_id = getattr(request, 'user_id', None) or data.get('user_id') or request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    try:
        r       = _get_redis()
        recents = _load_recents(r, user_id)
        before  = len(recents)
        recents = [e for e in recents if e.get('id') != entry_id]

        if len(recents) == before:
            return jsonify({'success': False, 'error': 'Entry not found'}), 404

        _save_recents(r, user_id, recents)
        return jsonify({'success': True, 'count': len(recents)}), 200

    except Exception as e:
        print(f"[RECENTS REMOVE] Error for {str(user_id)[:8]}: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# DELETE /api/user/recents
# Clear all recent entries for the user.
# =============================================================================

@recents_bp.route('', methods=['DELETE', 'OPTIONS'])
@optional_auth
def clear_recents():
    if request.method == 'OPTIONS':
        return '', 204

    data    = request.json or {}
    user_id = getattr(request, 'user_id', None) or data.get('user_id') or request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    try:
        r = _get_redis()
        r.delete(_recents_key(user_id))
        return jsonify({'success': True, 'count': 0}), 200

    except Exception as e:
        print(f"[RECENTS CLEAR] Error for {str(user_id)[:8]}: {e}")
        return jsonify({'error': str(e)}), 500