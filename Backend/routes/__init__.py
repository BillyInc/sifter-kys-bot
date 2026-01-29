"""Routes module for Flask blueprints."""
from .analyze import analyze_bp
from .watchlist import watchlist_bp
from .health import health_bp

__all__ = ['analyze_bp', 'watchlist_bp', 'health_bp']
