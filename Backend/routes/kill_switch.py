"""Kill-switch route for the mobile app.

Exposes a lightweight endpoint that the mobile client polls every 60 seconds.
When the kill switch is active, the app pauses all trading activity.

Toggle via Redis key ``mobile:kill_switch`` — set to a JSON object:
    {"active": true, "reason": "Maintenance window"}
or delete / set to ``{"active": false}`` to deactivate.

Quick toggle from CLI:
    redis-cli SET mobile:kill_switch '{"active": true, "reason": "Emergency"}'
    redis-cli DEL mobile:kill_switch
"""

import json
import logging

from flask import Blueprint, jsonify, request

from auth import optional_auth

logger = logging.getLogger(__name__)

kill_switch_bp = Blueprint('kill_switch', __name__)

REDIS_KEY = 'mobile:kill_switch'


def _read_kill_switch_redis() -> dict:
    """Read the kill-switch state from Redis.

    Returns ``{"active": bool, "reason": str | None}``.
    Falls back to inactive if Redis is unavailable or the key is missing.
    """
    try:
        from services.redis_pool import get_redis_client
        r = get_redis_client()
        raw = r.get(REDIS_KEY)
        if raw:
            data = json.loads(raw)
            return {
                'active': bool(data.get('active', False)),
                'reason': data.get('reason'),
            }
    except Exception as exc:
        logger.warning('kill-switch: could not read Redis (%s)', exc)

    return {'active': False, 'reason': None}


# ── Endpoints ───────────────────────────────────────────────────────────────

@kill_switch_bp.route('/kill-switch/status', methods=['GET'])
@optional_auth
def kill_switch_status():
    """Return the current kill-switch state.

    Mobile client expects:
        { "killEnabled": bool, "reason": str | null }
    """
    state = _read_kill_switch_redis()
    return jsonify({
        'killEnabled': state['active'],
        'reason': state['reason'],
    })


@kill_switch_bp.route('/api/mobile/kill-switch', methods=['GET'])
@optional_auth
def kill_switch_mobile():
    """Alternate path — returns the same payload.

    Provided so either ``/kill-switch/status`` or ``/api/mobile/kill-switch``
    work as the mobile client endpoint.
    """
    state = _read_kill_switch_redis()
    return jsonify({
        'active': state['active'],
        'reason': state['reason'],
    })
