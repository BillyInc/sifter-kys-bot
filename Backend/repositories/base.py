"""Abstract base classes defining the repository contracts.

Each ABC mirrors a domain boundary in the application. Route handlers and
services should depend on these interfaces, never on a concrete Supabase /
Redis / ClickHouse implementation directly.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional


# ---------------------------------------------------------------------------
# Twitter account watchlist (watchlist_accounts table)
# ---------------------------------------------------------------------------

class WatchlistRepository(ABC):
    """Twitter-account watchlist operations."""

    @abstractmethod
    def add_to_watchlist(self, user_id: str, account: dict) -> bool:
        ...

    @abstractmethod
    def get_watchlist(self, user_id: str, group_id: int | None = None) -> list[dict]:
        ...

    @abstractmethod
    def remove_from_watchlist(self, user_id: str, author_id: str) -> bool:
        ...

    @abstractmethod
    def update_account_notes(
        self, user_id: str, author_id: str,
        notes: str | None = None, tags: list[str] | None = None,
    ) -> bool:
        ...

    @abstractmethod
    def get_watchlist_stats(self, user_id: str) -> dict:
        ...

    @abstractmethod
    def get_user_groups(self, user_id: str) -> list[dict]:
        ...

    @abstractmethod
    def create_group(
        self, user_id: str, group_name: str, description: str = '',
    ) -> int | None:
        ...


# ---------------------------------------------------------------------------
# Wallet watchlist (wallet_watchlist table + premier league logic)
# ---------------------------------------------------------------------------

class WalletWatchlistRepository(ABC):
    """Solana wallet watchlist CRUD and Premier League table."""

    @abstractmethod
    def add_wallet(self, user_id: str, wallet_data: dict) -> bool:
        ...

    @abstractmethod
    def get_wallet_watchlist(
        self, user_id: str, tier_filter: str | None = None,
    ) -> list[dict]:
        ...

    @abstractmethod
    def remove_wallet(self, user_id: str, wallet_address: str) -> bool:
        ...

    @abstractmethod
    def update_wallet_notes(
        self, user_id: str, wallet_address: str,
        notes: str | None = None, tags: list[str] | None = None,
    ) -> bool:
        ...

    @abstractmethod
    def update_wallet_alert_settings(
        self, user_id: str, wallet_address: str,
        alert_enabled: bool | None = None,
        alert_threshold_usd: float | None = None,
    ) -> bool:
        ...

    @abstractmethod
    def get_wallet_watchlist_stats(self, user_id: str) -> dict:
        ...

    @abstractmethod
    def get_premier_league_table(self, user_id: str) -> dict:
        ...

    @abstractmethod
    def save_position_snapshot(self, user_id: str) -> bool:
        ...

    @abstractmethod
    def wallet_exists(self, user_id: str, wallet_address: str) -> bool:
        ...

    @abstractmethod
    def add_wallet_raw(self, user_id: str, data: dict) -> bool:
        """Insert a fully-formed wallet row (used by route-level custom inserts)."""
        ...

    @abstractmethod
    def get_wallet_watchlist_columns(
        self, user_id: str, columns: str, tier_filter: str | None = None,
    ) -> list[dict]:
        """Select specific columns from wallet_watchlist."""
        ...

    @abstractmethod
    def get_wallet_field(
        self, user_id: str, wallet_address: str, field: str,
    ) -> object | None:
        """Return a single field value for a wallet, or None if not found."""
        ...

    @abstractmethod
    def update_wallet_fields(
        self, user_id: str, wallet_address: str, data: dict,
    ) -> bool:
        """Update arbitrary fields on a wallet watchlist row."""
        ...


# ---------------------------------------------------------------------------
# Notifications (wallet_notifications table)
# ---------------------------------------------------------------------------

class NotificationRepository(ABC):

    @abstractmethod
    def add_notification(
        self, user_id: str, wallet_address: str,
        notification_type: str, title: str,
        message: str = '', metadata: dict | None = None,
    ) -> bool:
        ...

    @abstractmethod
    def get_notifications(
        self, user_id: str, unread_only: bool = False, limit: int = 50,
    ) -> list[dict]:
        ...

    @abstractmethod
    def get_unread_count(self, user_id: str) -> int:
        ...

    @abstractmethod
    def mark_notification_read(self, user_id: str, notification_id: int) -> bool:
        ...

    @abstractmethod
    def mark_all_notifications_read(self, user_id: str) -> bool:
        ...


# ---------------------------------------------------------------------------
# Analysis jobs (analysis_jobs table)
# ---------------------------------------------------------------------------

class AnalysisJobRepository(ABC):

    @abstractmethod
    def create_job(self, job_id: str, user_id: str, job_data: dict) -> dict:
        """Insert a new analysis job row. *job_data* contains extra columns
        like tokens_total, token_address, etc."""
        ...

    @abstractmethod
    def get_job(self, job_id: str) -> dict | None:
        ...

    @abstractmethod
    def get_job_progress(self, job_id: str) -> dict | None:
        """Return a slim projection: status, progress, phase, tokens_total,
        tokens_completed."""
        ...

    @abstractmethod
    def update_job(self, job_id: str, data: dict) -> bool:
        ...


# ---------------------------------------------------------------------------
# Users (users table)
# ---------------------------------------------------------------------------

class UserRepository(ABC):

    @abstractmethod
    def get_user(self, user_id: str) -> dict | None:
        ...

    @abstractmethod
    def create_user(self, user_id: str, wallet_address: str | None = None) -> bool:
        ...

    @abstractmethod
    def get_subscription_tier(self, user_id: str) -> str:
        """Return the subscription tier string ('free', 'pro', 'elite').
        Defaults to 'free' when the user is not found."""
        ...


# ---------------------------------------------------------------------------
# User settings (user_settings table)
# ---------------------------------------------------------------------------

class UserSettingsRepository(ABC):

    @abstractmethod
    def get_settings(self, user_id: str) -> dict | None:
        ...

    @abstractmethod
    def save_settings(self, user_id: str, settings: dict) -> bool:
        ...


# ---------------------------------------------------------------------------
# Analysis history (user_analysis_history table)
# ---------------------------------------------------------------------------

class AnalysisHistoryRepository(ABC):

    @abstractmethod
    def get_history(self, user_id: str, limit: int = 50) -> list[dict]:
        ...

    @abstractmethod
    def save_entry(self, user_id: str, entry: dict) -> bool:
        ...

    @abstractmethod
    def delete_entry(self, user_id: str, entry_id: str) -> bool:
        ...

    @abstractmethod
    def clear_all(self, user_id: str) -> bool:
        ...


# ---------------------------------------------------------------------------
# Support tickets (support_tickets table)
# ---------------------------------------------------------------------------

class SupportTicketRepository(ABC):

    @abstractmethod
    def create_ticket(
        self, user_id: str, subject: str, message: str,
    ) -> bool:
        ...


# ---------------------------------------------------------------------------
# Referral & Points (referral_codes, referrals, referral_earnings,
#                    point_transactions tables)
# ---------------------------------------------------------------------------

class ReferralRepository(ABC):

    @abstractmethod
    def get_referral_code_stats(self, code: str) -> dict | None:
        """Return clicks/signups/conversions for a referral code."""
        ...

    @abstractmethod
    def validate_referral_code(self, code: str) -> dict | None:
        """Return code row if active, else None."""
        ...

    @abstractmethod
    def get_referrals_by_referrer(self, user_id: str) -> list[dict]:
        ...

    @abstractmethod
    def get_earnings_by_referrer(self, user_id: str) -> list[dict]:
        ...

    @abstractmethod
    def get_point_transactions(
        self, user_id: str, limit: int = 50,
    ) -> list[dict]:
        ...


# ---------------------------------------------------------------------------
# Telegram (telegram_connection_tokens table)
# ---------------------------------------------------------------------------

class TelegramRepository(ABC):

    @abstractmethod
    def delete_unused_tokens(self, user_id: str) -> bool:
        ...

    @abstractmethod
    def create_connection_token(
        self, user_id: str, token: str, expires_at: str,
    ) -> bool:
        ...


# ---------------------------------------------------------------------------
# Diary (watchlist_diary, diary_user_salt tables)
# ---------------------------------------------------------------------------

class DiaryRepository(ABC):

    @abstractmethod
    def get_salt(self, user_id: str) -> dict | None:
        """Return {salt_b64, verification_token} or None."""
        ...

    @abstractmethod
    def save_salt(
        self, user_id: str, salt_b64: str, verification_token: str,
    ) -> dict:
        """If salt already exists return it, else insert and return new row."""
        ...

    @abstractmethod
    def list_notes(
        self, user_id: str,
        wallet_address: str | None = None,
        note_type: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        ...

    @abstractmethod
    def create_note(
        self, user_id: str,
        encrypted_payload: str,
        note_type: str = 'note',
        wallet_address: str | None = None,
    ) -> dict | None:
        """Return the inserted row (with id) or None."""
        ...

    @abstractmethod
    def update_note(
        self, user_id: str, note_id: str,
        encrypted_payload: str,
        note_type: str | None = None,
    ) -> bool:
        ...

    @abstractmethod
    def delete_note(self, user_id: str, note_id: str) -> bool:
        ...

    @abstractmethod
    def note_exists(self, user_id: str, note_id: str) -> bool:
        ...

    @abstractmethod
    def clear_all_notes(self, user_id: str) -> bool:
        ...
