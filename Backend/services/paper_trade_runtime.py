"""Runtime state, structured logs, and operator access helpers for paper trading."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from services.supabase_client import SCHEMA_NAME, get_supabase_client


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaperTradeRuntime:
    def __init__(self):
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME

    def _table(self, name: str):
        return self.supabase.schema(self.schema).table(name)

    def _default_settings(self) -> Dict[str, Any]:
        return {
            "id": True,
            "paper_trader_enabled": False,
            "execution_mode": "paper",
            "quote_ttl_seconds": 15,
            "min_liquidity_usd": 10_000,
            "max_price_impact_bps": int(os.environ.get("PAPER_TRADER_MAX_PRICE_IMPACT_BPS", "500")),
            "default_slippage_bps": int(os.environ.get("DEFAULT_SLIPPAGE_BPS", "250")),
            "default_priority_fee_lamports": int(os.environ.get("DEFAULT_PRIORITY_FEE_LAMPORTS", "500000")),
            "max_retry_count": 2,
            "latency_ms": 1500,
            "partial_fill_probability": 0.15,
            "route_failure_probability": 0.08,
            "no_route_probability": 0.05,
            "email_digest_enabled": True,
            "immediate_failure_alerts": True,
        }

    def get_settings(self) -> Dict[str, Any]:
        try:
            result = self._table("paper_trader_settings").select("*").eq("id", True).limit(1).execute()
            if result.data:
                return {**self._default_settings(), **result.data[0]}
            self._table("paper_trader_settings").upsert(self._default_settings()).execute()
        except Exception:
            pass
        return self._default_settings()

    def patch_settings(self, patch: Dict[str, Any], updated_by: str | None = None) -> Dict[str, Any]:
        payload = {k: v for k, v in patch.items() if v is not None}
        payload["updated_at"] = _utc_now_iso()
        if updated_by:
            payload["updated_by"] = updated_by
        try:
            self._table("paper_trader_settings").upsert({"id": True, **payload}).execute()
        except Exception:
            return self.get_settings()
        return self.get_settings()

    def get_active_run(self) -> Optional[Dict[str, Any]]:
        try:
            result = (
                self._table("paper_trade_runs")
                .select("*")
                .eq("status", "running")
                .order("started_at", desc=True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception:
            return None

    def start_run(self, started_by: str | None = None, source: str = "operator") -> Dict[str, Any]:
        active = self.get_active_run()
        if active:
            self.stop_run(stopped_by=started_by, reason="restarted")
        payload = {
            "status": "running",
            "source": source,
            "started_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "started_by": started_by,
            "summary": {},
        }
        try:
            result = self._table("paper_trade_runs").insert(payload).execute()
            run = result.data[0] if result.data else payload
        except Exception:
            run = payload
        self.patch_settings({"paper_trader_enabled": True}, updated_by=started_by)
        self.log(
            severity="info",
            component="operator",
            event_type="paper_trader_started",
            status="ok",
            message="Paper trader started",
            run_id=run.get("id"),
            payload={"source": source, "started_by": started_by},
        )
        return run

    def stop_run(self, stopped_by: str | None = None, reason: str = "operator_stop") -> Optional[Dict[str, Any]]:
        active = self.get_active_run()
        self.patch_settings({"paper_trader_enabled": False}, updated_by=stopped_by)
        if not active:
            self.log(
                severity="warning",
                component="operator",
                event_type="paper_trader_stop_without_run",
                status="noop",
                message="Stop requested with no active paper run",
                payload={"stopped_by": stopped_by, "reason": reason},
            )
            return None
        update = {
            "status": "stopped",
            "stopped_at": _utc_now_iso(),
            "stopped_by": stopped_by,
            "updated_at": _utc_now_iso(),
        }
        try:
            self._table("paper_trade_runs").update(update).eq("id", active["id"]).execute()
        except Exception:
            pass
        self.log(
            severity="info",
            component="operator",
            event_type="paper_trader_stopped",
            status="ok",
            message="Paper trader stopped",
            run_id=active.get("id"),
            payload={"stopped_by": stopped_by, "reason": reason},
        )
        active.update(update)
        return active

    def update_active_run_summary(self, summary: Dict[str, Any]):
        active = self.get_active_run()
        if not active:
            return
        try:
            self._table("paper_trade_runs").update(
                {"summary": summary, "updated_at": _utc_now_iso()}
            ).eq("id", active["id"]).execute()
        except Exception:
            return

    def log(
        self,
        *,
        severity: str,
        component: str,
        event_type: str,
        message: str,
        status: str | None = None,
        signal_key: str | None = None,
        token_address: str | None = None,
        payload: Dict[str, Any] | None = None,
        run_id: str | None = None,
    ):
        active = self.get_active_run()
        row = {
            "run_id": run_id or (active or {}).get("id"),
            "severity": severity,
            "component": component,
            "event_type": event_type,
            "status": status,
            "signal_key": signal_key,
            "token_address": token_address,
            "message": message,
            "payload": payload or {},
        }
        try:
            self._table("paper_trade_logs").insert(row).execute()
        except Exception:
            return

    def recent_logs(self, limit: int = 50, severity: str | None = None) -> List[Dict[str, Any]]:
        try:
            query = self._table("paper_trade_logs").select("*").order("created_at", desc=True).limit(limit)
            if severity:
                query = query.eq("severity", severity)
            result = query.execute()
            return result.data or []
        except Exception:
            return []

    def get_email_recipients(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            rows = (
                self._table("paper_trade_email_recipients")
                .select("*")
                .order("email")
                .execute()
                .data
                or []
            )
        except Exception:
            rows = []

        env_emails = [email.strip() for email in os.environ.get("PAPER_TRADER_EMAIL_TO", "").split(",") if email.strip()]
        known = {row["email"].lower() for row in rows}
        for email in env_emails:
            if email.lower() not in known:
                rows.append(
                    {
                        "id": None,
                        "email": email,
                        "digest_enabled": True,
                        "failure_alert_enabled": True,
                        "source": "env",
                    }
                )
        return rows

    def replace_email_recipients(self, recipients: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned = []
        for row in recipients:
            email = (row.get("email") or "").strip().lower()
            if not email:
                continue
            cleaned.append(
                {
                    "email": email,
                    "digest_enabled": bool(row.get("digest_enabled", True)),
                    "failure_alert_enabled": bool(row.get("failure_alert_enabled", True)),
                    "updated_at": _utc_now_iso(),
                }
            )
        try:
            existing = self._table("paper_trade_email_recipients").select("email").execute().data or []
            existing_set = {row["email"] for row in existing}
            incoming_set = {row["email"] for row in cleaned}
            for email in existing_set - incoming_set:
                self._table("paper_trade_email_recipients").delete().eq("email", email).execute()
            for row in cleaned:
                self._table("paper_trade_email_recipients").upsert(row).execute()
        except Exception:
            pass
        return self.get_email_recipients()

    def get_status(self) -> Dict[str, Any]:
        settings = self.get_settings()
        active_run = self.get_active_run()
        logs = self.recent_logs(limit=10)
        critical_count = len([row for row in logs if (row.get("severity") or "").lower() in {"error", "critical"}])
        return {
            "settings": settings,
            "active_run": active_run,
            "recent_logs": logs,
            "critical_count": critical_count,
        }


_runtime: PaperTradeRuntime | None = None


def get_paper_trade_runtime() -> PaperTradeRuntime:
    global _runtime
    if _runtime is None:
        _runtime = PaperTradeRuntime()
    return _runtime


def _parse_csv_env(name: str) -> set[str]:
    return {item.strip() for item in os.environ.get(name, "").split(",") if item.strip()}


def is_operator_chat_id(chat_id: str | None) -> bool:
    if not chat_id:
        return False
    return chat_id in _parse_csv_env("TELEGRAM_OPERATOR_CHAT_IDS")


def is_operator_user(user_id: str | None) -> bool:
    if not user_id:
        return False
    env_user_ids = _parse_csv_env("TELEGRAM_OPERATOR_USER_IDS")
    if user_id in env_user_ids:
        return True
    try:
        result = (
            get_supabase_client()
            .schema(SCHEMA_NAME)
            .table("users")
            .select("subscription_tier")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return False
        tier = (result.data[0].get("subscription_tier") or "").lower()
        return tier in {"admin", "owner"}
    except Exception:
        return False
