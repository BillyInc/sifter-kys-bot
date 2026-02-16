"""
Daily/Weekly watchlist stats updater with cron scheduling
Handles: Daily refresh, Weekly reranking, 4-week degradation checks
"""
from datetime import datetime, timedelta
from typing import List, Dict
from services.supabase_client import get_supabase_client, SCHEMA_NAME
from services.watchlist_manager import WatchlistLeagueManager


class WatchlistStatsUpdater:
    """Manages scheduled watchlist updates"""
    
    def __init__(self):
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
        self.manager = WatchlistLeagueManager()
    
    def _table(self, name: str):
        return self.supabase.schema(self.schema).table(name)
    
    # =========================================================================
    # DAILY UPDATE (3am UTC) - Refresh stats only, NO reranking
    # =========================================================================
    
    def daily_stats_refresh(self):
        """
        Refresh metrics for all watchlist wallets
        Updates: ROI, runners, win_rate, last_trade_time
        Does NOT change rankings (that's weekly)
        """
        print("\n" + "="*80)
        print(f"DAILY STATS REFRESH - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        # Get all unique wallets across all users
        result = self._table('wallet_watchlist').select(
            'wallet_address, user_id'
        ).execute()
        
        unique_wallets = {}
        for row in result.data:
            addr = row['wallet_address']
            if addr not in unique_wallets:
                unique_wallets[addr] = []
            unique_wallets[addr].append(row['user_id'])
        
        print(f"\n[DAILY] Refreshing {len(unique_wallets)} unique wallets...")
        
        success_count = 0
        error_count = 0
        
        for wallet_address, user_ids in unique_wallets.items():
            try:
                # Fetch latest metrics
                metrics = self.manager._refresh_wallet_metrics(wallet_address)
                
                # Update all users who have this wallet
                for user_id in user_ids:
                    self._table('wallet_watchlist').update({
                        'roi_7d': metrics.get('roi_7d', 0),
                        'roi_30d': metrics.get('roi_30d', 0),
                        'runners_7d': metrics.get('runners_7d', 0),
                        'runners_30d': metrics.get('runners_30d', 0),
                        'win_rate_7d': metrics.get('win_rate_7d', 0),
                        'last_trade_time': metrics.get('last_trade_time'),
                        'professional_score': metrics.get('professional_score', 0),
                        'consistency_score': metrics.get('consistency_score', 0),
                        'last_updated': datetime.utcnow().isoformat()
                    }).eq('user_id', user_id).eq('wallet_address', wallet_address).execute()
                
                success_count += 1
                
                if success_count % 10 == 0:
                    print(f"  Progress: {success_count}/{len(unique_wallets)}...")
                
            except Exception as e:
                print(f"  ✗ Error refreshing {wallet_address[:8]}...: {e}")
                error_count += 1
        
        print(f"\n[DAILY] Complete: {success_count} refreshed, {error_count} errors")
        print("="*80 + "\n")
        
        return {'success': success_count, 'errors': error_count}
    
    # =========================================================================
    # WEEKLY RERANK (Sunday 4am UTC) - Full rerank with position changes
    # =========================================================================
    
    def weekly_rerank_all(self):
        """
        Full watchlist reranking for all users
        Detects position changes, updates form, checks degradation
        """
        print("\n" + "="*80)
        print(f"WEEKLY RERANKING - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        # Get all unique user_ids
        result = self._table('wallet_watchlist').select('user_id').execute()
        user_ids = list(set(row['user_id'] for row in result.data))
        
        print(f"\n[WEEKLY] Reranking {len(user_ids)} users...")
        
        success_count = 0
        error_count = 0
        
        for user_id in user_ids:
            try:
                self.manager.rerank_user_watchlist(user_id)
                print(f"  ✓ {user_id[:8]}...")
                success_count += 1
            except Exception as e:
                print(f"  ✗ {user_id[:8]}...: {e}")
                error_count += 1
        
        print(f"\n[WEEKLY] Complete: {success_count} reranked, {error_count} errors")
        print("="*80 + "\n")
        
        return {'success': success_count, 'errors': error_count}
    
    # =========================================================================
    # 4-WEEK CHECK (Every 28 days) - Deep degradation analysis
    # =========================================================================
    
    def four_week_degradation_check(self):
        """
        Compare current performance vs 4 weeks ago
        Identifies wallets that need replacement
        """
        print("\n" + "="*80)
        print(f"4-WEEK DEGRADATION CHECK - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        # Get all wallets with 4+ weeks of history
        four_weeks_ago = (datetime.utcnow() - timedelta(days=28)).isoformat()
        
        result = self._table('wallet_watchlist').select('*').execute()
        all_wallets = result.data
        
        print(f"\n[4-WEEK] Analyzing {len(all_wallets)} wallets...")
        
        degraded_count = 0
        replacement_alerts = []
        
        for wallet in all_wallets:
            wallet_address = wallet['wallet_address']
            user_id = wallet['user_id']
            
            # Get performance from 4 weeks ago
            history = self._table('wallet_performance_history').select('*').eq(
                'wallet_address', wallet_address
            ).eq('user_id', user_id).gte(
                'week_start', four_weeks_ago
            ).order('week_start').execute()
            
            if not history.data or len(history.data) < 4:
                continue  # Not enough history
            
            # Compare first week vs last week
            first_week = history.data[0]
            last_week = history.data[-1]
            
            roi_drop = first_week.get('avg_roi', 0) - last_week.get('avg_roi', 0)
            runners_drop = first_week.get('runners_hit', 0) - last_week.get('runners_hit', 0)
            position_drop = last_week.get('position', 999) - first_week.get('position', 1)
            
            # Degradation thresholds
            is_degraded = (
                roi_drop > 50 or  # ROI dropped 50%+
                runners_drop >= 3 or  # Lost 3+ runners
                position_drop >= 5 or  # Dropped 5+ positions
                last_week.get('zone') == 'relegation'  # In relegation zone
            )
            
            if is_degraded:
                degraded_count += 1
                
                # Create replacement alert
                alert_data = {
                    'wallet_address': wallet_address,
                    'user_id': user_id,
                    'reason': self._get_degradation_reason(roi_drop, runners_drop, position_drop),
                    'current_position': last_week.get('position'),
                    'four_weeks_ago_position': first_week.get('position'),
                    'roi_change': -roi_drop,
                    'runners_change': -runners_drop
                }
                
                replacement_alerts.append(alert_data)
                
                # Update wallet status
                self._table('wallet_watchlist').update({
                    'status': 'critical',
                    'degradation_alerts': [{
                        'severity': 'red',
                        'message': f'4-week decline detected: {alert_data["reason"]}'
                    }]
                }).eq('user_id', user_id).eq('wallet_address', wallet_address).execute()
                
                print(f"  🚨 DEGRADED: {wallet_address[:8]}... - {alert_data['reason']}")
        
        print(f"\n[4-WEEK] Found {degraded_count} degraded wallets")
        
        # Send replacement suggestions (via Telegram/email)
        if replacement_alerts:
            self._send_replacement_alerts(replacement_alerts)
        
        print("="*80 + "\n")
        
        return {
            'degraded_count': degraded_count,
            'alerts_sent': len(replacement_alerts)
        }
    
    def _get_degradation_reason(self, roi_drop, runners_drop, position_drop):
        """Generate human-readable degradation reason"""
        reasons = []
        
        if roi_drop > 50:
            reasons.append(f"ROI dropped {roi_drop:.0f}%")
        if runners_drop >= 3:
            reasons.append(f"Lost {runners_drop} runners")
        if position_drop >= 5:
            reasons.append(f"Dropped {position_drop} positions")
        
        return ", ".join(reasons) if reasons else "Performance decline"
    
    def _send_replacement_alerts(self, alerts: List[Dict]):
        """Send replacement suggestion alerts to users"""
        try:
            # Queue Telegram alerts
            from flask import current_app
            from redis import Redis
            from rq import Queue
            
            redis = Redis(host='localhost', port=6379)
            q = Queue(connection=redis)
            
            for alert in alerts:
                q.enqueue('tasks.send_telegram_alert_async',
                          alert['user_id'],
                          'replacement',
                          alert)
            
            print(f"  ✓ Queued {len(alerts)} replacement alerts")
        except Exception as e:
            print(f"  ⚠️ Failed to queue alerts: {e}")


# Singleton instance
_updater = None

def get_updater():
    global _updater
    if _updater is None:
        _updater = WatchlistStatsUpdater()
    return _updater