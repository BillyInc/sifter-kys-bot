"""Redis-backed navigation state machine for the Telegram trading bot.

Every user's current screen and any awaited free-text input is tracked in
Redis so the bot knows how to interpret the next message and survives process
restarts. This replaces the in-memory ``_wallet_import_pending`` dict in
``telegram_notifier.py`` (which was lost on every restart).

Key:    sifter:bot_state:{chat_id}
Value:  {"screen": str, "awaiting": str|None, "data": dict, "updated_at": float}
TTL:    3600 seconds (1 hour) — abandoned flows auto-clear, refreshed on write.

State is shared across webhook threads and Celery workers via Redis. All reads
are defensive: a missing or corrupt value returns a fresh default rather than
raising, so a bad state can never wedge a user.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from services.redis_pool import get_redis_client

logger = logging.getLogger(__name__)

STATE_PREFIX = "sifter:bot_state:"
STATE_TTL_SECONDS = 3600
DEFAULT_SCREEN = "main"


def _key(chat_id: Any) -> str:
    return f"{STATE_PREFIX}{chat_id}"


def _default_state() -> Dict[str, Any]:
    return {"screen": DEFAULT_SCREEN, "awaiting": None, "data": {}}


def get_state(chat_id: Any) -> Dict[str, Any]:
    """Return the user's current state, or a fresh default if absent/corrupt.

    Never raises — a Redis error or malformed JSON yields the default state so
    navigation degrades gracefully instead of breaking the conversation.
    """
    try:
        raw = get_redis_client().get(_key(chat_id))
    except Exception as exc:  # pragma: no cover - redis unavailable
        logger.warning("[BOT_STATE] get failed for %s: %s", chat_id, exc)
        return _default_state()

    if not raw:
        return _default_state()

    try:
        state = json.loads(raw)
        if not isinstance(state, dict):
            return _default_state()
    except (ValueError, TypeError):
        logger.warning("[BOT_STATE] corrupt state for %s, resetting", chat_id)
        return _default_state()

    # Normalize shape so callers can rely on the keys existing.
    state.setdefault("screen", DEFAULT_SCREEN)
    state.setdefault("awaiting", None)
    state.setdefault("data", {})
    if not isinstance(state["data"], dict):
        state["data"] = {}
    return state


def _write(chat_id: Any, state: Dict[str, Any]) -> Dict[str, Any]:
    state["updated_at"] = time.time()
    try:
        get_redis_client().setex(
            _key(chat_id),
            STATE_TTL_SECONDS,
            json.dumps(state, default=str),
        )
    except Exception as exc:  # pragma: no cover - redis unavailable
        logger.warning("[BOT_STATE] write failed for %s: %s", chat_id, exc)
    return state


def set_state(
    chat_id: Any,
    *,
    screen: Optional[str] = None,
    awaiting: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    merge_data: bool = True,
) -> Dict[str, Any]:
    """Partially update a user's state and refresh the TTL (sliding window).

    Only the provided fields change. ``awaiting`` is always set to the passed
    value (pass ``None`` explicitly to clear it). When ``merge_data`` is True
    the ``data`` dict is shallow-merged into the existing one; otherwise it
    replaces it.
    """
    state = get_state(chat_id)

    if screen is not None:
        state["screen"] = screen
    state["awaiting"] = awaiting

    if data is not None:
        if merge_data:
            merged = dict(state.get("data") or {})
            merged.update(data)
            state["data"] = merged
        else:
            state["data"] = dict(data)

    return _write(chat_id, state)


def set_awaiting(
    chat_id: Any,
    awaiting: Optional[str],
    *,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Enter or leave a free-text input mode without changing the screen.

    e.g. ``set_awaiting(chat_id, "wallet_private_key")`` tells the router that
    the next plain-text message is the wallet key. Pass ``None`` to clear.
    """
    state = get_state(chat_id)
    state["awaiting"] = awaiting
    if data is not None:
        merged = dict(state.get("data") or {})
        merged.update(data)
        state["data"] = merged
    return _write(chat_id, state)


def push_screen(
    chat_id: Any,
    screen: str,
    *,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Navigate to ``screen``, clearing any awaited input and optionally
    merging screen-scoped data."""
    return set_state(chat_id, screen=screen, awaiting=None, data=data, merge_data=True)


def clear_state(chat_id: Any) -> None:
    """Delete a user's state entirely (e.g. /cancel, re-link, terminal action)."""
    try:
        get_redis_client().delete(_key(chat_id))
    except Exception as exc:  # pragma: no cover - redis unavailable
        logger.warning("[BOT_STATE] clear failed for %s: %s", chat_id, exc)


def is_awaiting(chat_id: Any, awaiting: Optional[str] = None) -> bool:
    """True if the user is in any awaited-input mode, or in the specific
    ``awaiting`` mode when one is given."""
    current = get_state(chat_id).get("awaiting")
    if awaiting is None:
        return current is not None
    return current == awaiting
