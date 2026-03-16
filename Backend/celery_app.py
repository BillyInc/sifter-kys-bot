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
    # ── ClickHouse Pipeline ──────────────────────────────────

    # Token discovery: poll just_graduated, newly_launched, trending_runners
    'discover-new-tokens': {
        'task': 'tasks.discover_new_tokens',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
        'options': {'expires': 240, 'queue': 'discovery'}
    },

    # ── Scheduled Jobs ───────────────────────────────────────

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
        'schedule': crontab(day_of_month='1,29', hour=5, minute=0),
        'options': {'expires': 7200}
    },

    # Elite 100 refresh every hour (top of hour)
    'elite-100-refresh': {
        'task': 'tasks.refresh_elite_100',
        'schedule': crontab(minute=0),
        'options': {'expires': 3600}
    },

    # Community Top 100 refresh every hour (:15 past)
    'community-top-100-refresh': {
        'task': 'tasks.refresh_community_top_100',
        'schedule': crontab(minute=15),
        'options': {'expires': 3600}
    },

    # Redis → DuckDB flush every hour (:30 past, staggered from other hourly tasks)
    'flush-redis-to-duckdb': {
        'task': 'tasks.flush_redis_to_duckdb',
        'schedule': crontab(minute=30),
        'options': {'expires': 3600}
    },

    # ATH invalidation — checks all active token caches for stale scores (:45 past)
    # If a token's ATH moved >10% since the cached result was computed, the Redis
    # cache key is deleted so the next search triggers a fresh pipeline with
    # correct distance_to_ath_pct / entry_to_ath_multiplier / professional_score.
    'invalidate-stale-ath-caches': {
        'task': 'tasks.invalidate_stale_ath_caches',
        'schedule': crontab(minute=45),
        'options': {'expires': 3600}
    },
}

# Task routes
celery.conf.task_routes = {
    'tasks.discover_new_tokens':         {'queue': 'discovery'},
    'tasks.wallet_qualification_scan':   {'queue': 'discovery'},
    'tasks.second_pass_patch':           {'queue': 'discovery'},
    'tasks.daily_stats_refresh':         {'queue': 'stats'},
    'tasks.weekly_rerank_all':           {'queue': 'stats'},
    'tasks.four_week_degradation_check': {'queue': 'stats'},
    'tasks.refresh_elite_100':           {'queue': 'rankings'},
    'tasks.refresh_community_top_100':   {'queue': 'rankings'},
    'tasks.flush_redis_to_duckdb':       {'queue': 'stats'},
    'tasks.invalidate_stale_ath_caches': {'queue': 'stats'},
    'tasks.purge_stale_analysis_cache':  {'queue': 'stats'},
}

print("""
╔══════════════════════════════════════════════════════════════════╗
║              CELERY BEAT SCHEDULER CONFIGURED                    ║
╚══════════════════════════════════════════════════════════════════╝
  🔎 Token discovery:          Every 5 minutes
  📅 Daily stats refresh:      3am UTC
  📊 Weekly rerank:            Sunday 4am UTC
  🔍 4-week degradation:       1st & 29th of month at 5am UTC
  🏆 Elite 100 refresh:        Every hour (:00)
  👥 Community Top 100:        Every hour (:15)
  💾 Redis → DuckDB flush:     Every hour (:30)
  🔄 ATH cache invalidation:   Every hour (:45)

  Start with:
    celery -A celery_app worker --loglevel=info -Q default,stats,rankings,discovery
    celery -A celery_app beat --loglevel=info
""")
