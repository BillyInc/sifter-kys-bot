"""
Signal aggregator — groups multiple Elite wallet buys on the same token
into a single signal with the correct wallet_count before execution.

Helius fires one webhook per wallet transaction. This module holds signals
for AGGREGATION_WINDOW_SECONDS, merges concurrent wallet buys, then emits
one grouped signal. The Celery beat task flush_signal_aggregator calls
flush_expired() every 10 seconds.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class _PendingSignal:
    token_address: str
    first_seen: float
    wallet_addresses: List[str] = field(default_factory=list)
    wallet_count: int = 0
    total_usd: float = 0.0
    base_signal: Optional[Dict] = None
    committed: bool = False

    def age_seconds(self) -> float:
        return time.time() - self.first_seen


class SignalAggregator:
    """Thread-safe signal grouping window for Elite 15 wallet buys."""

    def __init__(self):
        try:
            from services.trading_rules import AGGREGATION_WINDOW_SECONDS
            self._window = AGGREGATION_WINDOW_SECONDS
        except ImportError:
            self._window = 120

        self._pending: Dict[str, _PendingSignal] = {}
        self._lock = threading.Lock()
        logger.info("[AGGREGATOR] action=init status=ok window_seconds=%d", self._window)

    def receive(self, signal: Dict) -> None:
        token_address = signal.get("token_address", "")
        wallet_address = signal.get("wallet_address", "")
        usd_value = float(signal.get("usd_value") or 0)

        if not token_address or not wallet_address:
            logger.warning("[AGGREGATOR] action=receive status=skipped reason=missing_fields")
            return

        with self._lock:
            if token_address not in self._pending:
                self._pending[token_address] = _PendingSignal(
                    token_address=token_address,
                    first_seen=time.time(),
                    wallet_addresses=[wallet_address],
                    wallet_count=1,
                    total_usd=usd_value,
                    base_signal=signal,
                )
                logger.info(
                    "[AGGREGATOR] action=receive status=new token=%s wallet=%s usd=%.2f window=%ds",
                    token_address[:8], wallet_address[:8], usd_value, self._window,
                )
            else:
                agg = self._pending[token_address]
                if wallet_address not in agg.wallet_addresses:
                    agg.wallet_addresses.append(wallet_address)
                    agg.wallet_count += 1
                    agg.total_usd += usd_value
                    logger.info(
                        "[AGGREGATOR] action=receive status=grouped token=%s wallet=%s "
                        "wallet_count_now=%d age_seconds=%.1f",
                        token_address[:8], wallet_address[:8],
                        agg.wallet_count, agg.age_seconds(),
                    )

    def flush_expired(self, emit_callback: Callable[[Dict], None]) -> int:
        now = time.time()
        emitted = 0

        with self._lock:
            to_emit = [
                token for token, agg in self._pending.items()
                if not agg.committed and now - agg.first_seen >= self._window
            ]

            for token_address in to_emit:
                agg = self._pending[token_address]

                from services.trading_rules import classify_signal
                signal_type = classify_signal(agg.wallet_count)

                grouped_signal = {
                    **agg.base_signal,
                    "wallet_count": agg.wallet_count,
                    "total_usd": round(agg.total_usd, 2),
                    "wallet_addresses": agg.wallet_addresses,
                    "wallets": [{"wallet": w, "tier": "S"} for w in agg.wallet_addresses],
                    "trades": [{"usd_value": agg.total_usd}],
                    "signal_type_resolved": signal_type,
                    "aggregation_window_seconds": self._window,
                    "aggregation_first_seen": agg.first_seen,
                    "aggregation_age_seconds": round(now - agg.first_seen, 1),
                }

                agg.committed = True
                logger.info(
                    "[AGGREGATOR] action=emit status=ok token=%s wallet_count=%d "
                    "signal_type=%s total_usd=%.2f age_seconds=%.1f",
                    token_address[:8], agg.wallet_count, signal_type,
                    agg.total_usd, now - agg.first_seen,
                )

                try:
                    emit_callback(grouped_signal)
                    emitted += 1
                except Exception as exc:
                    logger.error(
                        "[AGGREGATOR] action=emit status=error token=%s error=%s",
                        token_address[:8], str(exc)[:200],
                    )

            stale = [
                token for token, agg in self._pending.items()
                if agg.committed and now - agg.first_seen > self._window * 3
            ]
            for token_address in stale:
                del self._pending[token_address]

        pending_count = self.get_pending_count()
        logger.info(
            "[AGGREGATOR] action=flush status=ok emitted=%d pending=%d",
            emitted, pending_count,
        )
        return emitted

    def get_pending_count(self) -> int:
        with self._lock:
            return sum(1 for agg in self._pending.values() if not agg.committed)


_instance: Optional[SignalAggregator] = None
_instance_lock = threading.Lock()


def get_aggregator() -> SignalAggregator:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SignalAggregator()
    return _instance
