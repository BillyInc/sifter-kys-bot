"""Tests for tasks/token_discovery.py — Token discovery row builder and fetch tests."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from tasks.token_discovery import build_token_scan_row, fetch_solanatracker


# ===================================================================
# Expected columns in a token_scans row
# ===================================================================
EXPECTED_COLUMNS = {
    "token_address",
    "scan_id",
    "discovered_via",
    "scan_timestamp",
    "launch_price",
    "current_price",
    "ath_price",
    "launch_to_ath_mult",
    "launch_to_current_mult",
    "qualified_10x",
    "qualified_30x",
    "market_cap_usd",
    "volume_24h_usd",
    "liquidity_usd",
    "holder_count",
    "scan_window_days",
    "token_symbol",
    "token_name",
}


class TestBuildTokenScanRow:
    """Tests for build_token_scan_row."""

    def test_produces_correct_columns(self):
        """Returned row has all expected columns matching schema."""
        token_data = {
            "token": {"mint": "SolMint123", "symbol": "SOL", "name": "Solana"},
            "pools": [{"price": {"usd": 1.5}, "liquidity": {"usd": 50000}}],
            "marketCap": 1000000,
            "volume24h": 500000,
            "athPrice": 3.0,
            "launchPrice": 0.1,
            "holders": 1200,
        }
        row = build_token_scan_row(token_data, "just_graduated")
        assert set(row.keys()) == EXPECTED_COLUMNS

    def test_correct_values(self):
        """Row values are correctly extracted from token data."""
        token_data = {
            "token": {"mint": "MintABC", "symbol": "ABC", "name": "ABC Token"},
            "pools": [{"price": {"usd": 2.0}, "liquidity": {"usd": 10000}}],
            "marketCap": 500000,
            "volume24h": 100000,
            "athPrice": 10.0,
            "launchPrice": 0.5,
            "holders": 300,
        }
        row = build_token_scan_row(token_data, "newly_launched")

        assert row["token_address"] == "MintABC"
        assert row["token_symbol"] == "ABC"
        assert row["token_name"] == "ABC Token"
        assert row["discovered_via"] == "newly_launched"
        assert row["current_price"] == 2.0
        assert row["ath_price"] == 10.0
        assert row["launch_price"] == 0.5
        assert row["launch_to_ath_mult"] == 20.0  # 10.0 / 0.5
        assert row["launch_to_current_mult"] == 4.0  # 2.0 / 0.5
        assert row["qualified_10x"] == 1  # 20x >= 10
        assert row["qualified_30x"] == 0  # 20x < 30
        assert row["market_cap_usd"] == 500000
        assert row["volume_24h_usd"] == 100000
        assert row["liquidity_usd"] == 10000
        assert row["holder_count"] == 300
        assert row["scan_window_days"] == 30
        assert isinstance(row["scan_timestamp"], datetime)

    def test_handles_missing_pools(self):
        """Gracefully handles missing pools field."""
        token_data = {
            "token": {"mint": "MintXYZ", "symbol": "XYZ", "name": "XYZ Token"},
            "marketCap": 0,
        }
        row = build_token_scan_row(token_data, "trending_runners")
        assert row["token_address"] == "MintXYZ"
        assert row["current_price"] == 0
        assert row["liquidity_usd"] == 0

    def test_handles_missing_token_field(self):
        """Falls back to top-level fields when 'token' key is missing."""
        token_data = {
            "address": "DirectAddr",
            "symbol": "DIR",
            "name": "Direct",
            "pools": [],
        }
        row = build_token_scan_row(token_data, "just_graduated")
        assert row["token_address"] == "DirectAddr"
        assert row["token_symbol"] == "DIR"
        assert row["token_name"] == "Direct"

    def test_handles_zero_launch_price(self):
        """launch_to_ath_mult and launch_to_current_mult are 0 when launch_price is 0."""
        token_data = {
            "token": {"mint": "NoLaunch"},
            "pools": [{"price": {"usd": 5.0}}],
            "athPrice": 10.0,
            "launchPrice": 0,
        }
        row = build_token_scan_row(token_data, "just_graduated")
        assert row["launch_to_ath_mult"] == 0
        assert row["launch_to_current_mult"] == 0

    def test_handles_missing_fields_gracefully(self):
        """Handles completely minimal token data without raising."""
        token_data = {}
        row = build_token_scan_row(token_data, "test_endpoint")
        assert row["token_address"] == ""
        assert row["token_symbol"] == ""
        assert row["token_name"] == ""
        assert row["market_cap_usd"] == 0
        assert row["holder_count"] == 0

    def test_qualified_30x(self):
        """Token with 30x+ launch-to-ATH is marked qualified_30x."""
        token_data = {
            "token": {"mint": "BigPump"},
            "athPrice": 30.0,
            "launchPrice": 0.5,  # 60x
        }
        row = build_token_scan_row(token_data, "trending_runners")
        assert row["qualified_10x"] == 1
        assert row["qualified_30x"] == 1


class TestFetchSolanatracker:
    """Tests for fetch_solanatracker."""

    @patch("tasks.token_discovery.requests.get")
    @patch("tasks.token_discovery.time.sleep")
    def test_returns_empty_list_on_request_error(self, mock_sleep, mock_get):
        """Returns empty list when requests raises an exception."""
        mock_get.side_effect = Exception("Connection refused")
        result = fetch_solanatracker("tokens/trending")
        assert result == []

    @patch("tasks.token_discovery.requests.get")
    @patch("tasks.token_discovery.time.sleep")
    def test_returns_empty_list_on_non_list_response(self, mock_sleep, mock_get):
        """Returns empty list when API returns a non-list JSON response."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "not found"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = fetch_solanatracker("tokens/trending")
        assert result == []

    @patch("tasks.token_discovery.requests.get")
    @patch("tasks.token_discovery.time.sleep")
    def test_returns_list_on_success(self, mock_sleep, mock_get):
        """Returns the list when API returns valid list data."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"token": {"mint": "ABC"}}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = fetch_solanatracker("tokens/trending")
        assert len(result) == 1
        assert result[0]["token"]["mint"] == "ABC"

    @patch("tasks.token_discovery.requests.get")
    @patch("tasks.token_discovery.time.sleep")
    def test_returns_empty_list_on_http_error(self, mock_sleep, mock_get):
        """Returns empty list when API returns HTTP error status."""
        import requests as req
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("500 Server Error")
        mock_get.return_value = mock_resp
        result = fetch_solanatracker("tokens/trending")
        assert result == []
