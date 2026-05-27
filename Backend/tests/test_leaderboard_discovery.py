"""
Comprehensive unit tests for core pipeline logic in
tasks/leaderboard_discovery.py and tasks/wallet_qualification.py.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from tasks.leaderboard_discovery import (
    _is_conviction,
    _parse_timestamp as ld_parse_timestamp,
    _extract_token_mint,
)
from tasks.wallet_qualification import (
    _extract_v2_fields,
    _parse_timestamp as wq_parse_timestamp,
    _compute_outcome,
)


# =====================================================================
# 1. _is_conviction (leaderboard_discovery.py)
# =====================================================================
# Conviction logic:
#   invested >= 100 AND (buys >= 2 OR invested >= 250)
#   AND (realized >= invested*3 OR unrealized >= invested*3)


class TestIsConviction:
    def test_high_realized_with_multiple_buys(self):
        """invested=100, buys=2, realized=300, unrealized=0 -> True
        realized (300) >= threshold (100*3=300)."""
        pos = {
            "invested": 100,
            "counts": {"buys": 2},
            "pnl": {"realized": 300, "unrealized": 0},
        }
        assert _is_conviction(pos) is True

    def test_single_buy_low_invested_fails(self):
        """invested=100, buys=1, realized=500, unrealized=0 -> False
        buys < 2 and invested < 250, so commitment check fails."""
        pos = {
            "invested": 100,
            "counts": {"buys": 1},
            "pnl": {"realized": 500, "unrealized": 0},
        }
        assert _is_conviction(pos) is False

    def test_high_invested_single_buy_unrealized(self):
        """invested=250, buys=1, realized=0, unrealized=800 -> True
        invested >= 250 bypasses buys check; unrealized (800) >= 250*3=750."""
        pos = {
            "invested": 250,
            "counts": {"buys": 1},
            "pnl": {"realized": 0, "unrealized": 800},
        }
        assert _is_conviction(pos) is True

    def test_realized_just_under_threshold(self):
        """invested=100, buys=2, realized=299, unrealized=0 -> False
        realized (299) < threshold (300)."""
        pos = {
            "invested": 100,
            "counts": {"buys": 2},
            "pnl": {"realized": 299, "unrealized": 0},
        }
        assert _is_conviction(pos) is False

    def test_unrealized_meets_threshold(self):
        """invested=100, buys=2, realized=0, unrealized=300 -> True
        unrealized (300) >= threshold (300)."""
        pos = {
            "invested": 100,
            "counts": {"buys": 2},
            "pnl": {"realized": 0, "unrealized": 300},
        }
        assert _is_conviction(pos) is True

    def test_zero_invested_fails(self):
        """invested=0, buys=5, realized=1000, unrealized=0 -> False
        invested < 100 immediately fails."""
        pos = {
            "invested": 0,
            "counts": {"buys": 5},
            "pnl": {"realized": 1000, "unrealized": 0},
        }
        assert _is_conviction(pos) is False

    def test_none_pnl_treated_as_zero(self):
        """invested=100, buys=2, realized=None, unrealized=None -> False
        None coerced to 0; threshold=300, both 0 < 300."""
        pos = {
            "invested": 100,
            "counts": {"buys": 2},
            "pnl": {"realized": None, "unrealized": None},
        }
        assert _is_conviction(pos) is False

    def test_invested_below_100_fails(self):
        """invested=50, buys=3, realized=1000, unrealized=0 -> False
        invested < 100 immediately fails."""
        pos = {
            "invested": 50,
            "counts": {"buys": 3},
            "pnl": {"realized": 1000, "unrealized": 0},
        }
        assert _is_conviction(pos) is False

    def test_neither_realized_nor_unrealized_alone_meets_threshold(self):
        """invested=100, buys=2, realized=200, unrealized=200 -> False
        Neither realized (200) nor unrealized (200) >= threshold (300).
        The check is OR, not combined sum."""
        pos = {
            "invested": 100,
            "counts": {"buys": 2},
            "pnl": {"realized": 200, "unrealized": 200},
        }
        assert _is_conviction(pos) is False

    def test_missing_counts_defaults_to_zero_buys(self):
        """No counts key -> buys defaults to 0; needs invested >= 250."""
        pos = {
            "invested": 100,
            "pnl": {"realized": 500, "unrealized": 0},
        }
        # buys=0, invested=100 < 250 -> False
        assert _is_conviction(pos) is False

    def test_missing_pnl_key_defaults_to_zero(self):
        """No pnl key -> realized and unrealized both 0."""
        pos = {
            "invested": 300,
            "counts": {"buys": 5},
        }
        # threshold=900, realized=0, unrealized=0 -> False
        assert _is_conviction(pos) is False


# =====================================================================
# 2. _parse_timestamp (leaderboard_discovery.py)
# =====================================================================
# Handles: None/0 -> epoch zero, ms epoch, sec epoch, ISO string,
#          fallback -> datetime.now(utc)

EPOCH_ZERO = datetime(1970, 1, 1, tzinfo=timezone.utc)


class TestLdParseTimestamp:
    def test_none_returns_epoch_zero(self):
        assert ld_parse_timestamp(None) == EPOCH_ZERO

    def test_zero_returns_epoch_zero(self):
        assert ld_parse_timestamp(0) == EPOCH_ZERO

    def test_millisecond_epoch(self):
        """1700000000000 ms -> 2023-11-14T22:13:20 UTC."""
        result = ld_parse_timestamp(1700000000000)
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        assert result == expected

    def test_seconds_epoch(self):
        """1700000000 seconds -> 2023-11-14T22:13:20 UTC."""
        result = ld_parse_timestamp(1700000000)
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        assert result == expected

    def test_iso_string_with_timezone(self):
        """ISO 8601 string with timezone offset."""
        result = ld_parse_timestamp("2024-01-15T10:30:00+00:00")
        expected = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_iso_string_with_z_suffix(self):
        """ISO 8601 string with Z suffix (common in API responses)."""
        result = ld_parse_timestamp("2024-01-15T10:30:00Z")
        expected = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_invalid_string_returns_now(self):
        """Unparseable string falls through to datetime.now(utc).
        The leaderboard _parse_timestamp returns now() for unrecognized formats,
        not epoch zero."""
        before = datetime.now(timezone.utc)
        result = ld_parse_timestamp("not-a-date")
        after = datetime.now(timezone.utc)
        assert before <= result <= after

    def test_negative_int_returns_valid_datetime(self):
        """Negative integer is treated as a seconds epoch.
        -1 -> 1969-12-31T23:59:59 UTC (valid datetime, not epoch zero).
        The code does not guard against negative values; it calls
        datetime.fromtimestamp(-1) which succeeds."""
        result = ld_parse_timestamp(-1)
        expected = datetime.fromtimestamp(-1, tz=timezone.utc)
        assert result == expected

    def test_float_millisecond_epoch(self):
        """Float > 1e12 treated as milliseconds."""
        result = ld_parse_timestamp(1700000000000.5)
        expected = datetime.fromtimestamp(1700000000.0005, tz=timezone.utc)
        assert result == expected


# =====================================================================
# 3. _extract_token_mint (leaderboard_discovery.py)
# =====================================================================


class TestExtractTokenMint:
    def test_string_token(self):
        assert _extract_token_mint({"token": "abc123"}) == "abc123"

    def test_dict_token_with_mint(self):
        assert _extract_token_mint({"token": {"mint": "abc123"}}) == "abc123"

    def test_none_token(self):
        assert _extract_token_mint({"token": None}) == ""

    def test_empty_dict(self):
        assert _extract_token_mint({}) == ""

    def test_dict_token_missing_mint(self):
        """Dict token without 'mint' key returns empty string."""
        assert _extract_token_mint({"token": {"name": "SomeToken"}}) == ""

    def test_falls_back_to_tokenAddress(self):
        """When token is falsy but tokenAddress exists, uses tokenAddress."""
        assert _extract_token_mint({"token": "", "tokenAddress": "xyz789"}) == "xyz789"

    def test_integer_token_coerced_to_string(self):
        """Non-dict, non-string token coerced via str()."""
        assert _extract_token_mint({"token": 12345}) == "12345"


# =====================================================================
# 4. Outcome logic based on roi_pct thresholds (leaderboard_discovery.py)
# =====================================================================
# From Step 5: roi_pct >= 900 -> "win", >= 400 -> "draw", < 400 -> "loss"


class TestOutcomeFromRoiPct:
    """Tests for the outcome assignment logic in Step 5 of leaderboard_discovery.
    Extracted into a helper to test the threshold logic directly."""

    @staticmethod
    def _compute_outcome_from_roi(roi_pct: float) -> str:
        """Mirror the inline outcome logic from leaderboard_discovery Step 5."""
        if roi_pct >= 900:
            return "win"
        elif roi_pct >= 400:
            return "draw"
        else:
            return "loss"

    def test_roi_900_is_win(self):
        assert self._compute_outcome_from_roi(900) == "win"

    def test_roi_above_900_is_win(self):
        assert self._compute_outcome_from_roi(1500) == "win"

    def test_roi_400_is_draw(self):
        assert self._compute_outcome_from_roi(400) == "draw"

    def test_roi_between_400_and_900_is_draw(self):
        assert self._compute_outcome_from_roi(899.99) == "draw"

    def test_roi_below_400_is_loss(self):
        assert self._compute_outcome_from_roi(399.99) == "loss"

    def test_roi_zero_is_loss(self):
        assert self._compute_outcome_from_roi(0) == "loss"

    def test_roi_negative_is_loss(self):
        assert self._compute_outcome_from_roi(-50) == "loss"

    def test_roi_exactly_at_boundary(self):
        """Boundary: 399 -> loss, 400 -> draw, 899 -> draw, 900 -> win."""
        assert self._compute_outcome_from_roi(399) == "loss"
        assert self._compute_outcome_from_roi(400) == "draw"
        assert self._compute_outcome_from_roi(899) == "draw"
        assert self._compute_outcome_from_roi(900) == "win"


# =====================================================================
# 5. _compute_outcome (wallet_qualification.py)
# =====================================================================
# Win:  realized_mult > 5.0 AND invested >= 75
# Draw: abs(realized_mult - 5.0) < 0.5 (i.e., 4.5 < mult <= 5.0)
# Loss: everything else


class TestComputeOutcome:
    def test_win_with_high_mult(self):
        """realized_mult=6.0, token_ath=35.0, invested=100 -> ("win", 1)."""
        outcome, qualifies = _compute_outcome(6.0, 35.0, 100)
        assert outcome == "win"
        assert qualifies == 1

    def test_loss_with_low_mult(self):
        """realized_mult=3.0, token_ath=35.0, invested=100 -> ("loss", 0).
        3.0 is not > 5.0 and abs(3.0 - 5.0) = 2.0 >= 0.5."""
        outcome, qualifies = _compute_outcome(3.0, 35.0, 100)
        assert outcome == "loss"
        assert qualifies == 0

    def test_draw_near_threshold(self):
        """realized_mult=4.8, token_ath=35.0, invested=100 -> ("draw", 0).
        abs(4.8 - 5.0) = 0.2 < 0.5 -> draw."""
        outcome, qualifies = _compute_outcome(4.8, 35.0, 100)
        assert outcome == "draw"
        assert qualifies == 0

    def test_loss_below_min_spend(self):
        """realized_mult=6.0, token_ath=35.0, invested=50 -> ("loss", 0).
        invested < 75 (SECOND_PASS_MIN_SPEND) -> immediate loss."""
        outcome, qualifies = _compute_outcome(6.0, 35.0, 50)
        assert outcome == "loss"
        assert qualifies == 0

    def test_exactly_at_win_boundary(self):
        """realized_mult=5.0 is NOT > 5.0, so not a win.
        abs(5.0 - 5.0) = 0.0 < 0.5 -> draw."""
        outcome, qualifies = _compute_outcome(5.0, 35.0, 100)
        assert outcome == "draw"
        assert qualifies == 0

    def test_just_above_win_threshold(self):
        """realized_mult=5.01 -> win."""
        outcome, qualifies = _compute_outcome(5.01, 35.0, 100)
        assert outcome == "win"
        assert qualifies == 1

    def test_draw_lower_edge(self):
        """realized_mult=4.51 -> abs(4.51 - 5.0) = 0.49 < 0.5 -> draw."""
        outcome, qualifies = _compute_outcome(4.51, 0.0, 100)
        assert outcome == "draw"
        assert qualifies == 0

    def test_loss_just_outside_draw_range(self):
        """realized_mult=4.5 -> abs(4.5 - 5.0) = 0.5, NOT < 0.5 -> loss."""
        outcome, qualifies = _compute_outcome(4.5, 0.0, 100)
        assert outcome == "loss"
        assert qualifies == 0

    def test_token_ath_not_used_as_gate(self):
        """token_ath_mult=0 should not prevent a win (gate is disabled)."""
        outcome, qualifies = _compute_outcome(6.0, 0.0, 100)
        assert outcome == "win"
        assert qualifies == 1

    def test_min_spend_boundary(self):
        """invested=75 is exactly at SECOND_PASS_MIN_SPEND, should not be loss."""
        outcome, qualifies = _compute_outcome(6.0, 35.0, 75)
        assert outcome == "win"
        assert qualifies == 1


# =====================================================================
# 6. _extract_v2_fields (wallet_qualification.py)
# =====================================================================


class TestExtractV2Fields:
    def test_flat_pnl_shape(self):
        """V2 positions: pnl.realized and pnl.unrealized at top level."""
        data = {
            "pnl": {"realized": 100, "unrealized": 50},
            "invested": 200,
            "averages": {"buy": 0.005},
            "timing": {"firstBuy": 1700000000000},
            "counts": {"buys": 3, "sells": 1},
            "roi": 75.0,
        }
        fields = _extract_v2_fields(data)
        assert fields["realized"] == 100.0
        assert fields["unrealized"] == 50.0
        assert fields["total_invested"] == 200.0
        assert fields["avg_buy"] == 0.005
        assert fields["first_buy_ms"] == 1700000000000
        assert fields["buy_count"] == 3
        assert fields["sell_count"] == 1
        assert fields["roi_pct"] == 75.0

    def test_nested_trader_pnl_shape(self):
        """V2 traders: pnl.token.realized nested under 'token' key."""
        data = {
            "pnl": {"token": {"realized": 100, "unrealized": 25}},
            "buyUsd": 200,
            "averages": {"buy": 0.01},
            "timing": {},
            "counts": {"buys": 2, "sells": 0},
            "roi": 50.0,
        }
        fields = _extract_v2_fields(data)
        assert fields["realized"] == 100.0
        assert fields["unrealized"] == 25.0
        assert fields["total_invested"] == 200.0

    def test_empty_fields_default_to_zero(self):
        """Missing or None fields should default to 0."""
        data = {}
        fields = _extract_v2_fields(data)
        assert fields["realized"] == 0.0
        assert fields["unrealized"] == 0.0
        assert fields["total_invested"] == 0.0
        assert fields["avg_buy"] == 0.0
        assert fields["first_buy_ms"] is None
        assert fields["buy_count"] == 1  # default is 1 per code
        assert fields["sell_count"] == 0
        assert fields["roi_pct"] == 0.0

    def test_none_pnl_values_coerced(self):
        """None inside pnl dict coerced to 0 via 'or 0' pattern."""
        data = {
            "pnl": {"realized": None, "unrealized": None},
            "invested": None,
        }
        fields = _extract_v2_fields(data)
        assert fields["realized"] == 0.0
        assert fields["unrealized"] == 0.0
        assert fields["total_invested"] == 0.0

    def test_invested_fallback_to_buyUsd(self):
        """When 'invested' is missing, falls back to 'buyUsd'."""
        data = {"buyUsd": 150}
        fields = _extract_v2_fields(data)
        assert fields["total_invested"] == 150.0

    def test_invested_fallback_to_total_invested(self):
        """Fallback chain: invested -> buyUsd -> total_invested -> totalInvested."""
        data = {"total_invested": 300}
        fields = _extract_v2_fields(data)
        assert fields["total_invested"] == 300.0

    def test_non_dict_pnl_uses_top_level_fields(self):
        """If pnl is not a dict (e.g., a number), falls back to top-level keys."""
        data = {
            "pnl": 999,  # not a dict
            "realized": 42,
            "unrealized": 10,
        }
        fields = _extract_v2_fields(data)
        assert fields["realized"] == 42.0
        assert fields["unrealized"] == 10.0

    def test_averages_not_dict_uses_entry_price(self):
        """When averages is not a dict, falls back to entry_price."""
        data = {"averages": "invalid", "entry_price": 0.123}
        fields = _extract_v2_fields(data)
        assert fields["avg_buy"] == 0.123


# =====================================================================
# 7. _parse_timestamp (wallet_qualification.py)
# =====================================================================
# Different from leaderboard_discovery version:
#   None -> now(), handles >1e15 as microseconds


class TestWqParseTimestamp:
    def test_none_returns_now(self):
        """wallet_qualification _parse_timestamp returns now() for None."""
        before = datetime.now(timezone.utc)
        result = wq_parse_timestamp(None)
        after = datetime.now(timezone.utc)
        assert before <= result <= after

    def test_millisecond_epoch(self):
        result = wq_parse_timestamp(1700000000000)
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        assert result == expected

    def test_seconds_epoch(self):
        result = wq_parse_timestamp(1700000000)
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        assert result == expected

    def test_microsecond_epoch(self):
        """Values > 1e15 treated as microseconds (divided by 1e6)."""
        ts = 1700000000000000  # microseconds
        result = wq_parse_timestamp(ts)
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        assert result == expected

    def test_iso_string(self):
        result = wq_parse_timestamp("2024-01-15T10:30:00+00:00")
        expected = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_iso_string_with_z(self):
        result = wq_parse_timestamp("2024-06-01T00:00:00Z")
        expected = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_invalid_string_returns_now(self):
        before = datetime.now(timezone.utc)
        result = wq_parse_timestamp("garbage")
        after = datetime.now(timezone.utc)
        assert before <= result <= after

    def test_zero_returns_now(self):
        """0 is not > 0, so falls through to final return now()."""
        before = datetime.now(timezone.utc)
        result = wq_parse_timestamp(0)
        after = datetime.now(timezone.utc)
        assert before <= result <= after

    def test_negative_returns_now(self):
        """Negative int: not > 0, so falls through to return now()."""
        before = datetime.now(timezone.utc)
        result = wq_parse_timestamp(-1)
        after = datetime.now(timezone.utc)
        assert before <= result <= after
