from typing import List, Dict
from collections import defaultdict
import pandas as pd
from datetime import datetime


class BatchTokenAnalyzer:
    """
    Analyzes multiple tokens and compares top callers across them
    Tracks how accounts perform and their SNA metrics change over time
    """
    
    def __init__(self):
        self.all_results = []
        self.cross_token_accounts = {}
    
    
    def analyze_multiple_tokens(
        self,
        token_list: List[Dict],
        rally_tweet_connector,
        days_back: int = 7  # SIMPLIFIED: Just a number now
    ) -> List[Dict]:
        """
        Analyze multiple tokens sequentially
        
        Args:
            token_list: List of dicts with 'address', 'ticker', 'name' (optional)
            rally_tweet_connector: Initialized RallyTweetConnector instance
            days_back: Number of days to analyze (1-90)
        
        Returns:
            List of analysis results for each token
        """
        print(f"\n{'='*100}")
        print(f"BATCH ANALYSIS: {len(token_list)} TOKENS")
        print(f"{'='*100}\n")
        
        for idx, token_info in enumerate(token_list, 1):
            print(f"\n[BATCH {idx}/{len(token_list)}] Analyzing token: {token_info.get('ticker', 'UNKNOWN')}")
            print(f"Address: {token_info['address']}")
            
            try:
                # Run single token analysis with simple days_back
                results = rally_tweet_connector.analyze_token_with_tweets(
                    token_address=token_info['address'],
                    days_back=days_back  # SIMPLIFIED: Just pass the number
                )
                
                if results:
                    # Store results with token metadata
                    self.all_results.append({
                        'token': token_info,
                        'results': results,
                        'timestamp': datetime.now()
                    })
                    
                    print(f"✓ Analysis complete: Found {len(results)} rallies")
                else:
                    print(f"⚠️ No rallies found for this token")
                    self.all_results.append({
                        'token': token_info,
                        'results': None,
                        'error': 'No rallies detected'
                    })
                
            except Exception as e:
                print(f"❌ Error analyzing token: {e}")
                self.all_results.append({
                    'token': token_info,
                    'results': None,
                    'error': str(e)
                })
        
        print(f"\n{'='*100}")
        print(f"BATCH ANALYSIS COMPLETE")
        print(f"Successful: {sum(1 for r in self.all_results if r['results'])}/{len(token_list)}")
        print(f"{'='*100}\n")
        
        return self.all_results

    
    
    def extract_cross_token_accounts(self) -> Dict[str, Dict]:
        """
        Find accounts that appear across multiple tokens
        Track their performance and metrics changes
        
        Returns:
            Dictionary mapping author_id -> aggregated stats across tokens
        """
        print(f"\n[CROSS-TOKEN] Analyzing accounts across {len(self.all_results)} tokens...")
        
        account_tracker = defaultdict(lambda: {
            'author_id': None,
            'username': None,
            'name': None,
            'tokens_called': [],
            'total_pumps': 0,
            'total_tweets': 0,
            'avg_timing_per_token': [],
            'earliest_calls': [],
            'influence_scores': [],
            'sna_metrics_timeline': [],
            'tokens_metadata': []
        })
        
        for token_result in self.all_results:
            if not token_result['results']:
                continue
            
            token_info = token_result['token']
            rally_results = token_result['results']
            
            # Extract all accounts from this token's analysis
            for result in rally_results:
                for scored_tweet in result.get('scored_tweets', []):
                    tweet = scored_tweet['tweet']
                    author_id = str(tweet['author_id'])
                    
                    tracker = account_tracker[author_id]
                    tracker['author_id'] = author_id
                    
                    # Track which tokens they called
                    if token_info['address'] not in [t['address'] for t in tracker['tokens_called']]:
                        tracker['tokens_called'].append({
                            'address': token_info['address'],
                            'ticker': token_info.get('ticker', 'UNKNOWN'),
                            'name': token_info.get('name', ''),
                            'timestamp': token_result.get('timestamp')
                        })
                    
                    tracker['total_pumps'] += 1
                    tracker['total_tweets'] += 1
                    tracker['avg_timing_per_token'].append(tweet['time_to_rally_minutes'])
                    tracker['earliest_calls'].append(tweet['time_to_rally_minutes'])
        
        # Calculate aggregated stats
        for author_id, stats in account_tracker.items():
            stats['tokens_count'] = len(stats['tokens_called'])
            stats['avg_timing_overall'] = (
                sum(stats['avg_timing_per_token']) / len(stats['avg_timing_per_token'])
                if stats['avg_timing_per_token'] else 0
            )
            stats['earliest_call_overall'] = (
                min(stats['earliest_calls']) if stats['earliest_calls'] else 0
            )
        
        self.cross_token_accounts = dict(account_tracker)
        
        print(f"[CROSS-TOKEN] Found {len(self.cross_token_accounts)} unique accounts")
        print(f"[CROSS-TOKEN] Accounts appearing in 2+ tokens: {sum(1 for a in self.cross_token_accounts.values() if a['tokens_count'] >= 2)}")
        
        return self.cross_token_accounts
    
    
    def rank_cross_token_accounts(self, min_tokens: int = 2) -> List[Dict]:
        """
        Rank accounts by cross-token performance
        
        Args:
            min_tokens: Minimum number of tokens account must appear in
        
        Returns:
            Sorted list of accounts by cross-token influence
        """
        if not self.cross_token_accounts:
            self.extract_cross_token_accounts()
        
        # Filter accounts that appear in multiple tokens
        multi_token_accounts = [
            acc for acc in self.cross_token_accounts.values() 
            if acc['tokens_count'] >= min_tokens
        ]
        
        # Calculate cross-token influence score
        for account in multi_token_accounts:
            score = (
                (account['tokens_count'] * 50) +  # More tokens = much better
                (account['total_pumps'] * 20) +   # Total pumps called
                (max(0, -account['avg_timing_overall']) * 3) +  # Average early timing
                (max(0, -account['earliest_call_overall']) * 5)  # Best early call
            )
            account['cross_token_influence'] = round(score, 1)
        
        # Sort by influence
        ranked = sorted(
            multi_token_accounts, 
            key=lambda x: x['cross_token_influence'], 
            reverse=True
        )
        
        print(f"\n[RANKING] Top 10 cross-token accounts:")
        for i, acc in enumerate(ranked[:10], 1):
            print(f"  {i}. @{acc.get('username', acc['author_id'])}: "
                  f"{acc['tokens_count']} tokens, "
                  f"{acc['total_pumps']} pumps, "
                  f"Avg timing: T{acc['avg_timing_overall']:.1f}m")
        
        return ranked
    
    
    def compare_account_across_tokens(self, author_id: str) -> Dict:
        """
        Deep dive into how one account performed across different tokens
        
        Args:
            author_id: Twitter user ID to analyze
        
        Returns:
            Detailed comparison across all tokens they called
        """
        if author_id not in self.cross_token_accounts:
            return None
        
        account = self.cross_token_accounts[author_id]
        
        comparison = {
            'author_id': author_id,
            'username': account.get('username'),
            'summary': {
                'tokens_count': account['tokens_count'],
                'total_pumps': account['total_pumps'],
                'avg_timing': account['avg_timing_overall'],
                'earliest_call': account['earliest_call_overall']
            },
            'per_token_breakdown': []
        }
        
        # Analyze performance per token
        for token_info in account['tokens_called']:
            # Find tweets for this specific token
            token_tweets = []
            for token_result in self.all_results:
                if token_result['token']['address'] == token_info['address'] and token_result['results']:
                    for rally_result in token_result['results']:
                        for scored_tweet in rally_result.get('scored_tweets', []):
                            if str(scored_tweet['tweet']['author_id']) == author_id:
                                token_tweets.append(scored_tweet)
            
            if token_tweets:
                timings = [t['tweet']['time_to_rally_minutes'] for t in token_tweets]
                scores = [t['score']['total_score'] for t in token_tweets]
                
                comparison['per_token_breakdown'].append({
                    'token': token_info,
                    'pumps_called': len(token_tweets),
                    'avg_timing': round(sum(timings) / len(timings), 1),
                    'earliest_timing': min(timings),
                    'avg_score': round(sum(scores) / len(scores), 1),
                    'high_confidence_count': sum(1 for t in token_tweets if t['score']['confidence'] == 'high')
                })
        
        return comparison
    
    
    def detect_coordination_across_tokens(self) -> Dict:
        """
        Identify groups of accounts that repeatedly appear together
        
        Returns:
            Coordination analysis across multiple tokens
        """
        print(f"\n[COORDINATION] Detecting cross-token coordination patterns...")
        
        # Build co-occurrence matrix
        token_account_sets = []
        
        for token_result in self.all_results:
            if not token_result['results']:
                continue
            
            accounts_in_token = set()
            for rally_result in token_result['results']:
                for scored_tweet in rally_result.get('scored_tweets', []):
                    accounts_in_token.add(str(scored_tweet['tweet']['author_id']))
            
            if accounts_in_token:
                token_account_sets.append({
                    'token': token_result['token'],
                    'accounts': accounts_in_token
                })
        
        # Find accounts that co-occur frequently
        cooccurrence = defaultdict(int)
        
        for i, set1 in enumerate(token_account_sets):
            for j, set2 in enumerate(token_account_sets[i+1:], i+1):
                shared = set1['accounts'] & set2['accounts']
                
                if len(shared) >= 3:  # At least 3 accounts in common
                    for acc1 in shared:
                        for acc2 in shared:
                            if acc1 < acc2:  # Avoid duplicates
                                pair = (acc1, acc2)
                                cooccurrence[pair] += 1
        
        # Find groups with high co-occurrence
        coordinated_groups = []
        
        for (acc1, acc2), count in cooccurrence.items():
            if count >= 2:  # Appeared together in 2+ tokens
                coordinated_groups.append({
                    'account_1': acc1,
                    'account_2': acc2,
                    'tokens_together': count,
                    'coordination_score': count * 10
                })
        
        coordinated_groups.sort(key=lambda x: x['coordination_score'], reverse=True)
        
        print(f"[COORDINATION] Found {len(coordinated_groups)} potentially coordinated pairs")
        
        return {
            'coordinated_pairs': coordinated_groups[:20],  # Top 20
            'total_pairs_detected': len(coordinated_groups),
            'high_coordination_count': sum(1 for g in coordinated_groups if g['tokens_together'] >= 3)
        }
    
    
    def export_to_csv(self, filename: str = 'cross_token_analysis.csv'):
        """
        Export cross-token account rankings to CSV
        
        Args:
            filename: Output filename
        """
        if not self.cross_token_accounts:
            self.extract_cross_token_accounts()
        
        # Prepare data for CSV
        csv_data = []
        
        for author_id, stats in self.cross_token_accounts.items():
            csv_data.append({
                'Author ID': author_id,
                'Username': stats.get('username', ''),
                'Tokens Called': stats['tokens_count'],
                'Total Pumps': stats['total_pumps'],
                'Avg Timing (min)': round(stats['avg_timing_overall'], 1),
                'Earliest Call (min)': round(stats['earliest_call_overall'], 1),
                'Cross-Token Influence': stats.get('cross_token_influence', 0),
                'Token List': ', '.join([t['ticker'] for t in stats['tokens_called']])
            })
        
        df = pd.DataFrame(csv_data)
        df = df.sort_values('Cross-Token Influence', ascending=False)
        df.to_csv(filename, index=False)
        
        print(f"\n[EXPORT] Saved to {filename}")
        return filename
    
    
    def _parse_time_range(self, time_range: str) -> int:
        """Convert time range string to days"""
        mapping = {
            'first_5m': 1,
            'first_24h': 1,
            'first_7d': 7,
            'first_30d': 30,
            'last_1h': 1,
            'last_5h': 1,
            'last_24h': 1,
            'last_3d': 3,
            'last_7d': 7,
            'last_30d': 30,
            'all': 90
        }
        return mapping.get(time_range, 7)