"""
diary_routes.py  (passphrase-based encryption edition)
──────────────────────────────────────────────────────────────────────────────
Key derivation: PBKDF2(userId + ":" + passphrase, salt, 310_000 iters) → AES-256-GCM
The backend never sees the passphrase or any plaintext.

Changes from userId-only version:
  - diary_user_salt also stores verification_token (AES-GCM blob of known
    plaintext, used client-side to validate the passphrase before decrypting)
  - GET /api/diary/salt returns both salt_b64 + verification_token
  - POST /api/diary/salt accepts both salt_b64 + verification_token

Supabase tables required (see diary_migration.sql):
  diary_user_salt   – user_id PK, salt_b64, verification_token, created_at
  watchlist_diary   – id uuid, user_id, wallet_address, type, encrypted_payload,
                      created_at, edited_at
──────────────────────────────────────────────────────────────────────────────
"""

from flask import Blueprint, request, jsonify
from datetime import datetime

from auth import optional_auth
from services.supabase_client import get_supabase_client, SCHEMA_NAME

diary_bp = Blueprint('diary', __name__, url_prefix='/api/diary')


def _supabase():
    return get_supabase_client()

def _table(name: str):
    return _supabase().schema(SCHEMA_NAME).table(name)

def _get_user_id() -> str | None:
    return (
        getattr(request, 'user_id', None)
        or (request.json or {}).get('user_id')
        or request.args.get('user_id')
    )


# ─── Salt + verification token ─────────────────────────────────────────────────

@diary_bp.route('/salt', methods=['GET', 'OPTIONS'])
@optional_auth
def get_salt():
    """
    Returns the user's PBKDF2 salt and passphrase verification token.
      is_new = true  → no passphrase set yet (show setup UI)
      is_new = false → passphrase exists (show unlock UI)
    """
    if request.method == 'OPTIONS':
        return '', 204
    user_id = _get_user_id()
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    try:
        result = _table('diary_user_salt').select(
            'salt_b64, verification_token'
        ).eq('user_id', user_id).execute()
        if result.data:
            row = result.data[0]
            return jsonify({
                'success':            True,
                'salt_b64':           row['salt_b64'],
                'verification_token': row['verification_token'],
                'is_new':             False,
            }), 200
        return jsonify({'success': True, 'salt_b64': None, 'verification_token': None, 'is_new': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@diary_bp.route('/salt', methods=['POST', 'OPTIONS'])
@optional_auth
def save_salt():
    """
    Save salt + verification_token when user sets passphrase for the first time.
    Idempotent — existing record is never overwritten (would invalidate all notes).
    """
    if request.method == 'OPTIONS':
        return '', 204
    data               = request.json or {}
    user_id            = _get_user_id()
    salt_b64           = data.get('salt_b64')
    verification_token = data.get('verification_token')
    if not user_id or not salt_b64 or not verification_token:
        return jsonify({'error': 'user_id, salt_b64, and verification_token required'}), 400
    try:
        existing = _table('diary_user_salt').select(
            'salt_b64, verification_token'
        ).eq('user_id', user_id).execute()
        if existing.data:
            row = existing.data[0]
            return jsonify({'success': True, 'salt_b64': row['salt_b64'], 'verification_token': row['verification_token']}), 200
        _table('diary_user_salt').insert({
            'user_id':            user_id,
            'salt_b64':           salt_b64,
            'verification_token': verification_token,
        }).execute()
        print(f"[DIARY] 🔐 Passphrase initialised for user {str(user_id)[:8]}...")
        return jsonify({'success': True, 'salt_b64': salt_b64, 'verification_token': verification_token}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Note CRUD ─────────────────────────────────────────────────────────────────

@diary_bp.route('/notes', methods=['GET', 'OPTIONS'])
@optional_auth
def list_notes():
    if request.method == 'OPTIONS':
        return '', 204
    user_id = _get_user_id()
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    wallet_address = request.args.get('wallet_address')
    note_type      = request.args.get('type')
    limit          = int(request.args.get('limit', 500))
    offset         = int(request.args.get('offset', 0))
    try:
        query = _table('watchlist_diary').select(
            'id, wallet_address, type, encrypted_payload, created_at, edited_at'
        ).eq('user_id', user_id)
        if wallet_address:
            query = query.eq('wallet_address', wallet_address)
        if note_type:
            query = query.eq('type', note_type)
        result = query.order('created_at', desc=True).range(offset, offset + limit - 1).execute()
        return jsonify({'success': True, 'notes': result.data, 'count': len(result.data)}), 200
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@diary_bp.route('/notes', methods=['POST', 'OPTIONS'])
@optional_auth
def create_note():
    if request.method == 'OPTIONS':
        return '', 204
    data              = request.json or {}
    user_id           = _get_user_id()
    note_type         = data.get('type', 'note')
    encrypted_payload = data.get('encrypted_payload')
    wallet_address    = data.get('wallet_address')
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    if not encrypted_payload:
        return jsonify({'error': 'encrypted_payload required'}), 400
    valid_types = {'thought', 'strategy', 'todo', 'note'}
    if note_type not in valid_types:
        return jsonify({'error': f'type must be one of {valid_types}'}), 400
    try:
        result = _table('watchlist_diary').insert({
            'user_id':           user_id,
            'wallet_address':    wallet_address,
            'type':              note_type,
            'encrypted_payload': encrypted_payload,
        }).execute()
        row = result.data[0] if result.data else {}
        print(f"[DIARY] ✅ {note_type} note saved for {str(user_id)[:8]}..." + (f" wallet={wallet_address[:8]}..." if wallet_address else " (global)"))
        return jsonify({'success': True, 'id': row.get('id')}), 201
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@diary_bp.route('/notes/<note_id>', methods=['PUT', 'OPTIONS'])
@optional_auth
def update_note(note_id):
    if request.method == 'OPTIONS':
        return '', 204
    data              = request.json or {}
    user_id           = _get_user_id()
    encrypted_payload = data.get('encrypted_payload')
    note_type         = data.get('type')
    if not user_id or not encrypted_payload:
        return jsonify({'error': 'user_id and encrypted_payload required'}), 400
    try:
        check = _table('watchlist_diary').select('id').eq('id', note_id).eq('user_id', user_id).execute()
        if not check.data:
            return jsonify({'error': 'Note not found or access denied'}), 404
        update_data = {'encrypted_payload': encrypted_payload, 'edited_at': datetime.utcnow().isoformat()}
        if note_type:
            valid_types = {'thought', 'strategy', 'todo', 'note'}
            if note_type not in valid_types:
                return jsonify({'error': f'type must be one of {valid_types}'}), 400
            update_data['type'] = note_type
        _table('watchlist_diary').update(update_data).eq('id', note_id).eq('user_id', user_id).execute()
        return jsonify({'success': True}), 200
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@diary_bp.route('/notes/<note_id>', methods=['DELETE', 'OPTIONS'])
@optional_auth
def delete_note(note_id):
    if request.method == 'OPTIONS':
        return '', 204
    user_id = _get_user_id()
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    try:
        check = _table('watchlist_diary').select('id').eq('id', note_id).eq('user_id', user_id).execute()
        if not check.data:
            return jsonify({'error': 'Note not found or access denied'}), 404
        _table('watchlist_diary').delete().eq('id', note_id).eq('user_id', user_id).execute()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@diary_bp.route('/notes', methods=['DELETE', 'OPTIONS'])
@optional_auth
def clear_all_notes():
    if request.method == 'OPTIONS':
        return '', 204
    data    = request.json or {}
    user_id = _get_user_id()
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    if data.get('confirm') != 'DELETE_ALL':
        return jsonify({'error': 'Pass { "confirm": "DELETE_ALL" } to confirm bulk deletion'}), 400
    try:
        _table('watchlist_diary').delete().eq('user_id', user_id).execute()
        print(f"[DIARY] 🗑️  Cleared all notes for user {str(user_id)[:8]}...")
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500