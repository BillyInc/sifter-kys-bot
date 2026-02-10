"""Services module for business logic."""
from .token_analyzer import TokenAnalyzerService
from .wallet_analyzer import WalletPumpAnalyzer
from .wallet_monitor import WalletActivityMonitor
from .telegram_notifier import TelegramNotifier  # ← ADD THIS 
from .wallet_analyzer import WalletPumpAnalyzer
import os  # Add this



__all__ = [
    'TokenAnalyzerService',
    'WalletPumpAnalyzer',
    'WalletActivityMonitor',
    'TelegramNotifier'  # ← ADD THIS LINE

    
]
def preload_trending_cache_parallel():
    analyzer = WalletPumpAnalyzer(
        solanatracker_api_key=os.getenv('SOLANATRACKER_API_KEY'),
        birdeye_api_key=os.getenv('BIRDEYE_API_KEY')
    )
    analyzer.preload_trending_cache()