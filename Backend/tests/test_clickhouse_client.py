"""Tests for services/clickhouse_client.py."""

import pytest
from unittest.mock import MagicMock, patch

from services.clickhouse_client import CH_DATABASE
from services.clickhouse_client import (
    _dicts_to_rows,
    insert_token_scans,
    insert_wallet_token_stats,
    get_wallet_stats,
)


# ---------------------------------------------------------------------------
# _dicts_to_rows
# ---------------------------------------------------------------------------

class TestDictsToRows:
    def test_dicts_to_rows_converts_correctly(self):
        """Verify list[dict] -> (list[list], list[str])."""
        rows = [
            {"wallet": "abc", "score": 10},
            {"wallet": "def", "score": 20},
        ]
        data, columns = _dicts_to_rows(rows)
        assert columns == ["wallet", "score"]
        assert data == [["abc", 10], ["def", 20]]

    def test_dicts_to_rows_preserves_column_order(self):
        """Verify column order matches dict key order."""
        rows = [{"z_col": 1, "a_col": 2, "m_col": 3}]
        data, columns = _dicts_to_rows(rows)
        assert columns == ["z_col", "a_col", "m_col"]
        assert data == [[1, 2, 3]]


# ---------------------------------------------------------------------------
# insert_token_scans
# ---------------------------------------------------------------------------

class TestInsertTokenScans:
    @patch('services.clickhouse_client.get_clickhouse_client')
    def test_insert_token_scans_skips_empty(self, mock_get_client):
        """Verify no insert call when rows=[]."""
        insert_token_scans([])
        mock_get_client.assert_not_called()

    @patch('services.clickhouse_client.get_clickhouse_client')
    def test_insert_token_scans_calls_client(self, mock_get_client):
        """Verify ch.insert() called with correct data format."""
        mock_ch = MagicMock()
        mock_get_client.return_value = mock_ch

        rows = [{"token": "SOL", "ts": 1000}]
        insert_token_scans(rows)

        mock_ch.insert.assert_called_once_with(
            table='token_scans',
            data=[["SOL", 1000]],
            database=CH_DATABASE,
            column_names=["token", "ts"],
        )


# ---------------------------------------------------------------------------
# insert_wallet_token_stats
# ---------------------------------------------------------------------------

class TestInsertWalletTokenStats:
    @patch('services.clickhouse_client.get_clickhouse_client')
    def test_insert_wallet_token_stats_calls_client(self, mock_get_client):
        """Verify ch.insert() called with correct data format."""
        mock_ch = MagicMock()
        mock_get_client.return_value = mock_ch

        rows = [{"wallet": "abc", "token": "SOL", "roi": 1.5}]
        insert_wallet_token_stats(rows)

        mock_ch.insert.assert_called_once_with(
            table='wallet_token_stats',
            data=[["abc", "SOL", 1.5]],
            database=CH_DATABASE,
            column_names=["wallet", "token", "roi"],
        )


# ---------------------------------------------------------------------------
# get_wallet_stats
# ---------------------------------------------------------------------------

class TestGetWalletStats:
    @patch('services.clickhouse_client.get_clickhouse_client')
    def test_get_wallet_stats_returns_none_when_empty(self, mock_get_client):
        """Verify None returned for no results."""
        mock_ch = MagicMock()
        mock_get_client.return_value = mock_ch
        mock_ch.query.return_value.result_rows = []

        result = get_wallet_stats("nonexistent_wallet")
        assert result is None

    @patch('services.clickhouse_client.get_clickhouse_client')
    def test_get_wallet_stats_returns_row(self, mock_get_client):
        """Verify first_row returned for valid result."""
        mock_ch = MagicMock()
        mock_get_client.return_value = mock_ch

        expected_row = {"wallet_address": "abc", "professional_score": 95.0}
        mock_ch.query.return_value.result_rows = [expected_row]
        mock_ch.query.return_value.first_row = expected_row

        result = get_wallet_stats("abc")
        assert result == expected_row
