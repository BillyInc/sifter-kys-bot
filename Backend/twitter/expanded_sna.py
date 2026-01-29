import tweepy
from datetime import datetime, timedelta
from typing import List, Dict
import time
from collections import defaultdict
import networkx as nx


class ExpandedSNAAnalyzer:
    """
    Analyzes interactions (mentions, replies, retweets) between top accounts
    over user-selected time windows (3d, 7d, 30d, all-time)
    """
    
    def __init__(self, twitter_client: tweepy.Client):
        """
        Initialize with Twitter API client
        
        Args:
            twitter_client: Authenticated Tweepy client
        """
        self.client = twitter_client
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
        
        # Calculate time window
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days_back)
        
        all_interactions = {
            'mentions': [],
            'replies': [],
            'retweets': [],
            'quote_tweets': []
        }
        
        # Build query to find interactions between these accounts
        username_list = ' OR '.join([f'@{u}' for u in account_usernames])
        from_list = ' OR '.join([f'from:{u}' for u in account_usernames])
        
        # Query: tweets FROM these accounts that MENTION any of these accounts
        query = f"({from_list}) ({username_list}) -is:retweet"
        
        print(f"[EXPANDED SNA] Query: {query[:100]}...")
        
        try:
            # Search for tweets
            tweets = self.client.search_recent_tweets(
                query=query,
                start_time=start_time,
                end_time=end_time,
                max_results=100,
                tweet_fields=['created_at', 'author_id', 'referenced_tweets', 'entities'],
                expansions=['author_id', 'referenced_tweets.id']
            )
            
            if not tweets.data:
                print("[EXPANDED SNA] No interactions found")
                return all_interactions
            
            print(f"[EXPANDED SNA] Found {len(tweets.data)} interaction tweets")
            
            # Process each tweet
            for tweet in tweets.data:
                tweet_data = {
                    'id': tweet.id,
                    'text': tweet.text,
                    'author_id': tweet.author_id,
                    'created_at': tweet.created_at
                }
                
                # Check for mentions
                if tweet.entities and 'mentions' in tweet.entities:
                    for mention in tweet.entities['mentions']:
                        all_interactions['mentions'].append({
                            **tweet_data,
                            'mentioned_user_id': mention['id'],
                            'mentioned_username': mention['username']
                        })
                
                # Check for replies
                if tweet.referenced_tweets:
                    for ref in tweet.referenced_tweets:
                        if ref.type == 'replied_to':
                            all_interactions['replies'].append({
                                **tweet_data,
                                'replied_to_id': ref.id
                            })
                        elif ref.type == 'retweeted':
                            all_interactions['retweets'].append({
                                **tweet_data,
                                'retweeted_id': ref.id
                            })
                        elif ref.type == 'quoted':
                            all_interactions['quote_tweets'].append({
                                **tweet_data,
                                'quoted_id': ref.id
                            })
            
            print(f"[EXPANDED SNA] Interactions breakdown:")
            print(f"   Mentions: {len(all_interactions['mentions'])}")
            print(f"   Replies: {len(all_interactions['replies'])}")
            print(f"   Retweets: {len(all_interactions['retweets'])}")
            print(f"   Quotes: {len(all_interactions['quote_tweets'])}")
            
            return all_interactions
            
        except tweepy.TweepyException as e:
            print(f"[EXPANDED SNA] Twitter API error: {e}")
            return all_interactions
    
    
    def build_interaction_network(self, interactions: Dict, account_ids: List[str]) -> nx.DiGraph:
        """
        Build directed graph from interaction data
        
        Args:
            interactions: Dictionary with mentions, replies, retweets
            account_ids: List of account IDs to include
        
        Returns:
            NetworkX DiGraph
        """
        print(f"\n[EXPANDED SNA] Building interaction network...")
        
        # Add all accounts as nodes
        for user_id in account_ids:
            self.interaction_graph.add_node(user_id)
        
        edge_count = 0
        
        # Add edges for mentions
        for mention in interactions['mentions']:
            source = str(mention['author_id'])
            target = str(mention['mentioned_user_id'])
            
            if source in account_ids and target in account_ids:
                if self.interaction_graph.has_edge(source, target):
                    self.interaction_graph[source][target]['weight'] += 1
                    self.interaction_graph[source][target]['mentions'] += 1
                else:
                    self.interaction_graph.add_edge(
                        source, target, 
                        weight=1, 
                        mentions=1, 
                        replies=0, 
                        retweets=0
                    )
                edge_count += 1
        
        # Add edges for replies
        for reply in interactions['replies']:
            source = str(reply['author_id'])
            # Note: We'd need to lookup who the replied_to_id belongs to
            # For now, we'll increment existing edges
            for target in account_ids:
                if target != source and self.interaction_graph.has_edge(source, target):
                    self.interaction_graph[source][target]['replies'] += 1
                    self.interaction_graph[source][target]['weight'] += 2  # Replies weighted higher
        
        # Add edges for retweets
        for rt in interactions['retweets']:
            source = str(rt['author_id'])
            for target in account_ids:
                if target != source and self.interaction_graph.has_edge(source, target):
                    self.interaction_graph[source][target]['retweets'] += 1
                    self.interaction_graph[source][target]['weight'] += 1.5
        
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
    
    
    def generate_interaction_matrix(self, account_usernames: List[str]) -> List[List[int]]:
        """
        Generate interaction matrix (who interacted with whom, how many times)
        
        Args:
            account_usernames: List of usernames in order
        
        Returns:
            2D matrix where matrix[i][j] = interactions from i to j
        """
        n = len(account_usernames)
        matrix = [[0] * n for _ in range(n)]
        
        username_to_idx = {username: i for i, username in enumerate(account_usernames)}
        
        for source, target, data in self.interaction_graph.edges(data=True):
            # Find indices (we'd need to map user_id back to username)
            # This is a simplified version
            weight = data.get('weight', 1)
            # matrix[source_idx][target_idx] = weight
        
        return matrix
    
    
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
        # Fetch interactions
        interactions = self.fetch_interactions_between_accounts(
            account_usernames=account_usernames,
            days_back=days_back
        )
        
        # Build network
        self.build_interaction_network(interactions, account_ids)
        
        # Calculate metrics
        metrics = self.calculate_interaction_metrics()
        
        # Export for visualization
        viz_data = self.export_for_visualization()
        
        return {
            'interactions': interactions,
            'metrics': metrics,
            'visualization': viz_data,
            'summary': {
                'total_interactions': sum(len(v) for v in interactions.values()),
                'unique_pairs': self.interaction_graph.number_of_edges(),
                'timeframe_days': days_back
            }
        }
    
    
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