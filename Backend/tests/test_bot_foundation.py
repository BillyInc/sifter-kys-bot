"""Tests for the Sprint 1 Telegram bot foundation.

Covers:
  * bot_state    — Redis state machine round-trip, corrupt-value safety
  * bot_screens  — pure render functions return (text, keyboard)
  * bot_execution — safe_noop boundary records a position, no decrypt/network
  * router       — telegram_notifier dispatch is backward-compatible

No real Redis / Supabase / ClickHouse / Telegram calls — everything mocked.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ════════════════════════════════════════════════════════════════════════════
# bot_state
# ════════════════════════════════════════════════════════════════════════════

class TestBotState:
    @pytest.fixture
    def fake_redis(self):
        """An in-memory stand-in for the redis client (get/setex/delete/ttl)."""
        store = {}

        class FakeRedis:
            def get(self, k):
                return store.get(k)

            def setex(self, k, ttl, v):
                store[k] = v

            def delete(self, k):
                store.pop(k, None)

            def ttl(self, k):
                return 3600 if k in store else -2

        return FakeRedis(), store

    def test_get_state_default_when_absent(self, fake_redis):
        client, _ = fake_redis
        with patch("services.bot_state.get_redis_client", return_value=client):
            from services import bot_state
            st = bot_state.get_state("123")
            assert st["screen"] == "main"
            assert st["awaiting"] is None
            assert st["data"] == {}

    def test_set_and_get_roundtrip(self, fake_redis):
        client, store = fake_redis
        with patch("services.bot_state.get_redis_client", return_value=client):
            from services import bot_state
            bot_state.set_state("123", screen="settings", data={"token": "ABC"})
            st = bot_state.get_state("123")
            assert st["screen"] == "settings"
            assert st["data"]["token"] == "ABC"
            # persisted under the namespaced key
            assert "sifter:bot_state:123" in store

    def test_set_awaiting_and_is_awaiting(self, fake_redis):
        client, _ = fake_redis
        with patch("services.bot_state.get_redis_client", return_value=client):
            from services import bot_state
            bot_state.set_awaiting("123", "wallet_private_key", data={"x": 1})
            assert bot_state.is_awaiting("123") is True
            assert bot_state.is_awaiting("123", "wallet_private_key") is True
            assert bot_state.is_awaiting("123", "something_else") is False

    def test_merge_data_preserves_existing(self, fake_redis):
        client, _ = fake_redis
        with patch("services.bot_state.get_redis_client", return_value=client):
            from services import bot_state
            bot_state.set_state("123", data={"a": 1})
            bot_state.set_state("123", data={"b": 2})
            st = bot_state.get_state("123")
            assert st["data"] == {"a": 1, "b": 2}

    def test_clear_state(self, fake_redis):
        client, store = fake_redis
        with patch("services.bot_state.get_redis_client", return_value=client):
            from services import bot_state
            bot_state.set_state("123", screen="settings")
            bot_state.clear_state("123")
            assert "sifter:bot_state:123" not in store
            # subsequent get returns default
            assert bot_state.get_state("123")["screen"] == "main"

    def test_corrupt_json_returns_default(self, fake_redis):
        client, store = fake_redis
        store["sifter:bot_state:123"] = "{not valid json"
        with patch("services.bot_state.get_redis_client", return_value=client):
            from services import bot_state
            st = bot_state.get_state("123")
            assert st["screen"] == "main"
            assert st["awaiting"] is None

    def test_push_screen_clears_awaiting(self, fake_redis):
        client, _ = fake_redis
        with patch("services.bot_state.get_redis_client", return_value=client):
            from services import bot_state
            bot_state.set_awaiting("123", "some_input")
            bot_state.push_screen("123", "positions")
            st = bot_state.get_state("123")
            assert st["screen"] == "positions"
            assert st["awaiting"] is None


# ════════════════════════════════════════════════════════════════════════════
# bot_screens
# ════════════════════════════════════════════════════════════════════════════

class TestBotScreens:
    def test_render_main_basic_user_has_access_gate(self):
        from services import bot_screens
        text, kb = bot_screens.render_main({
            "connected": True, "access_tier": "free", "username": "alice",
        })
        assert "Main Menu" in text
        flat = json.dumps(kb)
        assert "nav|access" in flat          # basic users see the access gate
        assert "nav|autotrade" not in flat   # but not the auto-trader section

    def test_render_main_autotrader_shows_bot_sections(self):
        from services import bot_screens
        text, kb = bot_screens.render_main({
            "connected": True, "access_tier": "autotrader",
            "auto_trade_enabled": True, "username": "bob",
        })
        flat = json.dumps(kb)
        assert "nav|autotrade" in flat
        assert "nav|elite15" in flat
        assert "ACTIVE" in text

    def test_render_main_operator_sees_operator_panel(self):
        from services import bot_screens
        _, kb = bot_screens.render_main({
            "connected": True, "access_tier": "autotrader", "is_operator": True,
        })
        assert "nav|operator" in json.dumps(kb)

    def test_render_settings_is_readonly_and_no_removed_filters(self):
        from services import bot_screens
        text, kb = bot_screens.render_settings_home({
            "consensus_threshold": 2, "trading_pool_pct": 50,
            "stop_loss_pct": -50, "take_profit_x": 5.0, "slippage_bps": 100,
        })
        # Read-only hint present
        assert "read-only" in text.lower()
        # The removed filters must never surface on screen
        low = text.lower()
        assert "fake vol" not in low
        assert "risk score" not in low
        assert "market cap" not in low and "mcap" not in low

    def test_render_error_has_main_menu_button(self):
        from services import bot_screens
        text, kb = bot_screens.render_error("boom")
        assert "boom" in text
        assert "nav|main" in json.dumps(kb)


# ════════════════════════════════════════════════════════════════════════════
# bot_execution — safe_noop boundary
# ════════════════════════════════════════════════════════════════════════════

class TestBotExecutionSafeNoop:
    def _patched_router(self):
        """Build a router with a mocked position store + supabase."""
        with patch("services.bot_execution.get_supabase_client", return_value=MagicMock()):
            from services.bot_execution import BotExecutionRouter
            router = BotExecutionRouter()
        router._store = MagicMock()
        return router

    def test_safe_noop_buy_fills_without_network(self):
        from services.bot_execution import BotTradeRequest
        router = self._patched_router()
        with patch("services.bot_execution.Config") as cfg:
            cfg.BOT_EXECUTION_MODE = "safe_noop"
            req = BotTradeRequest(
                user_id="u1", token_address="TOK", side="buy",
                requested_usd=100.0, snapshot={"price": 0.5},
            )
            result = router.execute(req)

        assert result.status == "filled"
        assert result.reason == "safe_noop"
        assert result.payload["execution_mode"] == "safe_noop"
        assert result.executed_usd == 100.0
        assert result.token_amount == 200.0          # 100 / 0.5
        assert result.txid and result.txid.startswith("NOOP")
        # a position was recorded via the store (buy path)
        router._store.record_buy.assert_called_once()
        router._store.record_sell.assert_not_called()

    def test_safe_noop_sell_routes_to_record_sell(self):
        from services.bot_execution import BotTradeRequest
        router = self._patched_router()
        with patch("services.bot_execution.Config") as cfg:
            cfg.BOT_EXECUTION_MODE = "safe_noop"
            req = BotTradeRequest(
                user_id="u1", token_address="TOK", side="sell",
                requested_usd=50.0, sell_pct=50, snapshot={"price": 1.0},
            )
            result = router.execute(req)

        assert result.status == "filled"
        router._store.record_sell.assert_called_once()
        router._store.record_buy.assert_not_called()

    def test_safe_noop_never_decrypts_or_calls_live_adapter(self):
        from services.bot_execution import BotTradeRequest
        router = self._patched_router()
        with patch("services.bot_execution.Config") as cfg, \
             patch("services.bot_execution.LiveJupiterExecutionAdapter") as live:
            cfg.BOT_EXECUTION_MODE = "safe_noop"
            router.execute(BotTradeRequest(
                user_id="u1", token_address="TOK", side="buy",
                requested_usd=10.0, snapshot={"price": 1.0},
            ))
            live.assert_not_called()   # live adapter is never even constructed

    def test_live_mode_blocked_by_kill_switch(self):
        from services.bot_execution import BotTradeRequest
        router = self._patched_router()
        with patch("services.bot_execution.Config") as cfg, \
             patch.object(router, "_kill_switch_active", return_value=True):
            cfg.BOT_EXECUTION_MODE = "live"
            result = router.execute(BotTradeRequest(
                user_id="u1", token_address="TOK", side="buy", requested_usd=10.0,
            ))
        assert result.status == "rejected"
        assert result.reason == "kill_switch"
        router._store.record_buy.assert_not_called()


# ════════════════════════════════════════════════════════════════════════════
# router backward-compat — telegram_notifier dispatch
# ════════════════════════════════════════════════════════════════════════════

class TestRouterBackwardCompat:
    @pytest.fixture
    def notifier(self):
        """A TelegramNotifier with network + supabase mocked out."""
        with patch("services.telegram_notifier.get_supabase_client", return_value=MagicMock()):
            from services.telegram_notifier import TelegramNotifier
            n = TelegramNotifier(bot_token="test-token")
        n._make_request = MagicMock(return_value={"ok": True})
        n.send_message = MagicMock(return_value=True)
        return n

    def test_new_nav_callback_routes_to_menu(self, notifier):
        """nav|main is routed to the new handlers, not the legacy no-op."""
        with patch("services.bot_handlers.handle_callback") as hc:
            notifier._handle_callback({
                "id": "q1", "from": {"id": 999}, "data": "nav|main",
            })
            hc.assert_called_once()
            # category/action correctly parsed
            args = hc.call_args[0]
            assert args[3] == "nav" and args[4] == "main"

    def test_legacy_sell_callback_still_handled(self, notifier):
        """The legacy sell| format must not be swallowed by the new dispatch."""
        with patch("services.bot_handlers.handle_callback") as hc, \
             patch("services.telegram_notifier.get_paper_trading_manager", create=True):
            # chat_id != owner → legacy branch answers "Not your button"
            notifier._handle_callback({
                "id": "q2", "from": {"id": 111},
                "data": "sell|222|TOKEN|50",
            })
            hc.assert_not_called()   # never routed to the new menu
            notifier._make_request.assert_called()  # legacy path answered

    def test_unknown_pipe_callback_falls_through_to_noop(self, notifier):
        """An unrecognized category falls through to the legacy answerCallbackQuery."""
        with patch("services.bot_handlers.handle_callback") as hc:
            notifier._handle_callback({
                "id": "q3", "from": {"id": 999}, "data": "xyz|foo|bar",
            })
            hc.assert_not_called()
            notifier._make_request.assert_called_with(
                "answerCallbackQuery", {"callback_query_id": "q3"}
            )

    def test_menu_command_routes_to_handler(self, notifier):
        """/menu is consumed by the new command handler."""
        with patch("services.bot_handlers.handle_command", return_value=True) as hcmd, \
             patch("services.bot_handlers.handle_text_input", return_value=False):
            notifier._handle_message({
                "chat": {"id": 999}, "from": {"id": 999, "username": "z"},
                "text": "/menu",
            })
            hcmd.assert_called_once()

    def test_legacy_help_command_still_falls_through(self, notifier):
        """A legacy command (/help) is NOT consumed by the new layer."""
        with patch("services.bot_handlers.handle_command", return_value=False), \
             patch("services.bot_handlers.handle_text_input", return_value=False):
            notifier._handle_message({
                "chat": {"id": 999}, "from": {"id": 999, "username": "z"},
                "text": "/help",
            })
            # Legacy /help path sends a message (the command reference)
            assert notifier.send_message.called


# ════════════════════════════════════════════════════════════════════════════
# Sprint 2 — onboarding + wallet-import migration to the state machine
# ════════════════════════════════════════════════════════════════════════════

class TestWelcomeAndHelpScreens:
    def test_welcome_has_register_and_dashboard_when_url_set(self):
        from services import bot_screens
        text, kb = bot_screens.render_welcome({"dashboard_url": "https://app.sifter.io"})
        assert "Welcome to SIFTER" in text
        flat = json.dumps(kb)
        assert "nav|register" in flat
        assert "https://app.sifter.io" in flat   # login + dashboard URL buttons

    def test_welcome_without_url_still_renders_register(self):
        from services import bot_screens
        text, kb = bot_screens.render_welcome({"dashboard_url": None})
        flat = json.dumps(kb)
        assert "nav|register" in flat
        assert "url" not in flat  # no URL buttons when dashboard is unset

    def test_not_connected_is_welcome_alias(self):
        from services import bot_screens
        assert bot_screens.render_not_connected({"dashboard_url": None}) == \
            bot_screens.render_welcome({"dashboard_url": None})

    def test_help_screen_has_back_to_main(self):
        from services import bot_screens
        text, kb = bot_screens.render_help()
        assert "Help" in text
        assert "nav|main" in json.dumps(kb)


class TestWalletImportStateMachine:
    """The /importwallet flow must run entirely on bot_state.awaiting now —
    the module-level _wallet_import_pending dict is gone."""

    def test_no_module_level_pending_dict(self):
        import services.telegram_notifier as tn
        assert not hasattr(tn, "_wallet_import_pending")

    def test_awaiting_wallet_key_dispatches_to_handler(self):
        """When awaiting='wallet_private_key', plain text is routed to the
        existing key handler and the awaited state is cleared."""
        from services import bot_handlers
        notifier = MagicMock()
        with patch("services.bot_state.get_state", return_value={"awaiting": "wallet_private_key"}), \
             patch("services.bot_state.set_awaiting") as set_awaiting:
            consumed = bot_handlers.handle_text_input(
                notifier, "123", "5Jkey...base58", {"message_id": 7}
            )
        assert consumed is True
        notifier._handle_wallet_key_message.assert_called_once()
        set_awaiting.assert_called_once_with("123", None)

    def test_cancel_during_wallet_import_clears_state(self):
        from services import bot_handlers
        notifier = MagicMock()
        with patch("services.bot_state.get_state", return_value={"awaiting": "wallet_private_key"}), \
             patch("services.bot_state.clear_state") as clear_state:
            consumed = bot_handlers.handle_text_input(notifier, "123", "/cancel", {})
        assert consumed is True
        clear_state.assert_called_once_with("123")
        notifier._handle_wallet_key_message.assert_not_called()

    def test_no_awaiting_falls_through(self):
        """With nothing awaited, text input is not consumed (legacy handles it)."""
        from services import bot_handlers
        notifier = MagicMock()
        with patch("services.bot_state.get_state", return_value={"awaiting": None}):
            assert bot_handlers.handle_text_input(notifier, "123", "hello", {}) is False


# ════════════════════════════════════════════════════════════════════════════
# Sprint 3 — auto-trade control + the two-filter stack
# ════════════════════════════════════════════════════════════════════════════

class TestAutoTradeFilters:
    """The filter stack is EXACTLY consensus + blacklist. No mcap/risk/fakevol."""

    def test_passes_when_consensus_met_and_not_blacklisted(self):
        from services.bot_filters import passes_auto_trade_filters
        ok, reason = passes_auto_trade_filters(
            {"consensus_threshold": 2},
            {"wallet_count": 3, "token_address": "TOK"},
            set(),
        )
        assert ok is True
        assert reason is None

    def test_blocked_below_consensus(self):
        from services.bot_filters import passes_auto_trade_filters
        ok, reason = passes_auto_trade_filters(
            {"consensus_threshold": 3},
            {"wallet_count": 2, "token_address": "TOK"},
            set(),
        )
        assert ok is False
        assert reason == "below_consensus"

    def test_blocked_when_blacklisted(self):
        from services.bot_filters import passes_auto_trade_filters
        ok, reason = passes_auto_trade_filters(
            {"consensus_threshold": 1},
            {"wallet_count": 5, "token_address": "TOK"},
            {"TOK"},
        )
        assert ok is False
        assert reason == "blacklisted"

    def test_consensus_zero_passes_any_single_signal(self):
        from services.bot_filters import passes_auto_trade_filters
        ok, _ = passes_auto_trade_filters(
            {"consensus_threshold": 0},
            {"wallet_count": 1, "token_address": "TOK"},
            set(),
        )
        assert ok is True

    def test_removed_filters_have_no_effect(self):
        """A signal carrying high fake-vol / risk / extreme mcap still passes —
        those filters were intentionally removed from the build."""
        from services.bot_filters import passes_auto_trade_filters
        signal = {
            "wallet_count": 2, "token_address": "TOK",
            # These keys must be ignored entirely:
            "fake_vol_pct": 99, "risk_score": 10, "mc_usd": 5,
        }
        ok, reason = passes_auto_trade_filters({"consensus_threshold": 1}, signal, set())
        assert ok is True and reason is None

    def test_no_removed_filter_keys_referenced_in_source(self):
        """Guard against re-introduction of the removed filters in bot_filters."""
        import inspect
        from services import bot_filters
        src = inspect.getsource(bot_filters)
        # The names may appear in the explanatory docstring, so check for usage
        # as dict lookups / attributes rather than mere mention.
        for bad in ("['fake_vol", '["fake_vol', "['risk_score", '["risk_score',
                    "['min_mc", "['max_mc", "['mc_usd"):
            assert bad not in src

    def test_load_blacklist_set_returns_addresses(self):
        from services.bot_filters import load_blacklist_set
        supabase = MagicMock()
        (supabase.schema.return_value.table.return_value.select.return_value
         .eq.return_value.execute.return_value.data) = [
            {"token_address": "AAA"}, {"token_address": "BBB"},
        ]
        assert load_blacklist_set(supabase, "u1") == {"AAA", "BBB"}

    def test_load_blacklist_set_empty_on_error(self):
        from services.bot_filters import load_blacklist_set
        supabase = MagicMock()
        supabase.schema.side_effect = RuntimeError("db down")
        assert load_blacklist_set(supabase, "u1") == set()


class TestAutoTradeScreens:
    def test_autotrade_home_shows_toggle_and_links(self):
        from services import bot_screens
        # Enabled → shows Pause
        text, kb = bot_screens.render_autotrade_home(
            {"auto_trade_enabled": True, "consensus_threshold": 2, "blacklist_count": 3}
        )
        flat = json.dumps(kb)
        assert "set|autotrade|off" in flat
        assert "nav|consensus" in flat
        assert "nav|blacklist" in flat
        assert "ACTIVE" in text
        # Disabled → shows Resume
        _, kb2 = bot_screens.render_autotrade_home(
            {"auto_trade_enabled": False, "consensus_threshold": 1}
        )
        assert "set|autotrade|on" in json.dumps(kb2)

    def test_consensus_picker_has_presets_and_custom(self):
        from services import bot_screens
        text, kb = bot_screens.render_consensus_picker({"consensus_threshold": 5})
        flat = json.dumps(kb)
        for n in (1, 3, 5, 8, 10, 12, 15):
            assert f"set|consensus|{n}" in flat
        assert "set|consensus|custom" in flat
        assert "🔵 5" in flat            # current value marked

    def test_blacklist_renders_entries_with_remove(self):
        from services import bot_screens
        text, kb = bot_screens.render_blacklist({"blacklist": [
            {"token_address": "TokenAddr123456", "token_symbol": "RUG", "reason": "auto_sl"},
        ]})
        flat = json.dumps(kb)
        assert "blk|del|TokenAddr123456" in flat
        assert "blk|add" in flat
        assert "RUG" in text

    def test_blacklist_empty_state(self):
        from services import bot_screens
        text, kb = bot_screens.render_blacklist({"blacklist": []})
        assert "No blacklisted tokens" in text
        assert "blk|add" in json.dumps(kb)


class TestAutoTradeHandlers:
    def _notifier(self, access_tier="autotrader"):
        n = MagicMock()
        n._is_operator.return_value = False
        # _load_user_ctx reads telegram_users then bot_wallets; emulate via the
        # handler's own loader by patching it in each test instead.
        return n

    def test_set_autotrade_off_writes_db(self):
        from services import bot_handlers
        notifier = self._notifier()
        ctx = {"user_id": "u1", "access_tier": "autotrader"}
        with patch.object(bot_handlers, "_load_user_ctx", return_value=dict(ctx)), \
             patch.object(bot_handlers, "_open_autotrade"), \
             patch.object(bot_handlers, "_load_blacklist", return_value=[]):
            bot_handlers._handle_set(notifier, "123", "autotrade", ["off"])
        notifier._table.assert_called_with("telegram_users")
        update = notifier._table.return_value.update
        update.assert_called_with({"auto_trade_enabled": False})

    def test_set_consensus_valid_value_writes_db(self):
        from services import bot_handlers
        notifier = self._notifier()
        with patch.object(bot_handlers, "_load_user_ctx",
                          return_value={"user_id": "u1", "access_tier": "autotrader"}), \
             patch.object(bot_handlers, "_open_consensus"):
            bot_handlers._handle_set(notifier, "123", "consensus", ["5"])
        notifier._table.return_value.update.assert_called_with({"consensus_threshold": 5})

    def test_set_consensus_custom_sets_awaiting(self):
        from services import bot_handlers
        notifier = self._notifier()
        with patch.object(bot_handlers, "_load_user_ctx",
                          return_value={"user_id": "u1", "access_tier": "autotrader"}), \
             patch("services.bot_state.set_awaiting") as set_awaiting:
            bot_handlers._handle_set(notifier, "123", "consensus", ["custom"])
        set_awaiting.assert_called_once_with("123", "consensus_value")

    def test_set_consensus_out_of_range_rejected(self):
        from services import bot_handlers
        notifier = self._notifier()
        with patch.object(bot_handlers, "_load_user_ctx",
                          return_value={"user_id": "u1", "access_tier": "autotrader"}):
            bot_handlers._handle_set(notifier, "123", "consensus", ["99"])
        # No DB write on invalid value
        notifier._table.return_value.update.assert_not_called()

    def test_blacklist_add_sets_awaiting(self):
        from services import bot_handlers
        notifier = self._notifier()
        with patch.object(bot_handlers, "_load_user_ctx",
                          return_value={"user_id": "u1", "access_tier": "autotrader"}), \
             patch("services.bot_state.set_awaiting") as set_awaiting:
            bot_handlers._handle_blacklist_action(notifier, "123", "add", [])
        set_awaiting.assert_called_once_with("123", "blacklist_token")

    def test_blacklist_del_removes_row(self):
        from services import bot_handlers
        notifier = self._notifier()
        with patch.object(bot_handlers, "_load_user_ctx",
                          return_value={"user_id": "u1", "access_tier": "autotrader"}), \
             patch.object(bot_handlers, "_open_blacklist"):
            bot_handlers._handle_blacklist_action(notifier, "123", "del", ["TOK"])
        notifier._table.assert_called_with("bot_token_blacklist")

    def test_free_user_blocked_from_autotrade(self):
        from services import bot_handlers
        notifier = self._notifier()
        notifier._is_operator.return_value = False
        with patch.object(bot_handlers, "_load_user_ctx",
                          return_value={"user_id": "u1", "access_tier": "free"}):
            result = bot_handlers._require_autotrader(notifier, "123")
        assert result is None
        notifier.send_message.assert_called_once()  # gate message sent

    def test_operator_passes_autotrade_gate(self):
        from services import bot_handlers
        notifier = self._notifier()
        notifier._is_operator.return_value = True
        with patch.object(bot_handlers, "_load_user_ctx",
                          return_value={"user_id": "u1", "access_tier": "free"}):
            result = bot_handlers._require_autotrader(notifier, "123")
        assert result is not None

    def test_strategy_setting_writes_stop_loss(self):
        from services import bot_handlers
        notifier = self._notifier()
        with patch.object(bot_handlers, "_load_user_ctx",
                          return_value={"user_id": "u1", "access_tier": "autotrader"}), \
             patch.object(bot_handlers, "_open_strategy"):
            bot_handlers._handle_setting_action(notifier, "123", "sl", ["-25"])
        notifier._table.return_value.update.assert_called_with({"stop_loss_pct": -25})

    def test_sizing_setting_writes_tier_value(self):
        from services import bot_handlers
        notifier = self._notifier()
        with patch.object(bot_handlers, "_load_user_ctx",
                          return_value={"user_id": "u1", "access_tier": "autotrader"}), \
             patch.object(bot_handlers, "_open_sizing"):
            bot_handlers._handle_setting_action(notifier, "123", "sizing", ["t2", "70"])
        notifier._table.return_value.update.assert_called_with({"tier2_pct_of_pool": 70.0})


class TestAutonomousBotQueue:
    def test_queue_autonomous_trade_uses_bot_signal_queue(self):
        from services.bot_autotrade import queue_autonomous_trade

        supabase = MagicMock()
        table = supabase.schema.return_value.table

        telegram_chain = table.return_value.select.return_value.eq.return_value.limit.return_value.execute
        telegram_chain.return_value.data = [{
            "user_id": "u1",
            "auto_trade_enabled": True,
            "access_tier": "autotrader",
            "consensus_threshold": 1,
            "auto_trade_max_usd": 100,
            "tier1_pct_of_pool": 30,
        }]

        # make bot_live_positions query empty, bot_signal_queue existing empty,
        # then insert returns the queued row.
        def table_side_effect(name):
            t = MagicMock()
            if name == "bot_token_blacklist":
                t.select.return_value.eq.return_value.execute.return_value.data = []
            elif name == "bot_live_positions":
                t.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
            elif name == "bot_signal_queue":
                t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
                t.insert.return_value.execute.return_value.data = [{"id": 7, "status": "pending"}]
            elif name == "telegram_users":
                t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
                    "user_id": "u1",
                    "auto_trade_enabled": True,
                    "access_tier": "autotrader",
                    "consensus_threshold": 1,
                    "auto_trade_max_usd": 100,
                    "tier1_pct_of_pool": 30,
                }]
            return t

        table.side_effect = table_side_effect
        result = queue_autonomous_trade(
            user_id="u1",
            signal={"signal_key": "sig1", "token_address": "TOK", "wallet_count": 1, "total_usd": 200},
            supabase=supabase,
        )
        assert result["queue_id"] == 7
        assert result["status"] == "pending"

    def test_record_buy_snapshots_strategy_settings(self):
        from services.bot_execution import BotPositionStore, BotTradeRequest
        from services.execution_adapters import ExecutionResult

        store = object.__new__(BotPositionStore)
        store._table = MagicMock()
        store._log_trade = MagicMock()
        store._table.return_value.insert.return_value.execute.return_value.data = [{"id": 1}]

        req = BotTradeRequest(
            user_id="u1",
            token_address="TOK",
            requested_usd=100,
            settings={"stop_loss_pct": -25, "take_profit_x": 3, "trailing_stop_pct": 20},
        )
        result = ExecutionResult(
            status="filled",
            stage="confirm",
            reason="safe_noop",
            message="ok",
            requested_usd=100,
            executed_usd=100,
            effective_price_usd=1,
            token_amount=100,
            payload={"execution_mode": "safe_noop"},
        )
        store.record_buy(req, result)
        row = store._table.return_value.insert.call_args[0][0]
        assert row["stop_loss_pct"] == -25
        assert row["take_profit_x"] == 3
        assert row["trailing_stop_pct"] == 20
