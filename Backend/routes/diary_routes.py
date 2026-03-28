"""
diary_routes.py  (passphrase-based encryption edition)
──────────────────────────────────────────────────────────────────────────────
Key derivation: PBKDF2(userId + ":" + passphrase, salt, 310_000 iters) → AES-256-GCM
The backend never sees the passphrase or any plaintext.

Supabase tables required:
  diary_user_salt   – user_id PK, salt_b64, verification_token, created_at
  watchlist_diary   – id uuid, user_id, wallet_address, type, encrypted_payload,
                      created_at, edited_at
──────────────────────────────────────────────────────────────────────────────
"""

import logging
from flask import Blueprint, request, jsonify, make_response
from datetime import datetime
import traceback

from auth import optional_auth
from services.supabase_client import get_supabase_client, SCHEMA_NAME

logger = logging.getLogger(__name__)

diary_bp = Blueprint('diary', __name__, url_prefix='/api/diary')


def _supabase():
    return get_supabase_client()

def _table(name: str):
    return _supabase().schema(SCHEMA_NAME).table(name)

def _get_user_id() -> str | None:
    # 1. Auth middleware (JWT)
    uid = getattr(request, 'user_id', None)
    if uid:
        return uid

    # 2. Query string (GET requests)
    uid = request.args.get('user_id')
    if uid:
        return uid

    # 3. JSON body (POST/PUT/DELETE)
    # MUST use get_json(silent=True) — request.json raises 400 on GET
    # requests that have Content-Type: application/json but no body
    try:
        body = request.get_json(silent=True, force=False) or {}
        uid = body.get('user_id')
        if uid:
            return uid
    except Exception:
        pass

    return None


def _cors_response(data=None, status=200):
    """Build a JSON response with CORS headers."""
    if data is None:
        resp = make_response()
    else:
        resp = make_response(jsonify(data))
    resp.headers['Content-Type'] = 'application/json'
    resp.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    return resp, status


def _cors_preflight():
    """Return a 204 preflight response."""
    resp = make_response()
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,Accept,X-Requested-With'
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS,PUT,DELETE'
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    resp.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
    return resp, 204


# ─── Salt + verification token ────────────────────────────────────────────────

@diary_bp.route('/salt', methods=['GET', 'OPTIONS'])
@optional_auth
def get_salt():
    if request.method == 'OPTIONS':
        return _cors_preflight()

    user_id = _get_user_id()
    if not user_id:
        return _cors_response({'error': 'user_id required'}, 400)

    try:
        result = _table('diary_user_salt').select(
            'salt_b64, verification_token'
        ).eq('user_id', user_id).execute()

        if result.data:
            row = result.data[0]
            return _cors_response({
                'success': True,
                'salt_b64': row['salt_b64'],
                'verification_token': row['verification_token'],
                'is_new': False,
            })
        else:
            return _cors_response({
                'success': True,
                'salt_b64': None,
                'verification_token': None,
                'is_new': True,
            })

    except Exception as e:
        traceback.print_exc()
        logger.exception("Request failed")
        return _cors_response({'error': 'Internal server error'}, 500)


@diary_bp.route('/salt', methods=['POST', 'OPTIONS'])
@optional_auth
def save_salt():
    if request.method == 'OPTIONS':
        return _cors_preflight()

    body               = request.get_json(silent=True) or {}
    user_id            = _get_user_id()
    salt_b64           = body.get('salt_b64')
    verification_token = body.get('verification_token')

    if not user_id or not salt_b64 or not verification_token:
        return _cors_response({'error': 'user_id, salt_b64, and verification_token required'}, 400)

    try:
        existing = _table('diary_user_salt').select(
            'salt_b64, verification_token'
        ).eq('user_id', user_id).execute()

        if existing.data:
            row = existing.data[0]
            return _cors_response({
                'success': True,
                'salt_b64': row['salt_b64'],
                'verification_token': row['verification_token'],
            })
        else:
            _table('diary_user_salt').insert({
                'user_id': user_id,
                'salt_b64': salt_b64,
                'verification_token': verification_token,
            }).execute()
            print(f"[DIARY] 🔐 Passphrase initialised for user {str(user_id)[:8]}...")
            return _cors_response({
                'success': True,
                'salt_b64': salt_b64,
                'verification_token': verification_token,
            }, 201)

    except Exception as e:
        traceback.print_exc()
        logger.exception("Request failed")
        return _cors_response({'error': 'Internal server error'}, 500)


# ─── Note CRUD ────────────────────────────────────────────────────────────────

@diary_bp.route('/notes', methods=['GET', 'OPTIONS'])
@optional_auth
def list_notes():
    if request.method == 'OPTIONS':
        return _cors_preflight()

    user_id = _get_user_id()
    if not user_id:
        return _cors_response({'error': 'user_id required'}, 400)

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

        return _cors_response({
            'success': True,
            'notes': result.data,
            'count': len(result.data),
        })

    except Exception as e:
        traceback.print_exc()
        logger.exception("Request failed")
        return _cors_response({'error': 'Internal server error'}, 500)


@diary_bp.route('/notes', methods=['POST', 'OPTIONS'])
@optional_auth
def create_note():
    if request.method == 'OPTIONS':
        return _cors_preflight()

    body              = request.get_json(silent=True) or {}
    user_id           = _get_user_id()
    note_type         = body.get('type', 'note')
    encrypted_payload = body.get('encrypted_payload')
    wallet_address    = body.get('wallet_address')

    if not user_id:
        return _cors_response({'error': 'user_id required'}, 400)
    if not encrypted_payload:
        return _cors_response({'error': 'encrypted_payload required'}, 400)

    valid_types = {'thought', 'strategy', 'todo', 'note'}
    if note_type not in valid_types:
        return _cors_response({'error': f'type must be one of {valid_types}'}, 400)

    try:
        result = _table('watchlist_diary').insert({
            'user_id':           user_id,
            'wallet_address':    wallet_address,
            'type':              note_type,
            'encrypted_payload': encrypted_payload,
        }).execute()

        row = result.data[0] if result.data else {}
        print(f"[DIARY] ✅ {note_type} note saved for {str(user_id)[:8]}..."
              + (f" wallet={wallet_address[:8]}..." if wallet_address else " (global)"))

        return _cors_response({'success': True, 'id': row.get('id')}, 201)

    except Exception as e:
        traceback.print_exc()
        logger.exception("Request failed")
        return _cors_response({'error': 'Internal server error'}, 500)


@diary_bp.route('/notes/<note_id>', methods=['PUT', 'OPTIONS'])
@optional_auth
def update_note(note_id):
    if request.method == 'OPTIONS':
        return _cors_preflight()

    body              = request.get_json(silent=True) or {}
    user_id           = _get_user_id()
    encrypted_payload = body.get('encrypted_payload')
    note_type         = body.get('type')

    if not user_id or not encrypted_payload:
        return _cors_response({'error': 'user_id and encrypted_payload required'}, 400)

    try:
        check = _table('watchlist_diary').select('id').eq('id', note_id).eq('user_id', user_id).execute()
        if not check.data:
            return _cors_response({'error': 'Note not found or access denied'}, 404)

        update_data = {
            'encrypted_payload': encrypted_payload,
            'edited_at':         datetime.utcnow().isoformat(),
        }

        if note_type:
            valid_types = {'thought', 'strategy', 'todo', 'note'}
            if note_type not in valid_types:
                return _cors_response({'error': f'type must be one of {valid_types}'}, 400)
            update_data['type'] = note_type

        _table('watchlist_diary').update(update_data).eq('id', note_id).eq('user_id', user_id).execute()
        return _cors_response({'success': True})

    except Exception as e:
        traceback.print_exc()
        logger.exception("Request failed")
        return _cors_response({'error': 'Internal server error'}, 500)


@diary_bp.route('/notes/<note_id>', methods=['DELETE', 'OPTIONS'])
@optional_auth
def delete_note(note_id):
    if request.method == 'OPTIONS':
        return _cors_preflight()

    user_id = _get_user_id()
    if not user_id:
        return _cors_response({'error': 'user_id required'}, 400)

    try:
        check = _table('watchlist_diary').select('id').eq('id', note_id).eq('user_id', user_id).execute()
        if not check.data:
            return _cors_response({'error': 'Note not found or access denied'}, 404)

        _table('watchlist_diary').delete().eq('id', note_id).eq('user_id', user_id).execute()
        return _cors_response({'success': True})

    except Exception as e:
        traceback.print_exc()
        logger.exception("Request failed")
        return _cors_response({'error': 'Internal server error'}, 500)


@diary_bp.route('/notes', methods=['DELETE', 'OPTIONS'])
@optional_auth
def clear_all_notes():
    if request.method == 'OPTIONS':
        return _cors_preflight()

    body    = request.get_json(silent=True) or {}
    user_id = _get_user_id()

    if not user_id:
        return _cors_response({'error': 'user_id required'}, 400)
    if body.get('confirm') != 'DELETE_ALL':
        return _cors_response({'error': 'Pass { "confirm": "DELETE_ALL" } to confirm bulk deletion'}, 400)

    try:
        _table('watchlist_diary').delete().eq('user_id', user_id).execute()
        print(f"[DIARY] 🗑️  Cleared all notes for user {str(user_id)[:8]}...")
        return _cors_response({'success': True})

    except Exception as e:
        traceback.print_exc()
        logger.exception("Request failed")
        return _cors_response({'error': 'Internal server error'}, 500)