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
    backend=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
    include=[
        'services.tasks',
        'services.worker_tasks',
        'tasks.token_discovery',
        'tasks.wallet_qualification',
        'tasks.clickhouse_backup',
    ],
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


    # Elite 15 monitor sync every hour (:05, after Elite 100 refresh at :00)
    'sync-elite-15-to-monitor': {
        'task': 'tasks.sync_elite_15_to_monitor',
        'schedule': crontab(minute=5),
        'options': {'expires': 3600, 'queue': 'rankings'}
    },

    # Purge notifications older than 30 days — daily at 2:30 AM UTC
    'purge-old-notifications': {
        'task': 'tasks.purge_old_notifications',
        'schedule': crontab(hour=2, minute=30),
        'options': {'expires': 3600, 'queue': 'stats'}
    },

    # Daily email summaries at 8:00 AM UTC
    'daily-email-summaries': {
        'task': 'tasks.send_daily_email_summaries',
        'schedule': crontab(hour=8, minute=0),
        'options': {'expires': 3600, 'queue': 'stats'}
    },

    # ── Paper Trader ──────────────────────────────────────────

    # Paper trader exit checker — every 2 minutes, independent of wallet monitor
    'paper-trader-check-exits': {
        'task': 'tasks.check_paper_trader_exits',
        'schedule': 120.0,
        'options': {'expires': 110}
    },

    # Paper trader daily digest — 7:00 AM UTC
    'paper-trader-daily-digest': {
        'task': 'tasks.send_paper_trader_daily_digest',
        'schedule': crontab(hour=7, minute=0),
        'options': {'expires': 3600, 'queue': 'stats'}
    },

    # ── Disaster Recovery ────────────────────────────────────

    # ClickHouse → Supabase backup every Monday at 2:00 AM UTC
    'clickhouse-backup-to-supabase': {
        'task': 'tasks.backup_clickhouse_to_supabase',
        'schedule': crontab(day_of_week='monday', hour=2, minute=0),
        'options': {'expires': 7200, 'queue': 'stats'}
    },
}

# Task routes
celery.conf.task_routes = {
    # ── Scheduled / cron tasks ──────────────────────────────────
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
    'tasks.purge_old_notifications':     {'queue': 'stats'},
    'tasks.backup_clickhouse_to_supabase': {'queue': 'stats'},
    'tasks.requalify_existing_data':     {'queue': 'stats'},
    'tasks.sync_elite_15_to_monitor':    {'queue': 'rankings'},
    'tasks.send_daily_email_summaries':  {'queue': 'stats'},
    'tasks.check_paper_trader_exits':    {'queue': 'alerts'},
    'tasks.send_paper_trader_daily_digest': {'queue': 'stats'},
    'tasks.send_telegram_alert_async':    {'queue': 'alerts'},
    'tasks.execute_bot_auto_trade':       {'queue': 'alerts'},
    # ── Analysis pipeline tasks (migrated from RQ) ──────────────
    'worker.perform_wallet_analysis':           {'queue': 'high'},
    'worker.perform_trending_batch_analysis':   {'queue': 'batch'},
    'worker.perform_auto_discovery':            {'queue': 'compute'},
    'worker.fetch_top_traders':                 {'queue': 'high'},
    'worker.fetch_first_buyers':                {'queue': 'high'},
    'worker.coordinate_pnl_phase':              {'queue': 'compute'},
    'worker.fetch_pnl_batch':                   {'queue': 'batch'},
    'worker.score_and_rank_single':             {'queue': 'compute'},
    'worker.fetch_from_token_cache':            {'queue': 'compute'},
    'worker.fetch_runner_history_batch':         {'queue': 'batch'},
    'worker.merge_and_save_final':              {'queue': 'compute'},
    'worker.aggregate_cross_token':             {'queue': 'compute'},
    'worker.merge_batch_final':                 {'queue': 'compute'},
    'worker.warm_cache_runners':                {'queue': 'batch'},
}

# Import task modules so `celery -A celery_app worker ...` registers both
# scheduled jobs and on-demand token-analysis pipeline tasks.
import services.tasks  # noqa: E402,F401
import services.worker_tasks  # noqa: E402,F401

print("""
╔══════════════════════════════════════════════════════════════════╗
║              CELERY BEAT SCHEDULER CONFIGURED                    ║
╚══════════════════════════════════════════════════════════════════╝
  📅 Daily stats refresh:      3am UTC
  📊 Weekly rerank:            Sunday 4am UTC
  🔍 4-week degradation:       1st & 29th of month at 5am UTC
  🏆 Elite 100 refresh:        Every hour (:00)
  👥 Community Top 100:        Every hour (:15)
  💾 Redis → DuckDB flush:     Every hour (:30)
  🔄 ATH cache invalidation:   Every hour (:45)
  📈 Paper trader exit checks:  Every 2 minutes
  📧 Paper trader digest:      Daily 7am UTC
  🗑️  Notification TTL purge:    Daily 2:30am UTC
  💾 CH → Supabase backup:     Monday 2am UTC

  Start with:
    celery -A celery_app worker --loglevel=info -Q default,high,batch,compute,stats,rankings,discovery,alerts
    celery -A celery_app beat --loglevel=info
""")
