"""
routes/abm_state.py
──────────────────────────────────────────────────────────────────
Flask endpoint that serves live simulation state to the Three.js
visualiser at http://localhost:8080/abm_3d_visualization.html

Two data modes:
  mode=simulation  → data written by simulation_harness.py
  mode=watchlist   → data pulled from your real Supabase watchlist

Redis keys used:
  abm:current_state      → the full JSON blob Three.js reads
  abm:mode               → "simulation" or "watchlist"
"""

import logging
from flask import Blueprint, jsonify, request, current_app
from auth import optional_auth
import json
import os
from redis import Redis
from routes import anon_user_id

logger = logging.getLogger(__name__)

abm_state_bp = Blueprint('abm_state', __name__)

def get_redis():
    return Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'),
                          decode_responses=True)


# ── GET current state ─────────────────────────────────────────────────────────

@abm_state_bp.route('/api/abm/state', methods=['GET'])
def get_abm_state():
    """
    Polled every second by Three.js.
    Returns the current simulation state as JSON.
    """
    try:
        r = get_redis()
        raw = r.get('abm:current_state')

        if not raw:
            # Nothing running yet — return idle state
            return jsonify({
                'status': 'idle',
                'mode': 'none',
                'day': 0,
                'market_state': 'NEUTRAL',
                'agents': [],
                'stats': {},
                'events': [],
                'monte_carlo': None,
            })

        state = json.loads(raw)
        return jsonify(state)

    except Exception as e:
        logger.exception("Request failed")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500


# ── POST to push a state update (called by simulation_harness.py) ─────────────

@abm_state_bp.route('/api/abm/state', methods=['POST'])
def push_abm_state():
    """
    Called by simulation_harness.py after each day step.
    Accepts JSON body and writes it to Redis.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data'}), 400

        r = get_redis()
        r.setex('abm:current_state', 300, json.dumps(data))  # expires after 5 min
        r.set('abm:mode', data.get('mode', 'simulation'))

        return jsonify({'success': True})

    except Exception as e:
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


# ── GET watchlist state (live data mode) ──────────────────────────────────────

@abm_state_bp.route('/api/abm/watchlist-state', methods=['GET'])
@optional_auth
def get_watchlist_abm_state():
    """
    Converts your real Supabase watchlist into the same JSON shape
    that Three.js expects — so the same visualiser works for both modes.
    """
    try:
        user_id = getattr(request, 'user_id', None)
        if not user_id:
            user_id = anon_user_id()

        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        supabase = get_supabase_client()

        result = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select(
            'wallet_address, tier, professional_score, roi_30d, '
            'runners_30d, win_rate_7d, consistency_score, zone, form'
        ).eq('user_id', user_id).execute()

        wallets = result.data or []

        # Convert to the agent shape Three.js expects
        agents = []
        for i, w in enumerate(wallets[:11]):  # max 11 agents like simulation
            score = w.get('professional_score') or 0
            zone  = w.get('zone', 'green')

            status = 'healthy'
            if zone in ('red', 'critical') or score < 40:
                status = 'critical'
            elif zone in ('orange', 'yellow') or score < 65:
                status = 'warning'

            agents.append({
                'id':           f"WALLET_{i}",
                'name':         w['wallet_address'][:8] + '...',
                'full_address': w['wallet_address'],
                'score':        round(score, 1),
                'status':       status,
                'tier':         w.get('tier', 'C'),
                'roi_30d':      w.get('roi_30d') or 0,
                'runners_30d':  w.get('runners_30d') or 0,
                'win_rate_7d':  w.get('win_rate_7d') or 0,
                'is_replacement': False,
                'role':         w.get('tier', 'C') + '-Tier',
            })

        state = {
            'status':       'live',
            'mode':         'watchlist',
            'day':          None,           # not time-stepped, it's live
            'market_state': 'LIVE',
            'agents':       agents,
            'stats': {
                'total_wallets':  len(agents),
                'elite_count':    sum(1 for a in agents if a['score'] >= 80),
                'warning_count':  sum(1 for a in agents if a['status'] == 'warning'),
                'critical_count': sum(1 for a in agents if a['status'] == 'critical'),
            },
            'events': [],
            'monte_carlo': None,
        }

        return jsonify(state)

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500


# ── Reset endpoint ────────────────────────────────────────────────────────────

@abm_state_bp.route('/api/abm/reset', methods=['POST'])
def reset_abm_state():
    try:
        r = get_redis()
        r.delete('abm:current_state')
        r.delete('abm:mode')
        return jsonify({'success': True})
    except Exception as e:
        logger.exception("Request failed")
        return jsonify({'error': 'Internal server error'}), 500