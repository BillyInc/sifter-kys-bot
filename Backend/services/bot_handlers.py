"""Action and input dispatch for the menu-driven Telegram bot.

This is the bridge between the router (``telegram_notifier`` entry points),
the Redis state machine (``bot_state``), the data layer, and the pure render
functions (``bot_screens``). Handlers receive the live ``TelegramNotifier``
instance so they can send/edit messages and answer callback queries without a
circular import at module load time.

Three entry points, all called from the notifier's router prologue:
    handle_command(notifier, chat_id, command, message) -> bool
    handle_callback(notifier, chat_id, query, category, action, params) -> None
    handle_text_input(notifier, chat_id, text, message) -> bool

``handle_command`` / ``handle_text_input`` return True when they consume the
update, so the router can fall through to the legacy slash-command chain when
they return False (backward compatibility).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services import bot_screens, bot_state

logger = logging.getLogger(__name__)

# Closed allow-list of callback categories this menu system owns. The router
# only dispatches pipe-delimited callbacks whose first segment is in this set;
# everything else falls through to legacy handling. Keep in sync with the
# router guard in telegram_notifier._handle_callback.
NEW_CATEGORIES = frozenset({
    "nav", "set", "exec", "wal", "pos", "stat", "blk", "alert", "note", "access",
})

# Menu commands this module owns (return False from handle_command otherwise).
NEW_COMMANDS = frozenset({"/menu"})


# ── data fetch helpers ──────────────────────────────────────────────────────

def _load_user_ctx(notifier, chat_id: str) -> Optional[Dict[str, Any]]:
    """Fetch the telegram_users row + derived context for screen rendering.

    Returns None when the chat isn't linked to an account yet.
    """
    try:
        res = (
            notifier._table("telegram_users")
            .select(
                "user_id, telegram_username, auto_trade_enabled, access_tier, "
                "auto_trade_max_usd, "
                "consensus_threshold, trading_pool_pct, max_deployment_pct, "
                "tier1_pct_of_pool, tier2_pct_of_pool, tier3_pct_of_total, "
                "position_size_mode, position_size_value, "
                "stop_loss_pct, take_profit_x, trailing_stop_pct, "
                "slippage_bps, mev_protection, notif_trade_open, "
                "notif_trade_close, notif_tp_hit, notif_sl_hit, notif_signal, "
                "notif_daily_summary, notif_weekly_summary"
            )
            .eq("telegram_chat_id", chat_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("[BOT_HANDLERS] user ctx load failed for %s: %s", chat_id, exc)
        return None

    if not res.data:
        return None

    row = dict(res.data[0])
    user_id = row.get("user_id")

    has_wallet = False
    if user_id:
        try:
            w = notifier._table("bot_wallets").select("id").eq("user_id", user_id).limit(1).execute()
            has_wallet = bool(w.data)
        except Exception:
            has_wallet = False

    row["connected"] = True
    row["has_wallet"] = has_wallet
    row["username"] = row.get("telegram_username")
    row["is_operator"] = notifier._is_operator(chat_id)
    return row


# ── entry points ────────────────────────────────────────────────────────────

def handle_command(notifier, chat_id: str, command: str, message: dict) -> bool:
    """Handle a NEW menu command. Returns False to fall through to legacy."""
    cmd = command.split()[0].lower() if command else ""
    if cmd not in NEW_COMMANDS:
        return False

    if cmd == "/menu":
        _open_main(notifier, chat_id)
        return True
    return False


def handle_text_input(notifier, chat_id: str, text: str, message: dict) -> bool:
    """Consume plain text iff the user is in an awaited-input mode.

    Returns False when nothing is awaited so the router falls through to the
    legacy slash-command chain. Slash commands always pre-empt awaited input
    (so /cancel etc. still work mid-flow)."""
    awaiting = bot_state.get_state(chat_id).get("awaiting")
    if not awaiting:
        return False

    # Let slash commands break out of any awaited-input flow.
    if text.startswith("/"):
        if text.lower() in ("/cancel", "/menu", "/start"):
            bot_state.clear_state(chat_id)
            if text.lower() == "/menu":
                _open_main(notifier, chat_id)
            elif text.lower() == "/cancel":
                notifier.send_message(chat_id, "❌ Cancelled.")
            return text.lower() != "/start"  # let /start fall through to legacy linking
        # Other slash commands abort the awaited flow and fall through.
        bot_state.set_awaiting(chat_id, None)
        return False

    # Dispatch by awaited-input kind.
    if awaiting == "wallet_private_key":
        # Clear first so a failure can't leave the user stuck mid-import, then
        # hand off to the existing (security-hardened) key handler, which
        # deletes the message and encrypts the key at rest.
        bot_state.set_awaiting(chat_id, None)
        notifier._handle_wallet_key_message(chat_id, text, message)
        return True

    if awaiting == "consensus_value":
        bot_state.set_awaiting(chat_id, None)
        _save_consensus_from_text(notifier, chat_id, text)
        return True

    if awaiting == "blacklist_token":
        bot_state.set_awaiting(chat_id, None)
        _add_blacklist_from_text(notifier, chat_id, text)
        return True

    if awaiting in {"custom_sl", "custom_tp", "custom_trailing", "custom_slippage"}:
        bot_state.set_awaiting(chat_id, None)
        _save_custom_setting_from_text(notifier, chat_id, awaiting, text)
        return True

    if awaiting == "access_code":
        bot_state.set_awaiting(chat_id, None)
        _redeem_access_code(notifier, chat_id, text)
        return True

    if awaiting in {"token_stats_ca", "manual_trade_ca"}:
        bot_state.set_awaiting(chat_id, None)
        _show_token_details(notifier, chat_id, text, manual=(awaiting == "manual_trade_ca"))
        return True

    # Unknown awaited state — clear safely and nudge back to the menu.
    logger.info("[BOT_HANDLERS] unhandled awaited input '%s' for %s", awaiting, chat_id)
    bot_state.set_awaiting(chat_id, None)
    notifier.send_message(chat_id, "Use the buttons below 👇")
    _open_main(notifier, chat_id)
    return True


def handle_callback(
    notifier,
    chat_id: str,
    query: dict,
    category: str,
    action: str,
    params: List[str],
) -> None:
    """Dispatch a pipe-delimited callback (already split by the router)."""
    query_id = query.get("id")

    try:
        if category == "nav":
            _answer(notifier, query_id)
            _navigate(notifier, chat_id, action, query)
            return
        if category == "set":
            _answer(notifier, query_id)
            _handle_set(notifier, chat_id, action, params)
            return
        if category == "blk":
            _answer(notifier, query_id)
            _handle_blacklist_action(notifier, chat_id, action, params)
            return
        if category == "pos":
            _answer(notifier, query_id, text="Processing...")
            _handle_position_action(notifier, chat_id, action, params)
            return
        if category == "wal":
            _answer(notifier, query_id)
            _handle_wallet_action(notifier, chat_id, action, params)
            return
        if category == "exec":
            _answer(notifier, query_id)
            _handle_exec_action(notifier, chat_id, action, params)
            return

        # Remaining categories (exec/pos/stat/alert/note/access) land in later
        # sprints. Acknowledge so the client stops spinning, then nudge.
        _answer(notifier, query_id)
        logger.info("[BOT_HANDLERS] unhandled callback %s|%s for %s", category, action, chat_id)
        _send_rendered(notifier, chat_id, bot_screens.render_error("That action isn't available yet."))
    except Exception as exc:
        logger.error("[BOT_HANDLERS] callback error %s|%s: %s", category, action, exc)
        _answer(notifier, query_id, text="Something went wrong.")
        _send_rendered(notifier, chat_id, bot_screens.render_error())


# ── navigation ──────────────────────────────────────────────────────────────

def _navigate(notifier, chat_id: str, screen: str, query: dict) -> None:
    if screen == "main":
        _open_main(notifier, chat_id)
    elif screen == "settings":
        _open_settings(notifier, chat_id)
    elif screen == "welcome":
        _open_welcome(notifier, chat_id)
    elif screen == "help":
        bot_state.push_screen(chat_id, "help")
        _send_rendered(notifier, chat_id, bot_screens.render_help())
    elif screen == "register":
        bot_state.push_screen(chat_id, "register")
        _send_rendered(notifier, chat_id, bot_screens.render_register_prompt(_public_ctx()))
    elif screen == "autotrade":
        _open_autotrade(notifier, chat_id)
    elif screen == "consensus":
        _open_consensus(notifier, chat_id)
    elif screen == "blacklist":
        _open_blacklist(notifier, chat_id)
    elif screen == "strategy":
        _open_strategy(notifier, chat_id)
    elif screen == "sizing":
        _open_sizing(notifier, chat_id)
    elif screen == "notifications":
        _open_notifications(notifier, chat_id)
    elif screen == "positions":
        _open_positions(notifier, chat_id)
    elif screen == "close_modify":
        _open_positions(notifier, chat_id)
    elif screen == "elite15":
        _open_elite15(notifier, chat_id)
    elif screen == "operator":
        _open_operator(notifier, chat_id)
    elif screen == "account":
        _open_account(notifier, chat_id)
    elif screen == "access":
        bot_state.set_awaiting(chat_id, "access_code")
        _send_rendered(notifier, chat_id, bot_screens.render_access_code_prompt())
    elif screen == "request_access":
        _send_rendered(notifier, chat_id, bot_screens.render_request_access(_public_ctx()))
    elif screen == "token_stats":
        bot_state.set_awaiting(chat_id, "token_stats_ca")
        _send_rendered(notifier, chat_id, bot_screens.render_token_stats_prompt())
    elif screen == "wallets":
        _open_wallets(notifier, chat_id)
    elif screen == "manual_trade":
        bot_state.set_awaiting(chat_id, "manual_trade_ca")
        _send_rendered(notifier, chat_id, bot_screens.render_manual_trade_entry())
    else:
        # Known nav target without a screen yet (lands in a later sprint).
        bot_state.push_screen(chat_id, screen)
        _send_rendered(
            notifier, chat_id,
            bot_screens.render_error("That screen is coming soon."),
        )


def _public_ctx() -> Dict[str, Any]:
    """Context available without a linked account (dashboard URL, etc.)."""
    try:
        from config import Config
        dashboard_url = Config.DASHBOARD_URL or None
        reset_url = f"{dashboard_url.rstrip('/')}/reset-password" if dashboard_url else None
        return {"dashboard_url": dashboard_url, "reset_url": reset_url}
    except Exception:
        return {"dashboard_url": None, "reset_url": None}


def _open_welcome(notifier, chat_id: str) -> None:
    bot_state.push_screen(chat_id, "welcome")
    _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))


def _open_main(notifier, chat_id: str) -> None:
    ctx = _load_user_ctx(notifier, chat_id)
    if ctx is None:
        bot_state.clear_state(chat_id)
        _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))
        return
    bot_state.push_screen(chat_id, "main")
    _send_rendered(notifier, chat_id, bot_screens.render_main(ctx))


def _open_settings(notifier, chat_id: str) -> None:
    ctx = _load_user_ctx(notifier, chat_id)
    if ctx is None:
        _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))
        return
    bot_state.push_screen(chat_id, "settings")
    _send_rendered(notifier, chat_id, bot_screens.render_settings_home(ctx))


# ── auto-trader control (Sprint 3) ──────────────────────────────────────────

def _require_autotrader(notifier, chat_id: str) -> Optional[Dict[str, Any]]:
    """Return the user ctx if they may use auto-trader features, else None
    (after sending the appropriate gate message). Operators always pass."""
    ctx = _load_user_ctx(notifier, chat_id)
    if ctx is None:
        _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))
        return None
    if ctx.get("access_tier") != "autotrader" and not notifier._is_operator(chat_id):
        notifier.send_message(
            chat_id,
            "🔒 Auto-Trader is invite-only. Enter an access code to unlock.",
        )
        return None
    return ctx


def _update_user(notifier, user_id: str, fields: Dict[str, Any]) -> None:
    try:
        notifier._table("telegram_users").update(fields).eq("user_id", user_id).execute()
    except Exception as exc:
        logger.error("[BOT_HANDLERS] telegram_users update failed: %s", exc)


def _load_blacklist(notifier, user_id: str) -> List[Dict[str, Any]]:
    try:
        res = (
            notifier._table("bot_token_blacklist")
            .select("token_address, token_symbol, reason, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[BOT_HANDLERS] load blacklist failed: %s", exc)
        return []


def _open_autotrade(notifier, chat_id: str) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    ctx["blacklist_count"] = len(_load_blacklist(notifier, ctx["user_id"]))
    bot_state.push_screen(chat_id, "autotrade")
    _send_rendered(notifier, chat_id, bot_screens.render_autotrade_home(ctx))


def _open_consensus(notifier, chat_id: str) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    bot_state.push_screen(chat_id, "consensus")
    _send_rendered(notifier, chat_id, bot_screens.render_consensus_picker(ctx))


def _open_blacklist(notifier, chat_id: str) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    entries = _load_blacklist(notifier, ctx["user_id"])
    bot_state.push_screen(chat_id, "blacklist")
    _send_rendered(notifier, chat_id, bot_screens.render_blacklist({"blacklist": entries}))


def _open_strategy(notifier, chat_id: str) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    bot_state.push_screen(chat_id, "strategy")
    _send_rendered(notifier, chat_id, bot_screens.render_strategy_settings(ctx))


def _open_sizing(notifier, chat_id: str) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    bot_state.push_screen(chat_id, "sizing")
    _send_rendered(notifier, chat_id, bot_screens.render_sizing_settings(ctx))


def _open_notifications(notifier, chat_id: str) -> None:
    ctx = _load_user_ctx(notifier, chat_id)
    if ctx is None:
        _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))
        return
    bot_state.push_screen(chat_id, "notifications")
    _send_rendered(notifier, chat_id, bot_screens.render_notification_settings(ctx))


def _open_positions(notifier, chat_id: str) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    positions = _load_positions(notifier, ctx["user_id"], status="open")
    bot_state.push_screen(chat_id, "positions")
    _send_rendered(notifier, chat_id, bot_screens.render_positions({"positions": positions}))


def _open_account(notifier, chat_id: str) -> None:
    ctx = _load_user_ctx(notifier, chat_id)
    if ctx is None:
        _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))
        return
    bot_state.push_screen(chat_id, "account")
    _send_rendered(notifier, chat_id, bot_screens.render_account({**ctx, **_public_ctx()}))


def _open_wallets(notifier, chat_id: str) -> None:
    ctx = _load_user_ctx(notifier, chat_id)
    if ctx is None:
        _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))
        return
    wallets = _load_bot_wallets(notifier, ctx["user_id"])
    tracked = _load_tracked_wallets(notifier, ctx["user_id"])
    bot_state.push_screen(chat_id, "wallets")
    _send_rendered(notifier, chat_id, bot_screens.render_wallets({"bot_wallets": wallets, "tracked_wallets": tracked}))


def _open_elite15(notifier, chat_id: str) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    wallets = _load_tracked_wallets(notifier, ctx["user_id"])
    elite = [w for w in wallets if str(w.get("tier") or "").upper() in ("S", "A")][:15]
    bot_state.push_screen(chat_id, "elite15")
    _send_rendered(notifier, chat_id, bot_screens.render_elite15({"wallets": elite}))


def _open_operator(notifier, chat_id: str) -> None:
    if not notifier._is_operator(chat_id):
        notifier.send_message(chat_id, "Operator access required.")
        return
    bot_state.push_screen(chat_id, "operator")
    _send_rendered(notifier, chat_id, bot_screens.render_operator_panel())


def _handle_set(notifier, chat_id: str, action: str, params: List[str]) -> None:
    """Dispatch set|<action>|<params> (auto-trade toggle, consensus)."""
    if action == "autotrade":
        ctx = _require_autotrader(notifier, chat_id)
        if ctx is None:
            return
        on = bool(params) and params[0].lower() == "on"
        _update_user(notifier, ctx["user_id"], {"auto_trade_enabled": on})
        _open_autotrade(notifier, chat_id)
        return

    if action == "consensus":
        ctx = _require_autotrader(notifier, chat_id)
        if ctx is None:
            return
        val = params[0] if params else ""
        if val == "custom":
            bot_state.set_awaiting(chat_id, "consensus_value")
            notifier.send_message(chat_id, "Enter a consensus threshold (0–15):")
            return
        try:
            n = int(val)
        except ValueError:
            _open_consensus(notifier, chat_id)
            return
        if not (0 <= n <= 15):
            notifier.send_message(chat_id, "⚠️ Consensus must be between 0 and 15.")
            return
        _update_user(notifier, ctx["user_id"], {"consensus_threshold": n})
        _open_consensus(notifier, chat_id)
        return

    if action in {"sl", "tp", "trailing", "slippage", "mev", "notif", "sizing"}:
        _handle_setting_action(notifier, chat_id, action, params)
        return

    logger.info("[BOT_HANDLERS] unhandled set action '%s' for %s", action, chat_id)


def _handle_setting_action(notifier, chat_id: str, action: str, params: List[str]) -> None:
    ctx = _require_autotrader(notifier, chat_id) if action != "notif" else _load_user_ctx(notifier, chat_id)
    if ctx is None:
        _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))
        return
    val = params[0] if params else ""

    if val == "custom":
        awaiting_map = {
            "sl": "custom_sl",
            "tp": "custom_tp",
            "trailing": "custom_trailing",
            "slippage": "custom_slippage",
        }
        awaiting = awaiting_map.get(action)
        if awaiting:
            bot_state.set_awaiting(chat_id, awaiting)
            notifier.send_message(chat_id, "Send the custom value as a number, or /cancel.")
        return

    fields: Dict[str, Any] = {}
    try:
        if action == "sl":
            n = int(val)
            if n > 0:
                n = -n
            if not (-95 <= n <= -1):
                raise ValueError
            fields = {"stop_loss_pct": n}
        elif action == "tp":
            n = float(val)
            if not (1 <= n <= 100):
                raise ValueError
            fields = {"take_profit_x": n}
        elif action == "trailing":
            fields = {"trailing_stop_pct": None if val == "off" else float(val)}
        elif action == "slippage":
            pct = float(val)
            if not (0.1 <= pct <= 50):
                raise ValueError
            fields = {"slippage_bps": int(pct * 100)}
        elif action == "mev":
            fields = {"mev_protection": val == "on"}
        elif action == "notif":
            name = params[0] if params else ""
            on = (params[1] if len(params) > 1 else "").lower() == "on"
            allowed = {
                "open": "notif_trade_open",
                "close": "notif_trade_close",
                "tp": "notif_tp_hit",
                "sl": "notif_sl_hit",
                "signal": "notif_signal",
                "daily": "notif_daily_summary",
                "weekly": "notif_weekly_summary",
            }
            if name not in allowed:
                raise ValueError
            fields = {allowed[name]: on}
        elif action == "sizing":
            tier = params[0] if params else ""
            pct = float(params[1]) if len(params) > 1 else float(val)
            columns = {"t1": "tier1_pct_of_pool", "t2": "tier2_pct_of_pool", "t3": "tier3_pct_of_total"}
            if tier not in columns or not (1 <= pct <= 100):
                raise ValueError
            fields = {columns[tier]: pct}
    except (TypeError, ValueError):
        notifier.send_message(chat_id, "Invalid value. Please choose one of the buttons or send /cancel.")
        return

    _update_user(notifier, ctx["user_id"], fields)
    if action == "notif":
        _open_notifications(notifier, chat_id)
    elif action == "sizing":
        _open_sizing(notifier, chat_id)
    else:
        _open_strategy(notifier, chat_id)


def _handle_blacklist_action(notifier, chat_id: str, action: str, params: List[str]) -> None:
    """Dispatch blk|<action>|<params> (add / delete)."""
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return

    if action == "add":
        bot_state.set_awaiting(chat_id, "blacklist_token")
        _send_rendered(notifier, chat_id, bot_screens.render_blacklist_add_prompt())
        return

    if action == "del":
        token = params[0] if params else ""
        if token:
            try:
                notifier._table("bot_token_blacklist").delete().eq(
                    "user_id", ctx["user_id"]
                ).eq("token_address", token).execute()
            except Exception as exc:
                logger.error("[BOT_HANDLERS] blacklist delete failed: %s", exc)
        _open_blacklist(notifier, chat_id)
        return

    logger.info("[BOT_HANDLERS] unhandled blk action '%s' for %s", action, chat_id)


def _handle_position_action(notifier, chat_id: str, action: str, params: List[str]) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    try:
        position_id = int(params[0])
    except (IndexError, TypeError, ValueError):
        _send_rendered(notifier, chat_id, bot_screens.render_error("Invalid position request."))
        return

    if action in {"sl", "tp"}:
        try:
            raw_value = params[1]
            if action == "sl":
                value = int(raw_value)
                if value > 0:
                    value = -value
                if not (-95 <= value <= -1):
                    raise ValueError
                fields = {"stop_loss_pct": value}
            else:
                value = float(raw_value)
                if not (1 <= value <= 100):
                    raise ValueError
                fields = {"take_profit_x": value}
        except (IndexError, TypeError, ValueError):
            _send_rendered(notifier, chat_id, bot_screens.render_error("Invalid modifier value."))
            return
        pos = _load_position_by_id(notifier, ctx["user_id"], position_id)
        if not pos:
            notifier.send_message(chat_id, "That position is already closed or no longer available.")
            _open_positions(notifier, chat_id)
            return
        try:
            notifier._table("bot_live_positions").update(fields).eq("id", position_id).eq(
                "user_id", ctx["user_id"]
            ).eq("status", "open").execute()
            notifier.send_message(chat_id, "Position updated.")
        except Exception as exc:
            logger.error("[BOT_HANDLERS] position modifier failed: %s", exc)
            notifier.send_message(chat_id, "Could not update that position.")
        _open_positions(notifier, chat_id)
        return

    if action == "archive":
        pos = _load_position_by_id(notifier, ctx["user_id"], position_id)
        if not pos:
            notifier.send_message(chat_id, "That position is already closed or archived.")
            _open_positions(notifier, chat_id)
            return
        try:
            notifier._table("bot_live_positions").update({
                "status": "archived",
                "take_profit_x": None,
                "last_checked_at": None,
            }).eq("id", position_id).eq("user_id", ctx["user_id"]).eq("status", "open").execute()
            notifier.send_message(chat_id, "Position archived. TP monitoring is removed; it will not appear in Active Trades.")
        except Exception as exc:
            logger.error("[BOT_HANDLERS] archive failed: %s", exc)
            notifier.send_message(chat_id, "Could not archive that position.")
        _open_positions(notifier, chat_id)
        return

    if action == "runrest":
        pos = _load_position_by_id(notifier, ctx["user_id"], position_id)
        if not pos:
            notifier.send_message(chat_id, "That position is already closed or archived.")
            _open_positions(notifier, chat_id)
            return
        if not _acquire_action_lock(chat_id, f"runrest:{position_id}"):
            notifier.send_message(chat_id, "That request is already being processed.")
            return
        notifier.send_message(chat_id, "Selling 50% and archiving the remainder...")
        try:
            from services.bot_execution import BotTradeRequest, get_bot_executor

            result = get_bot_executor().execute(BotTradeRequest(
                user_id=ctx["user_id"],
                token_address=pos["token_address"],
                token_symbol=pos.get("token_symbol"),
                side="sell",
                requested_usd=float(pos.get("current_value_usd") or pos.get("total_invested_usd") or 0) * 0.5,
                sell_pct=50,
                trigger_type="manual_run_rest",
                signal_key=pos.get("signal_key"),
                snapshot={"price": float(pos.get("avg_entry_price") or 1.0)},
                settings=ctx,
            ))
            if result.status != "filled":
                notifier.send_message(chat_id, f"Sell did not execute: {result.reason or result.message}")
                _open_positions(notifier, chat_id)
                return
            notifier._table("bot_live_positions").update({
                "status": "archived",
                "take_profit_x": None,
                "last_checked_at": None,
            }).eq("id", position_id).eq("user_id", ctx["user_id"]).execute()
            notifier.send_message(chat_id, "Sold 50%. Remaining position archived with TP removed.")
        except Exception as exc:
            logger.error("[BOT_HANDLERS] run-rest failed: %s", exc)
            notifier.send_message(chat_id, "Could not complete take-50%-and-run. No archive was applied after failure.")
        _open_positions(notifier, chat_id)
        return

    if action != "close":
        _send_rendered(notifier, chat_id, bot_screens.render_error("That position action is not available yet."))
        return
    try:
        pct = int(params[1])
        if not (1 <= pct <= 100):
            raise ValueError
    except (IndexError, TypeError, ValueError):
        _send_rendered(notifier, chat_id, bot_screens.render_error("Invalid close request."))
        return

    if not _acquire_action_lock(chat_id, f"close:{position_id}:{pct}"):
        notifier.send_message(chat_id, "That close request is already being processed.")
        return

    pos = _load_position_by_id(notifier, ctx["user_id"], position_id)
    if not pos:
        notifier.send_message(chat_id, "That position is already closed or no longer available.")
        _open_positions(notifier, chat_id)
        return

    notifier.send_message(chat_id, f"Closing {pct}% of ${pos.get('token_symbol') or pos.get('token_address', '')[:8]}...")
    try:
        from services.bot_execution import BotTradeRequest, get_bot_executor

        result = get_bot_executor().execute(BotTradeRequest(
            user_id=ctx["user_id"],
            token_address=pos["token_address"],
            token_symbol=pos.get("token_symbol"),
            side="sell",
            requested_usd=float(pos.get("current_value_usd") or pos.get("total_invested_usd") or 0) * (pct / 100.0),
            sell_pct=pct,
            trigger_type="manual_close",
            signal_key=pos.get("signal_key"),
            snapshot={"price": float(pos.get("avg_entry_price") or 1.0)},
            settings=ctx,
        ))
        if result.status == "filled":
            notifier.send_message(chat_id, f"Close order recorded: {pct}% sold. Tx: <code>{result.txid}</code>")
        else:
            notifier.send_message(chat_id, f"Close did not execute: {result.reason or result.message}")
    except Exception as exc:
        logger.error("[BOT_HANDLERS] close failed: %s", exc)
        notifier.send_message(chat_id, "Close failed. The position was not modified.")
    _open_positions(notifier, chat_id)


def _handle_wallet_action(notifier, chat_id: str, action: str, params: List[str]) -> None:
    if action == "import":
        bot_state.set_awaiting(chat_id, "wallet_private_key")
        notifier.send_message(
            chat_id,
            "Send the private key for the trading wallet. The message will be deleted and the key encrypted at rest. Send /cancel to stop.",
        )
        return
    _send_rendered(notifier, chat_id, bot_screens.render_error("That wallet action is not available yet."))


def _handle_exec_action(notifier, chat_id: str, action: str, params: List[str]) -> None:
    if action == "manual_ca":
        bot_state.set_awaiting(chat_id, "manual_trade_ca")
        notifier.send_message(chat_id, "Paste the token contract address for the manual trade preview, or /cancel.")
        return
    if action == "manual_signal":
        notifier.send_message(chat_id, "Recent Elite signal picker is coming next. Paste a CA for now.")
        bot_state.set_awaiting(chat_id, "manual_trade_ca")
        return
    if action == "manual_confirm":
        _execute_manual_trade(notifier, chat_id)
        return
    _send_rendered(notifier, chat_id, bot_screens.render_error("That trade action is not available yet."))


def _redeem_access_code(notifier, chat_id: str, text: str) -> None:
    ctx = _load_user_ctx(notifier, chat_id)
    if ctx is None:
        _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))
        return
    code = text.strip().upper()
    if not code:
        bot_state.set_awaiting(chat_id, "access_code")
        notifier.send_message(chat_id, "Send your access code, or /cancel.")
        return
    try:
        res = (
            notifier._table("access_codes")
            .select("*")
            .eq("code", code)
            .limit(1)
            .execute()
        )
        row = res.data[0] if res.data else None
        if not row or int(row.get("used_count") or 0) >= int(row.get("max_uses") or 1):
            notifier.send_message(chat_id, "That access code is invalid or already used.")
            return
        tier = row.get("tier") or "autotrader"
        _update_user(notifier, ctx["user_id"], {"access_tier": tier})
        notifier._table("access_codes").update({
            "used_count": int(row.get("used_count") or 0) + 1,
            "used_by": ctx["user_id"],
        }).eq("id", row["id"]).execute()
        notifier.send_message(chat_id, "Access unlocked. Your autonomous bot controls are now available.")
        _open_main(notifier, chat_id)
    except Exception as exc:
        logger.error("[BOT_HANDLERS] access redeem failed: %s", exc)
        notifier.send_message(chat_id, "Could not redeem that code right now. Please try again.")


def _show_token_details(notifier, chat_id: str, text: str, *, manual: bool = False) -> None:
    token = text.strip()
    if not (32 <= len(token) <= 60):
        bot_state.set_awaiting(chat_id, "manual_trade_ca" if manual else "token_stats_ca")
        notifier.send_message(chat_id, "That does not look like a Solana contract address. Paste the CA, or /cancel.")
        return
    if manual:
        bot_state.push_screen(chat_id, "manual_preview", data={"token_address": token})
    _send_rendered(notifier, chat_id, bot_screens.render_token_details({
        "token_address": token,
        "manual": manual,
    }))


def _execute_manual_trade(notifier, chat_id: str) -> None:
    ctx = _load_user_ctx(notifier, chat_id)
    if ctx is None:
        _send_rendered(notifier, chat_id, bot_screens.render_welcome(_public_ctx()))
        return
    token = (bot_state.get_state(chat_id).get("data") or {}).get("token_address")
    if not token:
        bot_state.set_awaiting(chat_id, "manual_trade_ca")
        notifier.send_message(chat_id, "Paste the token contract address again, or /cancel.")
        return
    if not _acquire_action_lock(chat_id, f"manual_buy:{token}"):
        notifier.send_message(chat_id, "That manual trade is already being processed.")
        return
    amount = float(ctx.get("auto_trade_max_usd") or ctx.get("position_size_value") or 100)
    notifier.send_message(chat_id, f"Executing manual trade for <code>{token}</code>...")
    try:
        from services.bot_execution import BotTradeRequest, get_bot_executor

        result = get_bot_executor().execute(BotTradeRequest(
            user_id=ctx["user_id"],
            token_address=token,
            side="buy",
            requested_usd=amount,
            signal_type="manual",
            trigger_type="manual",
            snapshot={"price": 1.0},
            settings=ctx,
        ))
        if result.status == "filled":
            notifier.send_message(chat_id, f"Manual trade recorded. Tx: <code>{result.txid}</code>")
            _open_positions(notifier, chat_id)
        else:
            notifier.send_message(chat_id, f"Manual trade did not execute: {result.reason or result.message}")
    except Exception as exc:
        logger.error("[BOT_HANDLERS] manual trade failed: %s", exc)
        notifier.send_message(chat_id, "Manual trade failed. No position was opened.")


def _acquire_action_lock(chat_id: str, key: str, ttl_seconds: int = 120) -> bool:
    """Best-effort per-chat idempotency lock for spend/close actions."""
    try:
        from services.redis_pool import get_redis_client

        lock_key = f"sifter:bot_action:{chat_id}:{key}"
        return bool(get_redis_client().set(lock_key, "1", nx=True, ex=ttl_seconds))
    except Exception:
        # If Redis is unavailable, continue with DB/state guards instead of
        # making the UI unusable in safe_noop/paper environments.
        return True


def _save_consensus_from_text(notifier, chat_id: str, text: str) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    try:
        n = int(text.strip())
        if not (0 <= n <= 15):
            raise ValueError
    except ValueError:
        notifier.send_message(chat_id, "⚠️ Please enter a whole number from 0 to 15.")
        bot_state.set_awaiting(chat_id, "consensus_value")
        return
    _update_user(notifier, ctx["user_id"], {"consensus_threshold": n})
    _open_consensus(notifier, chat_id)


def _add_blacklist_from_text(notifier, chat_id: str, text: str) -> None:
    ctx = _require_autotrader(notifier, chat_id)
    if ctx is None:
        return
    token = text.strip().lstrip("$")
    # Solana addresses are base58, ~32-44 chars. Reject obvious non-addresses
    # (ticker resolution can be added later).
    if not token or not (32 <= len(token) <= 44):
        notifier.send_message(
            chat_id,
            "⚠️ That doesn't look like a contract address. Send the token CA, or /cancel.",
        )
        bot_state.set_awaiting(chat_id, "blacklist_token")
        return
    try:
        notifier._table("bot_token_blacklist").upsert(
            {"user_id": ctx["user_id"], "token_address": token, "reason": "manual"},
            on_conflict="user_id,token_address",
        ).execute()
    except Exception as exc:
        logger.error("[BOT_HANDLERS] blacklist add failed: %s", exc)
        notifier.send_message(chat_id, "⚠️ Could not add to blacklist.")
        return
    _open_blacklist(notifier, chat_id)


def _save_custom_setting_from_text(notifier, chat_id: str, awaiting: str, text: str) -> None:
    action_map = {
        "custom_sl": "sl",
        "custom_tp": "tp",
        "custom_trailing": "trailing",
        "custom_slippage": "slippage",
    }
    _handle_setting_action(notifier, chat_id, action_map[awaiting], [text.strip()])


def _load_positions(notifier, user_id: str, status: str = "open") -> List[Dict[str, Any]]:
    try:
        res = (
            notifier._table("bot_live_positions")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", status)
            .order("opened_at", desc=True)
            .limit(20)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[BOT_HANDLERS] load positions failed: %s", exc)
        return []


def _load_position_by_id(notifier, user_id: str, position_id: int) -> Optional[Dict[str, Any]]:
    try:
        res = (
            notifier._table("bot_live_positions")
            .select("*")
            .eq("user_id", user_id)
            .eq("id", position_id)
            .eq("status", "open")
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as exc:
        logger.error("[BOT_HANDLERS] load position by id failed: %s", exc)
        return None


def _load_bot_wallets(notifier, user_id: str) -> List[Dict[str, Any]]:
    try:
        res = notifier._table("bot_wallets").select("public_key, registered_at, last_trade_at").eq(
            "user_id", user_id
        ).execute()
        return res.data or []
    except Exception:
        return []


def _load_tracked_wallets(notifier, user_id: str) -> List[Dict[str, Any]]:
    try:
        res = notifier._table("wallet_watchlist").select(
            "wallet_address, tier, alert_enabled, alert_threshold_usd, notes"
        ).eq("user_id", user_id).limit(10).execute()
        return res.data or []
    except Exception:
        return []


# ── low-level send helpers ──────────────────────────────────────────────────

def _send_rendered(notifier, chat_id: str, rendered) -> None:
    text, keyboard = rendered
    notifier.send_message(chat_id, text, reply_markup=keyboard)


def _answer(notifier, query_id: Optional[str], text: Optional[str] = None) -> None:
    """Always answer a callback query so the client stops its spinner."""
    if not query_id:
        return
    payload: Dict[str, Any] = {"callback_query_id": query_id}
    if text:
        payload["text"] = text
    try:
        notifier._make_request("answerCallbackQuery", payload)
    except Exception:
        pass
