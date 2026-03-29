"""Repository pattern interfaces and implementations for data access."""
from repositories.base import (
    WatchlistRepository,
    WalletWatchlistRepository,
    NotificationRepository,
    AnalysisJobRepository,
    UserRepository,
    UserSettingsRepository,
    AnalysisHistoryRepository,
)

__all__ = [
    'WatchlistRepository',
    'WalletWatchlistRepository',
    'NotificationRepository',
    'AnalysisJobRepository',
    'UserRepository',
    'UserSettingsRepository',
    'AnalysisHistoryRepository',
]
