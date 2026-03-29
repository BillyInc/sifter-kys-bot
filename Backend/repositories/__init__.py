"""Repository pattern interfaces and implementations for data access."""
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

__all__ = [
    'WatchlistRepository',
    'WalletWatchlistRepository',
    'NotificationRepository',
    'AnalysisJobRepository',
    'UserRepository',
    'UserSettingsRepository',
    'AnalysisHistoryRepository',
    'SupportTicketRepository',
    'ReferralRepository',
    'TelegramRepository',
    'DiaryRepository',
]
