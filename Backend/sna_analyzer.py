import networkx as nx
import numpy as np
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from tweet_extractor import TwitterTweetExtractor


class SocialNetworkAnalyzer:
    """
    Analyzes Twitter account networks to detect:
    1. Coordinated pump groups vs organic callers
    2. Network topology (star vs distributed)
    3. Influence metrics (centrality measures)
    4. Reciprocity patterns (bots, shills, organic users)
    
    UPDATED: Uses TwitterAPI.io via TwitterTweetExtractor
    """
    
    def __init__(self, tweet_extractor: TwitterTweetExtractor):
        """
        Initialize SNA with tweet extractor (contains API key pool)
        
        Args:
            tweet_extractor: TwitterTweetExtractor instance with API key pool
        """
        self.extractor = tweet_extractor
        self.graph = nx.DiGraph()  # Directed graph for follower relationships
    
    
    def build_network_from_accounts(
        self, 
        account_usernames: List[str], 
        account_ids: List[str],
        max_depth: int = 1
    ):
        """
        Build network graph by fetching follower/following relationships
        
        Args:
            account_usernames: List of Twitter usernames
            account_ids: List of Twitter user IDs
            max_depth: How many layers deep to fetch relationships (1 = direct only)
        
        Returns:
            NetworkX DiGraph
        """
        print(f"\n[SNA] Building network graph for {len(account_usernames)} accounts...")
        
        # Add all accounts as nodes
        for user_id in account_ids:
            self.graph.add_node(user_id)
        
        # Create lookup map
        username_to_id = dict(zip(account_usernames, account_ids))
        id_to_username = dict(zip(account_ids, account_usernames))
        
        # Fetch relationships between accounts
        relationships_found = 0
        
        for i, username in enumerate(account_usernames):
            user_id = username_to_id[username]
            
            print(f"[SNA] Fetching relationships for account {i+1}/{len(account_usernames)} (@{username})...")
            
            try:
                # Get who this user follows (using TwitterAPI.io)
                following_ids = self.extractor.get_user_followings(username, max_results=200)
                
                # Only keep followings that are in our account list
                for followed_id in following_ids:
                    if followed_id in account_ids:
                        self.graph.add_edge(user_id, followed_id)
                        relationships_found += 1
                
            except Exception as e:
                print(f"[SNA] Error fetching relationships for {username}: {e}")
                continue
        
        print(f"[SNA] Network built: {len(account_ids)} nodes, {relationships_found} edges\n")
        
        return self.graph
    
    
    def calculate_reciprocity(self) -> float:
        """
        Calculate network reciprocity (how many edges are bidirectional)
        
        Interpretation:
        - High (>0.7): Likely bots or tight pump groups (mutual following)
        - Medium (0.3-0.7): Coordinated shills or friend groups
        - Low (<0.3): Organic users with natural following patterns
        
        Returns:
            Reciprocity score between 0 and 1
        """
        if self.graph.number_of_edges() == 0:
            return 0.0
        
        reciprocity = nx.reciprocity(self.graph)
        
        print(f"[SNA] Reciprocity: {reciprocity:.3f}")
        
        if reciprocity > 0.7:
            print("      → High reciprocity: Likely coordinated group or bots")
        elif reciprocity > 0.3:
            print("      → Medium reciprocity: Possible friend group or loose coordination")
        else:
            print("      → Low reciprocity: Organic following patterns")
        
        return reciprocity
    
    
    def detect_topology(self) -> Dict[str, any]:
        """
        Detect network topology to identify coordination patterns
        
        Topologies:
        - STAR: One central node, others follow them (1 influencer, many followers)
        - DISTRIBUTED: No clear center, connections spread out (organic)
        - CLIQUE: Tight group where everyone follows everyone (coordinated pump group)
        - CHAIN: Linear connections (likely organic)
        
        Returns:
            Dictionary with topology type and metrics
        """
        print(f"\n[SNA] Analyzing network topology...")
        
        if self.graph.number_of_nodes() < 2:
            return {'type': 'isolated', 'coordinated': False}
        
        # Calculate degree centralization
        undirected_graph = self.graph.to_undirected()
        degrees = dict(undirected_graph.degree())
        
        if not degrees:
            return {'type': 'isolated', 'coordinated': False}
        
        max_degree = max(degrees.values())
        total_nodes = self.graph.number_of_nodes()
        
        # Calculate degree centralization (how concentrated connections are)
        numerator = sum(max_degree - d for d in degrees.values())
        denominator = (total_nodes - 1) * (total_nodes - 2)
        
        if denominator == 0:
            centralization = 0
        else:
            centralization = numerator / denominator
        
        # Calculate clustering coefficient (how tightly connected)
        try:
            clustering = nx.average_clustering(undirected_graph)
        except:
            clustering = 0
        
        # Determine topology
        topology_result = {
            'centralization': round(centralization, 3),
            'clustering': round(clustering, 3),
            'max_degree': max_degree,
            'avg_degree': round(np.mean(list(degrees.values())), 2)
        }
        
        # Classification logic
        if centralization > 0.7 and max_degree > total_nodes * 0.5:
            topology_result['type'] = 'star'
            topology_result['coordinated'] = False
            topology_result['description'] = 'Star topology: One central influencer, likely organic'
        
        elif clustering > 0.6 and centralization < 0.5:
            topology_result['type'] = 'clique'
            topology_result['coordinated'] = True
            topology_result['description'] = 'Clique topology: Tight group, likely coordinated pump'
        
        elif centralization < 0.4 and clustering < 0.4:
            topology_result['type'] = 'distributed'
            topology_result['coordinated'] = False
            topology_result['description'] = 'Distributed topology: Spread out, likely organic'
        
        else:
            topology_result['type'] = 'mixed'
            topology_result['coordinated'] = centralization > 0.5 and clustering > 0.5
            topology_result['description'] = 'Mixed topology: Combination of patterns'
        
        print(f"[SNA] Topology: {topology_result['type'].upper()}")
        print(f"      Centralization: {topology_result['centralization']}")
        print(f"      Clustering: {topology_result['clustering']}")
        print(f"      Coordinated: {'YES' if topology_result['coordinated'] else 'NO'}")
        
        return topology_result
    
    
    def calculate_influence_metrics(self) -> Dict[str, Dict[str, float]]:
        """
        Calculate multiple influence metrics for each account
        
        Metrics:
        - Degree Centrality: How many connections (basic popularity)
        - Betweenness Centrality: Who bridges disconnected groups (information broker)
        - Closeness Centrality: How fast can info spread from this person
        - Eigenvector Centrality: Connected to other influential people (quality over quantity)
        - PageRank: Google's algorithm adapted for social networks
        
        Returns:
            Dictionary mapping user_id -> metrics dict
        """
        print(f"\n[SNA] Calculating influence metrics...")
        
        if self.graph.number_of_nodes() < 2:
            return {}
        
        # Convert to undirected for some metrics
        undirected = self.graph.to_undirected()
        
        # Calculate all centrality measures
        try:
            degree_cent = nx.degree_centrality(undirected)
            betweenness_cent = nx.betweenness_centrality(self.graph)
            closeness_cent = nx.closeness_centrality(self.graph)
            eigenvector_cent = nx.eigenvector_centrality(self.graph, max_iter=100)
            pagerank = nx.pagerank(self.graph)
        except:
            print("[SNA] Warning: Could not calculate all metrics (graph may be disconnected)")
            return {}
        
        # Combine into per-user metrics
        influence_metrics = {}
        
        for user_id in self.graph.nodes():
            # Normalize scores to 0-100 scale
            influence_metrics[user_id] = {
                'degree_centrality': round(degree_cent.get(user_id, 0) * 100, 2),
                'betweenness_centrality': round(betweenness_cent.get(user_id, 0) * 100, 2),
                'closeness_centrality': round(closeness_cent.get(user_id, 0) * 100, 2),
                'eigenvector_centrality': round(eigenvector_cent.get(user_id, 0) * 100, 2),
                'pagerank': round(pagerank.get(user_id, 0) * 100, 2),
            }
            
            # Calculate composite influence score (weighted average)
            influence_metrics[user_id]['composite_influence'] = round(
                (degree_cent.get(user_id, 0) * 0.2 +
                 betweenness_cent.get(user_id, 0) * 0.3 +
                 closeness_cent.get(user_id, 0) * 0.2 +
                 eigenvector_cent.get(user_id, 0) * 0.2 +
                 pagerank.get(user_id, 0) * 0.1) * 100,
                2
            )
        
        # Find top influencers
        top_influencers = sorted(
            influence_metrics.items(),
            key=lambda x: x[1]['composite_influence'],
            reverse=True
        )[:3]
        
        print(f"[SNA] Top 3 Influencers:")
        for i, (user_id, metrics) in enumerate(top_influencers, 1):
            print(f"      {i}. User {user_id}: {metrics['composite_influence']:.1f} influence score")
        
        return influence_metrics
    
    
    def identify_bridges(self) -> List[str]:
        """
        Identify bridge accounts that connect disconnected groups
        
        These are high-value accounts because:
        - They can see information from multiple clusters
        - Removing them fragments the network
        - They're likely genuine connectors, not bots
        
        Returns:
            List of user IDs who are bridges
        """
        print(f"\n[SNA] Identifying bridge accounts...")
        
        if self.graph.number_of_nodes() < 3:
            return []
        
        # Find articulation points (nodes whose removal disconnects the graph)
        undirected = self.graph.to_undirected()
        
        try:
            bridges = list(nx.articulation_points(undirected))
            print(f"[SNA] Found {len(bridges)} bridge accounts")
            return bridges
        except:
            print("[SNA] Could not identify bridges (graph may be fully connected)")
            return []
    
    
    def detect_communities(self) -> Dict[str, int]:
        """
        Detect communities/clusters in the network
        
        Helps identify:
        - Separate pump groups
        - Organic vs coordinated clusters
        - Influencer communities
        
        Returns:
            Dictionary mapping user_id -> community_id
        """
        print(f"\n[SNA] Detecting communities...")
        
        if self.graph.number_of_nodes() < 3:
            return {}
        
        undirected = self.graph.to_undirected()
        
        try:
            # Try using Louvain method for community detection
            import community as community_louvain
            communities = community_louvain.best_partition(undirected)
            
            num_communities = len(set(communities.values()))
            print(f"[SNA] Found {num_communities} communities")
            
            # Show community sizes
            community_sizes = defaultdict(int)
            for user_id, comm_id in communities.items():
                community_sizes[comm_id] += 1
            
            for comm_id, size in sorted(community_sizes.items()):
                print(f"      Community {comm_id}: {size} members")
            
            return communities
        
        except ImportError:
            print("[SNA] Warning: python-louvain not installed, using connected components instead")
            
            # Fallback: Use connected components
            components = list(nx.connected_components(undirected))
            communities = {}
            
            for i, component in enumerate(components):
                for user_id in component:
                    communities[user_id] = i
            
            print(f"[SNA] Found {len(components)} connected components")
            return communities
    
    
    def analyze_temporal_coordination(self, tweets_by_user: Dict[str, List[datetime]]) -> Dict[str, any]:
        """
        Analyze timing patterns to detect coordination
        
        Coordinated groups often tweet:
        - Within minutes of each other
        - At unusual hours simultaneously
        - With consistent time gaps
        
        Args:
            tweets_by_user: Dict mapping user_id -> list of tweet timestamps
        
        Returns:
            Coordination analysis results
        """
        print(f"\n[SNA] Analyzing temporal coordination patterns...")
        
        all_times = []
        for user_id, timestamps in tweets_by_user.items():
            all_times.extend([(t, user_id) for t in timestamps])
        
        all_times.sort()
        
        # Find tweet clusters (multiple users tweeting within 5 min window)
        clusters = []
        window = timedelta(minutes=5)
        
        i = 0
        while i < len(all_times):
            cluster_start = all_times[i][0]
            cluster_users = {all_times[i][1]}
            j = i + 1
            
            while j < len(all_times) and all_times[j][0] - cluster_start <= window:
                cluster_users.add(all_times[j][1])
                j += 1
            
            if len(cluster_users) >= 3:  # At least 3 users tweeting within 5 mins
                clusters.append({
                    'time': cluster_start,
                    'users': list(cluster_users),
                    'size': len(cluster_users)
                })
            
            i = j if j > i + 1 else i + 1
        
        coordination_score = len(clusters) / max(len(tweets_by_user), 1) * 100
        
        result = {
            'clusters_found': len(clusters),
            'coordination_score': round(coordination_score, 2),
            'coordinated': coordination_score > 50,
            'clusters': clusters[:5]  # Top 5 clusters
        }
        
        print(f"[SNA] Temporal clusters: {len(clusters)}")
        print(f"[SNA] Coordination score: {coordination_score:.1f}%")
        print(f"[SNA] Coordinated: {'YES' if result['coordinated'] else 'NO'}")
        
        return result
    
    
    def generate_network_report(self) -> Dict[str, any]:
        """
        Generate comprehensive network analysis report
        
        Returns:
            Complete analysis with all metrics
        """
        print(f"\n{'='*80}")
        print("SOCIAL NETWORK ANALYSIS REPORT")
        print(f"{'='*80}")
        
        report = {
            'summary': {
                'total_nodes': self.graph.number_of_nodes(),
                'total_edges': self.graph.number_of_edges(),
                'density': round(nx.density(self.graph), 4),
            },
            'reciprocity': self.calculate_reciprocity(),
            'topology': self.detect_topology(),
            'influence_metrics': self.calculate_influence_metrics(),
            'bridges': self.identify_bridges(),
            'communities': self.detect_communities(),
        }
        
        # Overall coordination assessment
        coordination_indicators = 0
        
        if report['reciprocity'] > 0.7:
            coordination_indicators += 1
        
        if report['topology'].get('coordinated', False):
            coordination_indicators += 1
        
        if report['topology'].get('clustering', 0) > 0.6:
            coordination_indicators += 1
        
        report['summary']['coordination_indicators'] = coordination_indicators
        report['summary']['likely_coordinated'] = coordination_indicators >= 2
        
        print(f"\n{'='*80}")
        print(f"COORDINATION ASSESSMENT: {'LIKELY COORDINATED' if report['summary']['likely_coordinated'] else 'LIKELY ORGANIC'}")
        print(f"Indicators: {coordination_indicators}/3")
        print(f"{'='*80}\n")
        
        return report
    
    
    def export_graph_for_visualization(self) -> Dict[str, any]:
        """
        Export graph data in format suitable for D3.js visualization
        
        Returns:
            Dictionary with nodes and links for frontend
        """
        nodes = []
        links = []
        
        # Get influence metrics
        influence = self.calculate_influence_metrics()
        
        # Export nodes
        for node_id in self.graph.nodes():
            node_data = {
                'id': node_id,
                'influence': influence.get(node_id, {}).get('composite_influence', 0),
                'degree': self.graph.degree(node_id)
            }
            nodes.append(node_data)
        
        # Export edges
        for source, target in self.graph.edges():
            links.append({
                'source': source,
                'target': target
            })
        
        return {
            'nodes': nodes,
            'links': links
        }


# Example usage helper
def analyze_accounts_network(
    tweet_extractor: TwitterTweetExtractor,
    account_usernames: List[str],
    account_ids: List[str]
) -> Dict:
    """
    Convenience function to run full SNA on a list of accounts
    
    Args:
        tweet_extractor: TwitterTweetExtractor with API key pool
        account_usernames: List of Twitter usernames
        account_ids: List of Twitter user IDs
    
    Returns:
        Complete SNA report
    """
    sna = SocialNetworkAnalyzer(tweet_extractor)
    
    # Build network
    sna.build_network_from_accounts(account_usernames, account_ids)
    
    # Generate report
    report = sna.generate_network_report()
    
    # Add visualization data
    report['visualization'] = sna.export_graph_for_visualization()
    
    return report