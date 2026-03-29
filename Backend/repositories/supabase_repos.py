"""Concrete Supabase implementations of repository interfaces.

Each class wraps the existing query patterns found in routes and
db/watchlist_db.py so that the migration can be done incrementally:
swap the direct Supabase calls in a route for a repository method call
and the behaviour stays identical.
"""
from datetime import datetime, timedelta
import json
import logging
from typing import List, Dict, Optional

from repositories.base import (
    WatchlistRepository,
    WalletWatchlistRepository,
    NotificationRepository,
    AnalysisJobRepository,
    UserRepository,
    UserSettingsRepository,
    AnalysisHistoryRepository,
)
from services.supabase_client import get_supabase_client, SCHEMA_NAME

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers shared across repos
# ---------------------------------------------------------------------------

def _table(name: str):
    """Shorthand for schema-qualified table reference."""
    return get_supabase_client().schema(SCHEMA_NAME).table(name)


def _ensure_user(user_id: str, wallet_address: str | None = None) -> None:
    """Upsert into users table so FK constraints are satisfied."""
    try:
        data = {'user_id': user_id}
        if wallet_address:
            data['wallet_address'] = wallet_address
        _table('users').upsert(data, on_conflict='user_id').execute()
    except Exception as exc:
        logger.warning("ensure_user failed for %s: %s", user_id, exc)


# ===========================================================================
# Twitter account watchlist
# ===========================================================================

class SupabaseWatchlistRepo(WatchlistRepository):

    def add_to_watchlist(self, user_id: str, account: dict) -> bool:
        try:
            _ensure_user(user_id)

            tags = account.get('tags', [])
            if isinstance(tags, str):
                tags = json.loads(tags) if tags else []

            _table('watchlist_accounts').upsert({
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
                'last_updated': datetime.utcnow().isoformat(),
            }, on_conflict='user_id,author_id').execute()
            return True
        except Exception as exc:
            logger.error("add_to_watchlist failed: %s", exc)
            return False

    def get_watchlist(self, user_id: str, group_id: int | None = None) -> list[dict]:
        try:
            if group_id:
                result = _table('watchlist_accounts').select(
                    '*, group_memberships!inner(group_id)',
                ).eq('user_id', user_id).eq(
                    'group_memberships.group_id', group_id,
                ).order('influence_score', desc=True).execute()
            else:
                result = _table('watchlist_accounts').select('*').eq(
                    'user_id', user_id,
                ).order('influence_score', desc=True).execute()

            accounts = []
            for row in result.data:
                account = dict(row)
                account.pop('group_memberships', None)
                accounts.append(account)
            return accounts
        except Exception as exc:
            logger.error("get_watchlist failed: %s", exc)
            return []

    def remove_from_watchlist(self, user_id: str, author_id: str) -> bool:
        try:
            _table('watchlist_accounts').delete().eq(
                'user_id', user_id,
            ).eq('author_id', author_id).execute()
            return True
        except Exception as exc:
            logger.error("remove_from_watchlist failed: %s", exc)
            return False

    def update_account_notes(
        self, user_id: str, author_id: str,
        notes: str | None = None, tags: list[str] | None = None,
    ) -> bool:
        try:
            update_data: dict = {'last_updated': datetime.utcnow().isoformat()}
            if notes is not None:
                update_data['notes'] = notes
            if tags is not None:
                update_data['tags'] = tags

            _table('watchlist_accounts').update(update_data).eq(
                'user_id', user_id,
            ).eq('author_id', author_id).execute()
            return True
        except Exception as exc:
            logger.error("update_account_notes failed: %s", exc)
            return False

    def get_watchlist_stats(self, user_id: str) -> dict:
        try:
            result = _table('watchlist_accounts').select(
                'influence_score, pumps_called, username',
            ).eq('user_id', user_id).execute()

            accounts = result.data
            if not accounts:
                return {
                    'total_accounts': 0,
                    'avg_influence': 0,
                    'total_pumps_tracked': 0,
                    'best_performer': {'username': None, 'influence': 0},
                }

            total = len(accounts)
            total_influence = sum(a.get('influence_score', 0) or 0 for a in accounts)
            total_pumps = sum(a.get('pumps_called', 0) or 0 for a in accounts)

            best = max(accounts, key=lambda x: x.get('influence_score', 0) or 0)

            return {
                'total_accounts': total,
                'avg_influence': round(total_influence / total, 1),
                'total_pumps_tracked': total_pumps,
                'best_performer': {
                    'username': best.get('username'),
                    'influence': best.get('influence_score', 0),
                },
            }
        except Exception as exc:
            logger.error("get_watchlist_stats failed: %s", exc)
            return {}

    def get_user_groups(self, user_id: str) -> list[dict]:
        try:
            result = _table('watchlist_groups').select('*').eq(
                'user_id', user_id,
            ).order('created_at', desc=True).execute()
            return result.data
        except Exception as exc:
            logger.error("get_user_groups failed: %s", exc)
            return []

    def create_group(
        self, user_id: str, group_name: str, description: str = '',
    ) -> int | None:
        try:
            _ensure_user(user_id)
            result = _table('watchlist_groups').insert({
                'user_id': user_id,
                'group_name': group_name,
                'description': description,
            }).execute()
            if result.data:
                return result.data[0]['id']
            return None
        except Exception as exc:
            logger.error("create_group failed: %s", exc)
            return None


# ===========================================================================
# Wallet watchlist
# ===========================================================================

class SupabaseWalletWatchlistRepo(WalletWatchlistRepository):

    @staticmethod
    def _calculate_tier(grade: str | None) -> str:
        if not grade:
            return 'C'
        if grade == 'A+':
            return 'S'
        if grade.startswith('A'):
            return 'A'
        if grade.startswith('B'):
            return 'B'
        return 'C'

    def add_wallet(self, user_id: str, wallet_data: dict) -> bool:
        try:
            _ensure_user(user_id)

            normalized = {
                'user_id': user_id,
                'wallet_address': wallet_data.get('wallet', wallet_data.get('wallet_address')),
                'tier': self._calculate_tier(wallet_data.get('professional_grade', 'C')),
                'pump_count': wallet_data.get('runner_hits_30d', wallet_data.get('pump_count', 0)),
                'avg_distance_to_peak': wallet_data.get(
                    'distance_to_ath_pct',
                    wallet_data.get('avg_distance_to_peak', 0),
                ),
                'avg_roi_to_peak': wallet_data.get(
                    'roi_percent',
                    wallet_data.get('avg_roi_30d', wallet_data.get('avg_roi_to_peak', 0)),
                ),
                'professional_score': wallet_data.get('professional_score', 0),
                'consistency_score': wallet_data.get('consistency_score'),
                'tokens_hit': (
                    [r.get('symbol', '') for r in wallet_data.get('other_runners', [])]
                    if wallet_data.get('other_runners')
                    else wallet_data.get('tokens_hit', [])
                ),
                'notes': wallet_data.get('notes', ''),
                'tags': wallet_data.get('tags', []),
                'alert_enabled': wallet_data.get('alert_enabled', True),
                'alert_threshold_usd': wallet_data.get('alert_threshold_usd', 100),
                'last_updated': datetime.utcnow().isoformat(),
            }

            _table('wallet_watchlist').upsert(
                normalized, on_conflict='user_id,wallet_address',
            ).execute()
            return True
        except Exception as exc:
            logger.error("add_wallet failed: %s", exc, exc_info=True)
            return False

    def get_wallet_watchlist(
        self, user_id: str, tier_filter: str | None = None,
    ) -> list[dict]:
        try:
            query = _table('wallet_watchlist').select('*').eq('user_id', user_id)
            if tier_filter:
                query = query.eq('tier', tier_filter)

            result = query.order('pump_count', desc=True).execute()

            tier_order = {'S': 1, 'A': 2, 'B': 3, 'C': 4}
            return sorted(
                result.data,
                key=lambda x: (
                    tier_order.get(x.get('tier', 'C'), 5),
                    -x.get('pump_count', 0),
                ),
            )
        except Exception as exc:
            logger.error("get_wallet_watchlist failed: %s", exc)
            return []

    def remove_wallet(self, user_id: str, wallet_address: str) -> bool:
        try:
            _table('wallet_watchlist').delete().eq(
                'user_id', user_id,
            ).eq('wallet_address', wallet_address).execute()
            return True
        except Exception as exc:
            logger.error("remove_wallet failed: %s", exc)
            return False

    def update_wallet_notes(
        self, user_id: str, wallet_address: str,
        notes: str | None = None, tags: list[str] | None = None,
    ) -> bool:
        try:
            update_data: dict = {'last_updated': datetime.utcnow().isoformat()}
            if notes is not None:
                update_data['notes'] = notes
            if tags is not None:
                update_data['tags'] = tags

            _table('wallet_watchlist').update(update_data).eq(
                'user_id', user_id,
            ).eq('wallet_address', wallet_address).execute()
            return True
        except Exception as exc:
            logger.error("update_wallet_notes failed: %s", exc)
            return False

    def update_wallet_alert_settings(
        self, user_id: str, wallet_address: str,
        alert_enabled: bool | None = None,
        alert_threshold_usd: float | None = None,
    ) -> bool:
        try:
            update_data: dict = {'last_updated': datetime.utcnow().isoformat()}
            if alert_enabled is not None:
                update_data['alert_enabled'] = alert_enabled
            if alert_threshold_usd is not None:
                update_data['alert_threshold_usd'] = alert_threshold_usd

            _table('wallet_watchlist').update(update_data).eq(
                'user_id', user_id,
            ).eq('wallet_address', wallet_address).execute()
            return True
        except Exception as exc:
            logger.error("update_wallet_alert_settings failed: %s", exc)
            return False

    def get_wallet_watchlist_stats(self, user_id: str) -> dict:
        try:
            result = _table('wallet_watchlist').select('*').eq('user_id', user_id).execute()
            wallets = result.data
            if not wallets:
                return {
                    'total_wallets': 0, 's_tier': 0, 'a_tier': 0, 'b_tier': 0,
                    'avg_pump_count': 0, 'total_pumps_tracked': 0,
                }

            total = len(wallets)
            total_pumps = sum(w.get('pump_count', 0) or 0 for w in wallets)

            return {
                'total_wallets': total,
                's_tier': sum(1 for w in wallets if w.get('tier') == 'S'),
                'a_tier': sum(1 for w in wallets if w.get('tier') == 'A'),
                'b_tier': sum(1 for w in wallets if w.get('tier') == 'B'),
                'avg_pump_count': round(total_pumps / total, 1),
                'total_pumps_tracked': total_pumps,
            }
        except Exception as exc:
            logger.error("get_wallet_watchlist_stats failed: %s", exc)
            return {}

    def get_premier_league_table(self, user_id: str) -> dict:
        try:
            result = _table('wallet_watchlist').select('*').eq('user_id', user_id).execute()
            current_wallets = result.data

            if not current_wallets:
                return {'wallets': [], 'promotion_queue': [], 'stats': {}}

            # Sort by confidence-weighted score
            def ranking_score(w):
                base = w.get('professional_score', 0) or w.get('avg_roi_to_peak', 0)
                return base if w.get('source_type') == 'batch' else base * 0.75

            current_wallets.sort(key=ranking_score, reverse=True)

            # Yesterday's positions for movement tracking
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            history_result = _table('wallet_performance_history').select(
                'wallet_address, position, professional_score',
            ).eq('user_id', user_id).eq('date', yesterday).execute()

            yesterday_positions = {
                row['wallet_address']: {
                    'position': row['position'],
                    'score': row['professional_score'],
                }
                for row in history_result.data
            }

            table_wallets = []
            for idx, wallet in enumerate(current_wallets, 1):
                addr = wallet['wallet_address']
                old_data = yesterday_positions.get(addr, {})
                old_position = old_data.get('position', idx)
                positions_changed = old_position - idx

                if positions_changed > 0:
                    movement = 'up'
                elif positions_changed < 0:
                    movement = 'down'
                else:
                    movement = 'stable'

                if idx <= 3:
                    zone = 'Elite'
                elif idx <= 6:
                    zone = 'midtable'
                elif idx <= 8:
                    zone = 'monitoring'
                else:
                    zone = 'relegation'

                form = self._calculate_wallet_form(addr)
                degradation_alerts = self._check_degradation(wallet, old_data)
                status = 'healthy' if not degradation_alerts else (
                    'critical' if any(
                        a.get('severity') == 'critical' for a in degradation_alerts
                    ) else 'warning'
                )

                table_wallet = dict(wallet)
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
                    'form': form,
                })
                table_wallets.append(table_wallet)

            avg_roi = (
                sum(w['roi_30d'] for w in table_wallets) / len(table_wallets)
                if table_wallets else 0
            )

            return {
                'wallets': table_wallets,
                'promotion_queue': [],
                'stats': {
                    'avg_watchlist_roi': round(avg_roi, 2),
                    'platform_avg_roi': 234,
                    'performance_vs_platform': round(avg_roi - 234, 2),
                },
            }
        except Exception as exc:
            logger.error("get_premier_league_table failed: %s", exc, exc_info=True)
            return {'wallets': [], 'promotion_queue': [], 'stats': {}}

    def save_position_snapshot(self, user_id: str) -> bool:
        try:
            table_data = self.get_premier_league_table(user_id)
            today = datetime.utcnow().date().isoformat()

            snapshots = [
                {
                    'user_id': user_id,
                    'wallet_address': w['wallet_address'],
                    'date': today,
                    'position': w['position'],
                    'tier': w['tier'],
                    'avg_distance_to_peak': w.get('avg_distance_to_peak', 0),
                    'professional_score': w.get('professional_score', 0),
                    'runners_30d': w.get('runners_30d', 0),
                    'roi_30d': w.get('roi_30d', 0),
                    'form_score': 0,
                    'consistency_score': w.get('consistency_score', 0),
                }
                for w in table_data['wallets']
            ]

            if snapshots:
                _table('wallet_performance_history').upsert(
                    snapshots, on_conflict='user_id,wallet_address,date',
                ).execute()
                return True
            return False
        except Exception as exc:
            logger.error("save_position_snapshot failed: %s", exc)
            return False

    # -- private helpers -------------------------------------------------------

    @staticmethod
    def _calculate_wallet_form(wallet_address: str) -> list[str]:
        try:
            result = _table('wallet_activity').select(
                'side, usd_value, block_time, token_ticker',
            ).eq('wallet_address', wallet_address).order(
                'block_time', desc=True,
            ).limit(5).execute()

            activities = result.data
            if not activities:
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
        except Exception:
            return ['neutral'] * 5

    @staticmethod
    def _check_degradation(current_wallet: dict, old_data: dict) -> list[dict]:
        alerts: list[dict] = []
        current_score = current_wallet.get('avg_roi_to_peak', 0) or 0
        old_score = old_data.get('score', current_score)
        score_drop = old_score - current_score

        if score_drop > 20:
            alerts.append({
                'severity': 'critical',
                'message': f'ROI dropped from {old_score:.0f}% -> {current_score:.0f}%',
            })
        elif score_drop > 10:
            alerts.append({
                'severity': 'warning',
                'message': f'ROI declined by {score_drop:.0f}%',
            })

        if (current_wallet.get('pump_count', 0) or 0) == 0:
            alerts.append({
                'severity': 'warning',
                'message': 'No runner hits in recent period',
            })

        last_updated = current_wallet.get('last_updated')
        if last_updated:
            try:
                last_dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                days_inactive = (
                    datetime.utcnow().replace(tzinfo=last_dt.tzinfo) - last_dt
                ).days
                if days_inactive > 60:
                    alerts.append({
                        'severity': 'critical',
                        'message': f'No activity for {days_inactive} days',
                    })
            except Exception:
                pass

        return alerts


# ===========================================================================
# Notifications
# ===========================================================================

class SupabaseNotificationRepo(NotificationRepository):

    def add_notification(
        self, user_id: str, wallet_address: str,
        notification_type: str, title: str,
        message: str = '', metadata: dict | None = None,
    ) -> bool:
        try:
            _table('wallet_notifications').insert({
                'user_id': user_id,
                'wallet_address': wallet_address,
                'notification_type': notification_type,
                'title': title,
                'message': message,
                'metadata': metadata or {},
            }).execute()
            return True
        except Exception as exc:
            logger.error("add_notification failed: %s", exc)
            return False

    def get_notifications(
        self, user_id: str, unread_only: bool = False, limit: int = 50,
    ) -> list[dict]:
        try:
            query = _table('wallet_notifications').select('*').eq('user_id', user_id)
            if unread_only:
                query = query.eq('is_read', False)
            result = query.order('sent_at', desc=True).limit(limit).execute()
            return result.data
        except Exception as exc:
            logger.error("get_notifications failed: %s", exc)
            return []

    def get_unread_count(self, user_id: str) -> int:
        try:
            result = _table('wallet_notifications').select(
                'id', count='exact',
            ).eq('user_id', user_id).eq('is_read', False).execute()
            return result.count or 0
        except Exception as exc:
            logger.error("get_unread_count failed: %s", exc)
            return 0

    def mark_notification_read(self, user_id: str, notification_id: int) -> bool:
        try:
            _table('wallet_notifications').update({
                'is_read': True,
            }).eq('user_id', user_id).eq('id', notification_id).execute()
            return True
        except Exception as exc:
            logger.error("mark_notification_read failed: %s", exc)
            return False

    def mark_all_notifications_read(self, user_id: str) -> bool:
        try:
            _table('wallet_notifications').update({
                'is_read': True,
            }).eq('user_id', user_id).eq('is_read', False).execute()
            return True
        except Exception as exc:
            logger.error("mark_all_notifications_read failed: %s", exc)
            return False


# ===========================================================================
# Analysis jobs
# ===========================================================================

class SupabaseAnalysisJobRepo(AnalysisJobRepository):

    def create_job(self, job_id: str, user_id: str, job_data: dict) -> dict:
        row = {
            'job_id': job_id,
            'user_id': user_id,
            'status': 'pending',
            'progress': 0,
            'phase': 'queued',
            **job_data,
        }
        result = _table('analysis_jobs').insert(row).execute()
        return result.data[0] if result.data else row

    def get_job(self, job_id: str) -> dict | None:
        result = _table('analysis_jobs').select('*').eq('job_id', job_id).execute()
        return result.data[0] if result.data else None

    def get_job_progress(self, job_id: str) -> dict | None:
        result = _table('analysis_jobs').select(
            'status, progress, phase, tokens_total, tokens_completed',
        ).eq('job_id', job_id).execute()
        return result.data[0] if result.data else None

    def update_job(self, job_id: str, data: dict) -> bool:
        try:
            _table('analysis_jobs').update(data).eq('job_id', job_id).execute()
            return True
        except Exception as exc:
            logger.error("update_job failed: %s", exc)
            return False


# ===========================================================================
# Users
# ===========================================================================

class SupabaseUserRepo(UserRepository):

    def get_user(self, user_id: str) -> dict | None:
        result = _table('users').select('*').eq('user_id', user_id).limit(1).execute()
        return result.data[0] if result.data else None

    def create_user(self, user_id: str, wallet_address: str | None = None) -> bool:
        try:
            _ensure_user(user_id, wallet_address)
            return True
        except Exception:
            return False

    def get_subscription_tier(self, user_id: str) -> str:
        try:
            result = _table('users').select(
                'subscription_tier',
            ).eq('user_id', user_id).limit(1).execute()
            if result.data:
                return result.data[0].get('subscription_tier', 'free')
        except Exception:
            pass
        return 'free'


# ===========================================================================
# User settings
# ===========================================================================

class SupabaseUserSettingsRepo(UserSettingsRepository):

    def get_settings(self, user_id: str) -> dict | None:
        result = _table('user_settings').select('*').eq(
            'user_id', user_id,
        ).limit(1).execute()
        return result.data[0] if result.data else None

    def save_settings(self, user_id: str, settings: dict) -> bool:
        try:
            _table('user_settings').upsert({
                'user_id': user_id,
                'email': settings.get('email'),
                'timezone': settings.get('timezone', 'UTC'),
                'language': settings.get('language', 'English'),
                'email_alerts': settings.get('emailAlerts', True),
                'browser_notifications': settings.get('browserNotifications', True),
                'alert_threshold': settings.get('alertThreshold', 100),
                'default_timeframe': settings.get('defaultTimeframe', '7d'),
                'default_candle': settings.get('defaultCandle', '5m'),
                'min_roi_multiplier': settings.get('minRoiMultiplier', 3.0),
                'theme': settings.get('theme', 'dark'),
                'compact_mode': settings.get('compactMode', False),
                'data_refresh_rate': settings.get('dataRefreshRate', 30),
                'updated_at': 'now()',
            }, on_conflict='user_id').execute()
            return True
        except Exception as exc:
            logger.error("save_settings failed: %s", exc)
            return False


# ===========================================================================
# Analysis history
# ===========================================================================

class SupabaseAnalysisHistoryRepo(AnalysisHistoryRepository):

    def get_history(self, user_id: str, limit: int = 50) -> list[dict]:
        result = _table('user_analysis_history').select(
            'id, created_at, result_type, label, sublabel, data',
        ).eq('user_id', user_id).order(
            'created_at', desc=True,
        ).limit(limit).execute()

        return [
            {
                'id': r['id'],
                'resultType': r['result_type'],
                'label': r['label'],
                'sublabel': r['sublabel'],
                'timestamp': r['created_at'],
                'data': r['data'],
            }
            for r in result.data
        ]

    def save_entry(self, user_id: str, entry: dict) -> bool:
        try:
            _table('user_analysis_history').insert({
                'user_id': user_id,
                'result_type': entry.get('resultType'),
                'label': entry.get('label'),
                'sublabel': entry.get('sublabel'),
                'data': entry.get('data'),
            }).execute()
            return True
        except Exception as exc:
            logger.error("save_entry failed: %s", exc)
            return False

    def delete_entry(self, user_id: str, entry_id: str) -> bool:
        try:
            _table('user_analysis_history').delete().eq(
                'id', entry_id,
            ).eq('user_id', user_id).execute()
            return True
        except Exception as exc:
            logger.error("delete_entry failed: %s", exc)
            return False

    def clear_all(self, user_id: str) -> bool:
        try:
            _table('user_analysis_history').delete().eq(
                'user_id', user_id,
            ).execute()
            return True
        except Exception as exc:
            logger.error("clear_all failed: %s", exc)
            return False
