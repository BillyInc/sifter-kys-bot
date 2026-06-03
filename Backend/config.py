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
    HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")
    HELIUS_WEBHOOK_SECRET = os.environ.get("HELIUS_WEBHOOK_SECRET", "")

    # Telegram
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_OPERATOR_CHAT_IDS = [
        int(x.strip())
        for x in os.environ.get("TELEGRAM_OPERATOR_CHAT_IDS", "").split(",")
        if x.strip().isdigit()
    ]
    TELEGRAM_OPERATOR_USER_IDS = [
        int(x.strip())
        for x in os.environ.get("TELEGRAM_OPERATOR_USER_IDS", "").split(",")
        if x.strip().isdigit()
    ]
    WALLET_ENCRYPTION_SECRET = os.environ.get("WALLET_ENCRYPTION_SECRET", "")
    # Bot username (no @ prefix) for deep links, e.g. SifterTradingBot
    BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", os.environ.get("BOT_USERNAME", ""))
    MAGIC_LINK_BASE_URL = os.environ.get("MAGIC_LINK_BASE_URL", "")
    # Web dashboard URL for bot Welcome/Login/Register buttons (empty = hidden)
    DASHBOARD_URL = os.environ.get("DASHBOARD_URL", os.environ.get("FRONTEND_URL", ""))

    # Bot trade execution mode: safe_noop | paper | devnet | live
    # Defaults to safe_noop so the full UI/flows can be exercised with zero funds.
    # Real Jupiter execution + platform fees are only reachable in devnet/live.
    BOT_EXECUTION_MODE = os.environ.get("BOT_EXECUTION_MODE", "safe_noop")

    # Platform trading fee — wired but NOT applied until execution mode is devnet/live
    # AND fee_config.enabled is true. 100 bps = 1%.
    PLATFORM_FEE_BPS = int(os.environ.get("PLATFORM_FEE_BPS", "100"))
    TREASURY_WALLET_ADDRESS = os.environ.get("TREASURY_WALLET_ADDRESS", "")
    TREASURY_TOKEN_ACCOUNT = os.environ.get("TREASURY_TOKEN_ACCOUNT", "")

    # Rate limiting
    RATELIMIT_STORAGE_URI = os.environ.get("REDIS_URL", "redis://localhost:6379")
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
    CLICKHOUSE_DATABASE = os.environ.get('CLICKHOUSE_DATABASE', 'sifter-kys')

    # Email (Resend)
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
    FROM_EMAIL = os.environ.get('FROM_EMAIL', 'alerts@sifter.app')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')

    # SMTP fallback
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "")
    PAPER_TRADER_EMAIL_TO = os.environ.get("PAPER_TRADER_EMAIL_TO", "")

    # Worker mode flag — set to true on Celery worker processes
    WORKER_MODE = os.environ.get('WORKER_MODE', 'false').lower() == 'true'

    @classmethod
    def is_clickhouse_configured(cls) -> bool:
        """Check if ClickHouse is properly configured."""
        return bool(cls.CLICKHOUSE_HOST and cls.CLICKHOUSE_PASSWORD)

    @classmethod
    def is_live_execution_enabled(cls) -> bool:
        """True only when the bot is configured to submit real on-chain swaps."""
        return cls.BOT_EXECUTION_MODE == "live"

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
