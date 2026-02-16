"""
Elite 100 Manager - Generates and caches top performing wallets
"""
from datetime import datetime, timedelta
from typing import List, Dict
from services.supabase_client import get_supabase_client, SCHEMA_NAME


class Elite100Manager:
    """Manages Elite 100 and Community Top 100 rankings"""
    
    def __init__(self):
        self.supabase = get_supabase_client()
        self.schema = SCHEMA_NAME
    
    def _table(self, name: str):
        """Get table reference with schema"""
        return self.supabase.schema(self.schema).table(name)
    
    def generate_elite_100(self, sort_by='score') -> List[Dict]:
        """
        Generate Elite 100 - Top 100 wallets by professional performance
        Aggregates across ALL users' watchlists
        
        Args:
            sort_by: 'score', 'roi', 'runners'
        """
        print(f"\n[ELITE 100] Generating rankings (sort_by={sort_by})...")
        
        try:
            # Get ALL wallets from all users' watchlists
            result = self._table('wallet_watchlist').select(
                'wallet_address, tier, professional_score, roi_30d, '
                'runners_30d, win_rate_7d, consistency_score, '
                'last_trade_time, form'
            ).execute()
            
            wallets = result.data
            
            if not wallets:
                print("[ELITE 100] No wallets found")
                return []
            
            # Aggregate by wallet_address (same wallet may be in multiple watchlists)
            wallet_map = {}
            
            for w in wallets:
                addr = w['wallet_address']
                
                if addr not in wallet_map:
                    wallet_map[addr] = {
                        'wallet_address': addr,
                        'tier': w['tier'],
                        'professional_score': w['professional_score'] or 0,
                        'roi_30d': w['roi_30d'] or 0,
                        'runners_30d': w['runners_30d'] or 0,
                        'win_rate_7d': w['win_rate_7d'] or 0,
                        'consistency_score': w['consistency_score'] or 0,
                        'last_trade_time': w['last_trade_time'],
                        'form': w.get('form', []),
                        'times_added': 1
                    }
                else:
                    # Wallet is in multiple watchlists - take best metrics
                    existing = wallet_map[addr]
                    existing['professional_score'] = max(existing['professional_score'], w['professional_score'] or 0)
                    existing['roi_30d'] = max(existing['roi_30d'], w['roi_30d'] or 0)
                    existing['runners_30d'] = max(existing['runners_30d'], w['runners_30d'] or 0)
                    existing['times_added'] += 1
            
            # Convert to list
            elite_wallets = list(wallet_map.values())
            
            # Calculate composite score for each wallet
            for wallet in elite_wallets:
                wallet['composite_score'] = self._calculate_composite_score(wallet)
                wallet['win_streak'] = self._calculate_win_streak(wallet.get('form', []))
            
            # Sort based on preference
            if sort_by == 'roi':
                elite_wallets.sort(key=lambda x: x['roi_30d'], reverse=True)
            elif sort_by == 'runners':
                elite_wallets.sort(key=lambda x: x['runners_30d'], reverse=True)
            else:  # 'score' (default)
                elite_wallets.sort(key=lambda x: x['composite_score'], reverse=True)
            
            # Take top 100
            top_100 = elite_wallets[:100]
            
            print(f"[ELITE 100] ✅ Generated {len(top_100)} wallets")
            print(f"[ELITE 100] Top 3:")
            for i, w in enumerate(top_100[:3], 1):
                print(f"  #{i}: {w['wallet_address'][:8]}... - Score: {w['composite_score']:.0f}")
            
            # Cache results
            self._cache_elite_100(top_100, sort_by)
            
            return top_100
            
        except Exception as e:
            print(f"[ELITE 100] Error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _calculate_composite_score(self, wallet: Dict) -> float:
        """
        Calculate weighted composite score
        
        Factors:
        - Professional score (40%)
        - ROI 30d (30%)
        - Runner hits (20%)
        - Win rate (10%)
        """
        prof_score = wallet['professional_score'] or 0
        roi = wallet['roi_30d'] or 0
        runners = wallet['runners_30d'] or 0
        win_rate = wallet['win_rate_7d'] or 0
        
        # Normalize ROI to 0-100 scale (assume max 500% ROI)
        roi_normalized = min(100, (roi / 500) * 100)
        
        # Normalize runners to 0-100 scale (assume max 20 runners)
        runners_normalized = min(100, (runners / 20) * 100)
        
        composite = (
            (prof_score * 0.40) +
            (roi_normalized * 0.30) +
            (runners_normalized * 0.20) +
            (win_rate * 0.10)
        )
        
        return composite
    
    def _calculate_win_streak(self, form: List) -> int:
        """Calculate current win streak from form array"""
        if not form:
            return 0
        
        streak = 0
        for result in form:
            if result == 'win':
                streak += 1
            else:
                break
        
        return streak
    
    def _cache_elite_100(self, wallets: List[Dict], sort_by: str):
        """Cache Elite 100 results in database"""
        try:
            # Delete old cache
            self._table('elite_100_cache').delete().eq('cache_key', f'elite_100_{sort_by}').execute()
            
            # Insert new cache
            self._table('elite_100_cache').insert({
                'cache_key': f'elite_100_{sort_by}',
                'wallets': wallets,
                'generated_at': datetime.utcnow().isoformat()
            }).execute()
            
            print(f"[ELITE 100] Cached results for sort_by={sort_by}")
            
        except Exception as e:
            print(f"[ELITE 100] Cache error: {e}")
    
    def get_cached_elite_100(self, sort_by='score') -> List[Dict]:
        """Get cached Elite 100 (falls back to generating if cache is old)"""
        try:
            result = self._table('elite_100_cache').select(
                'wallets, generated_at'
            ).eq('cache_key', f'elite_100_{sort_by}').limit(1).execute()
            
            if result.data:
                cache = result.data[0]
                generated_at = datetime.fromisoformat(cache['generated_at'].replace('Z', '+00:00'))
                
                # Cache valid for 1 hour
                if datetime.utcnow().replace(tzinfo=generated_at.tzinfo) - generated_at < timedelta(hours=1):
                    print(f"[ELITE 100] Using cached results (age: {(datetime.utcnow().replace(tzinfo=generated_at.tzinfo) - generated_at).seconds // 60} min)")
                    return cache['wallets']
            
            # Cache miss or expired - regenerate
            print("[ELITE 100] Cache miss or expired - regenerating...")
            return self.generate_elite_100(sort_by)
            
        except Exception as e:
            print(f"[ELITE 100] Cache retrieval error: {e}")
            return self.generate_elite_100(sort_by)
    
    def generate_community_top_100(self) -> List[Dict]:
        """
        Generate Community Top 100 - Most added wallets this week
        """
        print("\n[COMMUNITY TOP 100] Generating rankings...")
        
        try:
            # Get wallets added in last 7 days
            week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
            
            result = self._table('wallet_watchlist').select(
                'wallet_address, tier, professional_score, added_at'
            ).gte('added_at', week_ago).execute()
            
            wallets = result.data
            
            if not wallets:
                print("[COMMUNITY TOP 100] No recent additions")
                return []
            
            # Count adds per wallet
            wallet_counts = {}
            
            for w in wallets:
                addr = w['wallet_address']
                
                if addr not in wallet_counts:
                    wallet_counts[addr] = {
                        'wallet_address': addr,
                        'times_added': 1,
                        'avg_score': w['professional_score'] or 0,
                        'tier_distribution': {w['tier']: 1},
                        'first_added': w['added_at']
                    }
                else:
                    entry = wallet_counts[addr]
                    entry['times_added'] += 1
                    
                    # Update avg score
                    current_total = entry['avg_score'] * (entry['times_added'] - 1)
                    entry['avg_score'] = (current_total + (w['professional_score'] or 0)) / entry['times_added']
                    
                    # Track tier distribution
                    tier = w['tier']
                    entry['tier_distribution'][tier] = entry['tier_distribution'].get(tier, 0) + 1
                    
                    # Track earliest add
                    if w['added_at'] < entry['first_added']:
                        entry['first_added'] = w['added_at']
            
            # Convert to list and calculate rank change
            community_wallets = list(wallet_counts.values())
            
            # Sort by times_added
            community_wallets.sort(key=lambda x: x['times_added'], reverse=True)
            
            # Take top 100
            top_100 = community_wallets[:100]
            
            # Add rank change (mock for now - would need historical data)
            for i, wallet in enumerate(top_100):
                wallet['rank_change'] = 0  # TODO: Compare with previous week's ranking
            
            print(f"[COMMUNITY TOP 100] ✅ Generated {len(top_100)} wallets")
            print(f"[COMMUNITY TOP 100] Top 3:")
            for i, w in enumerate(top_100[:3], 1):
                print(f"  #{i}: {w['wallet_address'][:8]}... - Added {w['times_added']} times")
            
            # Cache results
            self._cache_community_top_100(top_100)
            
            return top_100
            
        except Exception as e:
            print(f"[COMMUNITY TOP 100] Error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _cache_community_top_100(self, wallets: List[Dict]):
        """Cache Community Top 100 results"""
        try:
            # Delete old cache
            self._table('elite_100_cache').delete().eq('cache_key', 'community_top_100').execute()
            
            # Insert new cache
            self._table('elite_100_cache').insert({
                'cache_key': 'community_top_100',
                'wallets': wallets,
                'generated_at': datetime.utcnow().isoformat()
            }).execute()
            
            print("[COMMUNITY TOP 100] Cached results")
            
        except Exception as e:
            print(f"[COMMUNITY TOP 100] Cache error: {e}")
    
    def get_cached_community_top_100(self) -> List[Dict]:
        """Get cached Community Top 100"""
        try:
            result = self._table('elite_100_cache').select(
                'wallets, generated_at'
            ).eq('cache_key', 'community_top_100').limit(1).execute()
            
            if result.data:
                cache = result.data[0]
                generated_at = datetime.fromisoformat(cache['generated_at'].replace('Z', '+00:00'))
                
                # Cache valid for 1 hour
                if datetime.utcnow().replace(tzinfo=generated_at.tzinfo) - generated_at < timedelta(hours=1):
                    print(f"[COMMUNITY TOP 100] Using cached results")
                    return cache['wallets']
            
            # Cache miss or expired
            print("[COMMUNITY TOP 100] Cache miss - regenerating...")
            return self.generate_community_top_100()
            
        except Exception as e:
            print(f"[COMMUNITY TOP 100] Cache retrieval error: {e}")
            return self.generate_community_top_100()


def get_elite_manager():
    """Singleton getter for Elite100Manager"""
    global _elite_manager
    if '_elite_manager' not in globals():
        _elite_manager = Elite100Manager()
    return _elite_manager