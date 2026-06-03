"""Pure render functions for the menu-driven Telegram bot.

Each function takes already-fetched data and returns a ``(text, keyboard)``
tuple. They perform NO database, Redis, or network access, which keeps every
screen trivially unit-testable and free of side effects. Handlers
(``bot_handlers.py``) fetch the data and send what these functions produce.

Keyboards use Telegram's inline-keyboard shape::

    {"inline_keyboard": [[{"text": ..., "callback_data": ...}, ...], ...]}

Callback data is pipe-delimited ``category|action|param...`` (see
``bot_handlers.NEW_CATEGORIES`` for the routed categories). Telegram limits
callback_data to 64 bytes.

Sprint 1 surface: main menu + read-only settings + not-connected/error.
Later sprints add their own render functions here.
"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Tuple

Keyboard = Dict[str, List[List[Dict[str, str]]]]
Rendered = Tuple[str, Optional[Keyboard]]


# ── keyboard helpers ────────────────────────────────────────────────────────

def nav_button(label: str, screen: str) -> Dict[str, str]:
    """A button that navigates to a top-level screen (``nav|<screen>``)."""
    return {"text": label, "callback_data": f"nav|{screen}"}


def _kb(rows: List[List[Dict[str, str]]]) -> Keyboard:
    return {"inline_keyboard": rows}


def _back_row(to: str = "main") -> List[Dict[str, str]]:
    return [nav_button("⬅️ Back", to), nav_button("🏠 Main Menu", "main")]


# ── screens ─────────────────────────────────────────────────────────────────

def render_main(ctx: Dict[str, Any]) -> Rendered:
    """Main menu. ``ctx`` keys: connected, auto_trade_enabled, access_tier,
    has_wallet, username, balance_sol."""
    username = html.escape(str(ctx.get("username") or "trader"))
    is_autotrader = ctx.get("access_tier") == "autotrader"

    balance = ctx.get("balance_sol")
    balance_str = f"{float(balance):.2f} SOL" if balance is not None else "—"

    header = [
        "🏠 <b>SIFTER BOT — Main Menu</b>",
        f"👤 @{username}  |  💰 Balance: {balance_str}",
    ]
    if is_autotrader:
        status = "🟢 ACTIVE" if ctx.get("auto_trade_enabled") else "⏸️ PAUSED"
        header.append(f"🤖 Bot Status: {status}")

    rows: List[List[Dict[str, str]]] = []

    # Monitoring
    if is_autotrader:
        rows.append([nav_button("👛 Elite 15 Wallets", "elite15"),
                     nav_button("📊 Active Trades", "positions")])
    rows.append([nav_button("📈 Token Stats", "token_stats")])

    # Trading
    if is_autotrader:
        rows.append([nav_button("🤖 Auto-Trader", "autotrade"),
                     nav_button("⚡ Manual Trade", "manual_trade")])
        rows.append([nav_button("🔒 Close / Modify Trade", "close_modify")])
    else:
        rows.append([nav_button("⚡ Manual Trade", "manual_trade")])

    # Settings
    settings_row = [nav_button("⚙️ Settings", "settings"),
                    nav_button("👛 My Wallets", "wallets")]
    rows.append(settings_row)
    rows.append([nav_button("🔔 Notifications", "notifications"),
                 nav_button("👤 My Account", "account")])

    # Access gate for basic users
    if not is_autotrader:
        rows.append([nav_button("🎟️ Enter Access Code", "access"),
                     nav_button("📩 Request Access", "request_access")])

    if ctx.get("is_operator"):
        rows.append([nav_button("🔧 Operator Panel", "operator")])

    return "\n".join(header), _kb(rows)


def render_settings_home(ctx: Dict[str, Any]) -> Rendered:
    """Read-only settings summary (Sprint 1). Editing sub-screens land in S3/S4."""
    def _pct(v: Any, default: str = "—") -> str:
        return f"{float(v):.0f}%" if v is not None else default

    consensus = ctx.get("consensus_threshold")
    sl = ctx.get("stop_loss_pct")
    tp = ctx.get("take_profit_x")
    trailing = ctx.get("trailing_stop_pct")
    slippage = ctx.get("slippage_bps")

    lines = [
        "⚙️ <b>Settings</b>",
        "",
        "🤖 <b>Auto-Trade</b>",
        f"   Consensus: {consensus if consensus is not None else '—'} wallet(s)",
        f"   Trading pool: {_pct(ctx.get('trading_pool_pct'))}",
        f"   Deployment cap: {_pct(ctx.get('max_deployment_pct'))}",
        "",
        "📊 <b>Signal Sizing</b>",
        f"   Tier 1: {_pct(ctx.get('tier1_pct_of_pool'))} of pool",
        f"   Tier 2: {_pct(ctx.get('tier2_pct_of_pool'))} of pool",
        f"   Tier 3: {_pct(ctx.get('tier3_pct_of_total'))} of total",
        "",
        "🎯 <b>Risk</b>",
        f"   Stop loss: {sl if sl is not None else '—'}%",
        f"   Take profit: {f'{float(tp):.1f}x' if tp is not None else '—'}",
        f"   Trailing stop: {_pct(trailing, 'off')}",
        "",
        "⚡ <b>Execution</b>",
        f"   Slippage: {f'{float(slippage) / 100:.1f}%' if slippage is not None else '—'}",
        f"   MEV protection: {'ON' if ctx.get('mev_protection') else 'OFF'}",
        "",
        "<i>Editing these settings is coming online — read-only for now.</i>",
    ]
    rows = [
        [nav_button("Strategy / SL / TP", "strategy")],
        [nav_button("Portfolio & Sizing", "sizing")],
        [nav_button("Notifications", "notifications")],
        [nav_button("Archived Holdings", "archived")],
        _back_row("main"),
    ]
    return "\n".join(lines), _kb(rows)


def render_welcome(ctx: Optional[Dict[str, Any]] = None) -> Rendered:
    """Entry screen shown on bare /start (no link token).

    ``ctx`` keys: dashboard_url. Login/Dashboard become URL buttons when a
    dashboard URL is configured; otherwise they fall back to in-bot guidance.
    Register-via-bot is routed to ``nav|register`` (a "use the dashboard"
    screen for now — standalone Telegram signup lands in a later sprint).
    """
    ctx = ctx or {}
    dashboard_url = ctx.get("dashboard_url")
    text = (
        "👋 <b>Welcome to SIFTER Trading Bot</b>\n\n"
        "The smart Solana copy-trading system, powered by Elite 15 wallet "
        "signals.\n\n"
        "<b>Already have an account?</b> Connect it from the dashboard.\n"
        "<b>New here?</b> Create an account on the dashboard, then link it.\n\n"
        "Once linked, send /menu anytime to open the bot."
    )
    rows: List[List[Dict[str, str]]] = []
    if dashboard_url:
        rows.append([{"text": "🔑 Login with Email", "url": dashboard_url}])
        rows.append([{"text": "🌐 Go to Dashboard", "url": dashboard_url}])
    rows.append([nav_button("📝 Register via Bot", "register")])
    rows.append([nav_button("❓ Help", "help")])
    if ctx.get("reset_url"):
        rows.append([{"text": "Reset Password", "url": ctx["reset_url"]}])
    return text, _kb(rows)


# Backwards-compatible alias: a not-yet-connected chat sees the Welcome screen.
def render_not_connected(ctx: Optional[Dict[str, Any]] = None) -> Rendered:
    """Shown when the chat isn't linked to a Sifter account yet."""
    return render_welcome(ctx)


def render_register_prompt(ctx: Optional[Dict[str, Any]] = None) -> Rendered:
    """Register-via-bot placeholder — directs to the dashboard for now.

    Standalone Telegram signup (email + password → Supabase Auth user) is a
    dedicated later sprint; this keeps the button honest in the meantime.
    """
    ctx = ctx or {}
    dashboard_url = ctx.get("dashboard_url")
    text = (
        "📝 <b>Create your account</b>\n\n"
        "Sign up on the SIFTER dashboard, then link your Telegram from there "
        "to unlock the bot. In-bot signup is coming soon."
    )
    rows: List[List[Dict[str, str]]] = []
    if dashboard_url:
        rows.append([{"text": "🌐 Open Dashboard", "url": dashboard_url}])
    rows.append([nav_button("⬅️ Back", "welcome")])
    if ctx.get("reset_url"):
        rows.append([{"text": "Reset Password", "url": ctx["reset_url"]}])
    return text, _kb(rows)


def render_help(ctx: Optional[Dict[str, Any]] = None) -> Rendered:
    """How-to / command reference for the menu-driven bot."""
    text = (
        "❓ <b>SIFTER Bot — Help</b>\n\n"
        "This bot copy-trades the <b>Elite 15</b> wallets and lets you trade "
        "manually, all from the menu below.\n\n"
        "<b>Quick commands</b>\n"
        "/menu — open the main menu\n"
        "/cancel — cancel the current step\n"
        "/start — connect or restart\n\n"
        "<b>Getting started</b>\n"
        "1. Link your account from the dashboard\n"
        "2. Import a trading wallet → 👛 My Wallets\n"
        "3. Tune your strategy → ⚙️ Settings\n\n"
        "Use the buttons — they're faster than typing."
    )
    return text, _kb([_back_row("main")])


def render_error(message: str = "Something went wrong, please try again.") -> Rendered:
    """A friendly error screen — never surfaces a raw traceback."""
    return f"⚠️ {html.escape(message)}", _kb([[nav_button("🏠 Main Menu", "main")]])


# ── Sprint 3: auto-trader control + filter stack ────────────────────────────

CONSENSUS_PRESETS = (1, 3, 5, 8, 10, 12, 15)


def render_autotrade_home(ctx: Dict[str, Any]) -> Rendered:
    """Auto-Trader control screen. ``ctx`` keys: auto_trade_enabled,
    consensus_threshold, blacklist_count."""
    enabled = bool(ctx.get("auto_trade_enabled"))
    consensus = ctx.get("consensus_threshold")
    consensus = int(consensus) if consensus is not None else 1
    blacklist_count = int(ctx.get("blacklist_count") or 0)

    status = "🟢 <b>ACTIVE</b>" if enabled else "⏸️ <b>PAUSED</b>"
    lines = [
        "🤖 <b>AUTO-TRADER</b>",
        "",
        f"Status: {status}",
        f"Consensus: copies when <b>{consensus}</b> Elite wallet(s) agree "
        "within 120s",
        "",
        "The bot enters automatically on qualifying Elite 15 signals and "
        "manages exits per your strategy. Filters: consensus + blacklist.",
    ]

    toggle = (
        {"text": "⏸️ Pause Bot", "callback_data": "set|autotrade|off"}
        if enabled else
        {"text": "▶️ Resume Bot", "callback_data": "set|autotrade|on"}
    )
    rows = [
        [toggle],
        [{"text": f"🔢 Consensus Threshold: {consensus}", "callback_data": "nav|consensus"}],
        [{"text": f"🚫 Token Blacklist ({blacklist_count})", "callback_data": "nav|blacklist"}],
        _back_row("main"),
    ]
    return "\n".join(lines), _kb(rows)


def render_consensus_picker(ctx: Dict[str, Any]) -> Rendered:
    """Consensus threshold picker. ``ctx`` keys: consensus_threshold."""
    current = ctx.get("consensus_threshold")
    current = int(current) if current is not None else 1

    text = (
        "🔢 <b>CONSENSUS THRESHOLD</b>\n\n"
        f"Current: <b>{current}</b> wallet(s)\n\n"
        "The bot copies a trade when this many of the Elite 15 buy the same "
        "token within a 120-second window.\n\n"
        "⚠️ Setting <b>0</b> trades on any single Elite wallet buy."
    )

    # Preset buttons in rows of 4, then a custom-entry button.
    preset_buttons = [
        {
            "text": (f"🔵 {n}" if n == current else str(n)),
            "callback_data": f"set|consensus|{n}",
        }
        for n in CONSENSUS_PRESETS
    ]
    rows = [preset_buttons[i:i + 4] for i in range(0, len(preset_buttons), 4)]
    rows.append([{"text": "✏️ Custom (0–15)", "callback_data": "set|consensus|custom"}])
    rows.append(_back_row("autotrade"))
    return text, _kb(rows)


def render_blacklist(ctx: Dict[str, Any]) -> Rendered:
    """Token blacklist. ``ctx`` keys: blacklist (list of
    {token_address, token_symbol, reason})."""
    entries = ctx.get("blacklist") or []
    lines = [
        "🚫 <b>TOKEN BLACKLIST</b>",
        "The bot will never trade these tokens.",
        "",
    ]
    rows: List[List[Dict[str, str]]] = []
    if not entries:
        lines.append("<i>No blacklisted tokens.</i>")
    else:
        for e in entries[:25]:
            token = e.get("token_address", "")
            symbol = html.escape(e.get("token_symbol") or (token[:8] + "…" if token else "?"))
            reason = html.escape(e.get("reason") or "manual")
            lines.append(f"🔴 <b>${symbol}</b> — <code>{token[:10]}…</code>  ({reason})")
            rows.append([{
                "text": f"🗑️ Remove ${symbol}"[:60],
                "callback_data": f"blk|del|{token}"[:64],
            }])

    rows.append([{"text": "➕ Add Token", "callback_data": "blk|add"}])
    rows.append(_back_row("autotrade"))
    return "\n".join(lines), _kb(rows)


def render_blacklist_add_prompt() -> Rendered:
    """Prompt shown while awaiting a token to blacklist."""
    text = (
        "🚫 <b>Add to Blacklist</b>\n\n"
        "Send the token's contract address (CA) to block it.\n\n"
        "Send /cancel to abort."
    )
    return text, None


def render_strategy_settings(ctx: Dict[str, Any]) -> Rendered:
    """Strategy settings persisted for autonomous bot entries."""
    sl = ctx.get("stop_loss_pct")
    tp = ctx.get("take_profit_x")
    trailing = ctx.get("trailing_stop_pct")
    slippage_bps = ctx.get("slippage_bps")
    mev = bool(ctx.get("mev_protection"))
    lines = [
        "<b>STRATEGY SETTINGS</b>",
        "",
        f"Stop loss: <b>{sl if sl is not None else -50}%</b>",
        f"Take profit: <b>{float(tp or 5):.1f}x</b>",
        f"Trailing stop: <b>{str(trailing) + '%' if trailing is not None else 'off'}</b>",
        f"Slippage: <b>{float(slippage_bps or 100) / 100:.1f}%</b>",
        f"MEV protection: <b>{'ON' if mev else 'OFF'}</b>",
        "",
        "These values are copied into each autonomous entry when the bot trades.",
    ]
    rows = [
        [
            {"text": "SL -25%", "callback_data": "set|sl|-25"},
            {"text": "SL -50%", "callback_data": "set|sl|-50"},
            {"text": "SL -75%", "callback_data": "set|sl|-75"},
        ],
        [
            {"text": "TP 3x", "callback_data": "set|tp|3"},
            {"text": "TP 5x", "callback_data": "set|tp|5"},
            {"text": "TP 10x", "callback_data": "set|tp|10"},
        ],
        [
            {"text": "Trail off", "callback_data": "set|trailing|off"},
            {"text": "Trail 20%", "callback_data": "set|trailing|20"},
            {"text": "Trail custom", "callback_data": "set|trailing|custom"},
        ],
        [
            {"text": "Slip 1%", "callback_data": "set|slippage|1"},
            {"text": "Slip 3%", "callback_data": "set|slippage|3"},
            {"text": "Slip custom", "callback_data": "set|slippage|custom"},
        ],
        [
            {"text": "MEV ON", "callback_data": "set|mev|on"},
            {"text": "MEV OFF", "callback_data": "set|mev|off"},
        ],
        [{"text": "Custom SL", "callback_data": "set|sl|custom"},
         {"text": "Custom TP", "callback_data": "set|tp|custom"}],
        _back_row("settings"),
    ]
    return "\n".join(lines), _kb(rows)


def render_sizing_settings(ctx: Dict[str, Any]) -> Rendered:
    t1 = float(ctx.get("tier1_pct_of_pool") or 30)
    t2 = float(ctx.get("tier2_pct_of_pool") or 70)
    t3 = float(ctx.get("tier3_pct_of_total") or 40)
    lines = [
        "<b>PORTFOLIO & SIGNAL SIZING</b>",
        "",
        f"Tier 1 / single wallet: <b>{t1:.0f}%</b> of pool",
        f"Tier 2 / double wallet: <b>{t2:.0f}%</b> of pool",
        f"Tier 3 / 3+ wallets: <b>{t3:.0f}%</b> of total cap",
        "",
        "The autonomous bot uses these values when a signal qualifies.",
    ]
    rows = [
        [
            {"text": "T1 10%", "callback_data": "set|sizing|t1|10"},
            {"text": "T1 30%", "callback_data": "set|sizing|t1|30"},
            {"text": "T1 50%", "callback_data": "set|sizing|t1|50"},
        ],
        [
            {"text": "T2 30%", "callback_data": "set|sizing|t2|30"},
            {"text": "T2 70%", "callback_data": "set|sizing|t2|70"},
            {"text": "T2 100%", "callback_data": "set|sizing|t2|100"},
        ],
        [
            {"text": "T3 20%", "callback_data": "set|sizing|t3|20"},
            {"text": "T3 40%", "callback_data": "set|sizing|t3|40"},
            {"text": "T3 60%", "callback_data": "set|sizing|t3|60"},
        ],
        _back_row("settings"),
    ]
    return "\n".join(lines), _kb(rows)


def render_notification_settings(ctx: Dict[str, Any]) -> Rendered:
    toggles = [
        ("signal", "Signals", bool(ctx.get("notif_signal", True))),
        ("open", "Trade open", bool(ctx.get("notif_trade_open", True))),
        ("close", "Trade close", bool(ctx.get("notif_trade_close", True))),
        ("tp", "TP hit", bool(ctx.get("notif_tp_hit", True))),
        ("sl", "SL hit", bool(ctx.get("notif_sl_hit", True))),
        ("daily", "Daily summary", bool(ctx.get("notif_daily_summary", True))),
        ("weekly", "Weekly summary", bool(ctx.get("notif_weekly_summary", False))),
    ]
    lines = ["<b>NOTIFICATIONS</b>", ""]
    rows: List[List[Dict[str, str]]] = []
    for key, label, enabled in toggles:
        state = "ON" if enabled else "OFF"
        lines.append(f"{label}: <b>{state}</b>")
        rows.append([{
            "text": f"{label}: {'turn off' if enabled else 'turn on'}",
            "callback_data": f"set|notif|{key}|{'off' if enabled else 'on'}",
        }])
    rows.append(_back_row("settings"))
    return "\n".join(lines), _kb(rows)


def _chart_keyboard(token: str) -> List[Dict[str, str]]:
    token = token or ""
    return [
        {"text": "DexScreener", "url": f"https://dexscreener.com/solana/{token}"},
        {"text": "Birdeye", "url": f"https://birdeye.so/token/{token}?chain=solana"},
    ]


def render_positions(ctx: Dict[str, Any]) -> Rendered:
    positions = ctx.get("positions") or []
    if not positions:
        return (
            "<b>ACTIVE TRADES</b>\n\nNo open positions yet. When the autonomous bot enters, they appear here.",
            _kb([_back_row("main")]),
        )

    lines = ["<b>ACTIVE TRADES</b>", f"Open positions: <b>{len(positions)}</b>", ""]
    rows: List[List[Dict[str, str]]] = []
    for pos in positions[:10]:
        token = pos.get("token_address") or ""
        symbol = html.escape(pos.get("token_symbol") or token[:8] or "UNKNOWN")
        entry = float(pos.get("avg_entry_price") or 0)
        invested = float(pos.get("total_invested_usd") or 0)
        current = float(pos.get("current_value_usd") or invested)
        pnl_pct = ((current / invested) - 1) * 100 if invested > 0 else 0
        lines.extend([
            f"<b>${symbol}</b> {pnl_pct:+.1f}%",
            f"Entry: ${entry:.8f} | At risk: ${invested:,.2f}",
            f"TP: {pos.get('take_profit_x') or '-'}x | SL: {pos.get('stop_loss_pct') or '-'}%",
            "",
        ])
        rows.append(_chart_keyboard(token))
        rows.append([
            {"text": "Close 25%", "callback_data": f"pos|close|{pos.get('id')}|25"},
            {"text": "Close 50%", "callback_data": f"pos|close|{pos.get('id')}|50"},
            {"text": "Close 100%", "callback_data": f"pos|close|{pos.get('id')}|100"},
        ])
        rows.append([
            {"text": "SL -25%", "callback_data": f"pos|sl|{pos.get('id')}|-25"},
            {"text": "SL -50%", "callback_data": f"pos|sl|{pos.get('id')}|-50"},
            {"text": "TP 5x", "callback_data": f"pos|tp|{pos.get('id')}|5"},
            {"text": "TP 10x", "callback_data": f"pos|tp|{pos.get('id')}|10"},
        ])
        rows.append([
            {"text": "Take 50% + Run", "callback_data": f"pos|runrest|{pos.get('id')}"},
            {"text": "Archive", "callback_data": f"pos|archive|{pos.get('id')}"},
        ])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_access_code_prompt() -> Rendered:
    return (
        "<b>REDEEM ACCESS CODE</b>\n\nSend your invite/access code. Send /cancel to stop.",
        _kb([_back_row("main")]),
    )


def render_request_access(ctx: Dict[str, Any]) -> Rendered:
    lines = [
        "<b>REQUEST ACCESS</b>",
        "",
        "Auto-Trader access is invite based. Use the dashboard or contact the team for an access code.",
    ]
    rows: List[List[Dict[str, str]]] = []
    if ctx.get("dashboard_url"):
        rows.append([{"text": "Open Dashboard", "url": ctx["dashboard_url"]}])
    rows.append([nav_button("Enter Access Code", "access")])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_account(ctx: Dict[str, Any]) -> Rendered:
    tier = html.escape(str(ctx.get("access_tier") or "free"))
    username = html.escape(str(ctx.get("username") or "trader"))
    lines = [
        "<b>MY ACCOUNT</b>",
        "",
        f"Telegram: <b>@{username}</b>",
        f"Access: <b>{tier}</b>",
        "",
        "Password recovery uses the same secure dashboard reset flow for bot and dashboard accounts.",
    ]
    rows: List[List[Dict[str, str]]] = []
    if ctx.get("dashboard_url"):
        rows.append([{"text": "Open Dashboard", "url": ctx["dashboard_url"]}])
    if ctx.get("reset_url"):
        rows.append([{"text": "Reset Password", "url": ctx["reset_url"]}])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_token_stats_prompt() -> Rendered:
    text = (
        "<b>TOKEN STATS</b>\n\n"
        "Paste a Solana token contract address to inspect it. Risk score, fake-volume, and MC filters are not part of the bot filter stack."
    )
    return text, _kb([_back_row("main")])


def render_token_details(ctx: Dict[str, Any]) -> Rendered:
    token = ctx.get("token_address") or ""
    manual = bool(ctx.get("manual"))
    lines = [
        "<b>TOKEN DETAILS</b>",
        "",
        f"CA: <code>{html.escape(token)}</code>",
        "",
        "Open the chart links below for live price/liquidity context.",
        "No risk score, fake-volume, or MC filter is applied by the autonomous bot.",
    ]
    rows: List[List[Dict[str, str]]] = [
        _chart_keyboard(token),
    ]
    if manual:
        rows.append([{"text": "Confirm Manual Trade", "callback_data": "exec|manual_confirm"}])
    rows.append(_back_row("manual_trade" if manual else "main"))
    return "\n".join(lines), _kb(rows)


def render_manual_trade_entry() -> Rendered:
    text = (
        "<b>MANUAL TRADE</b>\n\n"
        "Manual trades require you to choose a token and confirm before execution. "
        "The autonomous bot is separate and enters qualifying Elite 15 signals on its own."
    )
    rows = [
        [{"text": "Paste Contract Address", "callback_data": "exec|manual_ca"}],
        [{"text": "Use Recent Elite Signal", "callback_data": "exec|manual_signal"}],
        _back_row("main"),
    ]
    return text, _kb(rows)


def render_wallets(ctx: Dict[str, Any]) -> Rendered:
    bot_wallets = ctx.get("bot_wallets") or []
    tracked_wallets = ctx.get("tracked_wallets") or []
    lines = ["<b>MY WALLETS</b>", ""]
    if bot_wallets:
        lines.append("<b>Trading wallet</b>")
        for wallet in bot_wallets[:3]:
            pk = wallet.get("public_key") or ""
            lines.append(f"<code>{pk[:8]}...{pk[-6:] if len(pk) > 6 else pk}</code>")
    else:
        lines.append("No trading wallet imported yet.")
    lines.append("")
    lines.append("<b>Tracked wallets</b>")
    if tracked_wallets:
        for wallet in tracked_wallets[:10]:
            addr = wallet.get("wallet_address") or ""
            tier = wallet.get("tier") or "C"
            alerts = "alerts ON" if wallet.get("alert_enabled") else "alerts OFF"
            lines.append(f"{tier} <code>{addr[:8]}...{addr[-6:] if len(addr) > 6 else addr}</code> - {alerts}")
    else:
        lines.append("No tracked wallets yet.")
    rows = [
        [{"text": "Import Trading Wallet", "callback_data": "wal|import"}],
        _back_row("main"),
    ]
    return "\n".join(lines), _kb(rows)


def render_elite15(ctx: Dict[str, Any]) -> Rendered:
    wallets = ctx.get("wallets") or []
    lines = ["<b>ELITE 15 WALLETS</b>", ""]
    if not wallets:
        lines.append("No Elite wallets are available for this account yet.")
    else:
        for idx, wallet in enumerate(wallets[:15], start=1):
            addr = wallet.get("wallet_address") or ""
            tier = wallet.get("tier") or "S"
            alerts = "alerts ON" if wallet.get("alert_enabled") else "alerts OFF"
            lines.append(f"#{idx} {tier} <code>{addr[:8]}...{addr[-6:] if len(addr) > 6 else addr}</code> - {alerts}")
    rows = [
        [nav_button("Consensus Threshold", "consensus")],
        _back_row("main"),
    ]
    return "\n".join(lines), _kb(rows)


def render_operator_panel() -> Rendered:
    lines = [
        "<b>OPERATOR PANEL</b>",
        "",
        "Operational commands remain slash-command gated. This panel keeps them invisible to regular users.",
        "",
        "Use the dashboard for fee revenue, logs, and runtime settings until those Telegram sub-screens are fully wired.",
    ]
    rows = [
        [nav_button("Main Menu", "main")],
    ]
    return "\n".join(lines), _kb(rows)
