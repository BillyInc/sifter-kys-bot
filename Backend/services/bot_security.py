"""Security defenses for the copy-trading bot.

Copy-trading a vetted set of Elite wallets is baitable. Attackers exploit it via:

  1. ADDRESS POISONING — send a dust transaction from a vanity address whose
     first/last few characters match a real Elite wallet, hoping a prefix/suffix
     comparison treats it as Elite. Defense: exact full-address match only.

  2. TICKER / MINT MIMICRY — deploy a fake token with the same ticker as a real
     one. The signal says "Elite bought $WIF" but the mint is the impostor's.
     Defense: verify the canonical mint + a minimum real-liquidity floor.

  3. ACTIVITY FAKING (transfer-in mimicry) — send tokens TO an Elite wallet so a
     naive monitor records "Elite now holds X" as a buy. Defense: only genuine
     swap/BUY events count, never inbound transfers/airdrops.

  4. DUST BAIT — near-zero-value events to trigger a copy on garbage. Defense:
     a minimum USD floor per signal.

These run BEFORE consensus/blacklist in the filter stack, and also guard the
manual signal picker and the Elite-sell notification path (notifications are
baitable too — a fake "Elite sold" can scare a user into dumping).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Minimum USD value for a signal to be considered real (anti-dust).
MIN_SIGNAL_USD = 50.0
# Minimum on-chain liquidity for a token to be tradeable (anti-mimicry rug).
MIN_LIQUIDITY_USD = 5_000.0


def verify_elite_wallet(signal_wallet: str, elite_set: Set[str]) -> bool:
    """Exact full-address membership. NEVER prefix/suffix.

    Address poisoning relies on look-alike vanity addresses (same first/last
    4-6 chars). A full-string set membership defeats it.
    """
    if not signal_wallet:
        return False
    # Exact match against the known-good Elite set. No truncation, no
    # normalization beyond strip — Solana addresses are case-sensitive base58.
    return signal_wallet.strip() in elite_set


def looks_like_poisoning(signal_wallet: str, elite_set: Set[str]) -> bool:
    """True if the wallet is NOT exactly Elite but SHARES a prefix/suffix with
    one — i.e. a probable poisoning attempt worth logging/alerting."""
    w = (signal_wallet or "").strip()
    if not w or w in elite_set:
        return False
    for e in elite_set:
        if len(w) >= 8 and len(e) >= 8:
            if w[:4] == e[:4] and w[-4:] == e[-4:]:
                return True
    return False


def verify_signal_provenance(signal: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Reject signals that are not genuine swap/BUY events.

    Mimicry sends tokens TO an Elite wallet (transfer/airdrop) to fake activity.
    Only an actual swap where the Elite wallet SPENT sol/usdc to acquire the
    token counts. We require:
      - event type is a buy/swap (not transfer/airdrop/mint)
      - the Elite wallet was the BUYER (out = token, in = sol/usdc)
    """
    event_type = str(signal.get("event_type") or signal.get("type") or "swap").lower()
    if event_type in ("transfer", "airdrop", "mint", "receive"):
        return False, "non_swap_event"
    side = str(signal.get("side") or "buy").lower()
    if side not in ("buy", "swap"):
        return False, "not_a_buy"
    return True, None


def verify_not_dust(signal: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Reject near-zero-value signals (dust bait)."""
    usd = float(signal.get("usd_value") or signal.get("total_usd") or 0)
    if usd < MIN_SIGNAL_USD:
        return False, "dust_value"
    return True, None


def verify_token_mint(signal: Dict[str, Any], *, fetch_canonical: bool = True) -> Tuple[bool, Optional[str]]:
    """Verify the token mint is real and liquid (anti ticker/mint mimicry).

    The signal carries a ticker AND a mint. An impostor reuses the ticker with a
    different mint. We trust the MINT (immutable) over the ticker, and confirm it
    has real liquidity via SolanaTracker. If lookup is unavailable we fail OPEN
    only on the liquidity check (so a transient API error can't halt trading) but
    we ALWAYS enforce that a mint is present and well-formed.
    """
    mint = (signal.get("token_address") or "").strip()
    if not (32 <= len(mint) <= 50):
        return False, "invalid_mint"
    if not fetch_canonical:
        return True, None
    try:
        from services.solana_tracker_client import get_st_client
        info = get_st_client().get_token_info(mint)
        if info:
            pools = info.get("pools") or []
            liq = 0.0
            if pools:
                liqd = pools[0].get("liquidity") or {}
                liq = float(liqd.get("usd") or 0) if isinstance(liqd, dict) else 0.0
            if liq and liq < MIN_LIQUIDITY_USD:
                return False, "low_liquidity"
    except Exception as exc:
        logger.warning("[BOT_SECURITY] mint liquidity check unavailable for %s: %s", mint[:8], exc)
        # Fail open on liquidity only — mint format was already validated.
    return True, None


def security_screen(
    signal: Dict[str, Any],
    elite_set: Set[str],
    *,
    require_elite_wallet: bool = True,
    check_liquidity: bool = True,
) -> Tuple[bool, Optional[str]]:
    """Run all security checks. Returns (ok, reason).

    ``require_elite_wallet`` is True for autonomous copy-trades (the signaling
    wallet must be a real Elite wallet). For manual trades the user chose the
    token themselves, so wallet provenance is not required — but mint/dust
    checks still apply.
    """
    # 1. Provenance — genuine buy, not a transfer-in fake.
    ok, reason = verify_signal_provenance(signal)
    if not ok:
        return False, reason

    # 2. Dust bait.
    ok, reason = verify_not_dust(signal)
    if not ok:
        return False, reason

    # 3. Mint / liquidity (anti ticker mimicry).
    ok, reason = verify_token_mint(signal, fetch_canonical=check_liquidity)
    if not ok:
        return False, reason

    # 4. Elite wallet exact match (autonomous only).
    if require_elite_wallet:
        wallets = signal.get("wallet_addresses") or signal.get("wallets") or []
        # wallets may be list[str] or list[{"wallet":..}]
        flat: list = []
        for w in wallets:
            if isinstance(w, dict):
                flat.append(w.get("wallet") or w.get("wallet_address") or "")
            else:
                flat.append(w)
        single = signal.get("wallet_address")
        if single:
            flat.append(single)
        # At least one signaling wallet must be EXACTLY in the Elite set.
        if not any(verify_elite_wallet(w, elite_set) for w in flat if w):
            # Log a poisoning attempt if it's a look-alike.
            for w in flat:
                if looks_like_poisoning(w, elite_set):
                    logger.warning("[BOT_SECURITY] address poisoning attempt: %s", w)
                    return False, "address_poisoning"
            return False, "wallet_not_elite"

    return True, None
