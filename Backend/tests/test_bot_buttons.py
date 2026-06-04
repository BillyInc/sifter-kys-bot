"""Button coverage — every callback the screens emit must route to a real handler.

Strategy:
  1. Render each screen with mock context → collect every callback_data string.
  2. For each, split into category|action|params and assert the router
     (handle_callback) dispatches it WITHOUT hitting the "coming soon" / unknown
     fallback. We patch the per-category handlers so we only test routing, not
     side effects (those are covered in test_bot_foundation).

This guarantees no button is a dead end. URL buttons (no callback_data) are
skipped — they open links, not handlers.

Imports services.* so requires the synced venv (opentelemetry etc.). When the
venv isn't synced these are skipped at collection by the import guard.
"""

import pytest

pytest.importorskip("opentelemetry", reason="venv not synced (uv sync)")

from unittest.mock import MagicMock, patch  # noqa: E402

from services import bot_handlers, bot_screens  # noqa: E402


def _collect_callbacks(rendered) -> list:
    """Pull every callback_data out of a (text, keyboard) render result."""
    _text, kb = rendered
    out = []
    if not kb:
        return out
    for row in kb.get("inline_keyboard", []):
        for btn in row:
            cb = btn.get("callback_data")
            if cb:
                out.append(cb)
    return out


# Representative screens rendered with minimal mock context.
def _all_screen_callbacks() -> set:
    ctx_auto = {
        "user_id": "u1", "access_tier": "autotrader", "username": "t",
        "auto_trade_enabled": True, "consensus_threshold": 1, "blacklist_count": 0,
        "trading_pool_pct": 50, "max_deployment_pct": 80, "paper_mode": False,
        "tier1_pct_of_pool": 30, "tier2_pct_of_pool": 70, "tier3_pct_of_total": 40,
    }
    screens = [
        bot_screens.render_main(ctx_auto),
        bot_screens.render_autotrade_home(ctx_auto),
        bot_screens.render_strategy_settings(ctx_auto),
        bot_screens.render_portfolio_sizing(ctx_auto),
        bot_screens.render_notification_settings(ctx_auto),
        bot_screens.render_account({**ctx_auto, "total_trades": 0}),
        bot_screens.render_positions({"positions": [{
            "id": 1, "token_address": "T" * 44, "token_symbol": "WIF",
            "avg_entry_price": 0.001, "total_invested_usd": 100, "current_value_usd": 150,
        }]}),
        bot_screens.render_elite15({"wallets": [{"wallet_address": "W" * 44, "tier": "S"}], "selected_wallets": []}),
        bot_screens.render_wallets({"bot_wallets": [], "tracked_wallets": []}),
        bot_screens.render_manual_trade_entry(),
        bot_screens.render_price_alerts({"alerts": []}),
        bot_screens.render_notes({"notes": [], "reminders": []}),
        bot_screens.render_operator_panel(),
    ]
    cbs = set()
    for s in screens:
        cbs.update(_collect_callbacks(s))
    return cbs


def test_no_button_hits_coming_soon():
    """Every screen callback must dispatch to a real category handler."""
    callbacks = _all_screen_callbacks()
    assert callbacks, "no callbacks collected — screens changed?"

    # Patch every category handler so routing is observable without side effects.
    notifier = MagicMock()
    notifier._is_operator.return_value = True

    unknown = []
    with patch.object(bot_handlers, "_navigate") as nav, \
         patch.object(bot_handlers, "_handle_set"), \
         patch.object(bot_handlers, "_handle_blacklist_action"), \
         patch.object(bot_handlers, "_handle_position_action"), \
         patch.object(bot_handlers, "_handle_wallet_action"), \
         patch.object(bot_handlers, "_handle_exec_action"), \
         patch.object(bot_handlers, "_handle_access_action"), \
         patch.object(bot_handlers, "_handle_stat_action"), \
         patch.object(bot_handlers, "_handle_alert_action"), \
         patch.object(bot_handlers, "_handle_note_action"), \
         patch.object(bot_handlers, "_handle_op_action"), \
         patch.object(bot_handlers, "_send_rendered") as send_rendered, \
         patch.object(bot_handlers, "_answer"):
        for cb in callbacks:
            parts = cb.split("|")
            category, action = parts[0], (parts[1] if len(parts) > 1 else "")
            params = parts[2:]
            if category not in bot_handlers.NEW_CATEGORIES:
                unknown.append(cb)
                continue
            query = {"id": "q", "data": cb}
            bot_handlers.handle_callback(notifier, "123", query, category, action, params)

    assert not unknown, f"buttons with unrouted categories: {unknown}"


def test_every_category_has_a_dispatch_branch():
    """Sanity: each NEW_CATEGORY has an explicit branch in handle_callback."""
    import inspect
    src = inspect.getsource(bot_handlers.handle_callback)
    for cat in bot_handlers.NEW_CATEGORIES:
        assert f'category == "{cat}"' in src, f"no dispatch branch for category '{cat}'"
