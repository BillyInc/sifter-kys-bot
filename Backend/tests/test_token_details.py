"""Token-details enrichment tests — risk block, top holders, refresh.

Covers:
  * bot_handlers._risk_metric        — scalar / nested / missing normalization
  * solana_tracker_client.get_token_holders + force_refresh cache bypass
  * bot_screens.render_token_details — Security/Risk/Top-Holders sections + Refresh
  * bot_handlers exec|refresh_token  — routes and forces a live re-fetch

No real network / Redis / Supabase — everything mocked.
"""

import json

import pytest

pytest.importorskip("opentelemetry", reason="venv not synced (uv sync)")

from unittest.mock import MagicMock, patch  # noqa: E402


# ── _risk_metric normalizer ─────────────────────────────────────────────────

class TestRiskMetric:
    def test_none_is_empty(self):
        from services.bot_handlers import _risk_metric
        assert _risk_metric(None) == {"count": None, "pct": None}

    def test_scalar_is_pct(self):
        from services.bot_handlers import _risk_metric
        assert _risk_metric(12.5) == {"count": None, "pct": 12.5}

    def test_nested_count_percentage(self):
        from services.bot_handlers import _risk_metric
        assert _risk_metric({"count": 3, "percentage": 8.0}) == {"count": 3, "pct": 8.0}

    def test_nested_alt_keys(self):
        from services.bot_handlers import _risk_metric
        out = _risk_metric({"wallets": 5, "percent": 4.2})
        assert out == {"count": 5, "pct": 4.2}

    def test_garbage_is_empty(self):
        from services.bot_handlers import _risk_metric
        assert _risk_metric("nonsense") == {"count": None, "pct": None}


# ── get_token_holders + cache bypass ────────────────────────────────────────

class TestHoldersClient:
    def _client(self):
        from services.solana_tracker_client import SolanaTrackerClient
        c = object.__new__(SolanaTrackerClient)
        return c

    def test_holders_passes_enrich_param(self):
        c = self._client()
        with patch.object(c, "_cached_get", return_value={"total": 42, "accounts": []}) as cg:
            out = c.get_token_holders("TOK", enrich=True)
        assert out["total"] == 42
        # enrich=identity param + 5-min ttl
        args, kwargs = cg.call_args
        assert args[0] == "/tokens/TOK/holders"
        assert args[1] == {"enrich": "identity"}

    def test_force_refresh_skips_cache_read(self):
        from services.solana_tracker_client import SolanaTrackerClient
        c = object.__new__(SolanaTrackerClient)
        redis = MagicMock()
        redis.get.return_value = json.dumps({"stale": True})
        with patch("services.solana_tracker_client.get_redis_client", return_value=redis), \
             patch.object(c, "_get", return_value={"fresh": True}) as get:
            out = c._cached_get("/tokens/TOK", ttl=3600, force_refresh=True)
        assert out == {"fresh": True}
        redis.get.assert_not_called()      # cache read bypassed
        get.assert_called_once()           # went to the API
        redis.setex.assert_called_once()   # fresh value written back

    def test_normal_get_uses_cache(self):
        from services.solana_tracker_client import SolanaTrackerClient
        c = object.__new__(SolanaTrackerClient)
        redis = MagicMock()
        redis.get.return_value = json.dumps({"cached": True})
        with patch("services.solana_tracker_client.get_redis_client", return_value=redis), \
             patch.object(c, "_get", return_value={"fresh": True}) as get:
            out = c._cached_get("/tokens/TOK", ttl=3600)
        assert out == {"cached": True}
        get.assert_not_called()


# ── render_token_details enriched sections ──────────────────────────────────

class TestTokenDetailsRender:
    def _ctx(self, **over):
        base = {
            "token_address": "T" * 44, "symbol": "WIF", "name": "dogwifhat",
            "price_usd": 0.01, "market_cap_usd": 2_000_000, "liquidity_usd": 80_000,
            "is_mint_revoked": True, "is_freeze_revoked": True, "lp_burn_pct": 100,
            "rugged": False, "jupiter_verified": True, "risk_score": 2,
            "bundlers": {"count": 3, "pct": 8.0},
            "snipers": {"count": 5, "pct": 4.2},
            "dev_holdings": {"count": None, "pct": 1.5},
            "top10": {"count": None, "pct": 22.0},
            "holders_total": 1234,
            "top_holders": [
                {"wallet": "Abc123xyz", "pct": 80.0, "usd": 4_700_000, "tag": "pool"},
                {"wallet": "Def456xyz", "pct": 2.9, "usd": 176_000, "tag": "kol"},
            ],
        }
        base.update(over)
        return base

    def test_renders_security_section(self):
        from services import bot_screens
        text, _kb = bot_screens.render_token_details(self._ctx())
        assert "Security" in text
        assert "Mint: ✅ Revoked" in text
        assert "Freeze: ✅ Revoked" in text
        assert "LP Burned: 100%" in text
        assert "Rugged: ✅ No" in text
        assert "Jupiter Verified: ✅ Yes" in text

    def test_renders_risk_section(self):
        from services import bot_screens
        text, _kb = bot_screens.render_token_details(self._ctx())
        assert "Risk" in text
        assert "Bundlers: 3 wallets • 8.0%" in text
        assert "Snipers: 5 wallets • 4.2%" in text
        assert "Dev holds: 1.5%" in text
        assert "Top 10: 22.0%" in text

    def test_renders_top_holders_with_tags(self):
        from services import bot_screens
        text, _kb = bot_screens.render_token_details(self._ctx())
        assert "Top Holders" in text
        assert "80.0%" in text
        assert "Pool" in text          # identity tag rendered
        assert "KOL" in text

    def test_has_refresh_button(self):
        from services import bot_screens
        _text, kb = bot_screens.render_token_details(self._ctx())
        flat = json.dumps(kb)
        assert "exec|refresh_token" in flat

    def test_rugged_token_shows_warning(self):
        from services import bot_screens
        text, _kb = bot_screens.render_token_details(self._ctx(rugged=True))
        assert "Rugged: 🛑 YES" in text

    def test_minimal_ctx_no_risk_section(self):
        # When risk metrics are absent, the Risk header must not appear.
        from services import bot_screens
        ctx = {"token_address": "T" * 44, "symbol": "WIF", "price_usd": 0.01}
        text, _kb = bot_screens.render_token_details(ctx)
        assert "Bundlers" not in text
        assert "Top Holders" not in text


# ── refresh routing ─────────────────────────────────────────────────────────

class TestRefreshRouting:
    def test_refresh_token_forces_live_fetch(self):
        from services import bot_handlers
        notifier = MagicMock()
        with patch("services.bot_state.get_state", return_value={"screen": "token_stats", "data": {}}), \
             patch.object(bot_handlers, "_show_token_details") as show:
            bot_handlers._handle_exec_action(notifier, "123", "refresh_token", ["TOKEN123"])
        show.assert_called_once()
        # force_refresh=True must be passed
        assert show.call_args.kwargs.get("force_refresh") is True

    def test_refresh_falls_back_to_state_token(self):
        from services import bot_handlers
        notifier = MagicMock()
        with patch("services.bot_state.get_state",
                   return_value={"screen": "manual_preview", "data": {"token_address": "STATETOK"}}), \
             patch.object(bot_handlers, "_show_token_details") as show:
            bot_handlers._handle_exec_action(notifier, "123", "refresh_token", [])
        show.assert_called_once()
        assert show.call_args[0][2] == "STATETOK"     # used state token
        assert show.call_args.kwargs.get("manual") is True
