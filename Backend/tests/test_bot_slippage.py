"""Adaptive slippage / congestion-retry tests.

Covers the three pieces of the slippage work:
  * bot_congestion   — fee → level classification and per-level tuning
  * bot_position_monitor._load_user_exec_settings — exit-path slippage/MEV parity
  * BotExecutionRouter._execute_live_with_retry   — congestion scaling + bounded,
    escalating retry with a hard slippage ceiling

No real RPC / Redis / Supabase — everything mocked.
"""

import pytest

pytest.importorskip("opentelemetry", reason="venv not synced (uv sync)")

from unittest.mock import MagicMock, patch  # noqa: E402

from services.execution_adapters import ExecutionResult  # noqa: E402


# ── bot_congestion ──────────────────────────────────────────────────────────

class TestCongestionClassification:
    def test_classify_buckets(self):
        from services import bot_congestion as bc
        assert bc._classify(None) == bc.NORMAL
        assert bc._classify(0) == bc.LOW
        assert bc._classify(5_000) == bc.NORMAL
        assert bc._classify(20_000) == bc.ELEVATED
        assert bc._classify(80_000) == bc.HIGH

    def test_tuning_normal_leaves_slippage_untouched(self):
        from services import bot_congestion as bc
        t = bc.get_tuning(bc.NORMAL)
        assert t.slippage_mult == 1.0

    def test_tuning_high_widens_slippage_and_priority(self):
        from services import bot_congestion as bc
        normal = bc.get_tuning(bc.NORMAL)
        high = bc.get_tuning(bc.HIGH)
        assert high.slippage_mult > normal.slippage_mult
        assert high.priority_fee_lamports > normal.priority_fee_lamports

    def test_get_level_failsoft_to_normal(self):
        from services import bot_congestion as bc
        # No Redis + sampler returns None (RPC unavailable) → NORMAL.
        with patch.object(bc, "_redis", return_value=None), \
             patch.object(bc, "_sample_median_priority_fee", return_value=None):
            assert bc.get_congestion_level() == bc.NORMAL


# ── exit-path slippage parity ───────────────────────────────────────────────

class TestExitExecSettings:
    def test_loads_user_slippage_and_mev(self):
        from services import bot_position_monitor as pm
        supabase = MagicMock()
        (supabase.schema.return_value.table.return_value.select.return_value
         .eq.return_value.limit.return_value.execute.return_value.data) = [
            {"slippage_bps": 250, "mev_protection": False},
        ]
        out = pm._load_user_exec_settings(supabase, "u1", {})
        assert out["slippage_bps"] == 250
        assert out["mev_protection"] is False

    def test_defaults_on_missing_user(self):
        from services import bot_position_monitor as pm
        supabase = MagicMock()
        (supabase.schema.return_value.table.return_value.select.return_value
         .eq.return_value.limit.return_value.execute.return_value.data) = []
        out = pm._load_user_exec_settings(supabase, "u1", {})
        assert out["slippage_bps"] == pm.DEFAULT_EXIT_SLIPPAGE_BPS
        assert out["mev_protection"] is True

    def test_cache_avoids_second_db_hit(self):
        from services import bot_position_monitor as pm
        supabase = MagicMock()
        (supabase.schema.return_value.table.return_value.select.return_value
         .eq.return_value.limit.return_value.execute.return_value.data) = [
            {"slippage_bps": 300, "mev_protection": True},
        ]
        cache: dict = {}
        pm._load_user_exec_settings(supabase, "u1", cache)
        pm._load_user_exec_settings(supabase, "u1", cache)
        # select() called only once thanks to the per-cycle cache
        assert supabase.schema.return_value.table.return_value.select.call_count == 1

    def test_defaults_on_error(self):
        from services import bot_position_monitor as pm
        supabase = MagicMock()
        supabase.schema.side_effect = RuntimeError("db down")
        out = pm._load_user_exec_settings(supabase, "u1", {})
        assert out["slippage_bps"] == pm.DEFAULT_EXIT_SLIPPAGE_BPS
        assert out["mev_protection"] is True


# ── router congestion scaling + retry ───────────────────────────────────────

def _result(status, reason):
    return ExecutionResult(
        status=status, stage="confirm" if status == "filled" else "execute",
        reason=reason, message=reason, requested_usd=100, executed_usd=100 if status == "filled" else 0,
        effective_price_usd=1.0, token_amount=100,
    )


def _router():
    from services.bot_execution import BotExecutionRouter
    with patch("services.bot_execution.get_supabase_client", return_value=MagicMock()):
        return BotExecutionRouter()


def _req():
    from services.bot_execution import BotTradeRequest
    return BotTradeRequest(
        user_id="u1", token_address="TOK", side="buy", requested_usd=100,
        settings={"slippage_bps": 100},
    )


class TestExecuteLiveRetry:
    def _signal(self):
        from services.execution_adapters import NormalizedTradeSignal
        return NormalizedTradeSignal(
            source="bot", side="buy", token_address="TOK", token_ticker="WIF",
            signal_key="k", wallet_count=1, total_usd=100, qualifying_usd=100,
        )

    def test_fill_first_attempt_no_retry(self):
        from services import bot_congestion as bc
        router = _router()
        adapter = MagicMock()
        adapter.execute.return_value = _result("filled", "live_fill")
        with patch("services.bot_execution.LiveJupiterExecutionAdapter", return_value=adapter), \
             patch.object(bc, "get_tuning", return_value=bc.CongestionTuning("normal", 1.0, 300_000)):
            res = router._execute_live_with_retry(self._signal(), _req(), {}, {"slippage_bps": 100})
        assert res.status == "filled"
        assert adapter.execute.call_count == 1
        assert res.payload["slippage_bps_used"] == 100   # normal → 1.0x

    def test_retryable_rejection_escalates_then_fills(self):
        from services import bot_congestion as bc
        router = _router()
        adapter = MagicMock()
        adapter.execute.side_effect = [
            _result("rejected", "stale_quote"),
            _result("filled", "live_fill"),
        ]
        with patch("services.bot_execution.LiveJupiterExecutionAdapter", return_value=adapter), \
             patch.object(bc, "get_tuning", return_value=bc.CongestionTuning("normal", 1.0, 300_000)):
            res = router._execute_live_with_retry(self._signal(), _req(), {}, {"slippage_bps": 100})
        assert res.status == "filled"
        assert adapter.execute.call_count == 2
        # Second attempt used a higher slippage than the first.
        first = adapter.execute.call_args_list[0].kwargs["settings"]["slippage_bps"]
        second = adapter.execute.call_args_list[1].kwargs["settings"]["slippage_bps"]
        assert second > first

    def test_non_retryable_rejection_stops_immediately(self):
        from services import bot_congestion as bc
        router = _router()
        adapter = MagicMock()
        adapter.execute.return_value = _result("rejected", "no_wallet_key")
        with patch("services.bot_execution.LiveJupiterExecutionAdapter", return_value=adapter), \
             patch.object(bc, "get_tuning", return_value=bc.CongestionTuning("normal", 1.0, 300_000)):
            res = router._execute_live_with_retry(self._signal(), _req(), {}, {"slippage_bps": 100})
        assert res.status == "rejected"
        assert adapter.execute.call_count == 1

    def test_slippage_never_exceeds_ceiling(self):
        from services import bot_congestion as bc
        from services import bot_execution as be
        router = _router()
        adapter = MagicMock()
        adapter.execute.return_value = _result("rejected", "stale_quote")  # always fails
        with patch("services.bot_execution.LiveJupiterExecutionAdapter", return_value=adapter), \
             patch.object(bc, "get_tuning", return_value=bc.CongestionTuning("high", 2.0, 3_000_000)):
            router._execute_live_with_retry(self._signal(), _req(), {}, {"slippage_bps": 100})
        used = [c.kwargs["settings"]["slippage_bps"] for c in adapter.execute.call_args_list]
        assert all(s <= be._MAX_SLIPPAGE_BPS for s in used)
        assert len(used) <= be._MAX_EXECUTION_ATTEMPTS

    def test_congestion_scales_initial_slippage(self):
        from services import bot_congestion as bc
        router = _router()
        adapter = MagicMock()
        adapter.execute.return_value = _result("filled", "live_fill")
        with patch("services.bot_execution.LiveJupiterExecutionAdapter", return_value=adapter), \
             patch.object(bc, "get_tuning", return_value=bc.CongestionTuning("elevated", 1.5, 1_000_000)):
            res = router._execute_live_with_retry(self._signal(), _req(), {}, {"slippage_bps": 100})
        # elevated → 1.5x of the user's 100 bps
        assert res.payload["slippage_bps_used"] == 150
