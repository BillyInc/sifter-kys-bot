"""Tests for services/watchlist_manager.py — Watchlist league mechanics."""

import pytest
from unittest.mock import patch, MagicMock


def _make_manager():
    """Create WatchlistLeagueManager with mocked Supabase."""
    with patch("services.watchlist_manager.get_supabase_client"):
        from services.watchlist_manager import WatchlistLeagueManager
        return WatchlistLeagueManager()


# ===========================================================================
# _calculate_entry_consistency_score
# ===========================================================================

class TestEntryConsistencyScore:
    """Tests for _calculate_entry_consistency_score (Bug 4 fix)."""

    def test_empty_list_returns_50(self):
        mgr = _make_manager()
        assert mgr._calculate_entry_consistency_score([]) == 50.0

    def test_single_entry_returns_70(self):
        mgr = _make_manager()
        assert mgr._calculate_entry_consistency_score([1.2]) == 70.0

    def test_identical_entries_returns_100(self):
        mgr = _make_manager()
        score = mgr._calculate_entry_consistency_score([1.0, 1.0, 1.0])
        assert score == 100.0

    def test_moderate_variance_mid_score(self):
        mgr = _make_manager()
        # CV of ~0.5 → score ~75
        score = mgr._calculate_entry_consistency_score([1.0, 1.5, 2.0])
        assert 50 < score < 90

    def test_high_variance_low_score(self):
        mgr = _make_manager()
        score = mgr._calculate_entry_consistency_score([1.0, 20.0])
        assert score < 40

    def test_filters_none_and_zero(self):
        mgr = _make_manager()
        # None and 0 should be filtered out, leaving [1.0, 1.0]
        score = mgr._calculate_entry_consistency_score([None, 0, 1.0, 1.0])
        assert score == 100.0

    def test_all_zeros_returns_50(self):
        mgr = _make_manager()
        assert mgr._calculate_entry_consistency_score([0, 0, 0]) == 50.0


# ===========================================================================
# _calculate_professional_score
# ===========================================================================

class TestProfessionalScore:
    """Tests for _calculate_professional_score (Bug 3 fix)."""

    def test_perfect_metrics(self):
        mgr = _make_manager()
        metrics = {
            "roi_7d": 80,       # min(80/2, 40) = 40
            "runners_7d": 5,    # min(5*6, 30) = 30
            "win_rate_7d": 100, # 100/100*20 = 20
            "consistency_score": 100,  # 100/100*10 = 10
        }
        score = mgr._calculate_professional_score(metrics)
        assert score == 100.0

    def test_zero_metrics(self):
        mgr = _make_manager()
        metrics = {
            "roi_7d": 0,
            "runners_7d": 0,
            "win_rate_7d": 0,
            "consistency_score": 0,
        }
        assert mgr._calculate_professional_score(metrics) == 0.0

    def test_negative_roi_floored_at_zero(self):
        """Bug 3: negative ROI should contribute 0, not negative score."""
        mgr = _make_manager()
        metrics = {
            "roi_7d": -50,
            "runners_7d": 3,
            "win_rate_7d": 60,
            "consistency_score": 70,
        }
        score = mgr._calculate_professional_score(metrics)
        # ROI contributes 0 (floored), runners = min(18,30)=18, win_rate=12, consistency=7
        expected = 0 + 18 + 12 + 7
        assert score == expected

    def test_roi_capped_at_40(self):
        mgr = _make_manager()
        metrics = {
            "roi_7d": 500,      # min(250, 40) = 40
            "runners_7d": 0,
            "win_rate_7d": 0,
            "consistency_score": 0,
        }
        assert mgr._calculate_professional_score(metrics) == 40.0

    def test_runners_capped_at_30(self):
        mgr = _make_manager()
        metrics = {
            "roi_7d": 0,
            "runners_7d": 100,  # min(600, 30) = 30
            "win_rate_7d": 0,
            "consistency_score": 0,
        }
        assert mgr._calculate_professional_score(metrics) == 30.0


# ===========================================================================
# _get_zone
# ===========================================================================

class TestGetZone:
    """Tests for _get_zone — zone assignment by position and total."""

    def test_small_watchlist_position_1(self):
        mgr = _make_manager()
        assert mgr._get_zone(1, 3) == "Elite"

    def test_small_watchlist_position_2(self):
        mgr = _make_manager()
        assert mgr._get_zone(2, 5) == "midtable"

    def test_small_watchlist_position_5(self):
        mgr = _make_manager()
        assert mgr._get_zone(5, 5) == "monitoring"

    def test_medium_watchlist_elite(self):
        mgr = _make_manager()
        assert mgr._get_zone(1, 10) == "Elite"

    def test_medium_watchlist_midtable(self):
        mgr = _make_manager()
        assert mgr._get_zone(5, 10) == "midtable"

    def test_medium_watchlist_monitoring(self):
        mgr = _make_manager()
        assert mgr._get_zone(7, 10) == "monitoring"

    def test_medium_watchlist_relegation(self):
        mgr = _make_manager()
        assert mgr._get_zone(10, 10) == "relegation"

    def test_large_watchlist_elite(self):
        mgr = _make_manager()
        # position 3 / 20 = 15% → Elite (<=30%)
        assert mgr._get_zone(3, 20) == "Elite"

    def test_large_watchlist_midtable(self):
        mgr = _make_manager()
        # position 8 / 20 = 40% → midtable (<=60%)
        assert mgr._get_zone(8, 20) == "midtable"

    def test_large_watchlist_monitoring(self):
        mgr = _make_manager()
        # position 15 / 20 = 75% → monitoring (<=80%)
        assert mgr._get_zone(15, 20) == "monitoring"

    def test_large_watchlist_relegation(self):
        mgr = _make_manager()
        # position 19 / 20 = 95% → relegation (>80%)
        assert mgr._get_zone(19, 20) == "relegation"


# ===========================================================================
# _calculate_league_positions
# ===========================================================================

class TestCalculateLeaguePositions:
    """Tests for _calculate_league_positions."""

    def test_sorts_by_professional_score_desc(self):
        mgr = _make_manager()
        wallets = [
            {"wallet_address": "W1", "professional_score": 30},
            {"wallet_address": "W2", "professional_score": 90},
            {"wallet_address": "W3", "professional_score": 60},
        ]
        result = mgr._calculate_league_positions(wallets)
        assert result[0]["wallet_address"] == "W2"
        assert result[0]["position"] == 1
        assert result[1]["wallet_address"] == "W3"
        assert result[2]["wallet_address"] == "W1"

    def test_batch_source_gets_full_score(self):
        """Batch-sourced wallets keep 100% score, single gets 75%."""
        mgr = _make_manager()
        wallets = [
            {"wallet_address": "W1", "professional_score": 80, "source_type": "batch"},
            {"wallet_address": "W2", "professional_score": 80, "source_type": "single"},
        ]
        result = mgr._calculate_league_positions(wallets)
        # batch 80*1.0=80 vs single 80*0.75=60 → batch ranks first
        assert result[0]["wallet_address"] == "W1"

    def test_assigns_zones(self):
        mgr = _make_manager()
        wallets = [
            {"wallet_address": f"W{i}", "professional_score": 100 - i}
            for i in range(20)
        ]
        result = mgr._calculate_league_positions(wallets)
        # Position 1 of 20 = Elite
        assert result[0]["zone"] == "Elite"
        # Last position = relegation
        assert result[-1]["zone"] == "relegation"


# ===========================================================================
# _update_position_movements
# ===========================================================================

class TestUpdatePositionMovements:
    """Tests for _update_position_movements."""

    def test_up_movement(self):
        mgr = _make_manager()
        watchlist = [{"wallet_address": "W1", "position": 2}]
        old = {"W1": 5}
        result = mgr._update_position_movements(watchlist, old)
        assert result[0]["movement"] == "up"
        assert result[0]["positions_changed"] == 3

    def test_down_movement(self):
        mgr = _make_manager()
        watchlist = [{"wallet_address": "W1", "position": 7}]
        old = {"W1": 3}
        result = mgr._update_position_movements(watchlist, old)
        assert result[0]["movement"] == "down"
        assert result[0]["positions_changed"] == 4

    def test_stable_movement(self):
        mgr = _make_manager()
        watchlist = [{"wallet_address": "W1", "position": 3}]
        old = {"W1": 3}
        result = mgr._update_position_movements(watchlist, old)
        assert result[0]["movement"] == "stable"
        assert result[0]["positions_changed"] == 0

    def test_new_wallet_defaults_to_up(self):
        """New wallet (not in old_positions) gets position 999 → always 'up'."""
        mgr = _make_manager()
        watchlist = [{"wallet_address": "NEW", "position": 5}]
        result = mgr._update_position_movements(watchlist, {})
        assert result[0]["movement"] == "up"
