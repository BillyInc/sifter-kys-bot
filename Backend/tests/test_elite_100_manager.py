"""Tests for services/elite_100_manager.py — Elite 100 and Community Top 100."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


# ===========================================================================
# _calculate_composite_score
# ===========================================================================

class TestCalculateCompositeScore:
    """Tests for Elite100Manager._calculate_composite_score."""

    def _make_manager(self):
        with patch("services.elite_100_manager.get_supabase_client"):
            from services.elite_100_manager import Elite100Manager
            return Elite100Manager()

    def test_perfect_wallet(self):
        mgr = self._make_manager()
        wallet = {
            "professional_score": 100,
            "roi_30d": 500,
            "runners_30d": 20,
            "win_rate_7d": 100,
        }
        score = mgr._calculate_composite_score(wallet)
        # 100*0.4 + 100*0.3 + 100*0.2 + 100*0.1 = 100
        assert score == 100.0

    def test_zero_wallet(self):
        mgr = self._make_manager()
        wallet = {
            "professional_score": 0,
            "roi_30d": 0,
            "runners_30d": 0,
            "win_rate_7d": 0,
        }
        assert mgr._calculate_composite_score(wallet) == 0.0

    def test_roi_capped_at_500(self):
        """ROI above 500% should still normalize to 100."""
        mgr = self._make_manager()
        wallet = {
            "professional_score": 0,
            "roi_30d": 1000,  # above 500% cap
            "runners_30d": 0,
            "win_rate_7d": 0,
        }
        score = mgr._calculate_composite_score(wallet)
        # roi_normalized capped at 100 → 100*0.3 = 30
        assert score == 30.0

    def test_runners_capped_at_20(self):
        """Runners above 20 should normalize to 100."""
        mgr = self._make_manager()
        wallet = {
            "professional_score": 0,
            "roi_30d": 0,
            "runners_30d": 50,  # above 20 cap
            "win_rate_7d": 0,
        }
        score = mgr._calculate_composite_score(wallet)
        # runners_normalized capped at 100 → 100*0.2 = 20
        assert score == 20.0

    def test_none_values_treated_as_zero(self):
        mgr = self._make_manager()
        wallet = {
            "professional_score": None,
            "roi_30d": None,
            "runners_30d": None,
            "win_rate_7d": None,
        }
        assert mgr._calculate_composite_score(wallet) == 0.0


# ===========================================================================
# _calculate_win_streak
# ===========================================================================

class TestCalculateWinStreak:
    """Tests for Elite100Manager._calculate_win_streak."""

    def _make_manager(self):
        with patch("services.elite_100_manager.get_supabase_client"):
            from services.elite_100_manager import Elite100Manager
            return Elite100Manager()

    def test_empty_form(self):
        assert self._make_manager()._calculate_win_streak([]) == 0

    def test_all_wins(self):
        assert self._make_manager()._calculate_win_streak(["win", "win", "win"]) == 3

    def test_streak_breaks_on_loss(self):
        assert self._make_manager()._calculate_win_streak(["win", "win", "loss", "win"]) == 2

    def test_starts_with_loss(self):
        assert self._make_manager()._calculate_win_streak(["loss", "win", "win"]) == 0

    def test_none_form(self):
        assert self._make_manager()._calculate_win_streak(None) == 0


# ===========================================================================
# generate_elite_100
# ===========================================================================

class TestGenerateElite100:
    """Tests for generate_elite_100."""

    def _setup(self):
        mock_supabase = MagicMock()
        with patch("services.elite_100_manager.get_supabase_client", return_value=mock_supabase):
            from services.elite_100_manager import Elite100Manager
            mgr = Elite100Manager()
        return mgr, mock_supabase

    def test_returns_empty_when_no_wallets(self):
        mgr, mock_sb = self._setup()
        mock_sb.schema.return_value.table.return_value.select.return_value.execute.return_value.data = []
        result = mgr.generate_elite_100()
        assert result == []

    def test_aggregates_duplicate_wallets(self):
        mgr, mock_sb = self._setup()
        table_mock = mock_sb.schema.return_value.table.return_value

        # Same wallet in two watchlists
        table_mock.select.return_value.execute.return_value.data = [
            {"wallet_address": "W1", "tier": "S", "professional_score": 80,
             "roi_30d": 200, "runners_30d": 5, "win_rate_7d": 70,
             "consistency_score": 60, "last_trade_time": "2025-01-01", "form": ["win"]},
            {"wallet_address": "W1", "tier": "A", "professional_score": 90,
             "roi_30d": 150, "runners_30d": 3, "win_rate_7d": 65,
             "consistency_score": 55, "last_trade_time": "2025-01-01", "form": ["loss"]},
        ]
        # Mock the cache operations
        table_mock.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        table_mock.insert.return_value.execute.return_value = MagicMock()

        result = mgr.generate_elite_100()
        assert len(result) == 1
        # Takes best professional_score
        assert result[0]["professional_score"] == 90
        assert result[0]["times_added"] == 2

    def test_sorts_by_roi(self):
        mgr, mock_sb = self._setup()
        table_mock = mock_sb.schema.return_value.table.return_value

        table_mock.select.return_value.execute.return_value.data = [
            {"wallet_address": "W1", "tier": "S", "professional_score": 90,
             "roi_30d": 100, "runners_30d": 5, "win_rate_7d": 70,
             "consistency_score": 60, "last_trade_time": None, "form": []},
            {"wallet_address": "W2", "tier": "A", "professional_score": 50,
             "roi_30d": 500, "runners_30d": 2, "win_rate_7d": 40,
             "consistency_score": 30, "last_trade_time": None, "form": []},
        ]
        table_mock.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        table_mock.insert.return_value.execute.return_value = MagicMock()

        result = mgr.generate_elite_100(sort_by="roi")
        assert result[0]["wallet_address"] == "W2"  # Higher ROI

    def test_limits_to_100(self):
        mgr, mock_sb = self._setup()
        table_mock = mock_sb.schema.return_value.table.return_value

        # 120 unique wallets
        wallets = [
            {"wallet_address": f"W{i}", "tier": "S", "professional_score": 50,
             "roi_30d": i, "runners_30d": 1, "win_rate_7d": 50,
             "consistency_score": 50, "last_trade_time": None, "form": []}
            for i in range(120)
        ]
        table_mock.select.return_value.execute.return_value.data = wallets
        table_mock.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        table_mock.insert.return_value.execute.return_value = MagicMock()

        result = mgr.generate_elite_100()
        assert len(result) == 100


# ===========================================================================
# generate_community_top_100
# ===========================================================================

class TestGenerateCommunityTop100:
    """Tests for generate_community_top_100."""

    def _setup(self):
        mock_supabase = MagicMock()
        with patch("services.elite_100_manager.get_supabase_client", return_value=mock_supabase):
            from services.elite_100_manager import Elite100Manager
            mgr = Elite100Manager()
        return mgr, mock_supabase

    def test_returns_empty_when_no_additions(self):
        mgr, mock_sb = self._setup()
        mock_sb.schema.return_value.table.return_value.select.return_value.gte.return_value.execute.return_value.data = []
        result = mgr.generate_community_top_100()
        assert result == []

    def test_counts_adds_correctly(self):
        mgr, mock_sb = self._setup()
        table_mock = mock_sb.schema.return_value.table.return_value

        table_mock.select.return_value.gte.return_value.execute.return_value.data = [
            {"wallet_address": "W1", "tier": "S", "professional_score": 80, "added_at": "2025-01-01"},
            {"wallet_address": "W1", "tier": "A", "professional_score": 70, "added_at": "2025-01-02"},
            {"wallet_address": "W2", "tier": "S", "professional_score": 60, "added_at": "2025-01-01"},
        ]
        table_mock.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        table_mock.insert.return_value.execute.return_value = MagicMock()

        result = mgr.generate_community_top_100()
        assert len(result) == 2
        # W1 added twice → first
        assert result[0]["wallet_address"] == "W1"
        assert result[0]["times_added"] == 2

    def test_includes_rank_change(self):
        mgr, mock_sb = self._setup()
        table_mock = mock_sb.schema.return_value.table.return_value

        table_mock.select.return_value.gte.return_value.execute.return_value.data = [
            {"wallet_address": "W1", "tier": "S", "professional_score": 80, "added_at": "2025-01-01"},
        ]
        table_mock.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        table_mock.insert.return_value.execute.return_value = MagicMock()

        result = mgr.generate_community_top_100()
        assert result[0]["rank_change"] == 0  # Default


# ===========================================================================
# get_cached_elite_100
# ===========================================================================

class TestGetCachedElite100:
    """Tests for cache retrieval."""

    def _setup(self):
        mock_supabase = MagicMock()
        with patch("services.elite_100_manager.get_supabase_client", return_value=mock_supabase):
            from services.elite_100_manager import Elite100Manager
            mgr = Elite100Manager()
        return mgr, mock_supabase

    def test_returns_cache_when_fresh(self):
        mgr, mock_sb = self._setup()
        table_mock = mock_sb.schema.return_value.table.return_value

        recent = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
        table_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"wallets": [{"wallet_address": "cached_W1"}], "generated_at": recent}
        ]

        result = mgr.get_cached_elite_100()
        assert len(result) == 1
        assert result[0]["wallet_address"] == "cached_W1"
