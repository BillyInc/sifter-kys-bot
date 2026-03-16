"""Application configuration."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration."""

    # API Keys
    TWITTER_BEARER_TOKEN = os.environ.get('TWITTER_BEARER_TOKEN', '')
    BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY', '')
    SOLANATRACKER_API_KEY = os.environ.get('SOLANATRACKER_API_KEY', '')

    # Rate limiting
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_STRATEGY = "fixed-window"
    RATELIMIT_DEFAULT = ["10000 per day", "1000 per hour"]  # ✅ Much higher

    # Analysis rate limits
    ANALYZE_RATE_LIMIT_HOUR = "5 per hour"
    ANALYZE_RATE_LIMIT_DAY = "20 per day"

    # Watchlist rate limits
    WATCHLIST_WRITE_LIMIT = "1000 per hour"
    WATCHLIST_READ_LIMIT = "60 per hour"

    # Supabase Configuration
    SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
    SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')

    # ClickHouse Analytics
    CLICKHOUSE_HOST = os.environ.get('CLICKHOUSE_HOST', 'localhost')
    CLICKHOUSE_PORT = int(os.environ.get('CLICKHOUSE_PORT', 8443))
    CLICKHOUSE_USER = os.environ.get('CLICKHOUSE_USER', 'default')
    CLICKHOUSE_PASSWORD = os.environ.get('CLICKHOUSE_PASSWORD', '')
    CLICKHOUSE_DATABASE = os.environ.get('CLICKHOUSE_DATABASE', 'kys')

    # Worker mode flag — set to true on Celery worker processes
    WORKER_MODE = os.environ.get('WORKER_MODE', 'false').lower() == 'true'

    @classmethod
    def is_clickhouse_configured(cls) -> bool:
        """Check if ClickHouse is properly configured."""
        return bool(cls.CLICKHOUSE_HOST and cls.CLICKHOUSE_PASSWORD)

    @classmethod
    def is_supabase_configured(cls) -> bool:
        """Check if Supabase is properly configured."""
        return bool(cls.SUPABASE_URL and cls.SUPABASE_SERVICE_KEY)

    @classmethod
    def is_twitter_configured(cls) -> bool:
        """Check if Twitter API is properly configured."""
        return bool(cls.TWITTER_BEARER_TOKEN) and cls.TWITTER_BEARER_TOKEN != 'your_twitter_token_here'

    @classmethod
    def is_birdeye_configured(cls) -> bool:
        """Check if Birdeye API is properly configured."""
        return bool(cls.BIRDEYE_API_KEY)

    @classmethod
    def is_solanatracker_configured(cls) -> bool:
        """Check if SolanaTracker API is properly configured."""
        return bool(cls.SOLANATRACKER_API_KEY)
