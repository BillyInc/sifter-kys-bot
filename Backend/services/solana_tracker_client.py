"""Shared SolanaTracker V2 API client with rate limiting, retries, and Redis caching.

Replaces the inline ``_st_get()`` calls scattered across multiple files with a
single, well-behaved client that respects the API's rate limits and avoids
redundant network calls via Redis caching.

Usage::

    from services.solana_tracker_client import get_st_client

    client = get_st_client()
    traders = client.get_leaderboard_top(days=7, limit=100)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any

from config import Config
from services.http_session import get_http_session
from services.redis_pool import get_redis_client

logger = logging.getLogger(__name__)

BASE_URL = "https://data.solanatracker.io"

# Rate-limit: 3 requests/second => 0.333s minimum between requests.
_MIN_INTERVAL = 1.0 / 3.0

# Retry configuration
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; exponential: 1s, 2s, 4s

# Default cache TTLs (seconds)
_CACHE_TTL_1H = 3600


class SolanaTrackerClient:
    """Thread-safe SolanaTracker API client with rate limiting, retries, and caching."""

    def __init__(self) -> None:
        self._api_key: str = Config.SOLANATRACKER_API_KEY
        self._headers: dict[str, str] = {
            "x-api-key": self._api_key,
            "Accept": "application/json",
        }
        self._lock = threading.Lock()
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Block until the minimum interval between requests has elapsed."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - elapsed)
            self._last_request_time = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request with rate limiting and exponential-backoff retries."""
        url = f"{BASE_URL}{path}"
        session = get_http_session()
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            self._rate_limit()
            try:
                resp = session.request(
                    method,
                    url,
                    headers=self._headers,
                    params=params,
                    json=json_body,
                    timeout=30,
                )

                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", _BACKOFF_BASE * (2 ** attempt)))
                    logger.warning(
                        "SolanaTracker 429 rate-limited on %s (attempt %d/%d), "
                        "sleeping %.1fs",
                        path, attempt + 1, _MAX_RETRIES, retry_after,
                    )
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp.json()

            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "SolanaTracker request failed for %s (attempt %d/%d): %s — "
                        "retrying in %.1fs",
                        path, attempt + 1, _MAX_RETRIES, exc, wait,
                    )
                    time.sleep(wait)

        logger.error("SolanaTracker request failed after %d attempts: %s", _MAX_RETRIES, last_exc)
        raise last_exc  # type: ignore[misc]

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json_body: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, json_body=json_body)

    @staticmethod
    def _cache_key(path: str, params: dict[str, Any] | None = None) -> str:
        """Build a deterministic Redis cache key from the URL path and params."""
        raw = f"{path}:{json.dumps(params, sort_keys=True)}" if params else path
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"st:v2:{digest}"

    def _cached_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        ttl: int = _CACHE_TTL_1H,
    ) -> Any:
        """GET with Redis caching.  Returns cached value if present, otherwise
        fetches from the API and stores the result."""
        key = self._cache_key(path, params)
        redis = get_redis_client()
        try:
            cached = redis.get(key)
            if cached is not None:
                logger.debug("SolanaTracker cache hit: %s", key)
                return json.loads(cached)
        except Exception:
            logger.debug("Redis read failed for %s, falling through to API", key)

        data = self._get(path, params)

        try:
            redis.setex(key, ttl, json.dumps(data))
        except Exception:
            logger.debug("Redis write failed for %s", key)

        return data

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_leaderboard_top(
        self,
        days: int = 30,
        sort: str = "roi",
        limit: int = 500,
        min_roi: float | None = None,
        min_invested: float | None = None,
        min_trades: int | None = None,
        exclude_arbitrage: bool = True,
    ) -> list[dict]:
        """Return the top trader leaderboard.

        ``GET /v2/pnl/leaderboard/top``
        """
        params: dict[str, Any] = {
            "days": days,
            "sort": sort,
            "direction": "desc",
            "limit": limit,
            "excludeArbitrage": exclude_arbitrage,
            "pnlMode": "strict",
        }
        if min_roi is not None:
            params["minRoi"] = min_roi
        if min_invested is not None:
            params["minInvested"] = min_invested
        if min_trades is not None:
            params["minTrades"] = min_trades

        data = self._get("/v2/pnl/leaderboard/top", params)
        return data.get("traders", [])

    def get_wallet_positions(
        self,
        wallet: str,
        holding_state: str = "closed",
        sort: str = "roi",
        limit: int = 100,
        roi_min: float | None = None,
        invested_min: float | None = None,
    ) -> list[dict]:
        """Return positions for a wallet.

        ``GET /v2/pnl/wallets/{wallet}/positions``
        """
        params: dict[str, Any] = {
            "holdingState": holding_state,
            "sort": sort,
            "direction": "desc",
            "limit": limit,
            "pnlMode": "strict",
        }
        if roi_min is not None:
            params["roiMin"] = roi_min
        if invested_min is not None:
            params["investedMin"] = invested_min

        data = self._get(f"/v2/pnl/wallets/{wallet}/positions", params)
        return data.get("positions", [])

    def get_wallet_token_position(self, wallet: str, token: str) -> dict | None:
        """Return a single wallet-token position (not cached — data changes frequently).

        ``GET /v2/pnl/wallets/{wallet}/tokens/{token}``
        """
        params: dict[str, Any] = {"pnlMode": "strict"}
        try:
            return self._get(f"/v2/pnl/wallets/{wallet}/tokens/{token}", params)
        except Exception:
            logger.debug("wallet-token position not found: %s / %s", wallet, token)
            return None

    def get_first_buyers(self, token: str, limit: int = 50) -> list[dict]:
        """Return first buyers for a token (cached 1 hour).

        ``GET /v2/pnl/tokens/{token}/first-buyers``
        """
        params: dict[str, Any] = {
            "sort": "first_trade",
            "direction": "asc",
            "limit": limit,
        }
        data = self._cached_get(
            f"/v2/pnl/tokens/{token}/first-buyers",
            params,
            ttl=_CACHE_TTL_1H,
        )
        return data.get("traders", [])

    def get_token_traders(
        self,
        token: str,
        sort: str = "roi",
        limit: int = 50,
    ) -> list[dict]:
        """Return traders for a token.

        ``GET /v2/pnl/tokens/{token}/traders``
        """
        params: dict[str, Any] = {
            "sort": sort,
            "direction": "desc",
            "limit": limit,
        }
        data = self._get(f"/v2/pnl/tokens/{token}/traders", params)
        return data.get("traders", [])

    def get_token_ath(self, token: str) -> dict | None:
        """Return all-time-high data for a token (cached 1 hour).

        ``GET /tokens/{token}/ath``  (note: NOT a /v2 path)
        """
        try:
            return self._cached_get(
                f"/tokens/{token}/ath",
                ttl=_CACHE_TTL_1H,
            )
        except Exception:
            logger.debug("token ATH not found: %s", token)
            return None

    def get_wallets_batch(self, wallets: list[str]) -> list[dict]:
        """Return batch wallet data.

        ``POST /v2/pnl/wallets/batch``
        """
        data = self._post("/v2/pnl/wallets/batch", json_body={"wallets": wallets})
        return data.get("wallets", [])


# ------------------------------------------------------------------
# Singleton accessor
# ------------------------------------------------------------------

_client: SolanaTrackerClient | None = None
_client_lock = threading.Lock()


def get_st_client() -> SolanaTrackerClient:
    """Return the module-level singleton ``SolanaTrackerClient``."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = SolanaTrackerClient()
    return _client
