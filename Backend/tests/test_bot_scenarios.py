"""Autonomous reject-path scenarios — each filter returns the right reason.

Tests the pure predicate passes_auto_trade_filters (consensus + blacklist) and
the security screen wiring. Requires the synced venv for the full autotrade
path; the pure-filter tests run via direct module load.
"""

import importlib.util
import os
import sys
import types

# Load bot_filters in isolation (it only imports supabase_client for SCHEMA_NAME).
_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if "services" not in sys.modules:
    pkg = types.ModuleType("services")
    pkg.__path__ = [os.path.join(_PKG, "services")]
    sys.modules["services"] = pkg
# Stub supabase_client so bot_filters imports cleanly without the real client.
if "services.supabase_client" not in sys.modules:
    stub = types.ModuleType("services.supabase_client")
    stub.SCHEMA_NAME = "sifter_dev"
    sys.modules["services.supabase_client"] = stub

_spec = importlib.util.spec_from_file_location(
    "bot_filters", os.path.join(_PKG, "services", "bot_filters.py")
)
bot_filters = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bot_filters)


class TestConsensusFilter:
    def test_below_consensus_rejected(self):
        ok, reason = bot_filters.passes_auto_trade_filters(
            {"consensus_threshold": 3}, {"wallet_count": 2, "token_address": "TOK"}, set())
        assert ok is False and reason == "below_consensus"

    def test_consensus_met_passes(self):
        ok, reason = bot_filters.passes_auto_trade_filters(
            {"consensus_threshold": 2}, {"wallet_count": 2, "token_address": "TOK"}, set())
        assert ok is True and reason is None

    def test_consensus_zero_passes_single(self):
        ok, _ = bot_filters.passes_auto_trade_filters(
            {"consensus_threshold": 0}, {"wallet_count": 1, "token_address": "TOK"}, set())
        assert ok is True


class TestBlacklistFilter:
    def test_blacklisted_rejected(self):
        ok, reason = bot_filters.passes_auto_trade_filters(
            {"consensus_threshold": 1}, {"wallet_count": 5, "token_address": "BAD"}, {"BAD"})
        assert ok is False and reason == "blacklisted"

    def test_not_blacklisted_passes(self):
        ok, _ = bot_filters.passes_auto_trade_filters(
            {"consensus_threshold": 1}, {"wallet_count": 5, "token_address": "OK"}, {"BAD"})
        assert ok is True


class TestNoRemovedFilters:
    def test_removed_filter_keys_have_no_effect(self):
        # risk_score / fake_vol / mc must NOT influence the decision.
        signal = {
            "wallet_count": 2, "token_address": "TOK",
            "risk_score": 10, "fake_vol_pct": 99, "mc_usd": 1,
        }
        ok, _ = bot_filters.passes_auto_trade_filters({"consensus_threshold": 1}, signal, set())
        assert ok is True
