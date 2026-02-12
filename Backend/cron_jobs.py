"""
Cron job entry points for external scheduling
Run these via system crontab
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from services import rerank_all_watchlists, track_weekly_performance


def run_daily_rerank():
    """Entry point for daily reranking cron job"""
    with app.app_context():
        rerank_all_watchlists()


def run_weekly_tracking():
    """Entry point for weekly tracking cron job"""
    with app.app_context():
        track_weekly_performance()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python cron_jobs.py [daily|weekly]")
        sys.exit(1)
    
    job_type = sys.argv[1]
    
    if job_type == 'daily':
        run_daily_rerank()
    elif job_type == 'weekly':
        run_weekly_tracking()
    else:
        print(f"Unknown job type: {job_type}")
        sys.exit(1)