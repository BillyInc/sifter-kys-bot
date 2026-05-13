"""SMTP-backed email digests and failure alerts for paper trading."""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Iterable, List

from services.paper_trade_runtime import get_paper_trade_runtime


class PaperTradeEmailService:
    def __init__(self):
        self.runtime = get_paper_trade_runtime()

    def _smtp_config(self) -> Dict[str, Any]:
        return {
            "host": os.environ.get("SMTP_HOST"),
            "port": int(os.environ.get("SMTP_PORT", "587")),
            "username": os.environ.get("SMTP_USERNAME"),
            "password": os.environ.get("SMTP_PASSWORD"),
            "from_email": os.environ.get("SMTP_FROM_EMAIL"),
        }

    def _recipients(self, *, failure_only: bool = False) -> List[str]:
        rows = self.runtime.get_email_recipients()
        emails = []
        for row in rows:
            if failure_only and not row.get("failure_alert_enabled", True):
                continue
            if not failure_only and not row.get("digest_enabled", True):
                continue
            email = row.get("email")
            if email:
                emails.append(email)
        return sorted(set(emails))

    def is_configured(self) -> bool:
        cfg = self._smtp_config()
        return all([cfg["host"], cfg["from_email"]])

    def send_daily_digest(self, *, summary: Dict[str, Any], failure_report: Dict[str, Any], logs: Iterable[Dict[str, Any]]) -> bool:
        recipients = self._recipients(failure_only=False)
        if not recipients or not self.is_configured():
            return False
        subject = "Paper Trader Daily Digest"
        html = self._build_digest_html(summary=summary, failure_report=failure_report, logs=list(logs))
        return self._send_html(subject=subject, html=html, recipients=recipients)

    def send_failure_alert(self, *, headline: str, summary: Dict[str, Any], logs: Iterable[Dict[str, Any]]) -> bool:
        recipients = self._recipients(failure_only=True)
        if not recipients or not self.is_configured():
            return False
        subject = f"Paper Trader Failure Alert: {headline}"
        html = self._build_failure_html(headline=headline, summary=summary, logs=list(logs))
        return self._send_html(subject=subject, html=html, recipients=recipients)

    def _send_html(self, *, subject: str, html: str, recipients: List[str]) -> bool:
        cfg = self._smtp_config()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg["from_email"]
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
                server.starttls()
                if cfg["username"] and cfg["password"]:
                    server.login(cfg["username"], cfg["password"])
                server.sendmail(cfg["from_email"], recipients, msg.as_string())
            return True
        except Exception:
            return False

    def _build_digest_html(self, *, summary: Dict[str, Any], failure_report: Dict[str, Any], logs: List[Dict[str, Any]]) -> str:
        portfolio = summary.get("portfolio", {})
        signals = summary.get("signals", {})
        skip_breakdown = summary.get("skip_breakdown", {})
        issues = failure_report.get("issues", [])
        recent_logs = logs[:10]
        rows = "".join(
            f"<tr><td style='padding:6px 10px'>{key}</td><td style='padding:6px 10px'>{value}</td></tr>"
            for key, value in skip_breakdown.items()
        ) or "<tr><td style='padding:6px 10px' colspan='2'>None</td></tr>"
        log_rows = "".join(
            f"<tr><td style='padding:6px 10px'>{row.get('created_at','')}</td><td style='padding:6px 10px'>{row.get('severity','')}</td><td style='padding:6px 10px'>{row.get('component','')}</td><td style='padding:6px 10px'>{row.get('message','')}</td></tr>"
            for row in recent_logs
        ) or "<tr><td style='padding:6px 10px' colspan='4'>No recent logs</td></tr>"
        issues_html = "".join(f"<li>{issue}</li>" for issue in issues) or "<li>No active issues</li>"
        return f"""
<html>
  <body style="font-family:Arial,sans-serif;color:#111827">
    <h2>Paper Trader Daily Digest</h2>
    <p>Runtime status, signal quality, and execution friction summary.</p>
    <h3>Portfolio</h3>
    <ul>
      <li>Starting balance: ${portfolio.get('starting_balance_usd', 0):,.2f}</li>
      <li>Available cash: ${portfolio.get('available_cash_usd', 0):,.2f}</li>
      <li>Deployed: ${portfolio.get('deployed_usd', 0):,.2f}</li>
      <li>Realized PnL: ${portfolio.get('realized_pnl_usd', 0):,.2f}</li>
      <li>Change: {portfolio.get('change_pct', 0)}%</li>
    </ul>
    <h3>Signals</h3>
    <ul>
      <li>Seen: {signals.get('seen', 0)}</li>
      <li>Entered: {signals.get('entered', 0)}</li>
      <li>Skipped: {signals.get('skipped', 0)}</li>
      <li>Open positions: {signals.get('open_positions', 0)}</li>
      <li>Closed positions: {signals.get('closed_positions', 0)}</li>
    </ul>
    <h3>Skip / Failure Breakdown</h3>
    <table border="1" cellspacing="0" cellpadding="0">{rows}</table>
    <h3>Issues</h3>
    <ul>{issues_html}</ul>
    <h3>Recent Critical Logs</h3>
    <table border="1" cellspacing="0" cellpadding="0">
      <tr><th style='padding:6px 10px'>Time</th><th style='padding:6px 10px'>Severity</th><th style='padding:6px 10px'>Component</th><th style='padding:6px 10px'>Message</th></tr>
      {log_rows}
    </table>
  </body>
</html>
"""

    def _build_failure_html(self, *, headline: str, summary: Dict[str, Any], logs: List[Dict[str, Any]]) -> str:
        portfolio = summary.get("portfolio", {})
        log_rows = "".join(
            f"<li><strong>{row.get('severity','info').upper()}</strong> [{row.get('component','')}]: {row.get('message','')}</li>"
            for row in logs[:10]
        ) or "<li>No recent logs</li>"
        return f"""
<html>
  <body style="font-family:Arial,sans-serif;color:#111827">
    <h2>{headline}</h2>
    <p>The paper trader reported a condition that needs attention.</p>
    <ul>
      <li>Available cash: ${portfolio.get('available_cash_usd', 0):,.2f}</li>
      <li>Deployed: ${portfolio.get('deployed_usd', 0):,.2f}</li>
      <li>Realized PnL: ${portfolio.get('realized_pnl_usd', 0):,.2f}</li>
      <li>Change: {portfolio.get('change_pct', 0)}%</li>
    </ul>
    <h3>Recent Logs</h3>
    <ul>{log_rows}</ul>
  </body>
</html>
"""
