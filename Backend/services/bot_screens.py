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
    """Register-via-bot: email -> password -> create account in Supabase.

    Standalone Telegram signup (email + password -> Supabase Auth user)."""
    ctx = ctx or {}
    dashboard_url = ctx.get("dashboard_url")
    step = ctx.get("reg_step", "start")
    error = ctx.get("reg_error")

    if step == "start":
        text = (
            "\U0001f4dd <b>Create your account</b>\n\n"
            "Sign up right here in Telegram! You'll need:\n"
            "• An email address\n"
            "• A password (min 8 characters)\n\n"
            "Or sign up on the dashboard instead."
        )
        rows: List[List[Dict[str, str]]] = [
            [{"text": "\U0001f4e7 Sign Up with Email", "callback_data": "access|register_email"}],
        ]
        if dashboard_url:
            rows.append([{"text": "\U0001f310 Open Dashboard", "url": dashboard_url}])
        if ctx.get("reset_url"):
            rows.append([{"text": "\U0001f511 Reset Password", "url": ctx["reset_url"]}])
        rows.append([nav_button("⬅️ Back", "welcome")])
    elif step == "enter_email":
        text = (
            "\U0001f4e7 <b>Enter your email address</b>\n\n"
            "Reply with your email to continue.\n"
            "Type /cancel to go back."
        )
        if error:
            text += f"\n\n⚠️ <b>{html.escape(error)}</b>"
        rows = [[_back_row("welcome")]]
    elif step == "enter_password":
        email = html.escape(str(ctx.get("reg_email") or ""))
        text = (
            f"\U0001f511 <b>Create your password</b>\n\n"
            f"Email: <b>{email}</b>\n\n"
            "Reply with a password (min 8 characters).\n"
            "Type /cancel to go back."
        )
        if error:
            text += f"\n\n⚠️ <b>{html.escape(error)}</b>"
        rows = [[_back_row("welcome")]]
    elif step == "success":
        text = (
            "✅ <b>Account created!</b>\n\n"
            "You're all set. A welcome email has been sent.\n\n"
            "Use <b>/menu</b> to get started."
        )
        rows = [[nav_button("\U0001f3e0 Main Menu", "main")]]
    else:
        text = "Something went wrong. Use /menu to start over."
        rows = [[nav_button("\U0001f3e0 Main Menu", "main")]]
    return text, _kb(rows)


def render_forgot_password_prompt(ctx: Optional[Dict[str, Any]] = None) -> Rendered:
    """Prompt for email to send a password-reset link."""
    ctx = ctx or {}
    step = ctx.get("pwd_step", "enter_email")
    error = ctx.get("pwd_error", "")
    text: str
    rows: List[List[Dict[str, str]]] = []

    if step == "enter_email":
        text = (
            "\U0001f511 <b>Reset your password</b>\n\n"
            "Reply with the email address linked to your account.\n"
            "We'll send a reset link.\n\n"
            "Type /cancel to go back."
        )
        if error:
            text += f"\n\n⚠️ <b>{html.escape(error)}</b>"
        rows = [[_back_row("account")]]
    elif step == "sent":
        text = (
            "\U0001f4e7 <b>Reset email sent</b>\n\n"
            "If that email is registered, you'll receive a link to reset your password.\n"
            "The link expires in <b>1 hour</b>.\n\n"
            "Check your inbox (and spam folder)."
        )
        rows = [[nav_button("\U0001f3e0 Main Menu", "main")]]
    elif step == "error":
        text = f"⚠️ <b>{html.escape(error)}</b>" if error else "Something went wrong. Please try again."
        rows = [[_back_row("account")]]
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
    """Full Auto-Trader dashboard with status, portfolio, sizing, and quick links."""
    enabled = bool(ctx.get("auto_trade_enabled"))
    consensus = ctx.get("consensus_threshold")
    consensus = int(consensus) if consensus is not None else 1
    blacklist_count = int(ctx.get("blacklist_count") or 0)

    # Portfolio breakdown
    total_wallet = float(ctx.get("total_wallet_sol") or 0)
    pool_pct = float(ctx.get("trading_pool_pct") or 50)
    pool_sol = round(total_wallet * pool_pct / 100, 2)
    deployed_pct = float(ctx.get("deployed_pct") or 0)
    deployed_sol = round(pool_sol * deployed_pct / 100, 2)
    available_sol = round(pool_sol - deployed_sol, 2)
    max_deploy = float(ctx.get("max_deployment_pct") or 80)

    open_count = int(ctx.get("open_positions") or 0)
    today_pnl = ctx.get("today_pnl")
    today_pnl_str = f"${float(today_pnl):+,.2f}" if today_pnl is not None else "—"

    # Tier sizing preview
    t1 = float(ctx.get("tier1_pct_of_pool") or 30)
    t2 = float(ctx.get("tier2_pct_of_pool") or 70)
    t3 = float(ctx.get("tier3_pct_of_total") or 40)
    t1_sol = round(pool_sol * t1 / 100, 2)
    t2_sol = round(pool_sol * t2 / 100, 2)
    t3_sol = round(total_wallet * t3 / 100, 2)

    # Rate limits
    hr_used = int(ctx.get("hourly_trades_used") or 0)
    hr_max = int(ctx.get("hourly_trade_limit") or 0)
    dy_used = int(ctx.get("daily_trades_used") or 0)
    dy_max = int(ctx.get("daily_trade_limit") or 0)

    if enabled:
        if deployed_pct >= max_deploy:
            status_line = "🔶 <b>DEPLOYMENT LIMIT</b>"
        else:
            status_line = "🟢 <b>ACTIVE</b>"
    else:
        status_line = "⏸️ <b>PAUSED</b>"

    lines = [
        "🤖 <b>AUTO-TRADER DASHBOARD</b>",
        "",
        f"Status: {status_line}",
        f"Today PnL: {today_pnl_str}",
        f"Open positions: {open_count}",
        "",
        "💼 <b>Portfolio</b>",
        f"Total wallet: {total_wallet:.1f} SOL",
        f"Trading pool ({pool_pct}%): {pool_sol} SOL",
        f"Deployed: {deployed_sol} SOL ({deployed_pct:.0f}%)",
        f"Available: {available_sol} SOL",
        f"Pause at: {max_deploy:.0f}% deployed",
        "",
        "💰 <b>Signal Sizing</b>",
        f"Tier 1 (1 wallet): {t1:.0f}% pool = {t1_sol} SOL",
        f"Tier 2 (2 wallets): {t2:.0f}% pool = {t2_sol} SOL",
        f"Tier 3 (3+ wallets): {t3:.0f}% total = {t3_sol} SOL",
        "",
        f"⏱ Limits: hourly {hr_used}/{hr_max if hr_max else 'no limit'}, daily {dy_used}/{dy_max if dy_max else 'no limit'}",
    ]

    toggle = (
        {"text": "⏸️ Pause Bot", "callback_data": "set|autotrade|off"}
        if enabled else
        {"text": "▶️ Resume Bot", "callback_data": "set|autotrade|on"}
    )
    rows: List[List[Dict[str, str]]] = [
        [toggle],
        [
            {"text": "💼 Portfolio & Sizing", "callback_data": "nav|sizing"},
            {"text": "🧠 Strategy", "callback_data": "nav|strategy"},
        ],
        [{"text": f"🔢 Consensus: {consensus}/15", "callback_data": "nav|consensus"}],
        [{"text": f"🚫 Blacklist ({blacklist_count})", "callback_data": "nav|blacklist"}],
        [
            {"text": "👛 Elite 15", "callback_data": "nav|elite15"},
            {"text": "📊 Positions", "callback_data": "nav|positions"},
        ],
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
    total_trades = ctx.get("total_trades") or "—"
    win_rate = ctx.get("win_rate") or "—"
    total_pnl = ctx.get("total_pnl") or "—"
    best_trade = ctx.get("best_trade") or "—"
    email = html.escape(str(ctx.get("email") or "—"))

    lines = [
        "<b>MY ACCOUNT</b>",
        "",
        f"Email: <b>{email}</b>",
        f"Telegram: <b>@{username}</b>",
        f"Access: <b>{tier}</b>",
        "",
        "<b>Stats</b>",
        f"Total trades: {total_trades}",
        f"Win rate: {win_rate}",
        f"Total PnL: {total_pnl}",
        f"Best trade: {best_trade}",
        "",
        "<b>⚠️ DANGER ZONE</b>",
    ]
    rows: List[List[Dict[str, str]]] = [
        [{"text": "\U0001f511 Forgot / Reset Password", "callback_data": "access|forgot_password"}],
        [{"text": "\U0001f6a8 Emergency Stop (Pause Bot)", "callback_data": "access|emergency_stop"}],
        [{"text": "\U0001f6aa Log Out", "callback_data": "access|logout"}],
    ]
    if ctx.get("dashboard_url"):
        rows.append([{"text": "Open Dashboard", "url": ctx["dashboard_url"]}])
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


# ── Trade History ──────────────────────────────────────────────────────────

def render_trade_history(ctx: Dict[str, Any]) -> Rendered:
    """Paginated list of closed positions with filters."""
    trades = ctx.get("trades") or []
    page = int(ctx.get("page") or 1)
    total = int(ctx.get("total") or 0)
    filter_name = ctx.get("filter") or "all"
    per_page = 10

    lines = ["<b>TRADE HISTORY</b>", ""]
    # Filter row
    filter_labels = {
        "all": "All", "wins": "Wins", "losses": "Losses",
        "auto": "Auto", "manual": "Manual",
    }
    filter_str = " | ".join(
        f"[{filter_labels.get(f, f)}]" if f == filter_name else filter_labels.get(f, f)
        for f in ["all", "wins", "losses", "auto", "manual"]
    )
    lines.append(f"Filter: {filter_str}")
    lines.append(f"Showing page {page} ({len(trades)} of {total} total)")
    lines.append("")

    if not trades:
        lines.append("No closed trades yet.")
    else:
        for t in trades:
            symbol = html.escape(str(t.get("token_symbol") or t.get("token_ticker") or "???"))
            pnl = float(t.get("unrealized_pnl_usd") or t.get("realized_pnl_usd") or 0)
            pnl_pct = float(t.get("roi_pct") or 0)
            trigger = t.get("trigger_type") or "auto"
            reason = t.get("close_reason") or "closed"
            date_str = (t.get("closed_at") or t.get("opened_at") or "")[:10]
            emoji = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")
            lines.append(
                f"{emoji} {symbol} — {trigger.upper()} — {reason} — "
                f"${pnl:+,.2f} ({pnl_pct:+.1f}%) — {date_str}"
            )

    rows: List[List[Dict[str, str]]] = []
    # Filter buttons
    for f in ["all", "wins", "losses", "auto", "manual"]:
        if f != filter_name:
            rows.append([{"text": f"Filter: {filter_labels[f]}", "callback_data": f"stat|filter|{f}"}])
    # Pagination
    if page > 1:
        rows.append([{"text": "◀ Previous", "callback_data": f"stat|page|{page - 1}"}])
    if len(trades) >= per_page:
        rows.append([{"text": "Next ▶", "callback_data": f"stat|page|{page + 1}"}])
    rows.append([{"text": "📊 Export CSV", "callback_data": "stat|export_csv"}])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_trade_detail(ctx: Dict[str, Any]) -> Rendered:
    """Single closed trade breakdown."""
    t = ctx.get("trade") or {}
    symbol = html.escape(str(t.get("token_symbol") or t.get("token_ticker") or "???"))
    trigger = t.get("trigger_type") or "auto"
    entry = float(t.get("avg_entry_price") or 0)
    close_reason = t.get("close_reason") or "unknown"
    pnl = float(t.get("unrealized_pnl_usd") or t.get("realized_pnl_usd") or 0)
    mult = float(t.get("roi_mult") or 0)
    opened = t.get("opened_at") or ""
    closed = t.get("closed_at") or ""
    entry_tx = t.get("entry_txid") or ""
    exit_tx = t.get("exit_txid") or ""
    token_addr = t.get("token_address") or ""

    lines = [
        f"<b>TRADE DETAIL: {symbol}</b>",
        "",
        f"Type: <b>{trigger.upper()}</b>",
        f"Close reason: <b>{close_reason}</b>",
        f"Entry price: ${entry:.8f}",
        f"Multiplier: {mult:.1f}x" if mult else "",
        f"PnL: ${pnl:+,.2f}",
        f"Opened: {opened[:19]}" if opened else "",
        f"Closed: {closed[:19]}" if closed else "",
    ]
    lines = [l for l in lines if l]  # filter empty

    rows: List[List[Dict[str, str]]] = []
    if entry_tx:
        rows.append([{
            "text": "Entry TX",
            "url": f"https://solscan.io/tx/{entry_tx}",
        }])
    if exit_tx:
        rows.append([{
            "text": "Exit TX",
            "url": f"https://solscan.io/tx/{exit_tx}",
        }])
    if token_addr:
        rows.append([{
            "text": "Chart (DexScreener)",
            "url": f"https://dexscreener.com/solana/{token_addr}",
        }])
    rows.append(_back_row("trade_history"))
    return "\n".join(lines), _kb(rows)


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
    selected = set(ctx.get("selected_wallets") or [])
    lines = ["<b>ELITE 15 WALLETS</b>", ""]
    if selected:
        lines.append(f"Auto-trader copying: <b>{len(selected)}/15</b> wallets selected")
    else:
        lines.append("Auto-trader copying: <b>ALL 15</b> (default)")
    lines.append("Tap a wallet for detail & copy-trade options.")
    lines.append("")
    if not wallets:
        lines.append("No Elite wallets are available for this account yet.")
    else:
        for idx, wallet in enumerate(wallets[:15], start=1):
            addr = wallet.get("wallet_address") or ""
            tier = wallet.get("tier") or "S"
            is_sel = addr in selected
            mark = "✅" if is_sel else "➕"
            lines.append(f"#{idx} {tier} <code>{addr[:8]}...{addr[-6:] if len(addr) > 6 else addr}</code> {mark}")
    rows: List[List[Dict[str, str]]] = []
    # Per-wallet toggle buttons: select/deselect
    for idx, wallet in enumerate(wallets[:15], start=1):
        addr = wallet.get("wallet_address") or ""
        is_sel = addr in selected
        action = "deselect" if is_sel else "select"
        label = "Stop Copying" if is_sel else "Copy This"
        rows.append([{
            "text": f"#{idx} {label}",
            "callback_data": f"wal|{action}|{addr}",
        }])
    rows.append([nav_button("Consensus Threshold", "consensus")])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_elite_wallet_detail(ctx: Dict[str, Any]) -> Rendered:
    """Deep-dive on a single Elite 15 wallet."""
    wallet = ctx.get("wallet") or {}
    addr = wallet.get("wallet_address") or "unknown"
    tier = wallet.get("tier") or "S"
    is_selected = ctx.get("is_selected", False)
    win_rate = wallet.get("win_rate_pct")
    roi = wallet.get("avg_roi_pct")
    total_pnl = wallet.get("total_pnl_sol")
    tokens_traded = wallet.get("token_count")
    best_trade = wallet.get("best_trade")
    worst_trade = wallet.get("worst_trade")
    avg_hold = wallet.get("avg_hold_time")

    lines = [
        f"<b>ELITE WALLET DETAIL</b>",
        "",
        f"Tier: <b>{tier}</b>",
        f"Address: <code>{addr[:8]}...{addr[-6:] if len(addr) > 6 else addr}</code>",
        "",
        "<b>Stats</b>",
        f"Tokens traded: {tokens_traded or '—'}",
        f"Win rate: {f'{float(win_rate):.0f}%' if win_rate is not None else '—'}",
        f"Avg ROI: {f'{float(roi):.0f}%' if roi is not None else '—'}",
        f"Total PnL: {f'{float(total_pnl):.1f} SOL' if total_pnl is not None else '—'}",
        f"Best trade: {best_trade or '—'}",
        f"Worst trade: {worst_trade or '—'}",
        f"Avg hold: {avg_hold or '—'}",
        "",
        "<b>Recent Trades</b>",
    ]
    recent = wallet.get("recent_trades") or []
    if recent:
        for t in recent[:3]:
            symbol = t.get("token_symbol") or "???"
            side = t.get("side") or ""
            pnl = t.get("pnl")
            pnl_str = f"{pnl:+,.1f}" if pnl is not None else "—"
            lines.append(f"{side.upper()} {symbol} :: {pnl_str}")
    else:
        lines.append("No recent trade data.")

    rows: List[List[Dict[str, str]]] = [
        [{"text": "📋 Copy Address", "callback_data": f"wal|copy|{addr}"}],
    ]
    if is_selected:
        rows.append([{"text": "⛔ Stop Copying", "callback_data": f"wal|deselect|{addr}"}])
    else:
        rows.append([{"text": "✅ Copy This Wallet", "callback_data": f"wal|select|{addr}"}])
    rows.append([nav_button("⬅️ Back to Elite 15", "elite15")])
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
