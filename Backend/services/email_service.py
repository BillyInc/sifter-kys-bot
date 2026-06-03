"""Email service for sending daily summaries, error alerts, and trade logs via Resend."""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

from config import Config
from services.log import get_logger
from services.supabase_client import get_supabase_client, SCHEMA_NAME

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "alerts@sifter.app")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_BASE_STYLE = (
    "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, "
    "Arial, sans-serif; color: #1a1a2e; background-color: #f5f5f5; padding: 24px;"
)

_TABLE_STYLE = (
    "width: 100%; border-collapse: collapse; margin: 16px 0; "
    "font-size: 14px; background: #ffffff; border-radius: 8px; overflow: hidden;"
)

_TH_STYLE = (
    "text-align: left; padding: 10px 14px; background: #16213e; color: #ffffff; "
    "font-weight: 600; font-size: 13px;"
)

_TD_STYLE = "padding: 10px 14px; border-bottom: 1px solid #e8e8e8;"


def _pnl_color(value: float) -> str:
    if value > 0:
        return "#10b981"
    elif value < 0:
        return "#ef4444"
    return "#6b7280"


def _wrap_html(title: str, body: str) -> str:
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="{_BASE_STYLE}">
  <div style="max-width: 640px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 32px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
    <h1 style="margin: 0 0 24px 0; font-size: 22px; color: #16213e;">{title}</h1>
    {body}
    <hr style="border: none; border-top: 1px solid #e8e8e8; margin: 24px 0 16px 0;">
    <p style="font-size: 12px; color: #9ca3af; margin: 0;">Sent by Sifter KYS &middot; {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# EmailService
# ---------------------------------------------------------------------------

class EmailService:
    """Sends transactional emails via the Resend API."""

    def __init__(self):
        self._ready = False
        if not RESEND_API_KEY:
            logger.warning("email_service_disabled", reason="RESEND_API_KEY not set")
            return

        import resend
        resend.api_key = RESEND_API_KEY
        self._resend = resend
        self._ready = True
        logger.info("email_service_initialized")

    # ------------------------------------------------------------------
    # Internal send wrapper
    # ------------------------------------------------------------------

    def _send(self, to: str, subject: str, html: str) -> bool:
        if not self._ready:
            logger.warning("email_send_skipped_resend", reason="service not configured")
            # Fall through to SMTP
            return self._send_via_smtp(to, subject, html)
        try:
            self._resend.Emails.send({
                "from": FROM_EMAIL,
                "to": to,
                "subject": subject,
                "html": html,
            })
            logger.info("email_sent", to=to, subject=subject, via="resend")
            return True
        except Exception as exc:
            logger.error("email_resend_failed", to=to, subject=subject, error=str(exc))
            # Try SMTP fallback
            return self._send_via_smtp(to, subject, html)

    # ------------------------------------------------------------------
    # SMTP fallback
    # ------------------------------------------------------------------

    def _send_via_smtp(self, to_email: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
        """SMTP fallback for email delivery. Returns True on success, False on failure."""
        if not Config.SMTP_HOST:
            logger.warning("smtp_send_skipped", reason="SMTP_HOST not configured")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = Config.SMTP_FROM_EMAIL or FROM_EMAIL
        msg["To"] = to_email

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if Config.SMTP_USERNAME and Config.SMTP_PASSWORD:
                    server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
                server.sendmail(msg["From"], [to_email], msg.as_string())
            logger.info("email_sent", to=to_email, subject=subject, via="smtp")
            return True
        except smtplib.SMTPAuthenticationError as exc:
            logger.error("smtp_auth_error", to=to_email, error=str(exc))
            return False
        except smtplib.SMTPConnectError as exc:
            logger.error("smtp_connect_error", to=to_email, host=Config.SMTP_HOST, error=str(exc))
            return False
        except Exception as exc:
            logger.error("smtp_send_failed", to=to_email, error=str(exc))
            return False

    # ------------------------------------------------------------------
    # 1) Daily paper-trading summary
    # ------------------------------------------------------------------

    def send_daily_summary(self, user_id: str, email: str) -> bool:
        """Send a daily paper-trading summary to *email* for *user_id*."""
        if not self._ready:
            logger.warning("email_send_skipped", reason="service not configured")
            return False

        supabase = get_supabase_client()
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        yesterday_iso = yesterday.isoformat()

        # --- Open positions ---
        positions_resp = (
            supabase.schema(SCHEMA_NAME).table("paper_portfolio")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        positions = positions_resp.data or []

        # --- Trades in last 24 h ---
        trades_resp = (
            supabase.schema(SCHEMA_NAME).table("paper_trades")
            .select("*")
            .eq("user_id", user_id)
            .gte("created_at", yesterday_iso)
            .order("created_at", desc=True)
            .execute()
        )
        trades = trades_resp.data or []

        # --- Portfolio PnL ---
        total_pnl = sum(float(p.get("unrealized_pnl", 0)) for p in positions)
        realized_pnl = sum(float(t.get("pnl", 0)) for t in trades if t.get("pnl"))

        # --- Build HTML ---
        sections: list[str] = []

        # Portfolio overview
        sections.append(
            f'<h2 style="font-size: 17px; color: #16213e; margin: 0 0 8px 0;">Portfolio Overview</h2>'
            f'<p style="margin: 0 0 4px 0;"><strong>Open positions:</strong> {len(positions)}</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Unrealized PnL:</strong> '
            f'<span style="color: {_pnl_color(total_pnl)};">{total_pnl:+,.2f} SOL</span></p>'
            f'<p style="margin: 0 0 16px 0;"><strong>Realized PnL (24 h):</strong> '
            f'<span style="color: {_pnl_color(realized_pnl)};">{realized_pnl:+,.2f} SOL</span></p>'
        )

        # Open positions table
        if positions:
            rows = ""
            for p in positions:
                pnl = float(p.get("unrealized_pnl", 0))
                rows += (
                    f'<tr>'
                    f'<td style="{_TD_STYLE}">{p.get("token_symbol", "???")}</td>'
                    f'<td style="{_TD_STYLE}">{p.get("quantity", 0)}</td>'
                    f'<td style="{_TD_STYLE}">{p.get("entry_price", 0)}</td>'
                    f'<td style="{_TD_STYLE}">{p.get("current_price", 0)}</td>'
                    f'<td style="{_TD_STYLE} color: {_pnl_color(pnl)};">{pnl:+,.4f}</td>'
                    f'</tr>'
                )
            sections.append(
                f'<h2 style="font-size: 17px; color: #16213e; margin: 0 0 8px 0;">Open Positions</h2>'
                f'<table style="{_TABLE_STYLE}">'
                f'<tr><th style="{_TH_STYLE}">Token</th><th style="{_TH_STYLE}">Qty</th>'
                f'<th style="{_TH_STYLE}">Entry</th><th style="{_TH_STYLE}">Current</th>'
                f'<th style="{_TH_STYLE}">PnL</th></tr>'
                f'{rows}</table>'
            )

        # Recent trades table
        if trades:
            rows = ""
            for t in trades:
                pnl = float(t.get("pnl", 0))
                rows += (
                    f'<tr>'
                    f'<td style="{_TD_STYLE}">{t.get("token_symbol", "???")}</td>'
                    f'<td style="{_TD_STYLE}">{t.get("side", "").upper()}</td>'
                    f'<td style="{_TD_STYLE}">{t.get("quantity", 0)}</td>'
                    f'<td style="{_TD_STYLE}">{t.get("price", 0)}</td>'
                    f'<td style="{_TD_STYLE} color: {_pnl_color(pnl)};">{pnl:+,.4f}</td>'
                    f'</tr>'
                )
            sections.append(
                f'<h2 style="font-size: 17px; color: #16213e; margin: 0 0 8px 0;">Trades (Last 24 h)</h2>'
                f'<table style="{_TABLE_STYLE}">'
                f'<tr><th style="{_TH_STYLE}">Token</th><th style="{_TH_STYLE}">Side</th>'
                f'<th style="{_TH_STYLE}">Qty</th><th style="{_TH_STYLE}">Price</th>'
                f'<th style="{_TH_STYLE}">PnL</th></tr>'
                f'{rows}</table>'
            )

        # Elite 15 activity blurb
        sections.append(
            '<h2 style="font-size: 17px; color: #16213e; margin: 0 0 8px 0;">Elite 15 Wallet Activity</h2>'
            '<p style="margin: 0 0 16px 0; color: #6b7280;">Check the app for the latest Elite wallet moves and signals.</p>'
        )

        body = "\n".join(sections)
        subject = f"Sifter KYS - Daily Summary ({now.strftime('%b %d')})"
        html = _wrap_html("Daily Paper Trading Summary", body)
        return self._send(email, subject, html)

    def send_bot_trade_open(self, email: str, trade: dict, dashboard_url: str = "") -> bool:
        """Send a bot trade-open notification email."""
        symbol = trade.get("token_ticker") or trade.get("token_symbol") or "UNKNOWN"
        token = trade.get("token_address") or ""
        amount = float(trade.get("usd_amount") or trade.get("executed_usd") or 0)
        chart = f"https://dexscreener.com/solana/{token}" if token else ""
        body = (
            f'<p style="margin: 0 0 12px 0;">The autonomous SIFTER bot entered a trade.</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Token:</strong> {symbol}</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Amount:</strong> ${amount:,.2f}</p>'
            f'<p style="margin: 0 0 16px 0;"><strong>Contract:</strong> {token}</p>'
        )
        if chart:
            body += f'<p><a href="{chart}">View chart</a></p>'
        if dashboard_url:
            body += f'<p><a href="{dashboard_url}">Manage position</a></p>'
        html = _wrap_html(f"SIFTER Bot Entered ${symbol}", body)
        return self._send(email, f"SIFTER Bot entered ${symbol}", html)

    # ------------------------------------------------------------------
    # 2) Password reset
    # ------------------------------------------------------------------

    def send_password_reset(self, email: str, reset_url: str, source: str = "dashboard") -> bool:
        """Send a password-reset email with a one-time reset link."""
        label = "SIFTER Telegram Bot" if source == "telegram" else "SIFTER Dashboard"
        body = (
            f'<p style="margin: 0 0 12px 0;">You (or someone) requested a password reset for your {label} account.</p>'
            f'<p style="margin: 0 0 16px 0;">Click the button below to set a new password. '
            f'This link expires in <strong>1 hour</strong>.</p>'
            f'<p style="margin: 16px 0;">'
            f'<a href="{reset_url}" style="background: #16213e; color: #ffffff; padding: 12px 24px; '
            f'border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-block;">'
            f'Reset My Password</a></p>'
            f'<p style="margin: 16px 0 0 0; color: #9ca3af; font-size: 12px;">'
            f'If you didn\'t request this, you can safely ignore this email.</p>'
        )
        html = _wrap_html("Reset Your Password", body)
        return self._send(email, "Reset your SIFTER password", html)

    def send_welcome(self, email: str) -> bool:
        """Send a welcome email after successful in-bot registration."""
        body = (
            '<p style="margin: 0 0 12px 0;">Welcome to <strong>SIFTER KYS</strong> — your account has been created!</p>'
            '<p style="margin: 0 0 8px 0;">Here\'s what you can do next:</p>'
            '<ul style="margin: 0 0 16px 0; padding-left: 20px;">'
            '<li>Return to Telegram and type <strong>/menu</strong> to explore the bot</li>'
            '<li>Import a trading wallet to start trading</li>'
            '<li>Configure your strategy settings</li>'
            '</ul>'
            '<p style="margin: 0;">Happy trading! 🚀</p>'
        )
        html = _wrap_html("Welcome to SIFTER KYS", body)
        return self._send(email, "Welcome to SIFTER KYS 🚀", html)

    def send_bot_trade_close(
        self, email: str, trade: dict, dashboard_url: str = ""
    ) -> bool:
        """Send a bot trade-close notification email."""
        symbol = trade.get("token_ticker") or trade.get("token_symbol") or "UNKNOWN"
        pnl = float(trade.get("realized_pnl_usd") or trade.get("pnl_usd") or 0)
        close_reason = trade.get("close_reason") or "manual"
        hold_time = trade.get("hold_time") or "—"
        pnl_color = "#10b981" if pnl > 0 else "#ef4444"
        body = (
            f'<p style="margin: 0 0 12px 0;">The SIFTER bot closed a position.</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Token:</strong> {symbol}</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Close reason:</strong> {close_reason}</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>PnL:</strong> '
            f'<span style="color: {pnl_color};">${pnl:+,.2f}</span></p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Hold time:</strong> {hold_time}</p>'
        )
        if dashboard_url:
            body += f'<p style="margin: 16px 0 0 0;"><a href="{dashboard_url}">View in dashboard</a></p>'
        html = _wrap_html("SIFTER Bot Closed Position", body)
        return self._send(email, f"SIFTER Bot closed ${symbol}", html)

    def send_bot_tp_hit(
        self, email: str, trade: dict, dashboard_url: str = ""
    ) -> bool:
        """Send a take-profit notification email."""
        symbol = trade.get("token_ticker") or trade.get("token_symbol") or "UNKNOWN"
        mult = float(trade.get("take_profit_x") or 0)
        pnl = float(trade.get("realized_pnl_usd") or 0)
        body = (
            f'<p style="margin: 0 0 12px 0;">🎯 <strong>Take Profit Hit!</strong></p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Token:</strong> {symbol}</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Multiplier:</strong> {mult:.1f}x</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>PnL:</strong> '
            f'<span style="color: #10b981;">${pnl:+,.2f}</span></p>'
        )
        if dashboard_url:
            body += f'<p style="margin: 16px 0 0 0;"><a href="{dashboard_url}">View in dashboard</a></p>'
        html = _wrap_html("SIFTER Bot — Take Profit", body)
        return self._send(email, f"🎯 Take Profit — ${symbol}", html)

    def send_bot_sl_hit(
        self, email: str, trade: dict, dashboard_url: str = ""
    ) -> bool:
        """Send a stop-loss notification email."""
        symbol = trade.get("token_ticker") or trade.get("token_symbol") or "UNKNOWN"
        pnl = float(trade.get("realized_pnl_usd") or 0)
        sl_pct = trade.get("stop_loss_pct") or "—"
        auto_blacklisted = trade.get("auto_blacklisted", False)
        body = (
            f'<p style="margin: 0 0 12px 0;">🛑 <strong>Stop Loss Hit</strong></p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Token:</strong> {symbol}</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>SL:</strong> {sl_pct}%</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>PnL:</strong> '
            f'<span style="color: #ef4444;">${pnl:+,.2f}</span></p>'
        )
        if auto_blacklisted:
            body += (
                f'<p style="margin: 12px 0 0 0; color: #ef4444;">'
                f'This token has been <strong>auto-blacklisted</strong>. '
                f'The bot will skip it on future signals.</p>'
            )
        if dashboard_url:
            body += f'<p style="margin: 16px 0 0 0;"><a href="{dashboard_url}">View in dashboard</a></p>'
        html = _wrap_html("SIFTER Bot — Stop Loss", body)
        return self._send(email, f"🛑 Stop Loss — ${symbol}", html)

    def send_bot_trailing_stop(
        self, email: str, trade: dict, dashboard_url: str = ""
    ) -> bool:
        """Send a trailing-stop notification email."""
        symbol = trade.get("token_ticker") or trade.get("token_symbol") or "UNKNOWN"
        peak = float(trade.get("peak_price_usd") or 0)
        close_price = float(trade.get("close_price_usd") or 0)
        pnl = float(trade.get("realized_pnl_usd") or 0)
        body = (
            f'<p style="margin: 0 0 12px 0;">📉 <strong>Trailing Stop Triggered</strong></p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Token:</strong> {symbol}</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Peak price:</strong> ${peak:.6f}</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>Close price:</strong> ${close_price:.6f}</p>'
            f'<p style="margin: 0 0 4px 0;"><strong>PnL:</strong> '
            f'<span style="color: {_pnl_color(pnl)};">${pnl:+,.2f}</span></p>'
        )
        if dashboard_url:
            body += f'<p style="margin: 16px 0 0 0;"><a href="{dashboard_url}">View in dashboard</a></p>'
        html = _wrap_html("SIFTER Bot — Trailing Stop", body)
        return self._send(email, f"📉 Trailing Stop — ${symbol}", html)

    # ------------------------------------------------------------------
    # 3) Error alert (to admin)
    # ------------------------------------------------------------------

    def send_error_alert(
        self,
        task_name: str,
        error_details: str,
        traceback_str: str | None = None,
    ) -> bool:
        """Send an error alert email to the admin address."""
        if not self._ready:
            logger.warning("email_send_skipped", reason="service not configured")
            return False

        if not ADMIN_EMAIL:
            logger.warning("email_send_skipped", reason="ADMIN_EMAIL not set")
            return False

        now = datetime.now(timezone.utc)
        truncated_tb = ""
        if traceback_str:
            lines = traceback_str.strip().splitlines()
            if len(lines) > 30:
                lines = lines[:10] + ["  ... truncated ..."] + lines[-15:]
            truncated_tb = (
                '<h2 style="font-size: 17px; color: #16213e; margin: 16px 0 8px 0;">Traceback</h2>'
                f'<pre style="background: #1a1a2e; color: #e2e8f0; padding: 16px; '
                f'border-radius: 8px; font-size: 12px; overflow-x: auto; white-space: pre-wrap;">'
                f'{chr(10).join(lines)}</pre>'
            )

        body = (
            f'<p style="margin: 0 0 8px 0;"><strong>Task:</strong> {task_name}</p>'
            f'<p style="margin: 0 0 8px 0;"><strong>Timestamp:</strong> {now.strftime("%Y-%m-%d %H:%M:%S UTC")}</p>'
            f'<p style="margin: 0 0 16px 0;"><strong>Error:</strong></p>'
            f'<pre style="background: #fef2f2; color: #991b1b; padding: 12px; '
            f'border-radius: 8px; font-size: 13px; white-space: pre-wrap;">{error_details}</pre>'
            f'{truncated_tb}'
        )

        subject = f"[ALERT] Sifter KYS - {task_name} failed"
        html = _wrap_html("Error Alert", body)
        return self._send(ADMIN_EMAIL, subject, html)

    # ------------------------------------------------------------------
    # 3) Paper trade execution log
    # ------------------------------------------------------------------

    def send_paper_trade_execution_log(
        self,
        email: str,
        trades: list[dict],
        summary: dict,
    ) -> bool:
        """Send a paper-trade execution log with summary stats."""
        if not self._ready:
            logger.warning("email_send_skipped", reason="service not configured")
            return False

        wins = summary.get("wins", 0)
        losses = summary.get("losses", 0)
        total_pnl = float(summary.get("total_pnl", 0))

        # Summary block
        sections: list[str] = [
            '<h2 style="font-size: 17px; color: #16213e; margin: 0 0 8px 0;">Execution Summary</h2>',
            f'<p style="margin: 0 0 4px 0;"><strong>Trades executed:</strong> {len(trades)}</p>',
            f'<p style="margin: 0 0 4px 0;"><strong>Wins / Losses:</strong> {wins} / {losses}</p>',
            f'<p style="margin: 0 0 16px 0;"><strong>Total PnL:</strong> '
            f'<span style="color: {_pnl_color(total_pnl)};">{total_pnl:+,.4f} SOL</span></p>',
        ]

        # Trades table
        if trades:
            rows = ""
            for t in trades:
                pnl = float(t.get("pnl", 0))
                rows += (
                    f'<tr>'
                    f'<td style="{_TD_STYLE}">{t.get("token_symbol", "???")}</td>'
                    f'<td style="{_TD_STYLE}">{t.get("side", "").upper()}</td>'
                    f'<td style="{_TD_STYLE}">{t.get("quantity", 0)}</td>'
                    f'<td style="{_TD_STYLE}">{t.get("price", 0)}</td>'
                    f'<td style="{_TD_STYLE} color: {_pnl_color(pnl)};">{pnl:+,.4f}</td>'
                    f'</tr>'
                )
            sections.append(
                f'<h2 style="font-size: 17px; color: #16213e; margin: 0 0 8px 0;">Trade Details</h2>'
                f'<table style="{_TABLE_STYLE}">'
                f'<tr><th style="{_TH_STYLE}">Token</th><th style="{_TH_STYLE}">Side</th>'
                f'<th style="{_TH_STYLE}">Qty</th><th style="{_TH_STYLE}">Price</th>'
                f'<th style="{_TH_STYLE}">PnL</th></tr>'
                f'{rows}</table>'
            )

        body = "\n".join(sections)
        subject = f"Sifter KYS - Trade Execution Log ({len(trades)} trades)"
        html = _wrap_html("Paper Trade Execution Log", body)
        return self._send(email, subject, html)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    """Return the singleton EmailService instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
