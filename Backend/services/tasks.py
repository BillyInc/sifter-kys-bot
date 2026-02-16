"""
Celery Scheduled Tasks - Production Cron Jobs
These run on Celery Beat scheduler (time-based, recurring)
For on-demand analysis workers, see worker_tasks.py (RQ)
"""
from celery_app import celery
from datetime import datetime
import os


@celery.task(name='tasks.daily_stats_refresh')
def daily_stats_refresh():
    """
    Daily stats refresh at 3am UTC
    Updates all watchlist wallet metrics
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Daily Stats Refresh - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")
    
    try:
        from services.watchlist_stats_updater import get_updater
        updater = get_updater()
        
        result = updater.daily_stats_refresh()
        
        print(f"\n[CELERY TASK] Daily refresh complete: {result}")
        return {
            'status': 'success',
            'result': result,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] Daily refresh failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.weekly_rerank_all')
def weekly_rerank_all():
    """
    Weekly rerank on Sunday at 4am UTC
    Reranks all user watchlists
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Weekly Rerank - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")
    
    try:
        from services.watchlist_stats_updater import get_updater
        updater = get_updater()
        
        result = updater.weekly_rerank_all()
        
        print(f"\n[CELERY TASK] Weekly rerank complete: {result}")
        return {
            'status': 'success',
            'result': result,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] Weekly rerank failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.four_week_degradation_check')
def four_week_degradation_check():
    """
    4-week degradation check every 28 days at 5am UTC
    Identifies wallets with declining performance over 4 weeks
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] 4-Week Degradation Check - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")
    
    try:
        from services.watchlist_stats_updater import get_updater
        updater = get_updater()
        
        result = updater.four_week_degradation_check()
        
        print(f"\n[CELERY TASK] 4-week check complete: {result}")
        return {
            'status': 'success',
            'result': result,
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] 4-week check failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.refresh_elite_100')
def refresh_elite_100():
    """
    Refresh Elite 100 rankings every hour
    Generates top 100 performing wallets across all metrics
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Elite 100 Refresh - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")
    
    try:
        from services.elite_100_manager import get_elite_manager
        manager = get_elite_manager()
        
        # Generate all 3 variants
        score_wallets = manager.generate_elite_100('score')
        roi_wallets = manager.generate_elite_100('roi')
        runners_wallets = manager.generate_elite_100('runners')
        
        print(f"\n[CELERY TASK] Elite 100 refresh complete")
        print(f"  - By Score: {len(score_wallets)} wallets")
        print(f"  - By ROI: {len(roi_wallets)} wallets")
        print(f"  - By Runners: {len(runners_wallets)} wallets")
        
        return {
            'status': 'success',
            'counts': {
                'score': len(score_wallets),
                'roi': len(roi_wallets),
                'runners': len(runners_wallets)
            },
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] Elite 100 refresh failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.refresh_community_top_100')
def refresh_community_top_100():
    """
    Refresh Community Top 100 every hour
    Shows most-added wallets this week
    """
    print(f"\n{'='*80}")
    print(f"[CELERY TASK] Community Top 100 Refresh - {datetime.utcnow().isoformat()}")
    print(f"{'='*80}\n")
    
    try:
        from services.elite_100_manager import get_elite_manager
        manager = get_elite_manager()
        
        wallets = manager.generate_community_top_100()
        
        print(f"\n[CELERY TASK] Community Top 100 refresh complete: {len(wallets)} wallets")
        
        return {
            'status': 'success',
            'count': len(wallets),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"\n[CELERY TASK] Community Top 100 refresh failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


@celery.task(name='tasks.send_telegram_alert_async')
def send_telegram_alert_async(user_id: str, alert_type: str, alert_data: dict):
    """
    Async Telegram alert sender
    Called by wallet monitor for background alert delivery
    """
    try:
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            print(f"[TELEGRAM TASK] Notifier not configured")
            return {'status': 'skipped', 'reason': 'no_notifier'}
        
        from services.telegram_notifier import TelegramNotifier
        telegram_notifier = TelegramNotifier(bot_token)
        
        if alert_type == 'trade':
            from services.supabase_client import get_supabase_client, SCHEMA_NAME
            supabase = get_supabase_client()
            
            wallet_result = supabase.schema(SCHEMA_NAME).table('wallet_watchlist').select(
                'tier, consistency_score'
            ).eq('user_id', user_id).eq('wallet_address', alert_data.get('wallet_address')).limit(1).execute()
            
            wallet_info = wallet_result.data[0] if wallet_result.data else {'tier': 'C', 'consistency_score': 0}
            
            payload = {
                'wallet': {
                    'address': alert_data.get('wallet_address', ''),
                    'tier': wallet_info.get('tier', 'C'),
                    'consistency_score': wallet_info.get('consistency_score', 0)
                },
                'action': alert_data.get('side', 'buy'),
                'token': {
                    'address': alert_data.get('token_address', ''),
                    'symbol': alert_data.get('token_ticker', 'UNKNOWN'),
                    'name': alert_data.get('token_name', 'Unknown')
                },
                'trade': {
                    'amount_tokens': alert_data.get('token_amount', 0),
                    'amount_usd': alert_data.get('usd_value', 0),
                    'price': alert_data.get('price', 0),
                    'tx_hash': alert_data.get('tx_hash', ''),
                    'dex': alert_data.get('dex', 'unknown'),
                    'timestamp': alert_data.get('block_time', 0)
                },
                'links': {
                    'solscan': f"https://solscan.io/tx/{alert_data.get('tx_hash', '')}",
                    'birdeye': f"https://birdeye.so/token/{alert_data.get('token_address', '')}",
                    'dexscreener': f"https://dexscreener.com/solana/{alert_data.get('token_address', '')}"
                }
            }
            
            telegram_notifier.send_wallet_alert(user_id, payload, alert_data.get('activity_id'))
            
        elif alert_type == 'multi_wallet':
            telegram_notifier.send_multi_wallet_signal_alert(user_id, alert_data)
        
        return {
            'status': 'sent',
            'user_id': user_id,
            'alert_type': alert_type
        }
        
    except Exception as e:
        print(f"[TELEGRAM TASK] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e)
        }