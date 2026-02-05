from datetime import datetime, timedelta
from typing import List, Dict
import time
from collections import defaultdict
import networkx as nx
from tweet_extractor import TwitterTweetExtractor


class ExpandedSNAAnalyzer:
    """
    Analyzes interactions (mentions, replies, retweets) between top accounts
    over user-selected time windows (3d, 7d, 30d, all-time)
    
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
    
    
    def fetch_interactions_between_accounts(
        self, 
        account_usernames: List[str], 
        days_back: int = 7,
        max_tweets_per_account: int = 100
    ) -> Dict[str, List[Dict]]:
        """
        Fetch all interactions (mentions, replies, RTs) between specific accounts
        
        Args:
            account_usernames: List of Twitter usernames (e.g., ['user1', 'user2'])
            days_back: How many days back to search (3, 7, 30, or 365 for all-time)
            max_tweets_per_account: Max tweets to fetch per account
        
        Returns:
            Dictionary with interaction data
        """
        print(f"\n[EXPANDED SNA] Fetching interactions for {len(account_usernames)} accounts over last {days_back} days...")
        
        all_interactions = {
            'mentions': [],
            'replies': [],
            'retweets': [],
            'quote_tweets': []
        }
        
        # Use TwitterAPI.io get_account_interactions method
        interactions = self.extractor.get_account_interactions(
            account_usernames=account_usernames,
            days_back=days_back
        )
        
        # Merge results
        all_interactions['mentions'].extend(interactions.get('mentions', []))
        all_interactions['replies'].extend(interactions.get('replies', []))
        all_interactions['retweets'].extend(interactions.get('retweets', []))
        all_interactions['quote_tweets'].extend(interactions.get('quote_tweets', []))
        
        print(f"[EXPANDED SNA] Interactions breakdown:")
        print(f"   Mentions: {len(all_interactions['mentions'])}")
        print(f"   Replies: {len(all_interactions['replies'])}")
        print(f"   Retweets: {len(all_interactions['retweets'])}")
        print(f"   Quotes: {len(all_interactions['quote_tweets'])}")
        
        return all_interactions
    
    
    def build_interaction_network(
        self, 
        interactions: Dict, 
        account_ids: List[str],
        account_usernames: List[str]
    ) -> nx.DiGraph:
        """
        Build directed graph from interaction data
        
        Args:
            interactions: Dictionary with mentions, replies, retweets
            account_ids: List of account IDs to include
            account_usernames: List of account usernames
        
        Returns:
            NetworkX DiGraph
        """
        print(f"\n[EXPANDED SNA] Building interaction network...")
        
        # Create username to ID mapping
        username_to_id = dict(zip(account_usernames, account_ids))
        
        # Add all accounts as nodes
        for user_id in account_ids:
            self.interaction_graph.add_node(user_id)
        
        edge_count = 0
        
        # Add edges for mentions
        for mention in interactions['mentions']:
            source_id = str(mention.get('author_id'))
            
            # Find target ID from username
            mentioned_username = mention.get('mentioned_username', '')
            target_id = username_to_id.get(mentioned_username)
            
            if source_id in account_ids and target_id and target_id in account_ids:
                if self.interaction_graph.has_edge(source_id, target_id):
                    self.interaction_graph[source_id][target_id]['weight'] += 1
                    self.interaction_graph[source_id][target_id]['mentions'] += 1
                else:
                    self.interaction_graph.add_edge(
                        source_id, target_id, 
                        weight=1, 
                        mentions=1, 
                        replies=0, 
                        retweets=0
                    )
                edge_count += 1
        
        # Note: For replies and retweets, we'd need additional API calls to resolve
        # who was replied to / retweeted. For now, we're primarily tracking mentions
        # which are the most direct form of interaction.
        
        print(f"[EXPANDED SNA] Interaction network: {self.interaction_graph.number_of_nodes()} nodes, {self.interaction_graph.number_of_edges()} edges")
        
        return self.interaction_graph
    
    
    def calculate_interaction_metrics(self) -> Dict[str, any]:
        """
        Calculate SNA metrics on the interaction network
        
        Returns:
            Dictionary with metrics
        """
        print(f"\n[EXPANDED SNA] Calculating interaction metrics...")
        
        if self.interaction_graph.number_of_nodes() < 2:
            return {}
        
        metrics = {}
        
        # Reciprocity
        try:
            reciprocity = nx.reciprocity(self.interaction_graph)
            metrics['reciprocity'] = round(reciprocity, 3)
        except:
            metrics['reciprocity'] = 0
        
        # Density
        metrics['density'] = round(nx.density(self.interaction_graph), 4)
        
        # Centrality measures
        undirected = self.interaction_graph.to_undirected()
        
        try:
            degree_cent = nx.degree_centrality(undirected)
            betweenness_cent = nx.betweenness_centrality(self.interaction_graph)
            closeness_cent = nx.closeness_centrality(self.interaction_graph)
            
            metrics['per_account'] = {}
            
            for user_id in self.interaction_graph.nodes():
                metrics['per_account'][user_id] = {
                    'degree_centrality': round(degree_cent.get(user_id, 0) * 100, 2),
                    'betweenness_centrality': round(betweenness_cent.get(user_id, 0) * 100, 2),
                    'closeness_centrality': round(closeness_cent.get(user_id, 0) * 100, 2),
                    'total_interactions_sent': self.interaction_graph.out_degree(user_id, weight='weight'),
                    'total_interactions_received': self.interaction_graph.in_degree(user_id, weight='weight')
                }
        except Exception as e:
            print(f"[EXPANDED SNA] Error calculating centrality: {e}")
            metrics['per_account'] = {}
        
        # Detect tight clusters
        try:
            clustering = nx.average_clustering(undirected)
            metrics['clustering'] = round(clustering, 3)
        except:
            metrics['clustering'] = 0
        
        # Identify strongly connected components (mutual interaction groups)
        try:
            strongly_connected = list(nx.strongly_connected_components(self.interaction_graph))
            metrics['strong_components'] = len(strongly_connected)
            metrics['largest_component_size'] = max(len(c) for c in strongly_connected) if strongly_connected else 0
        except:
            metrics['strong_components'] = 0
            metrics['largest_component_size'] = 0
        
        print(f"[EXPANDED SNA] Metrics calculated:")
        print(f"   Reciprocity: {metrics['reciprocity']}")
        print(f"   Density: {metrics['density']}")
        print(f"   Clustering: {metrics['clustering']}")
        print(f"   Strong components: {metrics['strong_components']}")
        
        return metrics
    
    
    def calculate_coordination_index(self, metrics: Dict) -> Dict[str, any]:
        """
        Calculate Coordination Index (0-100)
        
        High coordination indicators:
        - High reciprocity (mutual interaction)
        - High clustering (tight groups)
        - High interaction density
        - Many strongly connected components
        
        Returns:
            Dictionary with index and breakdown
        """
        print(f"\n[EXPANDED SNA] Calculating Coordination Index...")
        
        # Initialize score components
        scores = {
            'reciprocity_score': 0,
            'clustering_score': 0,
            'density_score': 0,
            'component_score': 0
        }
        
        # Reciprocity Score (0-35 points)
        if metrics['reciprocity'] > 0.7:
            scores['reciprocity_score'] = 35
        elif metrics['reciprocity'] > 0.5:
            scores['reciprocity_score'] = 25
        elif metrics['reciprocity'] > 0.3:
            scores['reciprocity_score'] = 15
        
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
        
        # Component Score (0-10 points)
        strong_components = metrics.get('strong_components', 0)
        if strong_components >= 3:
            scores['component_score'] = 10
        elif strong_components >= 2:
            scores['component_score'] = 6
        elif strong_components >= 1:
            scores['component_score'] = 3
        
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
        
        result = {
            'index': round(coordination_index, 1),
            'level': level,
            'description': description,
            'breakdown': scores,
            'max_possible': 100
        }
        
        print(f"[EXPANDED SNA] Coordination Index: {result['index']}/100 ({result['level']})")
        
        return result
    
    
    def get_top_interaction_pairs(self, top_n: int = 10) -> List[Dict]:
        """Get the most interactive account pairs"""
        
        pairs = []
        
        # Count interactions between pairs
        for edge in self.interaction_graph.edges(data=True):
            source, target, data = edge
            weight = data.get('weight', 1)
            
            pairs.append({
                'account_1': source,
                'account_2': target,
                'interactions': weight,
                'mentions': data.get('mentions', 0),
                'type': 'mentions'
            })
        
        # Sort by interaction count
        pairs.sort(key=lambda x: x['interactions'], reverse=True)
        
        return pairs[:top_n]
    
    
    def analyze_expanded_network(
        self, 
        account_usernames: List[str], 
        account_ids: List[str],
        days_back: int = 7
    ) -> Dict[str, any]:
        """
        Complete expanded SNA analysis
        
        Args:
            account_usernames: List of Twitter usernames
            account_ids: List of Twitter user IDs
            days_back: Days to look back (3, 7, 30, 365)
        
        Returns:
            Complete analysis report
        """
        print(f"\n{'='*80}")
        print(f"EXPANDED SNA ANALYSIS")
        print(f"Accounts: {len(account_usernames)} | Timeframe: {days_back} days")
        print(f"{'='*80}")
        
        # Fetch interactions
        interactions = self.fetch_interactions_between_accounts(
            account_usernames=account_usernames,
            days_back=days_back
        )
        
        # Build network
        self.build_interaction_network(interactions, account_ids, account_usernames)
        
        # Calculate metrics
        metrics = self.calculate_interaction_metrics()
        
        # Calculate coordination index
        coordination_index = self.calculate_coordination_index(metrics)
        
        # Get top pairs
        top_pairs = self.get_top_interaction_pairs()
        
        # Export for visualization
        viz_data = self.export_for_visualization()
        
        report = {
            'interactions': interactions,
            'metrics': metrics,
            'coordination_index': coordination_index,
            'top_interaction_pairs': top_pairs,
            'visualization': viz_data,
            'summary': {
                'total_interactions': sum(len(v) for v in interactions.values()),
                'unique_pairs': self.interaction_graph.number_of_edges(),
                'timeframe_days': days_back,
                'coordination_likely': coordination_index['index'] >= 50
            }
        }
        
        self._print_report(report)
        
        return report
    
    
    def export_for_visualization(self) -> Dict[str, any]:
        """Export network for D3.js visualization"""
        nodes = []
        links = []
        
        for node_id in self.interaction_graph.nodes():
            nodes.append({
                'id': node_id,
                'interactions_sent': self.interaction_graph.out_degree(node_id, weight='weight'),
                'interactions_received': self.interaction_graph.in_degree(node_id, weight='weight')
            })
        
        for source, target, data in self.interaction_graph.edges(data=True):
            links.append({
                'source': source,
                'target': target,
                'weight': data.get('weight', 1),
                'mentions': data.get('mentions', 0),
                'replies': data.get('replies', 0),
                'retweets': data.get('retweets', 0)
            })
        
        return {
            'nodes': nodes,
            'links': links
        }
    
    
    def _print_report(self, report: Dict):
        """Print formatted analysis report"""
        
        print(f"\n{'='*80}")
        print("EXPANDED SNA REPORT")
        print(f"{'='*80}\n")
        
        coord = report['coordination_index']
        
        print(f"📊 COORDINATION INDEX: {coord['index']}/100")
        print(f"   Level: {coord['level']}")
        print(f"   {coord['description']}\n")
        
        print(f"📈 SCORE BREAKDOWN:")
        for key, value in coord['breakdown'].items():
            print(f"   • {key.replace('_', ' ').title()}: {value}")
        
        print(f"\n💬 INTERACTION SUMMARY:")
        print(f"   Total Interactions: {report['summary']['total_interactions']}")
        for itype, count in report['interactions'].items():
            if count > 0:
                print(f"   • {itype.title()}: {len(count)}")
        
        if report['top_interaction_pairs']:
            print(f"\n🔗 TOP INTERACTION PAIRS:")
            for i, pair in enumerate(report['top_interaction_pairs'][:5], 1):
                print(f"   {i}. User {pair['account_1']} ↔ User {pair['account_2']}: "
                      f"{pair['interactions']} interactions")
        
        print(f"\n{'='*80}\n")


# Example usage helper
def analyze_expanded_interactions(
    tweet_extractor: TwitterTweetExtractor,
    account_usernames: List[str],
    account_ids: List[str],
    days_back: int = 30
) -> Dict:
    """
    Convenience function to analyze interactions between Top 20 accounts
    
    Args:
        tweet_extractor: TwitterTweetExtractor with API key pool
        account_usernames: List of usernames from Top 20
        account_ids: List of user IDs from Top 20
        days_back: Days to analyze (7, 30, 90, 180)
    
    Returns:
        Complete expanded SNA analysis report
    """
    analyzer = ExpandedSNAAnalyzer(tweet_extractor)
    
    report = analyzer.analyze_expanded_network(
        account_usernames=account_usernames,
        account_ids=account_ids,
        days_back=days_back
    )
    
    return report