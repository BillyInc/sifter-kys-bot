"""
Cron job entry points for external scheduling
Run these via system crontab or APScheduler
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from services.watchlist_stats_updater import get_updater


def run_daily_stats_refresh():
    """Daily stats refresh at 3am UTC"""
    with app.app_context():
        print("\n[CRON] Running daily stats refresh...")
        updater = get_updater()
        result = updater.daily_stats_refresh()
        print(f"[CRON] Daily refresh complete: {result}")


def run_weekly_rerank():
    """Weekly reranking on Sunday at 4am UTC"""
    with app.app_context():
        print("\n[CRON] Running weekly rerank...")
        updater = get_updater()
        result = updater.weekly_rerank_all()
        print(f"[CRON] Weekly rerank complete: {result}")


def run_four_week_check():
    """4-week degradation check every 28 days at 5am UTC"""
    with app.app_context():
        print("\n[CRON] Running 4-week degradation check...")
        updater = get_updater()
        result = updater.four_week_degradation_check()
        print(f"[CRON] 4-week check complete: {result}")


def refresh_ath_cache_hourly():
    """Run hourly to update token ATH cache"""
    from services.supabase_client import get_supabase_client
    
    with app.app_context():
        supabase = get_supabase_client()
        supabase.rpc('refresh_ath_cache').execute()
        print("[CRON] ATH cache refreshed")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python cron_jobs.py [daily|weekly|four_week|refresh_ath]")
        sys.exit(1)
    
    job_type = sys.argv[1]
    
    if job_type == 'daily':
        run_daily_stats_refresh()
    elif job_type == 'weekly':
        run_weekly_rerank()
    elif job_type == 'four_week':
        run_four_week_check()
    elif job_type == 'refresh_ath':
        refresh_ath_cache_hourly()
    else:
        print(f"Unknown job type: {job_type}")
        print("Valid types: daily, weekly, four_week, refresh_ath")
        sys.exit(1)

# Schedule with system cron:
# 0 3 * * * python /path/to/backend/cron_jobs.py daily
# 0 4 * * 0 python /path/to/backend/cron_jobs.py weekly
# 0 5 */28 * * python /path/to/backend/cron_jobs.py four_week
# 0 * * * * python /path/to/backend/cron_jobs.py refresh_ath