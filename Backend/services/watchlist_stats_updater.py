"""
Daily/Weekly watchlist stats updater with cron scheduling.
Handles: Daily refresh, Weekly reranking, 4-week degradation checks.

HARD QUALIFICATION FLOORS (from watchlist_manager):
  - Wallet must achieve >= 5x on every trade
  - Wallet must spend >= $75 per token (single or cumulative entries)
  - Token must do >= 30x from launch price to ATH
  - Anything below = Loss; at threshold = Draw; above = Win

ADDED_AT FILTERING:
  daily_stats_refresh fetches added_at per wallet and passes it to
  _refresh_wallet_metrics so only trades AFTER the wallet was added to the
  watchlist count toward stats.

MERGE POLICY:
  All Supabase updates are merge-only — only fields actually computed are
  written. Fields not in the update dict retain their existing values.
"""
from datetime import datetime, timedelta
from typing import List, Dict
from services.supabase_client import get_supabase_client, SCHEMA_NAME
from services.watchlist_manager import (
    WatchlistLeagueManager,
    MIN_WALLET_ROI_MULT,
    MIN_SPEND_USD,
    MIN_TOKEN_LAUNCH_TO_ATH,
)
import os


class WatchlistStatsUpdater:
    """Manages scheduled watchlist updates."""

    def __init__(self):
        self.supabase = get_supabase_client()
        self.schema   = SCHEMA_NAME
        self.manager  = WatchlistLeagueManager()

    def _table(self, name: str):
        return self.supabase.schema(self.schema).table(name)

    # =========================================================================
    # DAILY UPDATE (3am UTC) — Refresh stats only, NO reranking
    # =========================================================================

    def daily_stats_refresh(self):
        """
        Refresh metrics for all watchlist wallets.
        Updates: ROI, runners, win_rate, consistency_score, last_trade_time.
        Does NOT change rankings (that's weekly).
        All metrics respect the hard floors ($75 spend, 5x ROI, 30x token launch-to-ATH).

        Fetches added_at per wallet so _refresh_wallet_metrics only counts
        trades that occurred AFTER the wallet was added to the watchlist.
        MERGE-ONLY: only fields returned by _refresh_wallet_metrics are written.
        """
        print("\n" + "=" * 80)
        print(f"DAILY STATS REFRESH - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Floors: >=${MIN_SPEND_USD} spend | {MIN_WALLET_ROI_MULT}x ROI | {MIN_TOKEN_LAUNCH_TO_ATH}x token launch-to-ATH")
        print("=" * 80)

        # Fetch added_at alongside wallet/user so we can filter by watchlist date
        result = self._table('wallet_watchlist').select('wallet_address, user_id, added_at').execute()

        # Group by wallet address; keep the earliest added_at across all users
        # (a wallet watched by multiple users uses the earliest watchlist date so
        # we don't accidentally include pre-watchlist trades for newer watchers)
        unique_wallets = {}
        for row in result.data:
            addr = row['wallet_address']
            if addr not in unique_wallets:
                unique_wallets[addr] = {
                    'user_ids': [],
                    'added_at': row.get('added_at'),
                }
            unique_wallets[addr]['user_ids'].append(row['user_id'])
            existing_at = unique_wallets[addr]['added_at']
            row_at      = row.get('added_at')
            if row_at and (not existing_at or row_at < existing_at):
                unique_wallets[addr]['added_at'] = row_at

        print(f"\n[DAILY] Refreshing {len(unique_wallets)} unique wallets...")

        success_count = 0
        error_count   = 0

        for wallet_address, info in unique_wallets.items():
            try:
                # Pass added_at — only trades after this date count toward metrics
                metrics = self.manager._refresh_wallet_metrics(
                    wallet_address,
                    added_at=info.get('added_at'),
                )

                # MERGE-ONLY: skip fields that came back as None
                update_data = {'last_updated': datetime.utcnow().isoformat()}
                for field in [
                    'roi_7d', 'roi_30d', 'runners_7d', 'runners_30d',
                    'win_rate_7d', 'last_trade_time',
                    'professional_score', 'consistency_score',
                ]:
                    val = metrics.get(field)
                    if val is not None:
                        update_data[field] = val

                for user_id in info['user_ids']:
                    self._table('wallet_watchlist').update(
                        update_data
                    ).eq('user_id', user_id).eq('wallet_address', wallet_address).execute()

                success_count += 1
                if success_count % 10 == 0:
                    print(f"  Progress: {success_count}/{len(unique_wallets)}...")

            except Exception as e:
                print(f"  ✗ Error refreshing {wallet_address[:8]}...: {e}")
                error_count += 1

        print(f"\n[DAILY] Complete: {success_count} refreshed, {error_count} errors")
        print("=" * 80 + "\n")
        return {'success': success_count, 'errors': error_count}

    # =========================================================================
    # WEEKLY RERANK (Sunday 4am UTC) — Full rerank with position changes
    # =========================================================================

    def weekly_rerank_all(self):
        """
        Full watchlist reranking for all users.
        Detects position changes, updates form, checks degradation.
        Form and degradation use the hard qualification floors.
        rerank_user_watchlist internally fetches added_at per wallet.
        """
        print("\n" + "=" * 80)
        print(f"WEEKLY RERANKING - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Win criteria: wallet >{MIN_WALLET_ROI_MULT}x AND token >{MIN_TOKEN_LAUNCH_TO_ATH}x launch-to-ATH AND spend >=${MIN_SPEND_USD}")
        print("=" * 80)

        result   = self._table('wallet_watchlist').select('user_id').execute()
        user_ids = list(set(row['user_id'] for row in result.data))

        print(f"\n[WEEKLY] Reranking {len(user_ids)} users...")

        success_count = 0
        error_count   = 0

        for user_id in user_ids:
            try:
                self.manager.rerank_user_watchlist(user_id)
                print(f"  ✓ {user_id[:8]}...")
                success_count += 1
            except Exception as e:
                print(f"  ✗ {user_id[:8]}...: {e}")
                error_count += 1

        print(f"\n[WEEKLY] Complete: {success_count} reranked, {error_count} errors")
        print("=" * 80 + "\n")
        return {'success': success_count, 'errors': error_count}

    # =========================================================================
    # 4-WEEK CHECK (Every 28 days) — Deep degradation analysis
    # =========================================================================

    def four_week_degradation_check(self):
        """
        Compare current performance vs 4 weeks ago.
        Identifies wallets that need replacement.

        Degradation is assessed against the hard floors:
          - ROI drop measured in terms of the 5x floor equivalent
          - Runner drop uses floor-qualified runner counts (>= 5x AND >= $75 spend AND token >= 30x)
          - Consistency score drop indicates erratic entry timing across multiple entries
        """
        print("\n" + "=" * 80)
        print(f"4-WEEK DEGRADATION CHECK - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Using floors: {MIN_WALLET_ROI_MULT}x ROI | ${MIN_SPEND_USD} spend | {MIN_TOKEN_LAUNCH_TO_ATH}x token")
        print("=" * 80)

        four_weeks_ago = (datetime.utcnow() - timedelta(days=28)).isoformat()
        result         = self._table('wallet_watchlist').select('*').execute()
        all_wallets    = result.data

        print(f"\n[4-WEEK] Analyzing {len(all_wallets)} wallets...")

        degraded_count     = 0
        replacement_alerts = []

        for wallet in all_wallets:
            wallet_address = wallet['wallet_address']
            user_id        = wallet['user_id']

            history = (
                self._table('wallet_performance_history')
                .select('*')
                .eq('wallet_address', wallet_address)
                .eq('user_id', user_id)
                .gte('week_start', four_weeks_ago)
                .order('week_start')
                .execute()
            )

            if not history.data or len(history.data) < 4:
                continue

            first_week = history.data[0]
            last_week  = history.data[-1]

            # ── ROI comparison (floor-aware) ───────────────────────────────────
            # ROI drop threshold: losing more than half the floor-equivalent weekly target
            roi_drop       = first_week.get('avg_roi', 0)      - last_week.get('avg_roi', 0)
            runners_drop   = first_week.get('runners_hit', 0)  - last_week.get('runners_hit', 0)
            position_drop  = last_week.get('position', 999)    - first_week.get('position', 1)
            consistency_drop = (
                first_week.get('consistency_score', 50) - last_week.get('consistency_score', 50)
            )

            # Floor-calibrated degradation thresholds:
            #   ROI drop > 50% of the floor-equivalent: significant
            #   Runner drop >= 2 qualifying runners (each must be >= 5x AND >= $75 AND token >= 30x)
            #   Consistency drop >= 20pts: entry timing has become erratic
            ROI_FLOOR_EQUIV = (MIN_WALLET_ROI_MULT - 1) * 100   # 400%
            is_degraded = (
                roi_drop        > ROI_FLOOR_EQUIV * 0.50 or   # lost >200% (half the 5x floor equiv)
                runners_drop    >= 2                        or   # lost 2+ qualifying runners
                position_drop   >= 5                        or   # dropped 5+ positions
                consistency_drop >= 20                      or   # entry timing erratic (+20pt variance)
                last_week.get('zone') == 'relegation'
            )

            if is_degraded:
                degraded_count += 1
                alert_data = {
                    'wallet_address':            wallet_address,
                    'user_id':                   user_id,
                    'reason':                    self._get_degradation_reason(
                        roi_drop, runners_drop, position_drop, consistency_drop
                    ),
                    'current_position':          last_week.get('position'),
                    'four_weeks_ago_position':   first_week.get('position'),
                    'roi_change':                -roi_drop,
                    'runners_change':            -runners_drop,
                    'consistency_change':        -consistency_drop,
                    'floors': {
                        'min_roi_mult':          MIN_WALLET_ROI_MULT,
                        'min_spend_usd':         MIN_SPEND_USD,
                        'min_token_launch_ath':  MIN_TOKEN_LAUNCH_TO_ATH,
                    },
                }
                replacement_alerts.append(alert_data)

                # MERGE-ONLY: only status and degradation_alerts
                self._table('wallet_watchlist').update({
                    'status': 'critical',
                    'degradation_alerts': [{
                        'severity': 'red',
                        'message': (
                            f'4-week decline detected: {alert_data["reason"]} '
                            f'(floors: {MIN_WALLET_ROI_MULT}x ROI | ${MIN_SPEND_USD} spend | '
                            f'{MIN_TOKEN_LAUNCH_TO_ATH}x token launch-to-ATH)'
                        ),
                    }],
                    'last_updated': datetime.utcnow().isoformat(),
                }).eq('user_id', user_id).eq('wallet_address', wallet_address).execute()

                print(f"  🚨 DEGRADED: {wallet_address[:8]}... - {alert_data['reason']}")

        print(f"\n[4-WEEK] Found {degraded_count} degraded wallets")

        if replacement_alerts:
            self._send_replacement_alerts(replacement_alerts)

        print("=" * 80 + "\n")
        return {
            'degraded_count': degraded_count,
            'alerts_sent':    len(replacement_alerts),
        }

    def _get_degradation_reason(
        self,
        roi_drop: float,
        runners_drop: int,
        position_drop: int,
        consistency_drop: float = 0,
    ) -> str:
        """Generate human-readable degradation reason, floor-aware."""
        ROI_FLOOR_EQUIV = (MIN_WALLET_ROI_MULT - 1) * 100
        reasons = []

        if roi_drop > ROI_FLOOR_EQUIV * 0.50:
            reasons.append(f"ROI dropped {roi_drop:.0f}% (>{ROI_FLOOR_EQUIV * 0.50:.0f}% threshold)")
        if runners_drop >= 2:
            reasons.append(
                f"Lost {runners_drop} qualifying runners "
                f"(runners need {MIN_WALLET_ROI_MULT}x ROI + ${MIN_SPEND_USD} spend + {MIN_TOKEN_LAUNCH_TO_ATH}x token)"
            )
        if position_drop >= 5:
            reasons.append(f"Dropped {position_drop} positions")
        if consistency_drop >= 20:
            reasons.append(f"Entry consistency fell {consistency_drop:.0f}pts — erratic across multiple entries")

        return ", ".join(reasons) if reasons else "Performance decline below qualification floors"

    def _send_replacement_alerts(self, alerts: List[Dict]):
        """Send replacement suggestion alerts to users."""
        try:
            from redis import Redis
            from rq import Queue

            redis = Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))
            q     = Queue(connection=redis)

            for alert in alerts:
                q.enqueue('tasks.send_telegram_alert_async', alert['user_id'], 'replacement', alert)

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