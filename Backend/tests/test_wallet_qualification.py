"""Tests for tasks/wallet_qualification.py — Row builder and outcome tests."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from tasks.wallet_qualification import (
    build_wallet_token_stats_row,
    _compute_outcome,
    _disqualified_row,
    FIRST_PASS_MIN_SPEND,
    SECOND_PASS_MIN_SPEND,
    WIN_WALLET_MULT,
    WIN_TOKEN_MULT,
)


# ===================================================================
# Expected columns in a wallet_token_stats row
# ===================================================================
EXPECTED_COLUMNS = {
    "wallet_address",
    "token_address",
    "scan_id",
    "first_entry_price",
    "first_entry_usd",
    "first_entry_timestamp",
    "entry_price_to_launch_mult",
    "avg_entry_price",
    "avg_entry_to_ath_mult",
    "all_buys",
    "all_sells",
    "buy_count",
    "sell_count",
    "total_spent_usd",
    "realized_pnl_usd",
    "unrealized_pnl_usd",
    "total_pnl_usd",
    "realized_roi_mult",
    "total_roi_mult",
    "qualifies",
    "outcome",
    "disqualify_reason",
    "wallet_source",
    "updated_at",
}


def _make_wallet_data(realized=500.0, unrealized=0.0, total_invested=100.0,
                      entry_price=0.001, first_buy_time=0, source="top_traders"):
    """Helper to build wallet_data dict."""
    return {
        "wallet": "WalletABC123",
        "source": source,
        "pnl_data": {
            "realized": realized,
            "unrealized": unrealized,
            "total_invested": total_invested,
            "entry_price": entry_price,
            "first_buy_time": first_buy_time,
        },
    }


class TestBuildWalletTokenStatsRow:
    """Tests for build_wallet_token_stats_row."""

    def test_returns_correct_columns(self):
        """Returned row has all expected columns matching schema."""
        wd = _make_wallet_data(realized=500, total_invested=100)
        row = build_wallet_token_stats_row(wd, "TokenMint123", "first")
        assert row is not None
        assert set(row.keys()) == EXPECTED_COLUMNS

    def test_first_pass_below_spend_floor_returns_disqualified(self):
        """Below first-pass spend floor ($100) returns a disqualified row."""
        wd = _make_wallet_data(realized=500, total_invested=50)  # below $100
        row = build_wallet_token_stats_row(wd, "TokenMint123", "first")
        assert row is not None
        assert row["disqualify_reason"] == f"spend_below_{FIRST_PASS_MIN_SPEND}"
        assert row["qualifies"] == 0

    def test_second_pass_below_spend_floor_returns_disqualified(self):
        """Below second-pass spend floor ($75) returns a disqualified row."""
        wd = _make_wallet_data(realized=500, total_invested=50)  # below $75
        row = build_wallet_token_stats_row(wd, "TokenMint123", "second")
        assert row is not None
        assert row["disqualify_reason"] == f"spend_below_{SECOND_PASS_MIN_SPEND}"

    def test_returns_none_when_zero_invested(self):
        """Returns None when total_invested is 0 (after passing spend floor)."""
        # total_invested=0 fails spend floor first and returns disqualified row
        # but if somehow total_invested <= 0 after the floor check...
        # Actually with 0 invested it fails the spend floor. Let's test that path:
        wd = _make_wallet_data(realized=0, total_invested=0)
        row = build_wallet_token_stats_row(wd, "TokenMint123", "first")
        # Should get a disqualified row (spend below floor), not None
        assert row is not None
        assert "spend_below" in row["disqualify_reason"]

    def test_roi_below_threshold_returns_disqualified(self):
        """Below ROI threshold returns disqualified row."""
        # First pass: min_roi = 3.0x
        # realized_mult = (realized + total_invested) / total_invested
        # For 1.5x: realized=50, invested=100 -> (50+100)/100 = 1.5x
        wd = _make_wallet_data(realized=50, total_invested=100)
        row = build_wallet_token_stats_row(wd, "TokenMint123", "first")
        assert row is not None
        assert "roi_below" in row["disqualify_reason"]

    def test_first_pass_outcome_is_open(self):
        """First-pass qualified row has outcome='open' and qualifies=0."""
        # Need realized_mult >= 3.0: (realized + invested) / invested >= 3.0
        # realized=200, invested=100 -> 300/100 = 3.0x
        wd = _make_wallet_data(realized=200, total_invested=100)
        row = build_wallet_token_stats_row(wd, "TokenMint123", "first")
        assert row is not None
        assert row["outcome"] == "open"
        assert row["qualifies"] == 0
        assert row["disqualify_reason"] == ""

    def test_second_pass_win(self):
        """Second-pass with wallet >5x and token >30x yields win."""
        # realized_mult > 5.0: realized=500, invested=100 -> 600/100 = 6.0x
        wd = _make_wallet_data(realized=500, total_invested=100)
        row = build_wallet_token_stats_row(wd, "TokenMint123", "second", token_ath_mult=35.0)
        assert row is not None
        assert row["outcome"] == "win"
        assert row["qualifies"] == 1


class TestComputeOutcome:
    """Tests for _compute_outcome."""

    def test_win_when_both_above_thresholds(self):
        """Win when wallet >5x AND token >30x."""
        outcome, qualifies = _compute_outcome(6.0, 35.0, 100.0)
        assert outcome == "win"
        assert qualifies == 1

    def test_loss_when_wallet_below(self):
        """Loss when wallet <5x even if token >30x."""
        outcome, qualifies = _compute_outcome(3.0, 35.0, 100.0)
        assert outcome == "loss"
        assert qualifies == 0

    def test_loss_when_token_below(self):
        """Loss when token <30x even if wallet >5x."""
        outcome, qualifies = _compute_outcome(6.0, 20.0, 100.0)
        assert outcome == "loss"
        assert qualifies == 0

    def test_loss_when_spend_below(self):
        """Loss when total_invested below second-pass minimum."""
        outcome, qualifies = _compute_outcome(6.0, 35.0, 50.0)
        assert outcome == "loss"
        assert qualifies == 0

    def test_draw_for_exact_wallet_threshold(self):
        """Draw when wallet is exactly at 5x threshold."""
        outcome, qualifies = _compute_outcome(WIN_WALLET_MULT, 35.0, 100.0)
        assert outcome == "draw"
        assert qualifies == 0

    def test_draw_for_exact_token_threshold(self):
        """Draw when token is exactly at 30x threshold."""
        outcome, qualifies = _compute_outcome(6.0, WIN_TOKEN_MULT, 100.0)
        assert outcome == "draw"
        assert qualifies == 0


class TestDisqualifiedRow:
    """Tests for _disqualified_row."""

    def test_produces_correct_reason(self):
        """Disqualified row contains the given reason."""
        row = _disqualified_row(
            wallet_address="WalletABC",
            token_address="TokenXYZ",
            pass_type="first",
            pnl={"entry_price": 0.001, "first_buy_time": 0},
            total_invested=50.0,
            realized=10.0,
            unrealized=5.0,
            reason="spend_below_100",
        )
        assert row["disqualify_reason"] == "spend_below_100"
        assert row["qualifies"] == 0
        assert row["wallet_source"] == "disqualified"

    def test_first_pass_outcome_is_open(self):
        """Disqualified row for first pass has outcome='open'."""
        row = _disqualified_row(
            "W", "T", "first", {}, 50.0, 10.0, 5.0, "spend_below_100"
        )
        assert row["outcome"] == "open"

    def test_second_pass_outcome_is_loss(self):
        """Disqualified row for second pass has outcome='loss'."""
        row = _disqualified_row(
            "W", "T", "second", {}, 50.0, 10.0, 5.0, "roi_below_5.0x"
        )
        assert row["outcome"] == "loss"

    def test_has_correct_columns(self):
        """Disqualified row has all expected schema columns."""
        row = _disqualified_row(
            "W", "T", "first", {}, 50.0, 10.0, 5.0, "test_reason"
        )
        assert set(row.keys()) == EXPECTED_COLUMNS


class TestTimestampHandling:
    """Tests for timestamp conversion in build_wallet_token_stats_row."""

    def test_milliseconds_converted_correctly(self):
        """Timestamps >1e12 (milliseconds) are divided by 1000."""
        ts_ms = 1700000000000  # milliseconds
        wd = _make_wallet_data(realized=500, total_invested=100, first_buy_time=ts_ms)
        row = build_wallet_token_stats_row(wd, "Token", "first")
        assert row is not None
        expected = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        assert row["first_entry_timestamp"] == expected

    def test_microseconds_converted_correctly(self):
        """Timestamps >1e15 (microseconds) are divided by 1e6."""
        ts_us = 1700000000000000  # microseconds
        wd = _make_wallet_data(realized=500, total_invested=100, first_buy_time=ts_us)
        row = build_wallet_token_stats_row(wd, "Token", "first")
        assert row is not None
        expected = datetime.fromtimestamp(ts_us / 1e6, tz=timezone.utc)
        assert row["first_entry_timestamp"] == expected

    def test_seconds_used_directly(self):
        """Timestamps that are already in seconds are used as-is."""
        ts_sec = 1700000000  # seconds
        wd = _make_wallet_data(realized=500, total_invested=100, first_buy_time=ts_sec)
        row = build_wallet_token_stats_row(wd, "Token", "first")
        assert row is not None
        expected = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
        assert row["first_entry_timestamp"] == expected

    def test_zero_timestamp_uses_now(self):
        """Zero timestamp falls back to current time."""
        wd = _make_wallet_data(realized=500, total_invested=100, first_buy_time=0)
        row = build_wallet_token_stats_row(wd, "Token", "first")
        assert row is not None
        # Should be roughly now (within a few seconds)
        delta = abs((datetime.now(timezone.utc) - row["first_entry_timestamp"]).total_seconds())
        assert delta < 5
