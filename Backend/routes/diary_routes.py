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
from routes import anon_user_id

from auth import optional_auth
from repositories.registry import get_diary_repo

logger = logging.getLogger(__name__)

diary_bp = Blueprint('diary', __name__, url_prefix='/api/diary')


def _get_user_id() -> str | None:
    # Only trust the auth middleware (JWT) — never user-supplied input
    uid = getattr(request, 'user_id', None)
    if uid:
        return uid

    # Anonymous fallback for @optional_auth routes
    return anon_user_id()


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
        repo = get_diary_repo()
        row = repo.get_salt(user_id)

        if row:
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
        repo = get_diary_repo()
        existing = repo.get_salt(user_id)

        if existing:
            return _cors_response({
                'success': True,
                'salt_b64': existing['salt_b64'],
                'verification_token': existing['verification_token'],
            })
        else:
            result = repo.save_salt(user_id, salt_b64, verification_token)
            print(f"[DIARY] 🔐 Passphrase initialised for user {str(user_id)[:8]}...")
            return _cors_response({
                'success': True,
                'salt_b64': result['salt_b64'],
                'verification_token': result['verification_token'],
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
        repo = get_diary_repo()
        notes = repo.list_notes(user_id, wallet_address, note_type, limit, offset)

        return _cors_response({
            'success': True,
            'notes': notes,
            'count': len(notes),
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
        repo = get_diary_repo()
        row = repo.create_note(user_id, encrypted_payload, note_type, wallet_address)

        print(f"[DIARY] ✅ {note_type} note saved for {str(user_id)[:8]}..."
              + (f" wallet={wallet_address[:8]}..." if wallet_address else " (global)"))

        return _cors_response({'success': True, 'id': row.get('id') if row else None}, 201)

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
        repo = get_diary_repo()

        if not repo.note_exists(user_id, note_id):
            return _cors_response({'error': 'Note not found or access denied'}, 404)

        if note_type:
            valid_types = {'thought', 'strategy', 'todo', 'note'}
            if note_type not in valid_types:
                return _cors_response({'error': f'type must be one of {valid_types}'}, 400)

        repo.update_note(user_id, note_id, encrypted_payload, note_type)
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
        repo = get_diary_repo()

        if not repo.note_exists(user_id, note_id):
            return _cors_response({'error': 'Note not found or access denied'}, 404)

        repo.delete_note(user_id, note_id)
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
        repo = get_diary_repo()
        repo.clear_all_notes(user_id)
        print(f"[DIARY] 🗑️  Cleared all notes for user {str(user_id)[:8]}...")
        return _cors_response({'success': True})

    except Exception as e:
        traceback.print_exc()
        logger.exception("Request failed")
        return _cors_response({'error': 'Internal server error'}, 500)
