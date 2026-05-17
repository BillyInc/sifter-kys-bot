"""
Alert Router — severity-based notification dispatch for the trading pipeline.

Severity levels:
  P0 (Critical)  → Instant Telegram to operator + immediate email (< 60s)
  P1 (High)      → Telegram to operator within the minute
  P2 (Medium)    → Buffered to daily digest email
  P3 (Low)       → Log file only

Usage:
    from services.alert_router import alert, P0, P1, P2, P3

    alert(P0, "TRADE", "Duplicate trade executed",
          details={"user_id": uid, "signal_key": sk, "token": token})

    alert(P1, "EXIT_CHECKER", "Exit checker not running for 10+ minutes")

    alert(P2, "DIGEST", "Daily digest sent successfully",
          details={"sent": 5, "errors": 0})
"""

import json
import logging
import os
import smtplib
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

# ── Severity constants ────────────────────────────────────────────────────

P0 = "P0"  # Critical — instant Telegram + email
P1 = "P1"  # High — Telegram to operator
P2 = "P2"  # Medium — daily digest buffer
P3 = "P3"  # Low — log only


# ── Rate limiting to prevent alert storms ─────────────────────────────────

_last_alert_times: dict = {}  # key → timestamp
_COOLDOWN_SECONDS = {
    P0: 60,    # Max once per minute per unique key
    P1: 300,   # Max once per 5 min
    P2: 3600,  # Max once per hour
    P3: 0,     # No limit (log only)
}


def _is_rate_limited(severity: str, category: str, message: str) -> bool:
    """Prevent alert storms by rate-limiting per (severity, category, message)."""
    key = f"{severity}:{category}:{message[:50]}"
    cooldown = _COOLDOWN_SECONDS.get(severity, 60)
    if cooldown == 0:
        return False

    now = time.time()
    last = _last_alert_times.get(key, 0)
    if now - last < cooldown:
        return True

    _last_alert_times[key] = now
    return False


# ── Alert dispatch ────────────────────────────────────────────────────────

def alert(
    severity: str,
    category: str,
    message: str,
    details: Optional[dict] = None,
) -> None:
    """
    Route an alert based on severity.

    Args:
        severity: P0, P1, P2, or P3
        category: Short label (TRADE, SIGNAL, EXIT_CHECKER, REDIS, SUPABASE, etc.)
        message: Human-readable description
        details: Optional dict with context (user_id, token, error, etc.)
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    detail_str = ""
    if details:
        # Sanitize — never log secrets or full keys
        safe = {k: v for k, v in details.items()
                if k not in ("private_key", "encrypted_key", "password", "secret")}
        # Truncate long values
        for k, v in safe.items():
            if isinstance(v, str) and len(v) > 100:
                safe[k] = v[:100] + "..."
        detail_str = f" | {json.dumps(safe, default=str)}"

    log_line = f"[{severity}] [{category}] {message}{detail_str}"

    # Always log
    if severity == P0:
        logger.critical(log_line)
    elif severity == P1:
        logger.error(log_line)
    elif severity == P2:
        logger.warning(log_line)
    else:
        logger.info(log_line)

    # Rate limit check
    if _is_rate_limited(severity, category, message):
        return

    # Route by severity
    if severity == P0:
        _send_telegram_to_operators(f"🚨 *{severity} — {category}*\n\n{message}{detail_str}")
        _send_instant_email(
            subject=f"[{severity}] {category}: {message[:60]}",
            body=f"Severity: {severity}\nCategory: {category}\nTime: {timestamp}\n\n{message}\n\nDetails:\n{json.dumps(details or {}, indent=2, default=str)}",
        )

    elif severity == P1:
        _send_telegram_to_operators(f"⚠️ *{severity} — {category}*\n\n{message}{detail_str}")

    elif severity == P2:
        _buffer_for_digest(severity, category, message, details, timestamp)

    # P3 = log only, already done above


# ── Telegram dispatch ─────────────────────────────────────────────────────

def _send_telegram_to_operators(text: str) -> None:
    """Send alert to all operator Telegram chats."""
    try:
        import requests
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            logger.warning("[ALERT] No TELEGRAM_BOT_TOKEN — skipping Telegram alert")
            return

        from config import Config
        chat_ids = Config.TELEGRAM_OPERATOR_CHAT_IDS or []

        if not chat_ids:
            logger.warning("[ALERT] No TELEGRAM_OPERATOR_CHAT_IDS configured")
            return

        for chat_id in chat_ids:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text[:4000],  # Telegram limit
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                    timeout=10,
                )
            except Exception as e:
                logger.error(f"[ALERT] Failed to send Telegram to {chat_id}: {e}")

    except Exception as e:
        logger.error(f"[ALERT] Telegram dispatch error: {e}")


# ── Email dispatch ────────────────────────────────────────────────────────

def _send_instant_email(subject: str, body: str) -> None:
    """Send immediate email for P0 alerts."""
    try:
        smtp_host = os.environ.get("SMTP_HOST", "")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USERNAME", "")
        smtp_pass = os.environ.get("SMTP_PASSWORD", "")
        from_email = os.environ.get("SMTP_FROM_EMAIL", "") or os.environ.get("FROM_EMAIL", "")
        to_email = os.environ.get("PAPER_TRADER_EMAIL_TO", "") or os.environ.get("ADMIN_EMAIL", "")

        if not all([smtp_host, smtp_user, smtp_pass, from_email, to_email]):
            # Try Resend as fallback
            _send_instant_email_resend(subject, body, to_email or from_email)
            return

        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, [to_email], msg.as_string())

        logger.info(f"[ALERT] P0 email sent to {to_email}: {subject}")

    except Exception as e:
        logger.error(f"[ALERT] Email send failed: {e}")


def _send_instant_email_resend(subject: str, body: str, to_email: str) -> None:
    """Fallback: send via Resend API."""
    try:
        api_key = os.environ.get("RESEND_API_KEY", "")
        from_email = os.environ.get("FROM_EMAIL", "alerts@sifter.app")
        if not api_key or not to_email:
            logger.warning("[ALERT] No email config (SMTP or Resend) — P0 email skipped")
            return

        import resend
        resend.api_key = api_key
        resend.Emails.send({
            "from": from_email,
            "to": to_email,
            "subject": subject,
            "text": body,
        })
        logger.info(f"[ALERT] P0 email sent via Resend to {to_email}")

    except Exception as e:
        logger.error(f"[ALERT] Resend email failed: {e}")


# ── Digest buffer ─────────────────────────────────────────────────────────

def _buffer_for_digest(severity: str, category: str, message: str,
                       details: Optional[dict], timestamp: str) -> None:
    """Buffer P2 alerts in Redis for the daily digest."""
    try:
        import redis as redis_lib
        r = redis_lib.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        entry = json.dumps({
            "severity": severity,
            "category": category,
            "message": message,
            "details": details,
            "timestamp": timestamp,
        }, default=str)
        r.rpush("sifter:alert_digest_buffer", entry)
        r.expire("sifter:alert_digest_buffer", 86400 * 2)  # 2 day TTL
    except Exception as e:
        logger.error(f"[ALERT] Failed to buffer digest alert: {e}")


def flush_digest_buffer() -> list:
    """Flush all buffered P2 alerts (called by daily digest task)."""
    try:
        import redis as redis_lib
        r = redis_lib.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        items = r.lrange("sifter:alert_digest_buffer", 0, -1)
        if items:
            r.delete("sifter:alert_digest_buffer")
        return [json.loads(item) for item in items]
    except Exception as e:
        logger.error(f"[ALERT] Failed to flush digest buffer: {e}")
        return []
