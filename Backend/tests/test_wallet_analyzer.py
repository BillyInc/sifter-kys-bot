"""Tests for services/wallet_analyzer.py — WalletPumpAnalyzer."""

import pytest
import time
import json
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analyzer(**overrides):
    """Create a WalletPumpAnalyzer with all external deps mocked out."""
    defaults = dict(
        solanatracker_api_key="test-key",
        birdeye_api_key="test-birdeye",
        debug_mode=False,
        read_only=True,
    )
    defaults.update(overrides)

    with patch("services.wallet_analyzer.duckdb") as mock_duckdb, \
         patch("services.wallet_analyzer.redis_lib") as mock_redis_lib, \
         patch.dict("os.environ", {"WORKER_MODE": "true"}):
        mock_redis_lib.from_url.return_value = MagicMock()
        from services.wallet_analyzer import WalletPumpAnalyzer
        return WalletPumpAnalyzer(**defaults)


# ===========================================================================
# TokenBucket rate limiter
# ===========================================================================

class TestTokenBucket:
    """Tests for _TokenBucket rate limiter."""

    def test_acquire_succeeds_within_burst(self):
        """Burst tokens are available immediately."""
        from services.wallet_analyzer import _TokenBucket
        bucket = _TokenBucket(rate_per_second=10, burst=5)
        for _ in range(5):
            bucket.acquire()
        assert bucket.tokens < 1

    def test_acquire_waits_when_exhausted(self):
        """Blocks briefly when tokens exhausted."""
        from services.wallet_analyzer import _TokenBucket
        bucket = _TokenBucket(rate_per_second=100, burst=1)
        bucket.acquire()
        start = time.time()
        bucket.acquire()  # should wait ~0.01s
        elapsed = time.time() - start
        assert elapsed < 1.0


# ===========================================================================
# Redis helpers
# ===========================================================================

class TestRedisHelpers:
    """Tests for _redis_get / _redis_set / _redis_delete."""

    def test_redis_get_returns_parsed_json(self):
        analyzer = _make_analyzer()
        analyzer._redis = MagicMock()
        analyzer._redis.get.return_value = '{"foo": "bar"}'
        result = analyzer._redis_get("some_key")
        assert result == {"foo": "bar"}

    def test_redis_get_returns_none_when_empty(self):
        analyzer = _make_analyzer()
        analyzer._redis = MagicMock()
        analyzer._redis.get.return_value = None
        assert analyzer._redis_get("missing_key") is None

    def test_redis_get_returns_none_when_no_client(self):
        analyzer = _make_analyzer()
        analyzer._redis = None
        assert analyzer._redis_get("any_key") is None

    def test_redis_get_handles_exception(self):
        analyzer = _make_analyzer()
        analyzer._redis = MagicMock()
        analyzer._redis.get.side_effect = Exception("connection lost")
        assert analyzer._redis_get("key") is None

    def test_redis_set_calls_setex(self):
        analyzer = _make_analyzer()
        analyzer._redis = MagicMock()
        analyzer._redis_set("k", {"a": 1}, 300)
        analyzer._redis.setex.assert_called_once_with("k", 300, json.dumps({"a": 1}))

    def test_redis_set_no_op_without_client(self):
        analyzer = _make_analyzer()
        analyzer._redis = None
        analyzer._redis_set("k", {"a": 1}, 300)

    def test_redis_delete_calls_delete(self):
        analyzer = _make_analyzer()
        analyzer._redis = MagicMock()
        analyzer._redis_delete("k")
        analyzer._redis.delete.assert_called_once_with("k")

    def test_redis_delete_no_op_without_client(self):
        analyzer = _make_analyzer()
        analyzer._redis = None
        analyzer._redis_delete("k")


# ===========================================================================
# Hybrid cache
# ===========================================================================

class TestHybridCache:
    """Tests for _get_from_cache / _save_to_cache."""

    def test_returns_redis_data_when_available(self):
        analyzer = _make_analyzer()
        analyzer._redis = MagicMock()
        analyzer._redis.get.return_value = '{"cached": true}'
        data, source = analyzer._get_from_cache("rk", "SELECT 1", [])
        assert data == {"cached": True}
        assert source == "redis"

    def test_returns_none_when_nothing_cached(self):
        analyzer = _make_analyzer()
        analyzer._redis = MagicMock()
        analyzer._redis.get.return_value = None
        analyzer.con = None
        data, source = analyzer._get_from_cache("rk", "SELECT 1", [])
        assert data is None
        assert source is None


# ===========================================================================
# fetch_with_retry
# ===========================================================================

class TestFetchWithRetry:
    """Tests for fetch_with_retry — synchronous API calls."""

    @patch("services.wallet_analyzer.get_http_session")
    @patch("services.wallet_analyzer._st_rate_limiter")
    def test_returns_json_on_200(self, mock_limiter, mock_session):
        analyzer = _make_analyzer()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"wallets": ["a", "b"]}
        mock_session.return_value.get.return_value = mock_resp

        result = analyzer.fetch_with_retry("https://api.test/data", {"x-api-key": "k"})
        assert result == {"wallets": ["a", "b"]}

    @patch("services.wallet_analyzer.get_http_session")
    @patch("services.wallet_analyzer._st_rate_limiter")
    def test_returns_none_on_404(self, mock_limiter, mock_session):
        analyzer = _make_analyzer()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_session.return_value.get.return_value = mock_resp

        result = analyzer.fetch_with_retry("https://api.test/data", {"x-api-key": "k"})
        assert result is None

    @patch("services.wallet_analyzer.get_http_session")
    @patch("services.wallet_analyzer._st_rate_limiter")
    @patch("services.wallet_analyzer.time")
    def test_retries_on_429(self, mock_time, mock_limiter, mock_session):
        analyzer = _make_analyzer()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "1"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"ok": True}

        mock_session.return_value.get.side_effect = [resp_429, resp_200]
        result = analyzer.fetch_with_retry("https://api.test/data", {})
        assert result == {"ok": True}

    @patch("services.wallet_analyzer.get_http_session")
    @patch("services.wallet_analyzer._st_rate_limiter")
    @patch("services.wallet_analyzer.time")
    def test_returns_none_after_all_retries_fail(self, mock_time, mock_limiter, mock_session):
        analyzer = _make_analyzer()
        mock_session.return_value.get.side_effect = ConnectionError("refused")
        result = analyzer.fetch_with_retry("https://api.test/data", {}, max_retries=2)
        assert result is None


# ===========================================================================
# _process_wallet_pnl
# ===========================================================================

class TestProcessWalletPnl:
    """Tests for _process_wallet_pnl — wallet qualification logic."""

    def test_disqualifies_below_min_invested(self):
        analyzer = _make_analyzer()
        wallet_data = {"W1": {"source": "top_traders", "entry_price": 0.01}}
        pnl = {"realized": 500, "unrealized": 0, "total_invested": 50}
        qualified = []
        result = analyzer._process_wallet_pnl("W1", pnl, wallet_data, qualified, 3.0)
        assert result is False
        assert len(qualified) == 0

    def test_disqualifies_below_roi_threshold(self):
        analyzer = _make_analyzer()
        wallet_data = {"W1": {"source": "top_traders", "entry_price": 0.01}}
        # realized_mult = (50 + 200) / 200 = 1.25x
        pnl = {"realized": 50, "unrealized": 0, "total_invested": 200}
        qualified = []
        result = analyzer._process_wallet_pnl("W1", pnl, wallet_data, qualified, 3.0)
        assert result is False

    def test_qualifies_above_thresholds(self):
        analyzer = _make_analyzer()
        wallet_data = {
            "W1": {"source": "first_buyers", "entry_price": 0.001, "earliest_entry": 123},
        }
        # realized_mult = (400 + 100) / 100 = 5.0x
        pnl = {"realized": 400, "unrealized": 0, "total_invested": 100}
        qualified = []
        result = analyzer._process_wallet_pnl("W1", pnl, wallet_data, qualified, 3.0)
        assert result is True
        assert len(qualified) == 1
        assert qualified[0]["wallet"] == "W1"
        assert qualified[0]["realized_multiplier"] == 5.0
        assert qualified[0]["source"] == "first_buyers"

    def test_qualifies_via_total_multiplier(self):
        """Unrealized gains alone can push total_multiplier above threshold."""
        analyzer = _make_analyzer()
        wallet_data = {"W1": {"source": "top_traders", "entry_price": 0.01}}
        # total_mult = (0 + 500 + 200) / 200 = 3.5x
        pnl = {"realized": 0, "unrealized": 500, "total_invested": 200}
        qualified = []
        result = analyzer._process_wallet_pnl("W1", pnl, wallet_data, qualified, 3.0)
        assert result is True

    def test_zero_invested_disqualifies(self):
        analyzer = _make_analyzer()
        wallet_data = {"W1": {"source": "top_traders", "entry_price": 0.01}}
        pnl = {"realized": 0, "unrealized": 0, "total_invested": 0}
        qualified = []
        result = analyzer._process_wallet_pnl("W1", pnl, wallet_data, qualified, 3.0)
        assert result is False

    def test_preserves_entry_price_from_wallet_data(self):
        """Entry price from wallet_data is passed through to qualified entry."""
        analyzer = _make_analyzer()
        wallet_data = {"W1": {"source": "top_traders", "entry_price": 0.005}}
        pnl = {"realized": 400, "unrealized": 0, "total_invested": 100}
        qualified = []
        analyzer._process_wallet_pnl("W1", pnl, wallet_data, qualified, 3.0)
        assert len(qualified) == 1
        assert qualified[0]["entry_price"] == 0.005

    def test_entry_price_none_when_not_in_wallet_data(self):
        """Entry price is None when not set in wallet_data."""
        analyzer = _make_analyzer()
        wallet_data = {"W1": {"source": "top_traders"}}
        pnl = {"realized": 400, "unrealized": 0, "total_invested": 100}
        qualified = []
        analyzer._process_wallet_pnl("W1", pnl, wallet_data, qualified, 3.0)
        assert len(qualified) == 1
        assert qualified[0]["entry_price"] is None


# ===========================================================================
# _assign_tier
# ===========================================================================

class TestAssignTier:
    """Tests for _assign_tier batch grading."""

    def test_tier_s(self):
        analyzer = _make_analyzer()
        assert analyzer._assign_tier(8, 90, 10) == "S"

    def test_tier_a(self):
        analyzer = _make_analyzer()
        assert analyzer._assign_tier(7, 80, 10) == "A"

    def test_tier_b(self):
        analyzer = _make_analyzer()
        assert analyzer._assign_tier(5, 70, 10) == "B"

    def test_tier_c_low_participation(self):
        analyzer = _make_analyzer()
        assert analyzer._assign_tier(1, 90, 10) == "C"

    def test_tier_c_zero_tokens(self):
        analyzer = _make_analyzer()
        assert analyzer._assign_tier(0, 0, 0) == "C"


# ===========================================================================
# get_wallet_pnl_solanatracker
# ===========================================================================

class TestGetWalletPnlSolanatracker:
    """Tests for get_wallet_pnl_solanatracker."""

    @patch("services.wallet_analyzer.get_http_session")
    @patch("services.wallet_analyzer._st_rate_limiter")
    def test_returns_pnl_data(self, mock_limiter, mock_session):
        analyzer = _make_analyzer()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "realized": 500, "unrealized": 100, "total_invested": 200,
        }
        mock_session.return_value.get.return_value = mock_resp
        result = analyzer.get_wallet_pnl_solanatracker("WalletABC", "TokenXYZ")
        assert result["realized"] == 500

    @patch("services.wallet_analyzer.get_http_session")
    @patch("services.wallet_analyzer._st_rate_limiter")
    def test_returns_none_on_error(self, mock_limiter, mock_session):
        analyzer = _make_analyzer()
        mock_session.return_value.get.side_effect = Exception("timeout")
        result = analyzer.get_wallet_pnl_solanatracker("WalletABC", "TokenXYZ")
        assert result is None
