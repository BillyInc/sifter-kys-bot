"""Solana network-congestion sampling for adaptive slippage / priority fees.

Copy-trading fails in exactly the moment it matters most: when a token is moving
and the whole chain is congested, a fill at the default slippage / priority fee
sits unconfirmed while the price runs away. This module samples recent on-chain
priority fees and maps the result to a congestion *level* the execution router
uses to scale slippage and the priority fee before it ever submits — and to ramp
them further on a stale/failed retry.

The sampler is deliberately cheap and fail-soft: one RPC call (cached briefly in
Redis), and on ANY error it returns ``NORMAL`` so trading is never blocked by a
telemetry failure.
"""

from __future__ import annotations

import logging
import os
import statistics
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Congestion levels, lowest → highest.
LOW = "low"
NORMAL = "normal"
ELEVATED = "elevated"
HIGH = "high"

# Per-level multipliers applied to the user's configured slippage_bps and to a
# baseline priority fee. Tuned conservatively: NORMAL leaves the user's settings
# untouched (1.0x slippage), higher levels widen slippage and raise priority so
# fills land under load.
_LEVEL_TUNING = {
    LOW:      {"slippage_mult": 1.0, "priority_lamports": 100_000},
    NORMAL:   {"slippage_mult": 1.0, "priority_lamports": 300_000},
    ELEVATED: {"slippage_mult": 1.5, "priority_lamports": 1_000_000},
    HIGH:     {"slippage_mult": 2.0, "priority_lamports": 3_000_000},
}

# Micro-lamports/CU thresholds (median recent prioritization fee) → level.
# These are coarse buckets; the exact numbers matter less than the ordering.
_ELEVATED_THRESHOLD = 10_000
_HIGH_THRESHOLD = 50_000

_CACHE_KEY = "sifter:congestion_level"
_CACHE_TTL = 10  # seconds — congestion changes fast; keep this short.


@dataclass(frozen=True)
class CongestionTuning:
    level: str
    slippage_mult: float
    priority_fee_lamports: int


def _redis():
    try:
        import redis as _redis_lib
        return _redis_lib.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True
        )
    except Exception:
        return None


def _sample_median_priority_fee() -> Optional[float]:
    """Return the median recent prioritization fee (micro-lamports/CU) via RPC.

    Uses ``getRecentPrioritizationFees``. Returns None on any failure so the
    caller falls back to NORMAL."""
    try:
        import requests as _requests
        rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        resp = _requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "getRecentPrioritizationFees", "params": [[]]},
            timeout=5,
        )
        if resp.status_code != 200:
            return None
        result = resp.json().get("result") or []
        fees = [float(r.get("prioritizationFee") or 0) for r in result if isinstance(r, dict)]
        fees = [f for f in fees if f > 0]
        if not fees:
            return 0.0
        return statistics.median(fees)
    except Exception as exc:
        logger.debug("[CONGESTION] sample failed: %s", exc)
        return None


def _classify(median_fee: Optional[float]) -> str:
    if median_fee is None:
        return NORMAL
    if median_fee >= _HIGH_THRESHOLD:
        return HIGH
    if median_fee >= _ELEVATED_THRESHOLD:
        return ELEVATED
    if median_fee <= 0:
        return LOW
    return NORMAL


def get_congestion_level() -> str:
    """Return the current congestion level, cached briefly in Redis.

    Fail-soft: any error → NORMAL."""
    r = _redis()
    if r is not None:
        try:
            cached = r.get(_CACHE_KEY)
            if cached:
                return cached
        except Exception:
            pass
    level = _classify(_sample_median_priority_fee())
    if r is not None:
        try:
            r.setex(_CACHE_KEY, _CACHE_TTL, level)
        except Exception:
            pass
    return level


def get_tuning(level: Optional[str] = None) -> CongestionTuning:
    """Return the slippage multiplier + baseline priority fee for a level.

    Pass an explicit ``level`` to avoid re-sampling (e.g. the router samples once
    then derives tuning for each retry step)."""
    lvl = level or get_congestion_level()
    t = _LEVEL_TUNING.get(lvl, _LEVEL_TUNING[NORMAL])
    return CongestionTuning(
        level=lvl,
        slippage_mult=t["slippage_mult"],
        priority_fee_lamports=t["priority_lamports"],
    )
