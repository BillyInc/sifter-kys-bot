"""Dependency injection registry for repository instances.

Usage in routes / services:

    from repositories.registry import get_watchlist_repo
    repo = get_watchlist_repo()
    accounts = repo.get_watchlist(user_id)

Usage in tests:

    from repositories.registry import set_watchlist_repo
    set_watchlist_repo(FakeWatchlistRepo())   # inject mock
"""
from __future__ import annotations

from repositories.base import (
    WatchlistRepository,
    WalletWatchlistRepository,
    NotificationRepository,
    AnalysisJobRepository,
    UserRepository,
    UserSettingsRepository,
    AnalysisHistoryRepository,
    SupportTicketRepository,
    ReferralRepository,
    TelegramRepository,
    DiaryRepository,
)

# ---------------------------------------------------------------------------
# Internal singleton slots — lazily populated on first access.
# ---------------------------------------------------------------------------

_watchlist_repo: WatchlistRepository | None = None
_wallet_watchlist_repo: WalletWatchlistRepository | None = None
_notification_repo: NotificationRepository | None = None
_analysis_job_repo: AnalysisJobRepository | None = None
_user_repo: UserRepository | None = None
_user_settings_repo: UserSettingsRepository | None = None
_analysis_history_repo: AnalysisHistoryRepository | None = None
_support_ticket_repo: SupportTicketRepository | None = None
_referral_repo: ReferralRepository | None = None
_telegram_repo: TelegramRepository | None = None
_diary_repo: DiaryRepository | None = None


# ---------------------------------------------------------------------------
# Getters (lazy-init with Supabase defaults)
# ---------------------------------------------------------------------------

def get_watchlist_repo() -> WatchlistRepository:
    global _watchlist_repo
    if _watchlist_repo is None:
        from repositories.supabase_repos import SupabaseWatchlistRepo
        _watchlist_repo = SupabaseWatchlistRepo()
    return _watchlist_repo


def get_wallet_watchlist_repo() -> WalletWatchlistRepository:
    global _wallet_watchlist_repo
    if _wallet_watchlist_repo is None:
        from repositories.supabase_repos import SupabaseWalletWatchlistRepo
        _wallet_watchlist_repo = SupabaseWalletWatchlistRepo()
    return _wallet_watchlist_repo


def get_notification_repo() -> NotificationRepository:
    global _notification_repo
    if _notification_repo is None:
        from repositories.supabase_repos import SupabaseNotificationRepo
        _notification_repo = SupabaseNotificationRepo()
    return _notification_repo


def get_analysis_job_repo() -> AnalysisJobRepository:
    global _analysis_job_repo
    if _analysis_job_repo is None:
        from repositories.supabase_repos import SupabaseAnalysisJobRepo
        _analysis_job_repo = SupabaseAnalysisJobRepo()
    return _analysis_job_repo


def get_user_repo() -> UserRepository:
    global _user_repo
    if _user_repo is None:
        from repositories.supabase_repos import SupabaseUserRepo
        _user_repo = SupabaseUserRepo()
    return _user_repo


def get_user_settings_repo() -> UserSettingsRepository:
    global _user_settings_repo
    if _user_settings_repo is None:
        from repositories.supabase_repos import SupabaseUserSettingsRepo
        _user_settings_repo = SupabaseUserSettingsRepo()
    return _user_settings_repo


def get_analysis_history_repo() -> AnalysisHistoryRepository:
    global _analysis_history_repo
    if _analysis_history_repo is None:
        from repositories.supabase_repos import SupabaseAnalysisHistoryRepo
        _analysis_history_repo = SupabaseAnalysisHistoryRepo()
    return _analysis_history_repo


def get_support_ticket_repo() -> SupportTicketRepository:
    global _support_ticket_repo
    if _support_ticket_repo is None:
        from repositories.supabase_repos import SupabaseSupportTicketRepo
        _support_ticket_repo = SupabaseSupportTicketRepo()
    return _support_ticket_repo


def get_referral_repo() -> ReferralRepository:
    global _referral_repo
    if _referral_repo is None:
        from repositories.supabase_repos import SupabaseReferralRepo
        _referral_repo = SupabaseReferralRepo()
    return _referral_repo


def get_telegram_repo() -> TelegramRepository:
    global _telegram_repo
    if _telegram_repo is None:
        from repositories.supabase_repos import SupabaseTelegramRepo
        _telegram_repo = SupabaseTelegramRepo()
    return _telegram_repo


def get_diary_repo() -> DiaryRepository:
    global _diary_repo
    if _diary_repo is None:
        from repositories.supabase_repos import SupabaseDiaryRepo
        _diary_repo = SupabaseDiaryRepo()
    return _diary_repo


# ---------------------------------------------------------------------------
# Setters (for dependency injection in tests)
# ---------------------------------------------------------------------------

def set_watchlist_repo(repo: WatchlistRepository) -> None:
    global _watchlist_repo
    _watchlist_repo = repo


def set_wallet_watchlist_repo(repo: WalletWatchlistRepository) -> None:
    global _wallet_watchlist_repo
    _wallet_watchlist_repo = repo


def set_notification_repo(repo: NotificationRepository) -> None:
    global _notification_repo
    _notification_repo = repo


def set_analysis_job_repo(repo: AnalysisJobRepository) -> None:
    global _analysis_job_repo
    _analysis_job_repo = repo


def set_user_repo(repo: UserRepository) -> None:
    global _user_repo
    _user_repo = repo


def set_user_settings_repo(repo: UserSettingsRepository) -> None:
    global _user_settings_repo
    _user_settings_repo = repo


def set_analysis_history_repo(repo: AnalysisHistoryRepository) -> None:
    global _analysis_history_repo
    _analysis_history_repo = repo


def set_support_ticket_repo(repo: SupportTicketRepository) -> None:
    global _support_ticket_repo
    _support_ticket_repo = repo


def set_referral_repo(repo: ReferralRepository) -> None:
    global _referral_repo
    _referral_repo = repo


def set_telegram_repo(repo: TelegramRepository) -> None:
    global _telegram_repo
    _telegram_repo = repo


def set_diary_repo(repo: DiaryRepository) -> None:
    global _diary_repo
    _diary_repo = repo


def reset_all() -> None:
    """Reset every slot to None. Useful in test teardown."""
    global _watchlist_repo, _wallet_watchlist_repo, _notification_repo
    global _analysis_job_repo, _user_repo, _user_settings_repo
    global _analysis_history_repo, _support_ticket_repo, _referral_repo
    global _telegram_repo, _diary_repo

    _watchlist_repo = None
    _wallet_watchlist_repo = None
    _notification_repo = None
    _analysis_job_repo = None
    _user_repo = None
    _user_settings_repo = None
    _analysis_history_repo = None
    _support_ticket_repo = None
    _referral_repo = None
    _telegram_repo = None
    _diary_repo = None
