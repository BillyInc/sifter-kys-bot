"""
Watchlist league mechanics - handles ranking, degradation, and promotion
"""
from datetime import datetime, timedelta
from typing import List, Dict
from collections import defaultdict
import statistics
from services.supabase_client import get_supabase_client, SCHEMA_NAME


class WatchlistLeagueManager:
    """Manages Premier League-style watchlist mechanics"""
    
    def __init__(self):
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
    
    def _table(self, name: str):
        return self.supabase.schema(self.schema).table(name)
    
    
    def rerank_user_watchlist(self, user_id: str):
        """
        Recalculate positions for ONE user's watchlist
        Called after: adding/removing wallet, daily refresh
        """
        # Get current watchlist
        watchlist = self._get_watchlist(user_id)
        
        if not watchlist:
            return []
        
        # Store old positions for movement tracking
        old_positions = {w['wallet_address']: w.get('position', 999) for w in watchlist}
        
        # 1. Refresh metrics for each wallet
        for wallet in watchlist:
            updated = self._refresh_wallet_metrics(wallet['wallet_address'])
            wallet.update(updated)
        
        # 2. Recalculate positions (sort by professional_score)
        watchlist = self._calculate_league_positions(watchlist)
        
        # 3. Detect movement from old positions
        watchlist = self._update_position_movements(watchlist, old_positions)
        
        # 4. Update form (last 5 trades)
        for wallet in watchlist:
            wallet['form'] = self._calculate_form(wallet['wallet_address'])
        
        # 5. Detect degradation
        for wallet in watchlist:
            self._detect_degradation(wallet)
        
        # 6. Save updated watchlist to DB
        self._save_watchlist(user_id, watchlist)
        
        # 7. Generate promotion queue if needed
        critical_count = sum(1 for w in watchlist if w.get('status') == 'critical')
        if critical_count > 0:
            self._generate_promotion_queue(user_id, watchlist)
        
        return watchlist
    
    
    def _refresh_wallet_metrics(self, wallet_address: str) -> Dict:
        """
        Fetch LATEST performance metrics for a wallet
        Uses RECENT activity (7 days) + historical context (30 days)
        """
        # Get recent activity (last 7 days)
        recent_trades = self._get_recent_trades(wallet_address, days=7)
        
        # Get 30-day context for ROI calculation
        trades_30d = self._get_recent_trades(wallet_address, days=30)
        
        # Calculate average distance to ATH and entry quality
        distance_to_ath_values = []
        entry_quality_values = []
        
        # Group trades by token to calculate per-token metrics
        by_token = defaultdict(lambda: {'buys': [], 'sells': [], 'ath_price': 0})
        
        for trade in trades_30d:
            token = trade.get('token_address')
            if not token:
                continue
            
            price = float(trade.get('price_per_token', 0))
            if price == 0:
                continue
            
            if trade.get('side') == 'buy':
                by_token[token]['buys'].append(price)
            else:
                by_token[token]['sells'].append(price)
            
            # Track highest price seen (proxy for ATH)
            if price > by_token[token]['ath_price']:
                by_token[token]['ath_price'] = price
        
        # Calculate metrics for each token
        for token, data in by_token.items():
            if data['buys'] and data['ath_price'] > 0:
                avg_entry = sum(data['buys']) / len(data['buys'])
                
                # Distance to ATH multiplier (ATH / entry)
                distance_to_ath_mult = data['ath_price'] / avg_entry if avg_entry > 0 else 0
                if distance_to_ath_mult > 0:
                    distance_to_ath_values.append(distance_to_ath_mult)
                
                # Entry quality: use minimum buy price as proxy
                min_entry = min(data['buys'])
                entry_quality_mult = avg_entry / min_entry if min_entry > 0 else 1
                if entry_quality_mult > 0:
                    entry_quality_values.append(entry_quality_mult)
        
        # Calculate averages
        avg_distance_to_ath = sum(distance_to_ath_values) / len(distance_to_ath_values) if distance_to_ath_values else 0
        avg_entry_quality = sum(entry_quality_values) / len(entry_quality_values) if entry_quality_values else 0
        
        # Calculate ROI multipliers
        total_invested_7d = sum(float(t.get('usd_value', 0)) for t in recent_trades if t.get('side') == 'buy')
        total_realized_7d = sum(float(t.get('usd_value', 0)) for t in recent_trades if t.get('side') == 'sell')
        roi_7d_mult = (total_realized_7d / total_invested_7d) if total_invested_7d > 0 else 1
        
        total_invested_30d = sum(float(t.get('usd_value', 0)) for t in trades_30d if t.get('side') == 'buy')
        total_realized_30d = sum(float(t.get('usd_value', 0)) for t in trades_30d if t.get('side') == 'sell')
        roi_30d_mult = (total_realized_30d / total_invested_30d) if total_invested_30d > 0 else 1
        
        # Calculate win rates (both 7d and 30d)
        win_rate_7d = self._calculate_win_rate(recent_trades)
        win_rate_30d = self._calculate_win_rate(trades_30d)
        
        # Calculate metrics
        metrics = {
            'roi_7d': self._calculate_roi_from_trades(recent_trades),
            'roi_30d': self._calculate_roi_from_trades(trades_30d),
            'roi_30d_multiplier': roi_30d_mult,
            'runners_7d': self._count_runners(recent_trades, min_multiplier=5.0),
            'runners_30d': self._count_runners(trades_30d, min_multiplier=5.0),
            'win_rate_7d': win_rate_7d,
            'win_rate_30d': win_rate_30d,
            'avg_distance_to_ath_multiplier': avg_distance_to_ath,
            'avg_entry_quality_multiplier': avg_entry_quality,
            'consistency_score': self._calculate_consistency(trades_30d),
            'professional_score': 0,  # Will calculate below
            'last_trade_time': recent_trades[0]['block_time'] if recent_trades else None
        }
        
        # Professional score = weighted combination
        metrics['professional_score'] = self._calculate_professional_score(metrics)
        
        return metrics
    
    
    def _calculate_professional_score(self, metrics: Dict) -> float:
        """
        Score = 40% ROI_7d + 30% runners_7d + 20% win_rate + 10% consistency
        Emphasizes RECENT performance (7 days) over 30-day average
        """
        score = 0
        
        # 40% weight on 7-day ROI
        roi_7d = metrics.get('roi_7d', 0)
        score += min(roi_7d / 2, 40)  # Cap at 40 points (200% ROI = max)
        
        # 30% weight on 7-day runners
        runners_7d = metrics.get('runners_7d', 0)
        score += min(runners_7d * 6, 30)  # 5 runners = max 30 points
        
        # 20% weight on win rate
        win_rate = metrics.get('win_rate_7d', 0)
        score += (win_rate / 100) * 20
        
        # 10% weight on consistency
        consistency = metrics.get('consistency_score', 0)
        score += (consistency / 100) * 10
        
        return round(score, 1)
    
    
    def _calculate_league_positions(self, wallets: List[Dict]) -> List[Dict]:
        """
        Rank wallets by professional_score
        Position 1 = highest score
        """
        # Sort by score (descending)
        sorted_wallets = sorted(
            wallets, 
            key=lambda w: w.get('professional_score', 0), 
            reverse=True
        )
        
        # Assign positions
        for idx, wallet in enumerate(sorted_wallets):
            wallet['position'] = idx + 1
            wallet['zone'] = self._get_zone(idx + 1, len(sorted_wallets))
        
        return sorted_wallets
    
    
    def _get_zone(self, position: int, total_wallets: int) -> str:
        """
        Zones scale with watchlist size
        IMPROVED VERSION - handles small watchlists properly
        """
        if total_wallets <= 5:
            # Small watchlist: simpler zones
            if position == 1:
                return 'Elite'      # #1 only
            elif position <= 3:
                return 'midtable'       # #2-3
            else:
                return 'monitoring'     # #4-5 (no relegation yet)
        
        elif total_wallets <= 10:
            # Standard watchlist
            if position <= 3:
                return 'Elite'      # Top 3
            elif position <= 6:
                return 'midtable'       # #4-6
            elif position <= 8:
                return 'monitoring'     # #7-8
            else:
                return 'relegation'     # #9-10
        
        else:
            # Large watchlist: percentage-based
            percentage = position / total_wallets
            
            if percentage <= 0.3:
                return 'Elite'      # Top 30%
            elif percentage <= 0.6:
                return 'midtable'       # 30-60%
            elif percentage <= 0.8:
                return 'monitoring'     # 60-80%
            else:
                return 'relegation'     # Bottom 20%
    
    
    def _update_position_movements(self, watchlist: List[Dict], old_positions: Dict) -> List[Dict]:
        """Track position changes"""
        for wallet in watchlist:
            addr = wallet['wallet_address']
            old_pos = old_positions.get(addr, 999)
            new_pos = wallet['position']
            
            if new_pos < old_pos:
                wallet['movement'] = 'up'
                wallet['positions_changed'] = old_pos - new_pos
            elif new_pos > old_pos:
                wallet['movement'] = 'down'
                wallet['positions_changed'] = new_pos - old_pos
            else:
                wallet['movement'] = 'stable'
                wallet['positions_changed'] = 0
        
        return watchlist
    
    
    def _calculate_form(self, wallet_address: str) -> List[Dict]:
        """
        Last 5 trades as Win/Draw/Loss
        Win = ROI > 3x (300%)
        Draw = ROI 0-3x
        Loss = ROI < 0%
        
        Form = outcome of last 5 TRADES (not time-based)
        """
        trades = self._get_recent_trades(wallet_address, limit=5, days=30)  # Max 30d lookback
        
        form = []
        for trade in trades:
            # Get ROI from trade
            roi = trade.get('roi_percent', 0)
            
            # Win = >3x (300% ROI)
            if roi > 300:
                result = 'win'
            elif roi > 0:
                result = 'draw'
            else:
                result = 'loss'
            
            form.append({
                'type': result,
                'result': result,
                'token': trade.get('token_ticker', 'UNKNOWN'),
                'roi': f"{roi:.1f}%",
                'time': self._format_time_ago(trade.get('block_time')),
                'description': f"{trade.get('side', '').upper()} ${trade.get('token_ticker', '')}"
            })
        
        return form
    
    
    def _detect_degradation(self, wallet: Dict):
        """
        Flag wallets based on RECENT performance (7 days)
        IMPROVED VERSION - compares 7-day vs 30-day metrics
        More responsive than 30-day averages alone
        """
        alerts = []
        
        # PRIMARY: 7-day performance (what matters NOW)
        roi_7d = wallet.get('roi_7d', 0)
        runners_7d = wallet.get('runners_7d', 0)
        win_rate_7d = wallet.get('win_rate_7d', 0)
        
        # SECONDARY: 30-day context (is this a trend or blip?)
        roi_30d = wallet.get('roi_30d', 0)
        runners_30d = wallet.get('runners_30d', 0)
        
        # Alert 1: No recent activity (7 days)
        if not wallet.get('last_trade_time'):
            alerts.append({
                'severity': 'orange',
                'message': 'No trading activity in 7+ days'
            })
        else:
            last_trade = wallet['last_trade_time']
            if isinstance(last_trade, str):
                last_trade = datetime.fromisoformat(last_trade.replace('Z', '+00:00'))
            
            days_since = (datetime.utcnow().replace(tzinfo=last_trade.tzinfo) - last_trade).days
            if days_since > 7:
                alerts.append({
                    'severity': 'yellow',
                    'message': f'No activity for {days_since} days'
                })
        
        # Alert 2: Poor 7-day ROI (with 30-day context)
        if roi_7d < 10:  # Less than 10% THIS WEEK
            if roi_30d > 50:
                # Still good on 30d - just a bad week
                alerts.append({
                    'severity': 'yellow',
                    'message': f'Slow week: {roi_7d:.1f}% 7d ROI (but {roi_30d:.1f}% 30d)'
                })
            else:
                # Bad on both - CRITICAL
                alerts.append({
                    'severity': 'red',
                    'message': f'Sustained decline: {roi_7d:.1f}% 7d, {roi_30d:.1f}% 30d'
                })
        elif roi_7d < 25:  # Less than 25% in a week
            alerts.append({
                'severity': 'orange',
                'message': f'7-day ROI below target: {roi_7d:.1f}% (target: 25%+)'
            })
        
        # Alert 3: No runners this week (with 30-day context)
        if runners_7d == 0:
            if runners_30d >= 3:
                # Had runners recently - just quiet
                alerts.append({
                    'severity': 'yellow',
                    'message': f'No runners this week (but {runners_30d} in last 30d)'
                })
            else:
                # No runners at all - CRITICAL
                alerts.append({
                    'severity': 'red',
                    'message': 'No 5x+ runners in 30 days - replace immediately'
                })
        
        # Alert 4: Low win rate
        if win_rate_7d < 30:
            alerts.append({
                'severity': 'orange',
                'message': f'Win rate dropped to {win_rate_7d:.0f}% (threshold: 30%)'
            })
        
        # Alert 5: In relegation zone
        if wallet.get('zone') == 'relegation':
            alerts.append({
                'severity': 'red',
                'message': f'In relegation zone (position #{wallet["position"]})'
            })
        
        # Alert 6: Negative form (3+ losses in last 5)
        form = wallet.get('form', [])
        recent_losses = sum(1 for f in form[:3] if f.get('type') == 'loss')  # Last 3 trades
        
        if recent_losses >= 2:
            alerts.append({
                'severity': 'orange',
                'message': f'Poor form: {recent_losses}/3 recent losses'
            })
        
        # Set overall status
        if any(a['severity'] == 'red' for a in alerts):
            wallet['status'] = 'critical'
        elif any(a['severity'] in ['orange', 'yellow'] for a in alerts):
            wallet['status'] = 'warning'
        else:
            wallet['status'] = 'healthy'
        
        wallet['degradation_alerts'] = alerts
    
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _get_watchlist(self, user_id: str) -> List[Dict]:
        """Get user's current watchlist from database"""
        try:
            result = self._table('wallet_watchlist').select('*').eq('user_id', user_id).execute()
            return result.data
        except Exception as e:
            print(f"[WATCHLIST MANAGER] Error getting watchlist: {e}")
            return []
    
    
    def _save_watchlist(self, user_id: str, watchlist: List[Dict]):
        """Save updated watchlist back to database"""
        try:
            for wallet in watchlist:
                self._table('wallet_watchlist').update({
                    'position': wallet.get('position'),
                    'zone': wallet.get('zone'),
                    'movement': wallet.get('movement'),
                    'positions_changed': wallet.get('positions_changed', 0),
                    'form': wallet.get('form', []),
                    'status': wallet.get('status', 'healthy'),
                    'degradation_alerts': wallet.get('degradation_alerts', []),
                    'roi_7d': wallet.get('roi_7d', 0),
                    'roi_30d': wallet.get('roi_30d', 0),
                    'roi_30d_multiplier': wallet.get('roi_30d_multiplier', 1),
                    'runners_7d': wallet.get('runners_7d', 0),
                    'runners_30d': wallet.get('runners_30d', 0),
                    'win_rate_7d': wallet.get('win_rate_7d', 0),
                    'win_rate_30d': wallet.get('win_rate_30d', 0),
                    'avg_distance_to_ath_multiplier': wallet.get('avg_distance_to_ath_multiplier', 0),
                    'avg_entry_quality_multiplier': wallet.get('avg_entry_quality_multiplier', 0),
                    'last_trade_time': wallet.get('last_trade_time'),
                    'professional_score': wallet.get('professional_score', 0),
                    'consistency_score': wallet.get('consistency_score', 0),
                    'last_updated': datetime.utcnow().isoformat()
                }).eq('user_id', user_id).eq('wallet_address', wallet['wallet_address']).execute()
        except Exception as e:
            print(f"[WATCHLIST MANAGER] Error saving watchlist: {e}")
    
    
    def _generate_promotion_queue(self, user_id: str, watchlist: List[Dict]):
        """Find replacement candidates for degrading wallets"""
        try:
            from routes.wallets import get_wallet_analyzer
            analyzer = get_wallet_analyzer()
            
            # Find trending runners
            runners = analyzer.find_trending_runners_enhanced(
                days_back=30,
                min_multiplier=5.0,
                min_liquidity=50000
            )
            
            if not runners:
                return []
            
            # Analyze top runners for candidates
            all_candidates = []
            for runner in runners[:5]:  # Check top 5 runners
                wallets = analyzer.analyze_token_professional(
                    token_address=runner['address'],
                    token_symbol=runner['symbol'],
                    min_roi_multiplier=3.0,
                    user_id=user_id
                )
                
                # Filter for high performers not already in watchlist
                watchlist_addresses = {w['wallet_address'] for w in watchlist}
                qualified = [
                    w for w in wallets
                    if w['professional_score'] >= 70
                    and w.get('tier') in ['S', 'A']
                    and w['wallet'] not in watchlist_addresses
                ]
                
                all_candidates.extend(qualified[:3])  # Top 3 from each runner
            
            # Sort by score and return top 10
            all_candidates.sort(key=lambda x: x['professional_score'], reverse=True)
            return all_candidates[:10]
            
        except Exception as e:
            print(f"[WATCHLIST MANAGER] Error generating promotion queue: {e}")
            return []
    
    
    def _get_recent_trades(self, wallet_address: str, days: int = 7, limit: int = None) -> List[Dict]:
        """Get recent trades from wallet_activity table"""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            query = self._table('wallet_activity').select('*').eq(
                'wallet_address', wallet_address
            ).gte('block_time', cutoff.isoformat()).order('block_time', desc=True)
            
            if limit:
                query = query.limit(limit)
            
            result = query.execute()
            return result.data
        except Exception as e:
            print(f"[WATCHLIST MANAGER] Error getting recent trades: {e}")
            return []
    
    
    def _calculate_roi_from_trades(self, trades: List[Dict]) -> float:
        """Calculate ROI from list of trades"""
        if not trades:
            return 0
        
        total_invested = sum(float(t.get('usd_value', 0)) for t in trades if t.get('side') == 'buy')
        total_realized = sum(float(t.get('usd_value', 0)) for t in trades if t.get('side') == 'sell')
        
        if total_invested == 0:
            return 0
        
        return ((total_realized - total_invested) / total_invested) * 100
    
    
    def _count_runners(self, trades: List[Dict], min_multiplier: float = 5.0) -> int:
        """Count how many tokens hit 5x+"""
        if not trades:
            return 0
        
        # Group by token
        by_token = defaultdict(lambda: {'buys': [], 'sells': []})
        
        for trade in trades:
            token = trade.get('token_address')
            price = float(trade.get('price_per_token', 0))
            
            if price == 0:
                continue
            
            if trade.get('side') == 'buy':
                by_token[token]['buys'].append(price)
            else:
                by_token[token]['sells'].append(price)
        
        # Count runners
        runners = 0
        for token_data in by_token.values():
            if token_data['buys'] and token_data['sells']:
                avg_buy = sum(token_data['buys']) / len(token_data['buys'])
                avg_sell = sum(token_data['sells']) / len(token_data['sells'])
                
                if avg_sell / avg_buy >= min_multiplier:
                    runners += 1
        
        return runners
    
    
    def _calculate_win_rate(self, trades: List[Dict]) -> float:
        """% of profitable trades"""
        if not trades:
            return 0
        
        profitable = sum(1 for t in trades if float(t.get('roi_percent', 0)) > 0)
        return (profitable / len(trades)) * 100
    
    
    def _calculate_consistency(self, trades: List[Dict]) -> float:
        """How consistent are the wins? (0-100)"""
        if not trades:
            return 0
        
        # Standard deviation of ROIs
        rois = [float(t.get('roi_percent', 0)) for t in trades]
        
        if len(rois) < 2:
            return 50
        
        try:
            mean_roi = statistics.mean(rois)
            stdev = statistics.stdev(rois)
            
            # Lower stdev = higher consistency
            # Normalize to 0-100 scale
            consistency = max(0, 100 - (stdev / 2))
            
            return round(consistency, 1)
        except:
            return 50
    
    
    def _format_time_ago(self, timestamp) -> str:
        """Format timestamp as '2h ago', '3d ago', etc."""
        if not timestamp:
            return 'unknown'
        
        try:
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            
            now = datetime.utcnow()
            if timestamp.tzinfo:
                now = now.replace(tzinfo=timestamp.tzinfo)
            
            diff = (now - timestamp).total_seconds()
            
            if diff < 60:
                return 'just now'
            elif diff < 3600:
                return f'{int(diff / 60)}m ago'
            elif diff < 86400:
                return f'{int(diff / 3600)}h ago'
            else:
                return f'{int(diff / 86400)}d ago'
        except:
            return 'unknown'