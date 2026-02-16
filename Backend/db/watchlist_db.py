"""Watchlist database using Supabase - FIXED VERSION."""
from datetime import datetime, timedelta
import json
from typing import List, Dict, Optional

from services.supabase_client import get_supabase_client, SCHEMA_NAME


class WatchlistDatabase:
    """
    Manages user watchlists with Supabase database.
    Stores Twitter accounts AND wallets, tags, notes, and performance tracking.
    """

    def __init__(self, db_path: str = None):
        """
        Initialize Supabase connection.

        Args:
            db_path: Ignored (kept for backward compatibility)
        """
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
        print(f"[WATCHLIST DB] Connected to Supabase schema: {self.schema}")

    def _table(self, name: str):
        """Get table reference with schema."""
        return self.supabase.schema(self.schema).table(name)

    def create_user(self, user_id: str, wallet_address: str = None) -> bool:
        """Create new user (usually auto-created by trigger)."""
        try:
            self._table('users').upsert({
                'user_id': user_id,
                'wallet_address': wallet_address
            }, on_conflict='user_id').execute()
            return True
        except Exception as e:
            print(f"[WATCHLIST DB] Error creating user: {e}")
            return False

    # =========================================================================
    # TWITTER ACCOUNT WATCHLIST METHODS
    # =========================================================================

    def add_to_watchlist(self, user_id: str, account: Dict) -> bool:
        """Add Twitter account to user's watchlist."""
        try:
            self.create_user(user_id)

            tags = account.get('tags', [])
            if isinstance(tags, str):
                tags = json.loads(tags) if tags else []

            self._table('watchlist_accounts').upsert({
                'user_id': user_id,
                'author_id': account['author_id'],
                'username': account.get('username'),
                'name': account.get('name'),
                'followers': account.get('followers', 0),
                'verified': account.get('verified', False),
                'tags': tags,
                'notes': account.get('notes', ''),
                'influence_score': account.get('influence_score', 0),
                'avg_timing': account.get('avg_timing', 0),
                'pumps_called': account.get('pumps_called', 0),
                'last_updated': datetime.utcnow().isoformat()
            }, on_conflict='user_id,author_id').execute()

            print(f"[WATCHLIST DB] Added @{account.get('username')} to {user_id}'s watchlist")
            return True

        except Exception as e:
            print(f"[WATCHLIST DB] Error adding to watchlist: {e}")
            return False

    def get_watchlist(self, user_id: str, group_id: int = None) -> List[Dict]:
        """Get user's Twitter watchlist."""
        try:
            if group_id:
                # Get accounts in specific group via join
                result = self._table('watchlist_accounts').select(
                    '*, group_memberships!inner(group_id)'
                ).eq('user_id', user_id).eq(
                    'group_memberships.group_id', group_id
                ).order('influence_score', desc=True).execute()
            else:
                result = self._table('watchlist_accounts').select('*').eq(
                    'user_id', user_id
                ).order('influence_score', desc=True).execute()

            accounts = []
            for row in result.data:
                account = dict(row)
                # Remove join data if present
                account.pop('group_memberships', None)
                accounts.append(account)

            return accounts

        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching watchlist: {e}")
            return []

    def remove_from_watchlist(self, user_id: str, author_id: str) -> bool:
        """Remove Twitter account from watchlist."""
        try:
            self._table('watchlist_accounts').delete().eq(
                'user_id', user_id
            ).eq('author_id', author_id).execute()
            return True
        except Exception as e:
            print(f"[WATCHLIST DB] Error removing from watchlist: {e}")
            return False

    def update_account_notes(self, user_id: str, author_id: str,
                             notes: str = None, tags: List[str] = None) -> bool:
        """Update Twitter account notes and tags."""
        try:
            update_data = {'last_updated': datetime.utcnow().isoformat()}

            if notes is not None:
                update_data['notes'] = notes
            if tags is not None:
                update_data['tags'] = tags

            self._table('watchlist_accounts').update(update_data).eq(
                'user_id', user_id
            ).eq('author_id', author_id).execute()

            return True

        except Exception as e:
            print(f"[WATCHLIST DB] Error updating notes: {e}")
            return False

    def get_watchlist_stats(self, user_id: str) -> Dict:
        """Get statistics about user's Twitter watchlist."""
        try:
            result = self._table('watchlist_accounts').select(
                'influence_score, pumps_called, username'
            ).eq('user_id', user_id).execute()

            accounts = result.data
            if not accounts:
                return {
                    'total_accounts': 0,
                    'avg_influence': 0,
                    'total_pumps_tracked': 0,
                    'best_performer': {'username': None, 'influence': 0}
                }

            total_accounts = len(accounts)
            total_influence = sum(a.get('influence_score', 0) or 0 for a in accounts)
            total_pumps = sum(a.get('pumps_called', 0) or 0 for a in accounts)
            avg_influence = total_influence / total_accounts if total_accounts > 0 else 0

            # Find best performer
            best = max(accounts, key=lambda x: x.get('influence_score', 0) or 0)

            return {
                'total_accounts': total_accounts,
                'avg_influence': round(avg_influence, 1),
                'total_pumps_tracked': total_pumps,
                'best_performer': {
                    'username': best.get('username'),
                    'influence': best.get('influence_score', 0)
                }
            }

        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching stats: {e}")
            return {}

    # =========================================================================
    # WALLET WATCHLIST METHODS
    # =========================================================================

    def add_wallet_to_watchlist(self, user_id: str, wallet_data: Dict) -> bool:
        """
        Add wallet to watchlist with automatic field normalization.
        Accepts raw wallet object from analysis results.
        """
        try:
            self.create_user(user_id)
            
            # ✅ Sub-point 3-4: Backend normalizes inputs
            normalized = {
                'user_id': user_id,
                'wallet_address': wallet_data.get('wallet', wallet_data.get('wallet_address')),
                'tier': self._calculate_tier(wallet_data.get('professional_grade', 'C')),
                'pump_count': wallet_data.get('runner_hits_30d', wallet_data.get('pump_count', 0)),
                'avg_distance_to_peak': wallet_data.get('distance_to_ath_pct', 
                                                        wallet_data.get('avg_distance_to_peak', 0)),
                'avg_roi_to_peak': wallet_data.get('roi_percent', 
                                                   wallet_data.get('avg_roi_30d', 
                                                   wallet_data.get('avg_roi_to_peak', 0))),
                'professional_score': wallet_data.get('professional_score', 0),
                'consistency_score': wallet_data.get('consistency_score'),  # May be None
                'tokens_hit': [r.get('symbol', '') for r in wallet_data.get('other_runners', [])] if wallet_data.get('other_runners') else wallet_data.get('tokens_hit', []),
                'notes': wallet_data.get('notes', ''),
                'tags': wallet_data.get('tags', []),
                'alert_enabled': wallet_data.get('alert_enabled', True),
                'alert_threshold_usd': wallet_data.get('alert_threshold_usd', 100),
                'last_updated': datetime.utcnow().isoformat()
            }
            
            self._table('wallet_watchlist').upsert(
                normalized, 
                on_conflict='user_id,wallet_address'
            ).execute()
            return True
        except Exception as e:
            print(f"[WATCHLIST DB] Error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _calculate_tier(self, grade):
        """✅ Sub-point 4: Helper function to convert grade to tier"""
        if not grade:
            return 'C'
        if grade == 'A+':
            return 'S'
        if grade.startswith('A'):
            return 'A'
        if grade.startswith('B'):
            return 'B'
        return 'C'

    def get_wallet_watchlist(self, user_id: str, tier_filter: str = None) -> List[Dict]:
        """Get user's watched wallets, optionally filtered by tier."""
        try:
            query = self._table('wallet_watchlist').select('*').eq('user_id', user_id)

            if tier_filter:
                query = query.eq('tier', tier_filter)

            # Order by tier priority then pump_count
            result = query.order('pump_count', desc=True).execute()

            # Sort by tier manually (S > A > B > C)
            tier_order = {'S': 1, 'A': 2, 'B': 3, 'C': 4}
            wallets = sorted(
                result.data,
                key=lambda x: (tier_order.get(x.get('tier', 'C'), 5), -x.get('pump_count', 0))
            )

            return wallets

        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching wallet watchlist: {e}")
            return []

    def remove_wallet_from_watchlist(self, user_id: str, wallet_address: str) -> bool:
        """Remove wallet from user's watchlist."""
        try:
            self._table('wallet_watchlist').delete().eq(
                'user_id', user_id
            ).eq('wallet_address', wallet_address).execute()
            return True
        except Exception as e:
            print(f"[WATCHLIST DB] Error removing wallet: {e}")
            return False

    def update_wallet_notes(self, user_id: str, wallet_address: str,
                            notes: str = None, tags: List[str] = None) -> bool:
        """Update wallet notes and tags."""
        try:
            update_data = {'last_updated': datetime.utcnow().isoformat()}

            if notes is not None:
                update_data['notes'] = notes
            if tags is not None:
                update_data['tags'] = tags

            self._table('wallet_watchlist').update(update_data).eq(
                'user_id', user_id
            ).eq('wallet_address', wallet_address).execute()

            return True

        except Exception as e:
            print(f"[WATCHLIST DB] Error updating wallet notes: {e}")
            return False

    def get_wallet_watchlist_stats(self, user_id: str) -> Dict:
        """Get statistics about user's wallet watchlist."""
        try:
            result = self._table('wallet_watchlist').select('*').eq('user_id', user_id).execute()

            wallets = result.data
            if not wallets:
                return {
                    'total_wallets': 0,
                    's_tier': 0,
                    'a_tier': 0,
                    'b_tier': 0,
                    'avg_pump_count': 0,
                    'total_pumps_tracked': 0
                }

            total_wallets = len(wallets)
            s_tier = sum(1 for w in wallets if w.get('tier') == 'S')
            a_tier = sum(1 for w in wallets if w.get('tier') == 'A')
            b_tier = sum(1 for w in wallets if w.get('tier') == 'B')
            total_pumps = sum(w.get('pump_count', 0) or 0 for w in wallets)
            avg_pump_count = total_pumps / total_wallets if total_wallets > 0 else 0

            return {
                'total_wallets': total_wallets,
                's_tier': s_tier,
                'a_tier': a_tier,
                'b_tier': b_tier,
                'avg_pump_count': round(avg_pump_count, 1),
                'total_pumps_tracked': total_pumps
            }

        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching wallet stats: {e}")
            return {}

    def update_wallet_alert_settings(self, user_id: str, wallet_address: str,
                                     alert_enabled: bool = None,
                                     alert_threshold_usd: float = None) -> bool:
        """Update alert settings for a wallet."""
        try:
            update_data = {'last_updated': datetime.utcnow().isoformat()}

            if alert_enabled is not None:
                update_data['alert_enabled'] = alert_enabled
            if alert_threshold_usd is not None:
                update_data['alert_threshold_usd'] = alert_threshold_usd

            self._table('wallet_watchlist').update(update_data).eq(
                'user_id', user_id
            ).eq('wallet_address', wallet_address).execute()

            return True

        except Exception as e:
            print(f"[WATCHLIST DB] Error updating alert settings: {e}")
            return False

    # =========================================================================
    # PREMIER LEAGUE TABLE METHODS
    # =========================================================================

    def get_premier_league_table(self, user_id: str) -> Dict:
        """
        ✅ FIXED: Get watchlist as Premier League-style table.
        Now includes ALL wallet fields including alert settings.
        """
        try:
            # Get current watchlist with ALL fields
            result = self._table('wallet_watchlist').select('*').eq('user_id', user_id).execute()
            
            current_wallets = result.data
            
            if not current_wallets:
                return {
                    'wallets': [],
                    'promotion_queue': [],
                    'stats': {}
                }
            
            # ✅ FIX: Sort by consistency_score first, then avg_roi_to_peak
            # This ensures newly added wallets don't end up at the bottom
            current_wallets.sort(
                key=lambda x: (
                    x.get('consistency_score', 0),
                    x.get('avg_roi_to_peak', 0)
                ), 
                reverse=True
            )
            
            # Get yesterday's positions for movement tracking
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            history_result = self._table('wallet_performance_history').select(
                'wallet_address, position, professional_score'
            ).eq('user_id', user_id).eq('date', yesterday).execute()
            
            yesterday_positions = {
                row['wallet_address']: {
                    'position': row['position'], 
                    'score': row['professional_score']
                } 
                for row in history_result.data
            }
            
            # Build table data
            table_wallets = []
            for idx, wallet in enumerate(current_wallets, 1):
                wallet_address = wallet['wallet_address']
                old_data = yesterday_positions.get(wallet_address, {})
                old_position = old_data.get('position', idx)
                
                # Calculate movement
                positions_changed = old_position - idx
                if positions_changed > 0:
                    movement = 'up'
                elif positions_changed < 0:
                    movement = 'down'
                else:
                    movement = 'stable'
                
                # Determine zone based on position
                if idx <= 3:
                    zone = 'Elite'
                elif idx <= 6:
                    zone = 'midtable'
                elif idx <= 8:
                    zone = 'monitoring'
                else:
                    zone = 'relegation'
                
                # Get form (last 5 actions)
                form = self._calculate_wallet_form(user_id, wallet_address)
                
                # Check for degradation
                degradation_alerts = self._check_degradation(wallet, old_data)
                status = 'healthy' if not degradation_alerts else (
                    'critical' if any(a.get('severity') == 'critical' for a in degradation_alerts) else 'warning'
                )
                
                # ✅ FIX: Include ALL wallet fields plus table-specific fields
                table_wallet = dict(wallet)  # Copy all original fields
                table_wallet.update({
                    'position': idx,
                    'professional_score': wallet.get('avg_roi_to_peak', 0),
                    'runners_30d': wallet.get('pump_count', 0),
                    'roi_30d': wallet.get('avg_roi_to_peak', 0),
                    'movement': movement,
                    'positions_changed': abs(positions_changed),
                    'zone': zone,
                    'status': status,
                    'degradation_alerts': degradation_alerts,
                    'form': form
                })
                table_wallets.append(table_wallet)
            
            # Calculate stats
            avg_roi = sum(w['roi_30d'] for w in table_wallets) / len(table_wallets) if table_wallets else 0
            
            return {
                'wallets': table_wallets,
                'promotion_queue': [],
                'stats': {
                    'avg_watchlist_roi': round(avg_roi, 2),
                    'platform_avg_roi': 234,
                    'performance_vs_platform': round(avg_roi - 234, 2)
                }
            }
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error getting Premier League table: {e}")
            import traceback
            traceback.print_exc()
            return {'wallets': [], 'promotion_queue': [], 'stats': {}}

    def _calculate_wallet_form(self, user_id: str, wallet_address: str) -> List[str]:
        """
        Calculate form based on last 5 wallet activities.
        Returns list like: ['win', 'win', 'neutral', 'win', 'loss']
        """
        try:
            result = self._table('wallet_activity').select(
                'side, usd_value, block_time, token_ticker'
            ).eq('wallet_address', wallet_address).order(
                'block_time', desc=True
            ).limit(5).execute()
            
            activities = result.data
            
            if not activities or len(activities) == 0:
                return ['neutral'] * 5
            
            form = []
            
            for activity in activities:
                usd_value = activity.get('usd_value', 0) or 0
                side = activity.get('side', '').lower()
                
                if side == 'buy' and usd_value > 1000:
                    form.append('win')
                elif side == 'buy' and usd_value > 100:
                    form.append('neutral')
                elif side == 'sell':
                    form.append('loss')
                else:
                    form.append('neutral')
            
            while len(form) < 5:
                form.append('neutral')
            
            return form[:5]
            
        except Exception as e:
            print(f"[WATCHLIST DB] Error calculating form: {e}")
            return ['neutral'] * 5

    def _check_degradation(self, current_wallet: Dict, old_data: Dict) -> List[Dict]:
        """Check if wallet is degrading."""
        alerts = []
        
        current_score = current_wallet.get('avg_roi_to_peak', 0) or 0
        old_score = old_data.get('score', current_score)
        score_drop = old_score - current_score
        
        if score_drop > 20:
            alerts.append({
                'severity': 'critical',
                'message': f'ROI dropped from {old_score:.0f}% → {current_score:.0f}%'
            })
        elif score_drop > 10:
            alerts.append({
                'severity': 'warning',
                'message': f'ROI declined by {score_drop:.0f}%'
            })
        
        pump_count = current_wallet.get('pump_count', 0) or 0
        if pump_count == 0:
            alerts.append({
                'severity': 'warning',
                'message': 'No runner hits in recent period'
            })
        
        last_updated = current_wallet.get('last_updated')
        if last_updated:
            try:
                last_updated_dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                days_inactive = (datetime.utcnow().replace(tzinfo=last_updated_dt.tzinfo) - last_updated_dt).days
                
                if days_inactive > 60:
                    alerts.append({
                        'severity': 'critical',
                        'message': f'No activity for {days_inactive} days'
                    })
            except:
                pass
        
        return alerts

    def save_position_snapshot(self, user_id: str) -> bool:
        try:
            table_data = self.get_premier_league_table(user_id)
            today = datetime.utcnow().date().isoformat()
            
            snapshots = []
            for wallet in table_data['wallets']:
                snapshots.append({
                    'user_id': user_id,
                    'wallet_address': wallet['wallet_address'],
                    'date': today,
                    'position': wallet['position'],
                    'tier': wallet['tier'],
                    'avg_distance_to_peak': wallet.get('avg_distance_to_peak', 0), # Added to history
                    'professional_score': wallet.get('professional_score', 0),
                    'runners_30d': wallet.get('runners_30d', 0),
                    'roi_30d': wallet.get('roi_30d', 0),
                    'form_score': 0, 
                    'consistency_score': wallet.get('consistency_score', 0)
                })
            
            if snapshots:
                self._table('wallet_performance_history').upsert(snapshots, on_conflict='user_id,wallet_address,date').execute()
                return True
            return False
        except Exception as e:
            print(f"[WATCHLIST DB] Snapshot Error: {e}")
            return False

    # =========================================================================
    # GROUPS METHODS
    # =========================================================================

    def create_group(self, user_id: str, group_name: str, description: str = '') -> Optional[int]:
        """Create a watchlist group."""
        try:
            self.create_user(user_id)

            result = self._table('watchlist_groups').insert({
                'user_id': user_id,
                'group_name': group_name,
                'description': description
            }).execute()

            if result.data:
                return result.data[0]['id']
            return None

        except Exception as e:
            print(f"[WATCHLIST DB] Error creating group: {e}")
            return None

    def get_user_groups(self, user_id: str) -> List[Dict]:
        """Get user's watchlist groups."""
        try:
            result = self._table('watchlist_groups').select('*').eq(
                'user_id', user_id
            ).order('created_at', desc=True).execute()

            return result.data

        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching groups: {e}")
            return []

    # =========================================================================
    # NOTIFICATIONS METHODS
    # =========================================================================

    def add_notification(self, user_id: str, wallet_address: str,
                         notification_type: str, title: str,
                         message: str = '', metadata: Dict = None) -> bool:
        """Add a notification for a user."""
        try:
            self._table('wallet_notifications').insert({
                'user_id': user_id,
                'wallet_address': wallet_address,
                'notification_type': notification_type,
                'title': title,
                'message': message,
                'metadata': metadata or {}
            }).execute()
            return True

        except Exception as e:
            print(f"[WATCHLIST DB] Error adding notification: {e}")
            return False

    def get_notifications(self, user_id: str, unread_only: bool = False,
                          limit: int = 50) -> List[Dict]:
        """Get user's notifications."""
        try:
            query = self._table('wallet_notifications').select('*').eq('user_id', user_id)

            if unread_only:
                query = query.eq('is_read', False)

            result = query.order('sent_at', desc=True).limit(limit).execute()
            return result.data

        except Exception as e:
            print(f"[WATCHLIST DB] Error fetching notifications: {e}")
            return []

    def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications."""
        try:
            result = self._table('wallet_notifications').select(
                'id', count='exact'
            ).eq('user_id', user_id).eq('is_read', False).execute()

            return result.count or 0

        except Exception as e:
            print(f"[WATCHLIST DB] Error counting unread: {e}")
            return 0

    def mark_notification_read(self, user_id: str, notification_id: int) -> bool:
        """Mark a notification as read."""
        try:
            self._table('wallet_notifications').update({
                'is_read': True
            }).eq('user_id', user_id).eq('id', notification_id).execute()
            return True

        except Exception as e:
            print(f"[WATCHLIST DB] Error marking notification read: {e}")
            return False

    def mark_all_notifications_read(self, user_id: str) -> bool:
        """Mark all notifications as read for a user."""
        try:
            self._table('wallet_notifications').update({
                'is_read': True
            }).eq('user_id', user_id).eq('is_read', False).execute()
            return True

        except Exception as e:
            print(f"[WATCHLIST DB] Error marking all notifications read: {e}")
            return False