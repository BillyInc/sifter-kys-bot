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


# Friendly text for token-security block reasons (from bot_security.check_token_safety).
_SECURITY_REASON_TEXT = {
    "mint_not_revoked": "Mint authority is still active (can mint more supply).",
    "freeze_not_revoked": "Freeze authority is still active (can freeze your tokens).",
    "rugged": "This token is flagged as rugged.",
    "lp_not_burned": "Liquidity is not burned/locked.",
    "security_unavailable": "Safety data is unavailable right now.",
}



# ── keyboard helpers ────────────────────────────────────────────────────────

def nav_button(label: str, screen: str) -> Dict[str, str]:
    """A button that navigates to a top-level screen (``nav|<screen>``)."""
    return {"text": label, "callback_data": f"nav|{screen}"}


def _kb(rows: List[List[Dict[str, str]]]) -> Keyboard:
    return {"inline_keyboard": rows}


def _back_row(to: str = "main") -> List[Dict[str, str]]:
    return [nav_button("⬅️ Back", to), nav_button("🏠 Main Menu", "main")]


# ── persistent reply keyboard ────────────────────────────────────────────────
# Unlike inline keyboards (attached to a single message), a reply keyboard sits
# above the text box and stays there. Tapping a button sends its label as a
# normal text message, which the router intercepts (see telegram_notifier).

MENU_BTN_LABEL = "☰ Menu"
HELP_BTN_LABEL = "❓ Help"


def persistent_menu_keyboard() -> Dict[str, Any]:
    """A persistent two-button bar (Menu / Help) shown above the text box."""
    return {
        "keyboard": [[{"text": MENU_BTN_LABEL}, {"text": HELP_BTN_LABEL}]],
        "resize_keyboard": True,
        "is_persistent": True,
    }


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
    paper_mode = ctx.get("paper_mode") or False
    rows: List[List[Dict[str, str]]] = [
        [toggle],
        [
            {"text": "🧪 Disable Paper Mode" if paper_mode else "🧪 Paper Mode: Enable",
             "callback_data": f"set|paper_mode|{'off' if paper_mode else 'on'}"},
        ],
        [
            {"text": "💼 Portfolio & Sizing", "callback_data": "nav|portfolio_sizing"},
            {"text": "🧠 Strategy", "callback_data": "nav|strategy"},
        ],
        [{"text": f"🔢 Consensus: {consensus}/15", "callback_data": "nav|consensus"}],
        [{"text": f"🚫 Blacklist ({blacklist_count})", "callback_data": "nav|blacklist"}],
        [
            {"text": "👛 Elite 15", "callback_data": "nav|elite15"},
            {"text": "📊 Positions", "callback_data": "nav|positions"},
        ],
        [{"text": "📋 Trade History", "callback_data": "nav|trade_history"}],
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
    auto_bl = bool(ctx.get("auto_blacklist"))
    lines = [
        "<b>STRATEGY SETTINGS</b>",
        "",
        f"Stop loss: <b>{sl if sl is not None else -50}%</b>",
        f"Take profit: <b>{'♾️ None' if tp is None else f'{float(tp):.1f}x'}</b>",
        f"Trailing stop: <b>{str(trailing) + '%' if trailing is not None else 'off'}</b>",
        f"Slippage: <b>{float(slippage_bps or 100) / 100:.1f}%</b>",
        f"MEV protection: <b>{'ON' if mev else 'OFF'}</b>",
        f"Auto-blacklist on SL: <b>{'ON' if auto_bl else 'OFF'}</b>",
        "",
        "These values are copied into each autonomous entry when the bot trades.",
    ]
    rows: List[List[Dict[str, str]]] = [
        [
            {"text": "SL -25%", "callback_data": "set|sl|-25"},
            {"text": "SL -50%", "callback_data": "set|sl|-50"},
            {"text": "SL -75%", "callback_data": "set|sl|-75"},
        ],
        [
            {"text": "TP 2x", "callback_data": "set|tp|2"},
            {"text": "TP 3x", "callback_data": "set|tp|3"},
            {"text": "TP 5x", "callback_data": "set|tp|5"},
            {"text": "TP 10x", "callback_data": "set|tp|10"},
        ],
        [{"text": "♾️ No TP", "callback_data": "set|tp|none"}],
        [
            {"text": "Trail OFF", "callback_data": "set|trailing|off"},
            {"text": "Trail 20%", "callback_data": "set|trailing|20"},
            {"text": "Trail custom", "callback_data": "set|trailing|custom"},
        ],
        [
            {"text": "Slip 0.5%", "callback_data": "set|slippage|0.5"},
            {"text": "Slip 1%", "callback_data": "set|slippage|1"},
            {"text": "Slip 2%", "callback_data": "set|slippage|2"},
            {"text": "Slip 5%", "callback_data": "set|slippage|5"},
        ],
        [
            {"text": "MEV ON ✅", "callback_data": "set|mev|on"},
            {"text": "MEV OFF", "callback_data": "set|mev|off"},
        ],
        [
            {"text": "Auto-BL ON", "callback_data": "set|auto_bl|on"},
            {"text": "Auto-BL OFF", "callback_data": "set|auto_bl|off"},
        ],
        [{"text": "🗂️ Manage Blacklist →", "callback_data": "nav|blacklist"}],
        [{"text": "Custom SL", "callback_data": "set|sl|custom"},
         {"text": "Custom TP", "callback_data": "set|tp|custom"}],
        [{"text": "💼 Portfolio & Sizing →", "callback_data": "nav|portfolio_sizing"}],
        _back_row("main"),
    ]
    return "\n".join(lines), _kb(rows)


def render_portfolio_sizing(ctx: Dict[str, Any]) -> Rendered:
    """Portfolio & sizing configuration."""
    pool_pct = float(ctx.get("trading_pool_pct") or 50)
    max_deploy = float(ctx.get("max_deployment_pct") or 80)
    daily = int(ctx.get("daily_trade_limit") or 0)
    hourly = int(ctx.get("hourly_trade_limit") or 0)

    daily_str = str(daily) if daily > 0 else "∞"
    hourly_str = str(hourly) if hourly > 0 else "∞"

    lines = [
        "<b>PORTFOLIO & SIZING</b>",
        "",
        f"Trading Pool: <b>{pool_pct:.0f}%</b> of wallet",
        f"Deployment Limit: <b>{max_deploy:.0f}%</b>",
        f"Daily Limit: <b>{daily_str}</b>",
        f"Hourly Limit: <b>{hourly_str}</b>",
    ]
    rows: List[List[Dict[str, str]]] = [
        # Pool %
        [
            {"text": "Pool 10%", "callback_data": "set|pool|10"},
            {"text": "Pool 25%", "callback_data": "set|pool|25"},
            {"text": "Pool 50%", "callback_data": "set|pool|50"},
            {"text": "Pool 75%", "callback_data": "set|pool|75"},
        ],
        [{"text": "Pool 100%", "callback_data": "set|pool|100"}],
        # Deployment limit
        [
            {"text": "Max Deploy 50%", "callback_data": "set|deploy|50"},
            {"text": "Max Deploy 70%", "callback_data": "set|deploy|70"},
            {"text": "Max Deploy 80%", "callback_data": "set|deploy|80"},
        ],
        # Daily limit
        [
            {"text": "Daily 5", "callback_data": "set|daily|5"},
            {"text": "Daily 10", "callback_data": "set|daily|10"},
            {"text": "Daily 20", "callback_data": "set|daily|20"},
            {"text": "Daily ∞", "callback_data": "set|daily|0"},
        ],
        # Hourly limit
        [
            {"text": "Hourly 1", "callback_data": "set|hourly|1"},
            {"text": "Hourly 3", "callback_data": "set|hourly|3"},
            {"text": "Hourly 5", "callback_data": "set|hourly|5"},
            {"text": "Hourly ∞", "callback_data": "set|hourly|0"},
        ],
        [{"text": "💰 Signal Sizing →", "callback_data": "nav|sizing"}],
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
        ("signal", "Elite Buy Signals", "notif_signal"),
        ("elite_sell", "Elite Sell Signals", "notif_elite_sell"),
        ("open", "Trade Open", "notif_trade_open"),
        ("close", "Trade Close", "notif_trade_close"),
        ("tp", "TP Hit", "notif_tp_hit"),
        ("sl", "SL Hit", "notif_sl_hit"),
        ("tracked", "Tracked Wallet", "notif_tracked_wallet"),
        ("daily", "Daily Summary", "notif_daily_summary"),
        ("weekly", "Weekly Summary", "notif_weekly_summary"),
    ]
    lines = ["<b>NOTIFICATIONS</b>", ""]
    rows: List[List[Dict[str, str]]] = []
    for key, label, col in toggles:
        enabled = bool(ctx.get(col, True))
        state = "ON" if enabled else "OFF"
        lines.append(f"{label}: <b>{state}</b>")
        rows.append([{
            "text": f"{label}: {'turn off' if enabled else 'turn on'}",
            "callback_data": f"set|notif|{key}|{'off' if enabled else 'on'}",
        }])
    # Quiet hours
    qh_start = ctx.get("quiet_hours_start")
    qh_end = ctx.get("quiet_hours_end")
    qh_str = f"{qh_start}:00–{qh_end}:00 UTC" if qh_start is not None else "OFF"
    lines.append(f"Quiet Hours: <b>{qh_str}</b>")
    if qh_start is not None:
        rows.append([{"text": "Quiet Hours: Turn OFF", "callback_data": "set|quiet_hours|off"}])
    else:
        rows.append([{"text": "Quiet Hours: Set", "callback_data": "set|quiet_hours|custom"}])
    rows.append(_back_row("settings"))
    return "\n".join(lines), _kb(rows)


def render_quiet_hours_prompt() -> Rendered:
    """Prompt for quiet hours start/end hour."""
    text = (
        "<b>QUIET HOURS</b>\n\n"
        "Send start and end UTC hours (0-23), e.g.:\n"
        "<code>23 7</code> for 11PM to 7AM\n\n"
        "Type /cancel to go back."
    )
    return text, _kb([_back_row("notifications")])


# ── Price Alerts ────────────────────────────────────────────────────────────

def render_price_alerts(ctx: Dict[str, Any]) -> Rendered:
    alerts = ctx.get("alerts") or []
    lines = ["<b>MC PRICE ALERTS</b>", ""]
    if not alerts:
        lines.append("No price alerts set.")
    else:
        for a in alerts[:10]:
            symbol = html.escape(str(a.get("token_symbol") or a.get("token_ticker") or "???"))
            target = a.get("target_mc_usd") or 0
            active = a.get("active", True)
            status = "🟢" if active else "⚫"
            lines.append(f"{status} {symbol} — Target: ${int(target):,} MC")
    rows: List[List[Dict[str, str]]] = [
        [{"text": "➕ New Alert", "callback_data": "alert|new"}],
    ]
    for a in (alerts or [])[:8]:
        aid = a.get("id")
        symbol = html.escape(str(a.get("token_symbol") or "???"))
        rows.append([{
            "text": f"Delete {symbol}",
            "callback_data": f"alert|delete|{aid}",
        }])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_set_price_alert(ctx: Dict[str, Any]) -> Rendered:
    """Set a new MC price alert."""
    token_symbol = str(ctx.get("token_symbol") or "")
    token_addr = ctx.get("token_address") or ""
    lines = [
        "<b>SET MC PRICE ALERT</b>",
        "",
        f"Token: <b>{html.escape(token_symbol)}</b>" if token_symbol else "Enter token CA or select from positions",
    ]
    rows: List[List[Dict[str, str]]] = [
        [
            {"text": "$100K", "callback_data": f"alert|set|{token_addr}|100000"},
            {"text": "$200K", "callback_data": f"alert|set|{token_addr}|200000"},
            {"text": "$500K", "callback_data": f"alert|set|{token_addr}|500000"},
            {"text": "$1M", "callback_data": f"alert|set|{token_addr}|1000000"},
        ],
        _back_row("price_alerts"),
    ]
    return "\n".join(lines), _kb(rows)


# ── Notes & Reminders ───────────────────────────────────────────────────────

def render_notes(ctx: Dict[str, Any]) -> Rendered:
    notes = ctx.get("notes") or []
    reminders = ctx.get("reminders") or []
    lines = ["<b>NOTES & REMINDERS</b>", ""]
    if reminders:
        lines.append("<b>Upcoming Reminders</b>")
        for r in reminders[:5]:
            lines.append(f"⏰ {html.escape(str(r.get('body') or '')[:80])}")
        lines.append("")
    if notes:
        lines.append("<b>Notes</b>")
        for n in notes[:10]:
            pin = "📌 " if n.get("pinned") else ""
            lines.append(f"{pin}{html.escape(str(n.get('body') or '')[:100])}")
    if not notes and not reminders:
        lines.append("No notes or reminders yet.")
    rows: List[List[Dict[str, str]]] = [
        [{"text": "➕ New Note", "callback_data": "note|new"}],
        [{"text": "⏰ New Reminder", "callback_data": "note|new_reminder"}],
    ]
    for n in (notes or [])[:8]:
        nid = n.get("id")
        txt = str(n.get("body") or "")[:30]
        rows.append([{
            "text": f"Delete: {txt}",
            "callback_data": f"note|delete|{nid}",
        }])
    rows.append(_back_row("account"))
    return "\n".join(lines), _kb(rows)


def render_new_note_prompt() -> Rendered:
    return (
        "<b>NEW NOTE</b>\n\n"
        "Reply with your note (up to 500 characters).\n"
        "Type /cancel to go back.",
        _kb([_back_row("notes")])
    )


def render_new_reminder_prompt() -> Rendered:
    text = (
        "<b>NEW REMINDER</b>\n\n"
        "Choose type:"
    )
    rows: List[List[Dict[str, str]]] = [
        [{"text": "🕐 Time-based (1h)", "callback_data": "note|set_reminder|time|1h"}],
        [{"text": "🕐 Time-based (4h)", "callback_data": "note|set_reminder|time|4h"}],
        [{"text": "🕐 Time-based (24h)", "callback_data": "note|set_reminder|time|24h"}],
        [{"text": "📈 MC-based", "callback_data": "note|set_reminder|mc"}],
        _back_row("notes"),
    ]
    return text, _kb(rows)


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
        # PnL color dot
        if pnl_pct > 0:
            dot = "🟢"
        elif pnl_pct < -20:
            dot = "🔴"
        else:
            dot = "🟡"
        lines.extend([
            f"{dot} <b>${symbol}</b> {pnl_pct:+.1f}%",
            f"Entry: ${entry:.8f} | At risk: ${invested:,.2f}",
            f"TP: {pos.get('take_profit_x') or '-'}x | SL: {pos.get('stop_loss_pct') or '-'}%",
            "",
        ])
        rows.append(_chart_keyboard(token))
        rows.append([
            {"text": "Close 25%", "callback_data": f"pos|close|{pos.get('id')}|25"},
            {"text": "Close 50%", "callback_data": f"pos|close|{pos.get('id')}|50"},
            {"text": "Close 75%", "callback_data": f"pos|close|{pos.get('id')}|75"},
            {"text": "Close 100%", "callback_data": f"pos|close|{pos.get('id')}|100"},
        ])
        rows.append([
            {"text": "Close Custom %", "callback_data": f"pos|close_custom|{pos.get('id')}"},
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
        rows.append([
            {"text": "🔔 Set MC Alert", "callback_data": f"alert|new|{token}"},
        ])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_close_confirm(ctx: Dict[str, Any]) -> Rendered:
    """Confirmation screen with fee breakdown before closing a position."""
    symbol = str(ctx.get("token_symbol") or "???")
    pos_id = ctx.get("position_id")
    sell_pct = int(ctx.get("sell_pct") or 100)
    gross = float(ctx.get("gross_sol") or 0)
    fee = round(gross * 0.01, 4)
    net = round(gross - fee, 4)
    remaining = ctx.get("remaining_info") or ""

    lines = [
        f"<b>CONFIRM CLOSE</b>",
        "",
        f"Selling <b>{sell_pct}%</b> of <b>{html.escape(symbol)}</b>",
        "",
        "💰 <b>Breakdown</b>",
        f"Gross proceeds: {gross} SOL",
        f"Platform fee (1%): {fee} SOL",
        f"Net received: {net} SOL",
    ]
    if remaining:
        lines.append(f"Remaining held: {remaining}")
    rows: List[List[Dict[str, str]]] = [
        [{"text": "✅ Confirm Sale", "callback_data": f"pos|close_confirm|{pos_id}|{sell_pct}"}],
        [{"text": "❌ Cancel", "callback_data": "nav|positions"}],
    ]
    return "\n".join(lines), _kb(rows)


def render_runrest_confirm(ctx: Dict[str, Any]) -> Rendered:
    """Confirmation for take 50% + run rest."""
    symbol = str(ctx.get("token_symbol") or "???")
    pos_id = ctx.get("position_id")
    gross = float(ctx.get("gross_sol") or 0)
    fee = round(gross * 0.01, 4)
    net = round(gross - fee, 4)

    lines = [
        "<b>TAKE 50% + RUN ♾️</b>",
        "",
        f"Sell <b>50%</b> of <b>{html.escape(symbol)}</b>",
        "",
        "💰 <b>Breakdown</b>",
        f"Gross: {gross} SOL | Fee (1%): {fee} SOL",
        f"Net: {net} SOL",
        "",
        "Remaining 50%: TP removed (♾️), SL kept, moved to Archive",
    ]
    rows: List[List[Dict[str, str]]] = [
        [{"text": "✅ Confirm", "callback_data": f"pos|runrest_confirm|{pos_id}"}],
        [{"text": "❌ Cancel", "callback_data": "nav|positions"}],
    ]
    return "\n".join(lines), _kb(rows)


def render_archived_holdings(ctx: Dict[str, Any]) -> Rendered:
    """List of archived (no-TP-monitored) positions."""
    archived = ctx.get("archived") or []
    lines = ["<b>ARCHIVED HOLDINGS</b>", ""]
    total_value = 0.0
    if not archived:
        lines.append("No archived holdings.")
    else:
        for pos in archived[:15]:
            symbol = html.escape(pos.get("token_symbol") or "???")
            remaining = float(pos.get("remaining_amount") or 0)
            current_val = float(pos.get("current_value_usd") or 0)
            total_value += current_val
            lines.append(f"<b>{symbol}</b> — Hold: {remaining:.0f} tokens — Est: ${current_val:,.2f}")
        lines.append("")
        lines.append(f"Total archived value: ${total_value:,.2f}")

    rows: List[List[Dict[str, str]]] = []
    for pos in archived[:15]:
        pid = pos.get("id")
        rows.append([{
            "text": f"Manage {html.escape(pos.get('token_symbol') or '???')}",
            "callback_data": f"pos|manage_archived|{pid}",
        }])
    rows.append(_back_row("positions"))
    return "\n".join(lines), _kb(rows)


def render_archived_token_manage(ctx: Dict[str, Any]) -> Rendered:
    """Manage a single archived token."""
    symbol = str(ctx.get("token_symbol") or "???")
    pos_id = ctx.get("position_id")
    remaining = float(ctx.get("remaining_amount") or 0)
    current_val = float(ctx.get("current_value_usd") or 0)

    lines = [
        f"<b>ARCHIVED: {html.escape(symbol)}</b>",
        "",
        f"Holding: {remaining:.0f} tokens",
        f"Est. value: ${current_val:,.2f}",
    ]
    rows: List[List[Dict[str, str]]] = [
        [{"text": "▶️ Restore to Active", "callback_data": f"pos|restore|{pos_id}"}],
        [{"text": "Close 50%", "callback_data": f"pos|close|{pos_id}|50"}],
        [{"text": "Close 100%", "callback_data": f"pos|close|{pos_id}|100"}],
        _back_row("archived"),
    ]
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
    phrase = html.escape(str(ctx.get("anti_phishing_phrase") or "not set"))

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
        "🔒 <b>Email Security Phrase</b>",
        f"<code>{phrase}</code>",
        "<i>Every genuine SIFTER email shows this phrase. If an email lacks it, it's a scam.</i>",
        "",
        "<b>⚠️ DANGER ZONE</b>",
    ]
    rows: List[List[Dict[str, str]]] = [
        [{"text": "🔒 Change Security Phrase", "callback_data": "access|set_phrase"}],
        [{"text": "\U0001f511 Forgot / Reset Password", "callback_data": "access|forgot_password"}],
        [{"text": "\U0001f4ca Export Trade History (CSV)", "callback_data": "nav|trade_history"}],
        [{"text": "\U0001f4dd My Notes & Reminders", "callback_data": "nav|notes"}],
        [{"text": "\U0001f6a8 Emergency Stop (Pause Bot)", "callback_data": "access|emergency_stop"}],
        [{"text": "❄️ Suspend Account", "callback_data": "access|suspend"}],
        [{"text": "\U0001f5d1️ Delete Account", "callback_data": "access|delete"}],
        [{"text": "\U0001f6aa Log Out", "callback_data": "access|logout"}],
    ]
    if ctx.get("dashboard_url"):
        rows.append([{"text": "Open Dashboard", "url": ctx["dashboard_url"]}])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_token_stats_prompt() -> Rendered:
    text = (
        "<b>TOKEN STATS</b>\n\n"
        "Paste a Solana token contract address or type a ticker to inspect it.\n"
        "Token data from SolanaTracker."
    )
    return text, _kb([_back_row("main")])


_HOLDER_TAG_EMOJI = {
    "pool": "🏦 Pool", "developer": "🛠 Dev", "dev": "🛠 Dev",
    "kol": "📢 KOL", "bot": "🤖 Bot", "exchange": "🏛 CEX",
    "sniper": "🎯 Sniper", "insider": "🕵 Insider",
}


def _fmt_metric(metric: Dict[str, Any]) -> str:
    """Render a normalized risk metric {count, pct} → 'N wallets • X%'."""
    if not isinstance(metric, dict):
        return "—"
    count = metric.get("count")
    pct = metric.get("pct")
    parts = []
    if count is not None:
        parts.append(f"{count} wallet" + ("s" if count != 1 else ""))
    if pct is not None:
        parts.append(f"{float(pct):.1f}%")
    return " • ".join(parts) if parts else "—"


def render_token_details(ctx: Dict[str, Any]) -> Rendered:
    token = ctx.get("token_address") or ""
    symbol = str(ctx.get("symbol") or "???")
    name = str(ctx.get("name") or "")
    manual = bool(ctx.get("manual"))
    price = ctx.get("price_usd")
    mc = ctx.get("market_cap_usd")
    liquidity = ctx.get("liquidity_usd")
    vol_24h = ctx.get("volume_24h_usd")
    holders = ctx.get("holders_total") if ctx.get("holders_total") is not None else ctx.get("holders")
    lp_burn = ctx.get("lp_burn_pct")
    mint_revoked = ctx.get("is_mint_revoked")
    freeze_revoked = ctx.get("is_freeze_revoked")
    ath = ctx.get("ath_price")
    age = ctx.get("age_days")

    lines = [
        f"<b>TOKEN DETAILS</b>",
        "",
        f"<b>{html.escape(symbol)}</b> — {html.escape(name)}" if name else f"<b>{html.escape(symbol)}</b>",
        f"CA: <code>{html.escape(token)}</code>",
        "",
    ]
    if mc is not None:
        mc_str = f"${float(mc):,.0f}" if float(mc) >= 1000000 else f"${float(mc):,.2f}"
        lines.append(f"MC: <b>{mc_str}</b>")
    if price is not None:
        lines.append(f"Price: ${float(price):.8f}")
    if ath is not None:
        lines.append(f"ATH: ${float(ath):.8f}")
    if liquidity is not None:
        lines.append(f"Liquidity: ${float(liquidity):,.0f}")
    if vol_24h is not None:
        lines.append(f"Volume 24h: ${float(vol_24h):,.0f}")
    if holders is not None:
        lines.append(f"Holders: {holders}")
    if age is not None:
        lines.append(f"Age: {age} day(s)")

    # ── Security ───────────────────────────────────────────────────────────
    has_security = (
        mint_revoked is not None or freeze_revoked is not None
        or lp_burn is not None or ctx.get("rugged") is not None
    )
    if has_security:
        lines.append("")
        lines.append("<b>Security</b>")
        if mint_revoked is not None:
            lines.append(f"Mint: {'✅ Revoked' if mint_revoked else '⚠️ Active'}")
        if freeze_revoked is not None:
            lines.append(f"Freeze: {'✅ Revoked' if freeze_revoked else '⚠️ Active'}")
        if lp_burn is not None:
            lines.append(f"LP Burned: {lp_burn}%")
        if ctx.get("rugged") is not None:
            lines.append(f"Rugged: {'🛑 YES' if ctx.get('rugged') else '✅ No'}")
        if ctx.get("jupiter_verified") is not None:
            lines.append(f"Jupiter Verified: {'✅ Yes' if ctx.get('jupiter_verified') else '—'}")
        if ctx.get("risk_score") is not None:
            lines.append(f"Risk Score: {ctx.get('risk_score')}")

    # ── Risk (bundlers / snipers / dev / top10) ────────────────────────────
    bundlers = ctx.get("bundlers")
    snipers = ctx.get("snipers")
    dev = ctx.get("dev_holdings")
    top10 = ctx.get("top10")
    if any(isinstance(m, dict) and (m.get("count") is not None or m.get("pct") is not None)
           for m in (bundlers, snipers, dev, top10)):
        lines.append("")
        lines.append("<b>Risk</b>")
        if isinstance(bundlers, dict) and (bundlers.get("count") is not None or bundlers.get("pct") is not None):
            lines.append(f"Bundlers: {_fmt_metric(bundlers)}")
        if isinstance(snipers, dict) and (snipers.get("count") is not None or snipers.get("pct") is not None):
            lines.append(f"Snipers: {_fmt_metric(snipers)}")
        if isinstance(dev, dict) and dev.get("pct") is not None:
            lines.append(f"Dev holds: {float(dev['pct']):.1f}%")
        if isinstance(top10, dict) and top10.get("pct") is not None:
            lines.append(f"Top 10: {float(top10['pct']):.1f}%")

    # ── Top holders ────────────────────────────────────────────────────────
    top_holders = ctx.get("top_holders") or []
    if top_holders:
        lines.append("")
        lines.append("<b>Top Holders</b>")
        for i, h in enumerate(top_holders[:5], start=1):
            wallet = str(h.get("wallet") or "")[:6]
            pct = h.get("pct")
            usd = h.get("usd")
            tag = (h.get("tag") or "").lower()
            tag_str = f" [{_HOLDER_TAG_EMOJI.get(tag, tag.title())}]" if tag else ""
            pct_str = f"{float(pct):.1f}%" if pct is not None else "—"
            usd_str = f" ${float(usd):,.0f}" if usd is not None else ""
            lines.append(f"{i}. {html.escape(wallet)}…  {pct_str}{usd_str}{tag_str}")

    lines.append("")
    lines.append("Token data from SolanaTracker.")

    rows: List[List[Dict[str, str]]] = [
        _chart_keyboard(token),
        [{"text": "🔄 Refresh", "callback_data": f"exec|refresh_token|{token}"}],
    ]
    if manual:
        rows.append([{"text": "⚡ Trade This Token", "callback_data": "exec|manual_preview"}])
    rows.append(_back_row("manual_trade" if manual else "main"))
    return "\n".join(lines), _kb(rows)


def render_token_search_results(ctx: Dict[str, Any]) -> Rendered:
    """Show search results when multiple tokens match a ticker query."""
    results = ctx.get("results") or []
    manual = bool(ctx.get("manual"))
    lines = ["<b>SEARCH RESULTS</b>", "", "Multiple tokens found. Select one:"]
    rows: List[List[Dict[str, str]]] = []
    for r in results[:8]:
        symbol = str(r.get("symbol") or "???")
        name = str(r.get("name") or "")
        addr = str(r.get("mint") or r.get("address") or "")
        liq = r.get("liquidityUsd")
        liq_str = f" — Liq: ${float(liq):,.0f}" if liq else ""
        lines.append(f"<b>{html.escape(symbol)}</b> {html.escape(name)}{liq_str}")
        label = f"select_{symbol}"[:30]
        rows.append([{
            "text": f"{symbol} — {addr[:8]}...",
            "callback_data": f"exec|token_search_select|{addr}",
        }])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_manual_trade_entry() -> Rendered:
    text = (
        "<b>MANUAL TRADE</b>\n\n"
        "Manual trades require you to choose a token and confirm before execution. "
        "The autonomous bot is separate and enters qualifying Elite 15 signals on its own."
    )
    rows = [
        [{"text": "📋 Paste Contract Address", "callback_data": "exec|manual_ca"}],
        [{"text": "🔤 Type Token Ticker", "callback_data": "exec|manual_ticker"}],
        [{"text": "👛 Use Recent Elite Signal", "callback_data": "exec|manual_signal"}],
        [{"text": "🔒 Close / Modify Open Trade", "callback_data": "nav|positions"}],
        [{"text": "📦 Archived Holdings", "callback_data": "nav|archived"}],
        _back_row("main"),
    ]
    return text, _kb(rows)


# ── Manual Trade Flow ──────────────────────────────────────────────────────

def render_manual_trade_preview(ctx: Dict[str, Any]) -> Rendered:
    """Token preview + sizing screen before a manual trade."""
    token = ctx.get("token_address") or ""
    symbol = str(ctx.get("symbol") or "???")
    name = str(ctx.get("name") or "")
    price = ctx.get("price_usd")
    mc = ctx.get("market_cap_usd")
    liquidity = ctx.get("liquidity_usd")
    vol_24h = ctx.get("volume_24h_usd")
    ath = ctx.get("ath_price")
    security_ok = ctx.get("security_ok")
    security_reason = ctx.get("security_reason")

    # Portfolio context
    total_wallet = float(ctx.get("total_wallet_sol") or 10)
    pool_pct = float(ctx.get("trading_pool_pct") or 50)
    pool_sol = round(total_wallet * pool_pct / 100, 2)
    deployed_pct = float(ctx.get("deployed_pct") or 0)
    deployed_sol = round(pool_sol * deployed_pct / 100, 2)
    available_sol = round(pool_sol - deployed_sol, 2)

    # Current trade settings from state
    amount_pool_pct = ctx.get("amount_pool_pct")
    amount_total_pct = ctx.get("amount_total_pct")
    tp = ctx.get("tp_x")
    sl = ctx.get("sl_pct")
    slippage = ctx.get("slippage_bps")
    mev = ctx.get("mev_on")

    lines = [
        f"<b>MANUAL TRADE — {html.escape(symbol)}</b>",
        f"<code>{html.escape(token)}</code>",
        "",
    ]
    if price is not None:
        lines.append(f"Price: ${float(price):.8f}")
    if mc is not None:
        lines.append(f"MC: ${float(mc):,.0f}")
    if liquidity is not None:
        lines.append(f"Liq: ${float(liquidity):,.0f}")
    if vol_24h is not None:
        lines.append(f"Vol 24h: ${float(vol_24h):,.0f}")
    if ath is not None:
        lines.append(f"ATH: ${float(ath):.8f}")
    lines.append("")
    lines.append("💼 <b>Portfolio</b>")
    lines.append(f"Total: {total_wallet:.1f} SOL | Pool: {pool_sol} SOL")
    lines.append(f"Deployed: {deployed_sol} SOL | Available: {available_sol} SOL")
    lines.append("")
    lines.append("💰 <b>Position Size</b>")
    if amount_pool_pct:
        amount_sol = round(pool_sol * float(amount_pool_pct) / 100, 2)
        lines.append(f"% of Pool: <b>{amount_pool_pct}%</b> = {amount_sol} SOL")
    if amount_total_pct:
        amount_total_sol = round(total_wallet * float(amount_total_pct) / 100, 2)
        lines.append(f"% of Total: <b>{amount_total_pct}%</b> = {amount_total_sol} SOL")

    if tp or sl or slippage or mev is not None:
        lines.append("")
        lines.append("🔧 <b>Settings</b>")
        if tp:
            lines.append(f"TP: {tp}x{' (no TP)' if tp == 'inf' else ''}")
        if sl:
            lines.append(f"SL: {sl}%")
        if slippage:
            lines.append(f"Slippage: {float(slippage)/100:.1f}%")
        if mev is not None:
            lines.append(f"MEV: {'ON ✅' if mev in (True, 'on', 'true') else 'OFF'}")

    # Token-level rug gate — block the buy flow if the token is unsafe.
    if security_ok is False:
        reason_text = _SECURITY_REASON_TEXT.get(
            security_reason, "This token failed the safety check."
        )
        lines.append("")
        lines.append(f"🛑 <b>BLOCKED</b> — {reason_text}")
        lines.append("Manual buy is disabled for this token.")
        rows: List[List[Dict[str, str]]] = [
            _chart_keyboard(token),
            [{"text": "❌ Back", "callback_data": "nav|main"}],
        ]
        return "\n".join(lines), _kb(rows)

    rows: List[List[Dict[str, str]]] = [
        # Pool % presets
        [
            {"text": "10% Pool", "callback_data": "exec|set_amount|pool|10"},
            {"text": "25% Pool", "callback_data": "exec|set_amount|pool|25"},
            {"text": "50% Pool", "callback_data": "exec|set_amount|pool|50"},
            {"text": "75% Pool", "callback_data": "exec|set_amount|pool|75"},
        ],
        # Total % presets
        [
            {"text": "5% Total", "callback_data": "exec|set_amount|total|5"},
            {"text": "10% Total", "callback_data": "exec|set_amount|total|10"},
            {"text": "25% Total", "callback_data": "exec|set_amount|total|25"},
        ],
    ]
    # TP presets
    rows.append([
        {"text": "TP 2x", "callback_data": "exec|set_tp|2"},
        {"text": "TP 3x", "callback_data": "exec|set_tp|3"},
        {"text": "TP 5x", "callback_data": "exec|set_tp|5"},
        {"text": "TP 10x", "callback_data": "exec|set_tp|10"},
    ])
    rows.append([
        {"text": "TP: No TP", "callback_data": "exec|set_tp|inf"},
    ])
    # SL presets
    rows.append([
        {"text": "SL -25%", "callback_data": "exec|set_sl|-25"},
        {"text": "SL -50%", "callback_data": "exec|set_sl|-50"},
        {"text": "SL -75%", "callback_data": "exec|set_sl|-75"},
    ])
    # Slippage link + MEV
    rows.append([
        {"text": "⚡ Slippage & MEV →", "callback_data": "exec|manual_slippage"},
    ])
    rows.append([
        {"text": "✅ Review & Buy", "callback_data": "exec|manual_review"},
    ])
    rows.append([{"text": "❌ Cancel", "callback_data": "nav|main"}])
    return "\n".join(lines), _kb(rows)


def render_manual_trade_slippage(ctx: Dict[str, Any]) -> Rendered:
    """Per-trade slippage and MEV configuration."""
    slippage_bps = ctx.get("slippage_bps")
    current_slippage = f"{float(slippage_bps)/100:.1f}%" if slippage_bps else "Not set"
    mev_on = ctx.get("mev_on", True)

    lines = [
        "<b>SLIPPAGE & MEV</b>",
        "",
        f"Slippage: <b>{current_slippage}</b>",
        f"MEV: <b>{'ON ✅' if mev_on in (True, 'on', 'true') else 'OFF ⚪'}</b>",
        "",
        "<b>Slippage Presets</b>",
    ]
    rows: List[List[Dict[str, str]]] = [
        [
            {"text": "0.5%", "callback_data": "exec|set_slippage|50"},
            {"text": "1%", "callback_data": "exec|set_slippage|100"},
            {"text": "2%", "callback_data": "exec|set_slippage|200"},
            {"text": "5%", "callback_data": "exec|set_slippage|500"},
        ],
        [
            {"text": "MEV ON (Rec)", "callback_data": "exec|set_mev|on"},
            {"text": "MEV OFF (Fast)", "callback_data": "exec|set_mev|off"},
        ],
        [{"text": "✅ Done", "callback_data": "exec|back_to_preview"}],
    ]
    return "\n".join(lines), _kb(rows)


def render_manual_trade_confirm(ctx: Dict[str, Any]) -> Rendered:
    """Final confirmation screen with fee breakdown before executing."""
    symbol = str(ctx.get("symbol") or "???")
    token = ctx.get("token_address") or ""
    price = ctx.get("price_usd")

    amount_pool_pct = ctx.get("amount_pool_pct")
    amount_total_pct = ctx.get("amount_total_pct")
    tp = ctx.get("tp_x")
    sl = ctx.get("sl_pct")
    slippage_bps = ctx.get("slippage_bps")
    mev_on = ctx.get("mev_on", True)

    total_wallet = float(ctx.get("total_wallet_sol") or 10)
    pool_pct = float(ctx.get("trading_pool_pct") or 50)
    pool_sol = round(total_wallet * pool_pct / 100, 2)

    # Calculate estimated SOL amount
    if amount_pool_pct:
        est_sol = round(pool_sol * float(amount_pool_pct) / 100, 3)
    elif amount_total_pct:
        est_sol = round(total_wallet * float(amount_total_pct) / 100, 3)
    else:
        est_sol = 0.1

    platform_fee_sol = round(est_sol * 0.01, 4)  # 1% platform fee
    net_sol = round(est_sol - platform_fee_sol, 4)

    lines = [
        f"<b>CONFIRM MANUAL TRADE</b>",
        "",
        f"Token: <b>{html.escape(symbol)}</b>",
        f"Amount: <b>{est_sol} SOL</b>",
    ]
    if tp:
        lines.append(f"TP: <b>{tp}x</b>" if tp != "inf" else "TP: <b>♾️ None</b>")
    if sl:
        lines.append(f"SL: <b>{sl}%</b>")
    slippage_str = f"{float(slippage_bps)/100:.1f}%" if slippage_bps else "default"
    lines.append(f"Slippage: <b>{slippage_str}</b>")
    lines.append(f"MEV: <b>{'ON ✅' if mev_on in (True, 'on', 'true') else 'OFF'}</b>")
    lines.append("")
    lines.append("💰 <b>Fee Breakdown</b>")
    lines.append(f"Gross: {est_sol} SOL")
    lines.append(f"Platform fee (1%): {platform_fee_sol} SOL")
    lines.append(f"You receive: ~{net_sol} SOL")
    if price:
        est_tokens = round(est_sol / float(price), 2) if float(price) > 0 else 0
        lines.append(f"Est. tokens: ~{est_tokens:,.0f}")

    rows: List[List[Dict[str, str]]] = [
        [{"text": "🟢 EXECUTE BUY", "callback_data": "exec|manual_execute"}],
        [{"text": "⬅️ Adjust", "callback_data": "exec|back_to_preview"}],
    ]
    return "\n".join(lines), _kb(rows)


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
    balance = ctx.get("wallet_balance")
    lines = ["<b>MY WALLETS</b>", ""]
    if bot_wallets:
        lines.append("<b>Trading wallet</b>")
        for wallet in bot_wallets[:3]:
            pk = wallet.get("public_key") or ""
            lines.append(f"<code>{pk[:8]}...{pk[-6:] if len(pk) > 6 else pk}</code>")
            if balance is not None:
                lines.append(f"Balance: {float(balance):.4f} SOL")
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
    rows: List[List[Dict[str, str]]] = [
        [{"text": "Import Private Key", "callback_data": "wal|import"}],
        [{"text": "Import Seed Phrase", "callback_data": "wal|import_seed"}],
    ]
    if not bot_wallets:
        rows.append([{"text": "✨ Create New Wallet (Email)", "callback_data": "wal|create_email"}])
    if bot_wallets:
        rows.append([{"text": "💰 Fund Wallet", "callback_data": "wal|fund"}])
    rows.append(_back_row("main"))
    return "\n".join(lines), _kb(rows)


def render_fund_wallet(ctx: Dict[str, Any]) -> Rendered:
    """Show wallet address + balance + SOL conversion table."""
    addr = ctx.get("wallet_address") or "No wallet imported"
    balance = ctx.get("balance_sol")
    sol_price = float(ctx.get("sol_price") or 150)
    lines = [
        "<b>FUND WALLET</b>",
        "",
        f"Address: <code>{html.escape(addr)}</code>",
    ]
    if balance is not None:
        bal = float(balance)
        lines.append(f"Balance: <b>{bal:.4f} SOL</b> (${bal * sol_price:,.2f})")
    lines.append("")
    lines.append("<b>$ → SOL</b>")
    for usd in [10, 25, 50, 100, 500, 1000]:
        sol = round(usd / sol_price, 4)
        lines.append(f"${usd} ≈ {sol} SOL")
    rows: List[List[Dict[str, str]]] = [
        [{"text": "📋 Copy Address", "callback_data": "wal|copy|" + addr}],
        _back_row("wallets"),
    ]
    return "\n".join(lines), _kb(rows)


def render_tracked_wallet_detail(ctx: Dict[str, Any]) -> Rendered:
    """Deep dive on a single tracked wallet."""
    addr = ctx.get("wallet_address") or "unknown"
    status = "🟢 Active" if ctx.get("is_active") else "⚫ Inactive"
    last_trade = ctx.get("last_trade_at") or "—"
    lines = [
        "<b>TRACKED WALLET</b>",
        "",
        f"Address: <code>{html.escape(addr)[:12]}...</code>",
        f"Status: {status}",
        f"Last trade: {last_trade}",
        "",
        "30-day stats coming soon.",
    ]
    recent = ctx.get("recent_activity") or []
    if recent:
        lines.append("<b>Recent</b>")
        for act in recent[:5]:
            lines.append(f"{act.get('type','')} {act.get('symbol','')}")
    rows: List[List[Dict[str, str]]] = [
        [{"text": "📋 Copy", "callback_data": f"wal|copy|{addr}"}],
        [{"text": "➕ Add to Auto-Trader", "callback_data": f"wal|select|{addr}"}],
        _back_row("wallets"),
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
        "Operator controls. Visible to authorized chat IDs only.",
    ]
    rows: List[List[Dict[str, str]]] = [
        [{"text": "📊 System Health", "callback_data": "op|health"}],
        [{"text": "👥 Users", "callback_data": "op|users"},
         {"text": "📰 Send Digest", "callback_data": "op|digest"}],
        [{"text": "📂 Open Positions", "callback_data": "op|open_positions"},
         {"text": "📈 Paper Stats", "callback_data": "op|paper_stats"}],
        [{"text": "📊 Paper Status", "callback_data": "op|paper_status"},
         {"text": "📜 Paper Logs", "callback_data": "op|paper_logs"}],
        [{"text": "▶️ Paper Start", "callback_data": "op|paper_start"},
         {"text": "⏹️ Paper Stop", "callback_data": "op|paper_stop"}],
        [{"text": "🧪 Paper Test", "callback_data": "op|paper_test"},
         {"text": "⚠️ Paper Failures", "callback_data": "op|paper_failures"}],
        [{"text": "🚨 Close All Positions", "callback_data": "op|close_all_warn"}],
        [{"text": "🎟️ Generate Access Codes", "callback_data": "op|gen_codes"}],
        [{"text": "💰 Fee Revenue", "callback_data": "op|fee_revenue"}],
        [{"text": "✏️ Change Fee Rate", "callback_data": "op|change_fee"}],
        [{"text": "🔪 Kill Switch", "callback_data": "op|kill"}],
        [nav_button("Main Menu", "main")],
    ]
    return "\n".join(lines), _kb(rows)
