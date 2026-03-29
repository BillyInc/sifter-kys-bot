"""Tests for services/tasks.py — Scheduled task tests."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


class TestPurgeOldNotifications:
    """Tests for purge_old_notifications."""

    @patch("services.supabase_client.get_supabase_client")
    def test_deletes_old_notifications(self, mock_get_client):
        """Deletes notifications older than 30 days via Supabase."""
        mock_supabase = MagicMock()
        mock_get_client.return_value = mock_supabase

        # Chain: schema -> table -> delete -> lt -> execute
        mock_supabase.schema.return_value.table.return_value.delete.return_value.lt.return_value.execute.return_value = MagicMock(
            data=[{"id": 1}, {"id": 2}, {"id": 3}]
        )

        from services.tasks import purge_old_notifications
        result = purge_old_notifications()

        assert result["status"] == "success"
        assert result["deleted"] == 3

        # Verify correct table was targeted
        mock_supabase.schema.assert_called_with("sifter_dev")
        mock_supabase.schema.return_value.table.assert_called_with("wallet_notifications")

        # Verify .lt was called with 'sent_at' and a cutoff date string
        lt_call = mock_supabase.schema.return_value.table.return_value.delete.return_value.lt
        lt_call.assert_called_once()
        args = lt_call.call_args[0]
        assert args[0] == "sent_at"
        # The cutoff should be roughly 30 days ago
        cutoff = datetime.fromisoformat(args[1])
        expected = datetime.utcnow() - timedelta(days=30)
        assert abs((cutoff - expected).total_seconds()) < 10

    @patch("services.supabase_client.get_supabase_client")
    def test_handles_no_results(self, mock_get_client):
        """Handles case where no old notifications are found."""
        mock_supabase = MagicMock()
        mock_get_client.return_value = mock_supabase

        mock_supabase.schema.return_value.table.return_value.delete.return_value.lt.return_value.execute.return_value = MagicMock(
            data=[]
        )

        from services.tasks import purge_old_notifications
        result = purge_old_notifications()

        assert result["status"] == "success"
        assert result["deleted"] == 0

    @patch("services.supabase_client.get_supabase_client", side_effect=Exception("DB connection failed"))
    def test_handles_exception(self, mock_get_client):
        """Returns error status when Supabase call fails."""
        from services.tasks import purge_old_notifications
        result = purge_old_notifications()

        assert result["status"] == "error"
        assert "DB connection failed" in result["error"]


class TestDailyStatsRefresh:
    """Tests for daily_stats_refresh."""

    @patch("services.clickhouse_client.get_clickhouse_client")
    @patch("services.supabase_client.get_supabase_client")
    def test_handles_empty_watchlist(self, mock_get_supa, mock_get_ch):
        """Returns early with wallets=0 when watchlist is empty."""
        mock_supabase = MagicMock()
        mock_get_supa.return_value = mock_supabase

        # Watchlist query returns no data
        mock_supabase.schema.return_value.table.return_value.select.return_value.execute.return_value = MagicMock(
            data=[]
        )

        from services.tasks import daily_stats_refresh
        result = daily_stats_refresh()

        assert result["status"] == "success"
        assert result["wallets"] == 0
        assert result["synced"] == 0

    @patch("services.clickhouse_client.get_clickhouse_client")
    @patch("services.supabase_client.get_supabase_client")
    def test_handles_empty_watchlist_none_data(self, mock_get_supa, mock_get_ch):
        """Returns early when watchlist data is None."""
        mock_supabase = MagicMock()
        mock_get_supa.return_value = mock_supabase

        mock_supabase.schema.return_value.table.return_value.select.return_value.execute.return_value = MagicMock(
            data=None
        )

        from services.tasks import daily_stats_refresh
        result = daily_stats_refresh()

        assert result["status"] == "success"
        assert result["wallets"] == 0
