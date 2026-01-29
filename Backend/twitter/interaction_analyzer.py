from datetime import datetime, timedelta
from typing import List, Dict
from collections import defaultdict
import networkx as nx
import time
from tweet_extractor_twitterapiio import TwitterTweetExtractor


class InteractionAnalyzer:
    """
    Analyzes Twitter interactions (likes, retweets, replies, mentions) 
    between accounts to calculate a Coordination Index.
    
    This determines if accounts are working together organically or as part 
    of an organized group.
    
    UPDATED: Uses TwitterAPI.io via TwitterTweetExtractor
    """
    
    def __init__(self, tweet_extractor: TwitterTweetExtractor):
        """
        Initialize with tweet extractor (contains API key pool)
        
        Args:
            tweet_extractor: TwitterTweetExtractor instance with API key pool
        """
        self.extractor = tweet_extractor
        self.interaction_graph = nx.DiGraph()
        self.interactions = {
            'likes': [],
            'retweets': [],
            'replies': [],
            'mentions': [],
            'quote_tweets': []
        }
    
    
    def analyze_account_interactions(
        self, 
        account_ids: List[str],
        account_usernames: List[str],
        days_back: int = 30
    ) -> Dict[str, any]:
        """
        Main analysis function - checks how accounts interact with each other
        
        Args:
            account_ids: List of Twitter user IDs (from Top 20)
            account_usernames: List of Twitter usernames
            days_back: How many days back to analyze (7, 30, 90, 180)
        
        Returns:
            Complete interaction analysis with Coordination Index
        """
        print(f"\n{'='*80}")
        print(f"INTERACTION ANALYSIS: {len(account_ids)} accounts over last {days_back} days")
        print(f"{'='*80}\n")
        
        print(f"[STEP 1/4] Fetching recent tweets from each account...")
        
        # Fetch tweets from each account
        account_tweets = {}
        total_tweets_fetched = 0
        
        for idx, (user_id, username) in enumerate(zip(account_ids, account_usernames), 1):
            print(f"   [{idx}/{len(account_ids)}] @{username}...", end=' ')
            
            try:
                # Get user's recent tweets using TwitterAPI.io
                tweets = self.extractor.get_user_timeline(user_id, max_results=100)
                
                if tweets:
                    account_tweets[user_id] = tweets
                    total_tweets_fetched += len(tweets)
                    print(f"✓ {len(tweets)} tweets")
                else:
                    account_tweets[user_id] = []
                    print("✓ 0 tweets")
                
                time.sleep(1)  # Rate limiting
                
            except Exception as e:
                print(f"✗ Error: {e}")
                account_tweets[user_id] = []
        
        print(f"\n   Total tweets fetched: {total_tweets_fetched}\n")
        
        # Extract interactions
        print(f"[STEP 2/4] Analyzing interactions between accounts...")
        
        self._extract_interactions_from_tweets(
            account_tweets=account_tweets,
            account_ids=account_ids
        )
        
        # Also get direct interactions via API
        interactions_data = self.extractor.get_account_interactions(
            account_usernames=account_usernames,
            days_back=days_back
        )
        
        # Merge interactions
        self.interactions['mentions'].extend(interactions_data.get('mentions', []))
        self.interactions['replies'].extend(interactions_data.get('replies', []))
        self.interactions['retweets'].extend(interactions_data.get('retweets', []))
        self.interactions['quote_tweets'].extend(interactions_data.get('quote_tweets', []))
        
        # Build interaction graph
        print(f"\n[STEP 3/4] Building interaction network...")
        
        self._build_interaction_graph(account_ids, account_usernames)
        
        # Calculate metrics
        print(f"\n[STEP 4/4] Calculating Coordination Index...\n")
        
        metrics = self._calculate_interaction_metrics()
        
        coordination_index = self._calculate_coordination_index(metrics)
        
        # Generate report
        report = {
            'summary': {
                'accounts_analyzed': len(account_ids),
                'days_analyzed': days_back,
                'total_tweets': total_tweets_fetched,
                'total_interactions': sum(len(v) for v in self.interactions.values())
            },
            'interactions': {
                'likes': len(self.interactions['likes']),
                'retweets': len(self.interactions['retweets']),
                'replies': len(self.interactions['replies']),
                'mentions': len(self.interactions['mentions']),
                'quote_tweets': len(self.interactions['quote_tweets'])
            },
            'metrics': metrics,
            'coordination_index': coordination_index,
            'assessment': self._generate_assessment(coordination_index),
            'interaction_pairs': self._get_top_interaction_pairs(),
            'visualization_data': self._export_for_visualization()
        }
        
        self._print_report(report)
        
        return report
    
    
    def _extract_interactions_from_tweets(
        self, 
        account_tweets: Dict[str, List],
        account_ids: List[str]
    ):
        """Extract all interactions from tweet data"""
        
        account_id_set = set(account_ids)
        
        for user_id, tweets in account_tweets.items():
            for tweet in tweets:
                
                # Check tweet structure (from our extractor)
                # Tweets have: id, text, created_at, likes, retweets
                
                # Note: TwitterAPI.io doesn't return referenced_tweets or entities
                # in the basic timeline, so we're limited in what we can extract here
                # We'll rely more on the get_account_interactions() method
                
                pass
        
        print(f"   Extracted interactions from timelines (limited data)")
    
    
    def _build_interaction_graph(self, account_ids: List[str], account_usernames: List[str]):
        """Build directed graph from interactions"""
        
        # Add all accounts as nodes
        for user_id in account_ids:
            self.interaction_graph.add_node(user_id)
        
        # Create username to ID mapping
        username_to_id = dict(zip(account_usernames, account_ids))
        
        # Add edges for mentions (weighted)
        mention_counts = defaultdict(lambda: defaultdict(int))
        
        for mention in self.interactions['mentions']:
            source_id = str(mention.get('author_id'))
            mentioned_username = mention.get('mentioned_username', '')
            target_id = username_to_id.get(mentioned_username)
            
            if source_id in account_ids and target_id:
                mention_counts[source_id][target_id] += 1
        
        # Add edges to graph
        for source in mention_counts:
            for target, count in mention_counts[source].items():
                self.interaction_graph.add_edge(
                    source, 
                    target, 
                    weight=count,
                    mentions=count,
                    retweets=0,
                    replies=0
                )
        
        print(f"   Network: {self.interaction_graph.number_of_nodes()} nodes, "
              f"{self.interaction_graph.number_of_edges()} edges")
    
    
    def _calculate_interaction_metrics(self) -> Dict[str, float]:
        """Calculate network metrics"""
        
        if self.interaction_graph.number_of_nodes() < 2:
            return {
                'density': 0,
                'reciprocity': 0,
                'clustering': 0,
                'average_degree': 0
            }
        
        # Network density
        density = nx.density(self.interaction_graph)
        
        # Reciprocity (how many edges are bidirectional)
        try:
            reciprocity = nx.reciprocity(self.interaction_graph)
        except:
            reciprocity = 0
        
        # Clustering coefficient
        undirected = self.interaction_graph.to_undirected()
        try:
            clustering = nx.average_clustering(undirected)
        except:
            clustering = 0
        
        # Average degree
        degrees = dict(undirected.degree())
        avg_degree = sum(degrees.values()) / len(degrees) if degrees else 0
        
        return {
            'density': round(density, 4),
            'reciprocity': round(reciprocity, 3),
            'clustering': round(clustering, 3),
            'average_degree': round(avg_degree, 2)
        }
    
    
    def _calculate_coordination_index(self, metrics: Dict) -> Dict[str, any]:
        """
        Calculate Coordination Index (0-100)
        
        High coordination indicators:
        - High reciprocity (mutual following/interaction)
        - High clustering (tight groups)
        - High interaction density
        - Synchronized timing patterns
        
        Returns:
            Dictionary with index and breakdown
        """
        
        # Initialize score components
        scores = {
            'reciprocity_score': 0,
            'clustering_score': 0,
            'density_score': 0,
            'interaction_volume_score': 0
        }
        
        # Reciprocity Score (0-30 points)
        if metrics['reciprocity'] > 0.7:
            scores['reciprocity_score'] = 30
        elif metrics['reciprocity'] > 0.5:
            scores['reciprocity_score'] = 20
        elif metrics['reciprocity'] > 0.3:
            scores['reciprocity_score'] = 10
        
        # Clustering Score (0-30 points)
        if metrics['clustering'] > 0.6:
            scores['clustering_score'] = 30
        elif metrics['clustering'] > 0.4:
            scores['clustering_score'] = 20
        elif metrics['clustering'] > 0.2:
            scores['clustering_score'] = 10
        
        # Density Score (0-25 points)
        if metrics['density'] > 0.3:
            scores['density_score'] = 25
        elif metrics['density'] > 0.2:
            scores['density_score'] = 15
        elif metrics['density'] > 0.1:
            scores['density_score'] = 8
        
        # Interaction Volume Score (0-15 points)
        total_interactions = sum(len(v) for v in self.interactions.values())
        if total_interactions > 100:
            scores['interaction_volume_score'] = 15
        elif total_interactions > 50:
            scores['interaction_volume_score'] = 10
        elif total_interactions > 20:
            scores['interaction_volume_score'] = 5
        
        # Calculate final index
        coordination_index = sum(scores.values())
        
        # Determine coordination level
        if coordination_index >= 70:
            level = 'Very High'
            description = 'Strong evidence of organized coordination'
        elif coordination_index >= 50:
            level = 'High'
            description = 'Likely coordinated group activity'
        elif coordination_index >= 30:
            level = 'Moderate'
            description = 'Some coordination patterns detected'
        else:
            level = 'Low'
            description = 'Organic interaction patterns'
        
        return {
            'index': round(coordination_index, 1),
            'level': level,
            'description': description,
            'breakdown': scores,
            'max_possible': 100
        }
    
    
    def _generate_assessment(self, coordination_data: Dict) -> Dict[str, any]:
        """Generate human-readable assessment"""
        
        index = coordination_data['index']
        
        # Key findings
        findings = []
        
        if coordination_data['breakdown']['reciprocity_score'] >= 20:
            findings.append("High reciprocal interaction patterns detected")
        
        if coordination_data['breakdown']['clustering_score'] >= 20:
            findings.append("Tight-knit group structure identified")
        
        if coordination_data['breakdown']['density_score'] >= 15:
            findings.append("Dense interaction network observed")
        
        total_interactions = sum(len(v) for v in self.interactions.values())
        if total_interactions > 50:
            findings.append(f"High interaction volume ({total_interactions} interactions)")
        
        # Red flags
        red_flags = []
        
        if index >= 70:
            red_flags.append("Coordination Index exceeds 70% - strong coordination")
        
        mention_count = len(self.interactions['mentions'])
        if mention_count > 30:
            red_flags.append(f"Unusually high mention activity ({mention_count} mentions)")
        
        return {
            'coordination_likely': index >= 50,
            'confidence': 'high' if index >= 70 else 'medium' if index >= 50 else 'low',
            'key_findings': findings,
            'red_flags': red_flags if red_flags else ['No major red flags detected']
        }
    
    
    def _get_top_interaction_pairs(self, top_n: int = 10) -> List[Dict]:
        """Get the most interactive account pairs"""
        
        pairs = []
        
        # Count mentions between pairs
        for edge in self.interaction_graph.edges(data=True):
            source, target, data = edge
            weight = data.get('weight', 1)
            
            pairs.append({
                'account_1': source,
                'account_2': target,
                'interactions': weight,
                'type': 'mentions'
            })
        
        # Sort by interaction count
        pairs.sort(key=lambda x: x['interactions'], reverse=True)
        
        return pairs[:top_n]
    
    
    def _export_for_visualization(self) -> Dict[str, any]:
        """Export graph data for D3.js visualization"""
        
        nodes = []
        links = []
        
        # Export nodes
        for node_id in self.interaction_graph.nodes():
            out_degree = self.interaction_graph.out_degree(node_id, weight='weight')
            in_degree = self.interaction_graph.in_degree(node_id, weight='weight')
            
            nodes.append({
                'id': node_id,
                'interactions_sent': out_degree,
                'interactions_received': in_degree,
                'total_interactions': out_degree + in_degree
            })
        
        # Export edges
        for source, target, data in self.interaction_graph.edges(data=True):
            links.append({
                'source': source,
                'target': target,
                'weight': data.get('weight', 1),
                'mentions': data.get('mentions', 0)
            })
        
        return {
            'nodes': nodes,
            'links': links
        }
    
    
    def _print_report(self, report: Dict):
        """Print formatted analysis report"""
        
        print(f"\n{'='*80}")
        print("INTERACTION ANALYSIS REPORT")
        print(f"{'='*80}\n")
        
        coord = report['coordination_index']
        
        print(f"📊 COORDINATION INDEX: {coord['index']}/100")
        print(f"   Level: {coord['level']}")
        print(f"   {coord['description']}\n")
        
        print(f"📈 SCORE BREAKDOWN:")
        for key, value in coord['breakdown'].items():
            print(f"   • {key.replace('_', ' ').title()}: {value}")
        
        print(f"\n🔍 KEY FINDINGS:")
        assessment = report['assessment']
        for finding in assessment['key_findings']:
            print(f"   ✓ {finding}")
        
        if assessment['red_flags']:
            print(f"\n⚠️  RED FLAGS:")
            for flag in assessment['red_flags']:
                print(f"   • {flag}")
        
        print(f"\n💬 INTERACTION SUMMARY:")
        print(f"   Total Interactions: {report['summary']['total_interactions']}")
        for itype, count in report['interactions'].items():
            if count > 0:
                print(f"   • {itype.title()}: {count}")
        
        if report['interaction_pairs']:
            print(f"\n🔗 TOP INTERACTION PAIRS:")
            for i, pair in enumerate(report['interaction_pairs'][:5], 1):
                print(f"   {i}. User {pair['account_1']} ↔ User {pair['account_2']}: "
                      f"{pair['interactions']} interactions")
        
        print(f"\n{'='*80}\n")


# Example usage helper
def analyze_top_accounts(
    tweet_extractor: TwitterTweetExtractor,
    account_ids: List[str],
    account_usernames: List[str],
    days_back: int = 30
) -> Dict:
    """
    Convenience function to analyze interactions between Top 20 accounts
    
    Args:
        tweet_extractor: TwitterTweetExtractor with API key pool
        account_ids: List of user IDs from Top 20
        account_usernames: List of usernames from Top 20
        days_back: Days to analyze (7, 30, 90, 180)
    
    Returns:
        Complete interaction analysis report
    """
    analyzer = InteractionAnalyzer(tweet_extractor)
    
    report = analyzer.analyze_account_interactions(
        account_ids=account_ids,
        account_usernames=account_usernames,
        days_back=days_back
    )
    
    return report