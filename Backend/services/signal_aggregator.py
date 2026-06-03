"""
Signal aggregator — groups multiple Elite wallet buys on the same token
into a single signal with the correct wallet_count before execution.

Helius fires one webhook per wallet transaction. This module holds signals
for AGGREGATION_WINDOW_SECONDS, merges concurrent wallet buys, then emits
one grouped signal. The Celery beat task flush_signal_aggregator calls
flush_expired() every 10 seconds.

State is stored in Redis so it's shared across Celery worker processes.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

REDIS_PREFIX = "sifter:sigagg:"


class SignalAggregator:
    """Redis-backed signal grouping window for Elite 15 wallet buys."""

    def __init__(self):
        try:
            from services.trading_rules import AGGREGATION_WINDOW_SECONDS
            self._window = AGGREGATION_WINDOW_SECONDS
        except ImportError:
            self._window = 120

        from services.redis_pool import get_redis_client
        self._redis = get_redis_client()
        logger.info("[AGGREGATOR] action=init status=ok window_seconds=%d", self._window)

    def _key(self, token_address: str) -> str:
        return f"{REDIS_PREFIX}{token_address}"

    def receive(self, signal: Dict) -> None:
        token_address = signal.get("token_address", "")
        wallet_address = signal.get("wallet_address", "")
        usd_value = float(signal.get("usd_value") or 0)

        if not token_address or not wallet_address:
            logger.warning("[AGGREGATOR] action=receive status=skipped reason=missing_fields")
            return

        key = self._key(token_address)
        existing = self._redis.get(key)

        if existing is None:
            entry = {
                "token_address": token_address,
                "first_seen": time.time(),
                "wallet_addresses": [wallet_address],
                "wallet_count": 1,
                "total_usd": usd_value,
                "base_signal": signal,
                "committed": False,
            }
            # TTL = 3x window to auto-cleanup stale entries
            self._redis.setex(key, self._window * 3, json.dumps(entry, default=str))
            logger.info(
                "[AGGREGATOR] action=receive status=new token=%s wallet=%s usd=%.2f window=%ds",
                token_address[:8], wallet_address[:8], usd_value, self._window,
            )
        else:
            entry = json.loads(existing)
            if wallet_address not in entry["wallet_addresses"]:
                entry["wallet_addresses"].append(wallet_address)
                entry["wallet_count"] += 1
                entry["total_usd"] += usd_value
                ttl = self._redis.ttl(key)
                self._redis.setex(key, max(ttl, 60), json.dumps(entry, default=str))
                logger.info(
                    "[AGGREGATOR] action=receive status=grouped token=%s wallet=%s "
                    "wallet_count_now=%d",
                    token_address[:8], wallet_address[:8], entry["wallet_count"],
                )

    def flush_expired(self, emit_callback: Callable[[Dict], None]) -> int:
        now = time.time()
        emitted = 0

        # Scan for all pending signal keys
        keys = list(self._redis.scan_iter(match=f"{REDIS_PREFIX}*", count=100))

        for key in keys:
            raw = self._redis.get(key)
            if raw is None:
                continue

            entry = json.loads(raw)
            if entry.get("committed"):
                continue

            first_seen = float(entry["first_seen"])
            if now - first_seen < self._window:
                continue

            # Window expired — emit
            from services.trading_rules import classify_signal
            signal_type = classify_signal(entry["wallet_count"])

            grouped_signal = {
                **entry["base_signal"],
                "wallet_count": entry["wallet_count"],
                "total_usd": round(entry["total_usd"], 2),
                "wallet_addresses": entry["wallet_addresses"],
                "wallets": [{"wallet": w, "tier": "S"} for w in entry["wallet_addresses"]],
                "trades": [{"usd_value": entry["total_usd"]}],
                "signal_type_resolved": signal_type,
                "signal_key": f"elite:{entry['token_address']}:{int(first_seen)}:{entry['wallet_count']}",
                "side": "buy",
                "aggregation_window_seconds": self._window,
                "aggregation_first_seen": first_seen,
                "aggregation_age_seconds": round(now - first_seen, 1),
            }

            entry["committed"] = True
            # Keep committed entry briefly for dedup, then let TTL expire
            self._redis.setex(key, 300, json.dumps(entry, default=str))

            logger.info(
                "[AGGREGATOR] action=emit status=ok token=%s wallet_count=%d "
                "signal_type=%s total_usd=%.2f age_seconds=%.1f",
                entry["token_address"][:8], entry["wallet_count"], signal_type,
                entry["total_usd"], now - first_seen,
            )

            try:
                emit_callback(grouped_signal)
                emitted += 1
            except Exception as exc:
                logger.error(
                    "[AGGREGATOR] action=emit status=error token=%s error=%s",
                    entry["token_address"][:8], str(exc)[:200],
                )

        pending_count = self.get_pending_count()
        logger.info(
            "[AGGREGATOR] action=flush status=ok emitted=%d pending=%d",
            emitted, pending_count,
        )
        return emitted

    def get_pending_count(self) -> int:
        count = 0
        for key in self._redis.scan_iter(match=f"{REDIS_PREFIX}*", count=100):
            raw = self._redis.get(key)
            if raw:
                entry = json.loads(raw)
                if not entry.get("committed"):
                    count += 1
        return count


_instance: Optional[SignalAggregator] = None


def get_aggregator() -> SignalAggregator:
    global _instance
    if _instance is None:
        _instance = SignalAggregator()
    return _instance
