"""
Celery configuration with Beat scheduler for production-grade cron jobs
"""
from celery import Celery
from celery.schedules import crontab
import os

# Initialize Celery
celery = Celery(
    'sifter_tasks',
    broker=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
    backend=os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
)

# Celery configuration
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

# Beat schedule - Production cron jobs
celery.conf.beat_schedule = {
    # Daily stats refresh at 3am UTC
    'daily-stats-refresh': {
        'task': 'tasks.daily_stats_refresh',
        'schedule': crontab(hour=3, minute=0),
        'options': {'expires': 3600}
    },
    
    # Weekly rerank on Sunday at 4am UTC
    'weekly-rerank': {
        'task': 'tasks.weekly_rerank_all',
        'schedule': crontab(day_of_week='sunday', hour=4, minute=0),
        'options': {'expires': 7200}
    },
    
    # 4-week degradation check every 28 days at 5am UTC
    'four-week-degradation': {
        'task': 'tasks.four_week_degradation_check',
        'schedule': crontab(day_of_month='1,29', hour=5, minute=0),  # Every 28 days (approx)
        'options': {'expires': 7200}
    },
    
    # Elite 100 refresh every hour
    'elite-100-refresh': {
        'task': 'tasks.refresh_elite_100',
        'schedule': crontab(minute=0),  # Top of every hour
        'options': {'expires': 3600}
    },
    
    # Community Top 100 refresh every hour
    'community-top-100-refresh': {
        'task': 'tasks.refresh_community_top_100',
        'schedule': crontab(minute=15),  # 15 minutes past every hour
        'options': {'expires': 3600}
    },
}

# Task routes (optional - for multiple queues)
celery.conf.task_routes = {
    'tasks.daily_stats_refresh': {'queue': 'stats'},
    'tasks.weekly_rerank_all': {'queue': 'stats'},
    'tasks.four_week_degradation_check': {'queue': 'stats'},
    'tasks.refresh_elite_100': {'queue': 'rankings'},
    'tasks.refresh_community_top_100': {'queue': 'rankings'},
}

print("""
╔══════════════════════════════════════════════════════════════════╗
║                   CELERY BEAT SCHEDULER CONFIGURED               ║
╚══════════════════════════════════════════════════════════════════╝
  📅 Daily stats refresh: 3am UTC
  📊 Weekly rerank: Sunday 4am UTC
  🔍 4-week degradation: 1st & 29th of month at 5am UTC
  🏆 Elite 100 refresh: Every hour (top of hour)
  👥 Community Top 100: Every hour (:15 past)
  
  Start with:
    celery -A celery_app worker --loglevel=info
    celery -A celery_app beat --loglevel=info
""")