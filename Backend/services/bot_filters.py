"""Auto-trade signal filters for the Telegram bot.

The filter stack is INTENTIONALLY just two checks:

    1. Consensus  — enough Elite wallets agreed within the 120s window
                    (wallet_count >= user's consensus_threshold)
    2. Blacklist  — the token is not on the user's bot_token_blacklist

There are deliberately NO fake-volume, risk-score, or market-cap filters.
When the bot copy-trades a vetted set of Elite wallets, the wallets ARE the
token-quality filter — re-screening would only second-guess the very wallets
the user selected. Honeypot/rug protection lives in the execution layer, not
here. Do not add fake_vol/risk_score/min_mc/max_mc checks to this module.

``passes_auto_trade_filters`` is a pure predicate so it is trivially testable;
``load_blacklist_set`` is the small DB helper the signal fan-out (Sprint 4)
uses to build the blacklist argument once per user.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set, Tuple

from services.supabase_client import SCHEMA_NAME

logger = logging.getLogger(__name__)


def passes_auto_trade_filters(
    user_row: Dict[str, Any],
    signal: Dict[str, Any],
    blacklist_set: Set[str],
) -> Tuple[bool, Optional[str]]:
    """Return ``(ok, reason)`` for whether ``signal`` should auto-trade for a user.

    ``reason`` is ``None`` on pass, otherwise a short machine code:
        "below_consensus" | "blacklisted"

    Exactly two checks — see the module docstring for why there are no
    fake-volume / risk-score / market-cap filters.
    """
    # 1. Consensus threshold: how many Elite wallets must agree (0-15).
    wallet_count = int(signal.get("wallet_count") or 1)
    threshold = int(user_row.get("consensus_threshold") or 1)
    if wallet_count < threshold:
        return False, "below_consensus"

    # 2. Token blacklist.
    token_address = signal.get("token_address") or ""
    if token_address and token_address in blacklist_set:
        return False, "blacklisted"

    return True, None


def load_blacklist_set(supabase, user_id: str) -> Set[str]:
    """Return the set of token addresses a user has blacklisted.

    Best-effort: returns an empty set on any error so a transient DB issue
    can't silently widen trading (the caller still applies consensus)."""
    try:
        res = (
            supabase.schema(SCHEMA_NAME)
            .table("bot_token_blacklist")
            .select("token_address")
            .eq("user_id", user_id)
            .execute()
        )
        return {row["token_address"] for row in (res.data or []) if row.get("token_address")}
    except Exception as exc:
        logger.error("[BOT_FILTERS] load_blacklist_set failed for %s: %s", user_id, exc)
        return set()
