"""Token analysis service - handles pump detection and Twitter caller analysis."""
from datetime import datetime
from typing import Optional
import traceback

from analyzers import PrecisionRallyDetector, NLPDisambiguator
from twitter import TwitterTweetExtractor
from config import Config


class TokenAnalyzerService:
    """Service for analyzing tokens for pump patterns and Twitter callers."""

    def __init__(self):
        self.birdeye_api_key = Config.BIRDEYE_API_KEY
        self.twitter_token = Config.TWITTER_BEARER_TOKEN

    def analyze_single_token(self, token: dict, idx: int, total: int) -> dict:
        """
        Analyze a single token for pump patterns.

        Args:
            token: Token data with address, pair_address, ticker, name, chain, settings
            idx: Current token index (1-based)
            total: Total number of tokens being analyzed

        Returns:
            Analysis result dictionary
        """
        settings = token.get('settings', {})
        prefix = f"[{idx}/{total}]"

        try:
            detector = PrecisionRallyDetector(birdeye_api_key=self.birdeye_api_key)

            # Get launch time if needed for first_X windows
            launch_timestamp = self._get_launch_timestamp(
                detector, token, settings, prefix
            )

            # Get OHLCV data
            print(f"{prefix} Fetching price data...")
            ohlcv_data = detector.get_ohlcv_data_with_launch(
                pair_address=token['pair_address'],
                chain=token['chain'],
                launch_timestamp=launch_timestamp,
                window_type=settings.get('analysis_timeframe', 'first_7d'),
                candle_size=settings.get('candle_size', '5m')
            )

            if not ohlcv_data:
                print(f"{prefix} No price data available")
                return self._error_result(token, 'No price data available')

            # Detect rallies
            print(f"{prefix} Detecting pumps...")
            rallies = detector.detect_all_rallies(ohlcv_data)

            if not rallies:
                print(f"{prefix} Analysis complete - No pumps detected")
                return self._success_result(token, [], [], 'No significant pumps detected')

            # Format rally details
            rally_details = self._format_rally_details(rallies, ohlcv_data)
            print(f"{prefix} Found {len(rallies)} pump(s)")

            # Get Twitter callers
            top_accounts, all_account_data = self._get_twitter_callers(
                token, rallies, settings, prefix
            )

            print(f"{prefix} Analysis complete")
            return self._success_result(
                token, rally_details, top_accounts,
                f"{len(rallies)} pump(s) detected",
                all_account_data
            )

        except Exception as e:
            print(f"{prefix} Error: {str(e)}")
            print(traceback.format_exc())
            return self._error_result(token, str(e))

    def _get_launch_timestamp(
        self, detector, token: dict, settings: dict, prefix: str
    ) -> Optional[int]:
        """Get token launch timestamp if needed for first_X analysis windows."""
        if settings.get('analysis_timeframe', '').startswith('first_'):
            print(f"{prefix} Fetching launch time...")
            return detector.get_token_launch_time(token['address'])
        return None

    def _format_rally_details(self, rallies: list, ohlcv_data: list) -> list:
        """Format rally data into response structure."""
        rally_details = []

        for rally in rallies:
            start_unix = rally['window'][0]['unix_time']
            end_unix = rally['window'][-1]['unix_time']

            # Calculate volume stats
            volumes = [candle.get('v_usd', 0) for candle in rally['window']]
            avg_volume = sum(volumes) / len(volumes) if volumes else 0
            peak_volume = max(volumes) if volumes else 0

            # Get baseline volume
            baseline_volumes = [
                candle.get('v_usd', 0)
                for candle in ohlcv_data
                if candle['unix_time'] < start_unix
            ]
            baseline_avg = (
                sum(baseline_volumes[-10:]) / 10
                if len(baseline_volumes) >= 10
                else avg_volume
            )
            volume_spike_ratio = (
                round(peak_volume / baseline_avg, 2)
                if baseline_avg > 0
                else 1.0
            )

            rally_details.append({
                'start_time': start_unix,
                'end_time': end_unix,
                'total_gain_pct': round(rally['total_gain'], 2),
                'peak_gain_pct': round(rally['peak_gain'], 2),
                'rally_type': rally['type'],
                'candle_count': rally['length'],
                'green_ratio': round(rally['green_ratio'] * 100, 1),
                'volume_data': {
                    'avg_volume': avg_volume,
                    'peak_volume': peak_volume,
                    'volume_spike_ratio': volume_spike_ratio
                }
            })

        return rally_details

    def _get_twitter_callers(
        self, token: dict, rallies: list, settings: dict, prefix: str
    ) -> tuple[list, dict]:
        """
        Get Twitter accounts that called the pump.

        Returns:
            Tuple of (top_accounts list, all_account_data dict for cross-token tracking)
        """
        if not Config.is_twitter_configured():
            print(f"{prefix} Twitter API not configured - skipping caller analysis")
            return [], {}

        try:
            print(f"{prefix} Searching Twitter for callers...")
            tweet_extractor = TwitterTweetExtractor(bearer_token=self.twitter_token)
            nlp_scorer = NLPDisambiguator({
                'ticker': token['ticker'],
                'name': token['name'],
                'contract_address': token['address'],
                'chain': token['chain']
            })

            # Collect tweets for each rally
            rally_results = []
            for rally_idx, rally in enumerate(rallies, 1):
                rally_start = datetime.fromtimestamp(rally['window'][0]['unix_time'])
                print(f"{prefix}   Pump {rally_idx}/{len(rallies)}: Searching tweets...")

                tweets = tweet_extractor.search_tweets_for_rally(
                    token_ticker=token['ticker'],
                    token_name=token['name'],
                    rally_start_time=rally_start,
                    t_minus_minutes=settings.get('t_minus', 35),
                    t_plus_minutes=settings.get('t_plus', 10)
                )

                scored_tweets = [
                    {'tweet': tweet, 'score': score_result}
                    for tweet in tweets
                    if (score_result := nlp_scorer.score_tweet(tweet))['accept']
                ]

                rally_results.append({
                    'rally': rally,
                    'scored_tweets': scored_tweets
                })

            # Aggregate account statistics
            account_stats = self._aggregate_account_stats(rally_results)
            ranked_accounts = self._rank_accounts(account_stats, token['ticker'])
            top_accounts = ranked_accounts['top_accounts']
            all_account_data = ranked_accounts['all_account_data']

            # Fetch user info for top accounts
            if top_accounts:
                user_ids = [acc['author_id'] for acc in top_accounts]
                user_info = tweet_extractor.get_user_info(user_ids)
                for account in top_accounts:
                    if account['author_id'] in user_info:
                        account.update(user_info[account['author_id']])

            print(f"{prefix} Found {len(top_accounts)} top callers")
            return top_accounts, all_account_data

        except Exception as e:
            print(f"{prefix} Twitter API error: {str(e)}")
            return [], {}

    def _aggregate_account_stats(self, rally_results: list) -> dict:
        """Aggregate statistics for each Twitter account across rallies."""
        account_stats = {}

        for result in rally_results:
            for scored_tweet in result['scored_tweets']:
                tweet = scored_tweet['tweet']
                author_id = str(tweet['author_id'])

                if author_id not in account_stats:
                    account_stats[author_id] = {
                        'author_id': author_id,
                        'pumps_called': 0,
                        'timings': [],
                        'scores': [],
                        'high_confidence_count': 0
                    }

                stats = account_stats[author_id]
                stats['pumps_called'] += 1
                stats['timings'].append(tweet['time_to_rally_minutes'])
                stats['scores'].append(scored_tweet['score']['total_score'])

                if scored_tweet['score']['confidence'] == 'high':
                    stats['high_confidence_count'] += 1

        return account_stats

    def _rank_accounts(self, account_stats: dict, ticker: str) -> dict:
        """
        Rank accounts by influence score.

        Returns:
            Dict with 'top_accounts' (top 20) and 'all_account_data' for cross-token tracking
        """
        ranked = []
        all_account_data = {}

        for author_id, stats in account_stats.items():
            if not stats['timings']:
                continue

            avg_timing = sum(stats['timings']) / len(stats['timings'])
            avg_score = sum(stats['scores']) / len(stats['scores'])
            earliest = min(stats['timings'])

            influence_score = (
                (stats['pumps_called'] * 30) +
                (max(0, -avg_timing) * 2) +
                (stats['high_confidence_count'] * 15) +
                (avg_score * 0.5)
            )

            account = {
                'author_id': author_id,
                'pumps_called': stats['pumps_called'],
                'avg_timing': round(avg_timing, 1),
                'earliest_call': round(earliest, 1),
                'influence_score': round(influence_score, 1),
                'high_confidence_count': stats['high_confidence_count']
            }
            ranked.append(account)

            # Track for cross-token analysis
            all_account_data[author_id] = {
                'author_id': author_id,
                'tokens_called': [ticker],
                'total_influence': influence_score
            }

        ranked.sort(key=lambda x: x['influence_score'], reverse=True)
        return {
            'top_accounts': ranked[:20],
            'all_account_data': all_account_data
        }

    def _success_result(
        self, token: dict, rally_details: list, top_accounts: list,
        pump_info: str, account_data: dict = None
    ) -> dict:
        """Build success result dictionary."""
        return {
            'token': token,
            'success': True,
            'rallies': len(rally_details),
            'rally_details': rally_details,
            'top_accounts': top_accounts,
            'pump_info': pump_info,
            '_account_data': account_data or {}
        }

    def _error_result(self, token: dict, error: str) -> dict:
        """Build error result dictionary."""
        return {
            'token': token,
            'success': False,
            'rallies': 0,
            'error': error
        }
