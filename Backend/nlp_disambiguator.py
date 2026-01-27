import re
from typing import Dict, List


class NLPDisambiguator:
    """
    Advanced NLP-based tweet scoring for crypto trading signals
    Fixed version with proper validation and filtering
    """
    
    def __init__(self, token_profile: Dict):
        """
        Initialize with token profile
        
        Args:
            token_profile: Dict with 'ticker', 'name', 'contract_address', 'chain'
        """
        self.ticker = token_profile['ticker'].upper()
        self.name = token_profile['name']
        self.contract_address = token_profile.get('contract_address', '')
        self.chain = token_profile.get('chain', '')
        
        # Compile regex patterns
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Compile all regex patterns for efficiency"""
        # Contract address patterns
        self.solana_ca_pattern = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}pump')
        self.eth_ca_pattern = re.compile(r'0x[a-fA-F0-9]{40}')
        
        # Market cap patterns
        self.mc_at_pattern = re.compile(r'at\s+(\d+\.?\d*[kKmM])', re.IGNORECASE)
        self.mc_from_pattern = re.compile(r'from\s+(\d+\.?\d*[kKmM])', re.IGNORECASE)
        self.mc_arrow_pattern = re.compile(
            r'(\d+\.?\d*[kKmM])\s*[→↗️⬆️➡️-]+\s*(\d+\.?\d*[kKmM])', 
            re.IGNORECASE
        )
        
        # Token disambiguation
        self.ticker_pattern = re.compile(r'\$[A-Z]{2,10}')
        
        # Language detection (basic)
        self.non_english_pattern = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]')
    
    def _is_english(self, text: str) -> bool:
        """Check if text is primarily English"""
        # Reject if contains CJK characters
        if self.non_english_pattern.search(text):
            return False
        
        # Reject if too many non-ASCII characters
        non_ascii = sum(1 for c in text if ord(c) > 127)
        if len(text) > 0 and non_ascii / len(text) > 0.3:
            return False
        
        return True
    
    def _is_ticker_spam(self, text: str, tickers: List[str]) -> bool:
        """Detect if tweet is just listing multiple tickers (spam)"""
        # If more than 4 different tickers mentioned, likely spam
        if len(tickers) > 4:
            return True
        
        # If tweet is very short but has many tickers
        words = text.split()
        if len(words) < 20 and len(tickers) > 3:
            return True
        
        # Check for airdrop spam patterns
        spam_keywords = ['airdrop', 'allocation', 'claim', 'wallet confirmation']
        if any(keyword in text.lower() for keyword in spam_keywords):
            if len(tickers) > 2:
                return True
        
        return False
    
    def _get_ticker_context_strength(self, text: str, ticker: str) -> int:
        """
        Calculate how strongly the ticker is discussed (not just mentioned)
        Returns position score: lower is better (ticker mentioned earlier)
        """
        ticker_with_dollar = f'${ticker}'
        
        # Find position of ticker in text
        pos = text.find(ticker_with_dollar)
        if pos == -1:
            pos = text.lower().find(ticker.lower())
        
        if pos == -1:
            return 9999  # Not found
        
        # Earlier mention = stronger signal
        # Position 0-50 chars = strong (0-10 points)
        # Position 50-100 = medium (10-20 points)
        # Position 100+ = weak (20+ points)
        return min(pos // 5, 50)
    
    def score_tweet(self, tweet: Dict) -> Dict:
        """
        Score a tweet based on trading signal strength
        
        Args:
            tweet: Tweet dictionary with 'text', 'time_to_rally_minutes', etc.
        
        Returns:
            Dict with 'accept', 'total_score', 'confidence', 'flags', 'breakdown'
        """
        text = tweet['text'].lower()
        original_text = tweet['text']
        time_to_rally = tweet['time_to_rally_minutes']
        
        score = 0
        flags = []
        breakdown = {}
        
        # ===================================================================
        # CRITICAL VALIDATION CHECKS (REJECT IMMEDIATELY IF FAILED)
        # ===================================================================
        
        # 1. TIME WINDOW VALIDATION - Must be within T-35 to T+10
        if time_to_rally < -35 or time_to_rally > 10:
            return {
                'accept': False,
                'total_score': 0,
                'confidence': 'rejected',
                'flags': ['OUTSIDE_TIME_WINDOW'],
                'breakdown': {},
                'reason': f'Outside time window (T{time_to_rally:+.0f}m, need -35 to +10)'
            }
        
        # 2. LANGUAGE VALIDATION - Must be English
        if not self._is_english(original_text):
            return {
                'accept': False,
                'total_score': 0,
                'confidence': 'rejected',
                'flags': ['NON_ENGLISH'],
                'breakdown': {},
                'reason': 'Non-English content detected'
            }
        
        # 3. ENGAGEMENT VALIDATION - Must meet minimum thresholds
        likes = tweet.get('likes', 0)
        retweets = tweet.get('retweets', 0)
        
        if likes < 2 or retweets < 1:
            return {
                'accept': False,
                'total_score': 0,
                'confidence': 'rejected',
                'flags': ['LOW_ENGAGEMENT'],
                'breakdown': {},
                'reason': f'Below engagement threshold (likes={likes}, RTs={retweets})'
            }
        
        # 4. TOKEN DISAMBIGUATION - Check which tickers are mentioned
        all_tickers = self.ticker_pattern.findall(original_text)
        
        # Check for ticker spam
        if self._is_ticker_spam(original_text, all_tickers):
            return {
                'accept': False,
                'total_score': 0,
                'confidence': 'rejected',
                'flags': ['TICKER_SPAM'],
                'breakdown': {},
                'reason': f'Ticker spam detected ({len(all_tickers)} tickers)'
            }
        
        # Check if target ticker is mentioned
        target_ticker_mentioned = f'${self.ticker}' in original_text or self.ticker in text
        
        if not target_ticker_mentioned:
            return {
                'accept': False,
                'total_score': 0,
                'confidence': 'rejected',
                'flags': ['TARGET_TICKER_MISSING'],
                'breakdown': {},
                'reason': f'${self.ticker} not mentioned'
            }
        
        # Check if OTHER tickers are mentioned and prioritized
        if all_tickers:
            # Get context strength for our ticker
            our_ticker_strength = self._get_ticker_context_strength(original_text, self.ticker)
            
            # Check if other tickers appear earlier or more prominently
            for other_ticker in all_tickers:
                if other_ticker == f'${self.ticker}':
                    continue
                
                other_ticker_name = other_ticker.replace('$', '')
                other_strength = self._get_ticker_context_strength(original_text, other_ticker_name)
                
                # If other ticker appears significantly earlier, likely wrong token
                if other_strength < our_ticker_strength - 20:
                    score -= 50
                    flags.append('OTHER_TICKER_PRIORITIZED')
                    breakdown['wrong_token_penalty'] = -50
                    break
        
        # ===================================================================
        # ULTRA HIGH CONFIDENCE SIGNALS (30+ points each)
        # ===================================================================
        
        # Contract address detection
        if self.solana_ca_pattern.search(original_text):
            score += 30
            flags.append('SOLANA_CA_POSTED')
            breakdown['solana_ca'] = 30
        
        if self.eth_ca_pattern.search(original_text):
            score += 30
            flags.append('ETH_CA_POSTED')
            breakdown['eth_ca'] = 30
        
        # Market cap mentions
        mc_found = False
        
        if self.mc_at_pattern.search(original_text):
            score += 18
            flags.append('MC_ENTRY_POINT')
            breakdown['mc_at'] = 18
            mc_found = True
        
        if self.mc_arrow_pattern.search(original_text):
            score += 18
            flags.append('MC_PROGRESSION')
            breakdown['mc_arrow'] = 18
            mc_found = True
        
        if self.mc_from_pattern.search(original_text):
            score += 18
            flags.append('MC_FROM_PATTERN')
            breakdown['mc_from'] = 18
            mc_found = True
        
        # ===================================================================
        # HIGH CONFIDENCE SIGNALS (20-25 points)
        # ===================================================================
        
        # Platform mentions
        platforms = [
            'pump.fun', 'pumpfun', 'dexscreener', 'birdeye', 'solscan',
            'etherscan', 'basescan', 'jupiter', 'raydium', 'photon', 'bullx'
        ]
        if any(platform in text for platform in platforms):
            score += 20
            flags.append('PLATFORM_MENTIONED')
            breakdown['platform'] = 20
        
        # Chain mentions
        chains = ['solana', 'sol', 'base', 'eth', 'ethereum', 'bsc']
        if any(chain in text for chain in chains):
            score += 10
            flags.append('CHAIN_MENTIONED')
            breakdown['chain'] = 10
        
        # Dev credibility signals
        dev_signals = [
            'dev behind', 'founder of', 'dev for', 'insane github',
            'strong technical', 'technical background'
        ]
        if any(signal in text for signal in dev_signals):
            score += 25
            flags.append('DEV_CREDIBILITY')
            breakdown['dev_credibility'] = 25
        
        # Predictive language
        predictive_phrases = [
            'will trade', 'gonna be', 'going to', 'tomorrow',
            'next week', 'when the', 'once', 'after'
        ]
        if any(phrase in text for phrase in predictive_phrases):
            score += 15
            flags.append('PREDICTIVE_SIGNAL')
            breakdown['predictive'] = 15
        
        # ===================================================================
        # MEDIUM CONFIDENCE SIGNALS (12-18 points)
        # ===================================================================
        
        # Momentum/Dip language
        momentum_signals = [
            'dip', 'dips', 'loading', 'adding', 'higher', 'send', 'sending',
            'vibe shift', 'trenches back', 'volume coming back',
            'fumbled', 'sold too early', 'bid the bottom'
        ]
        momentum_count = sum(1 for signal in momentum_signals if signal in text)
        if momentum_count > 0:
            score += min(momentum_count * 12, 18)
            flags.append('MOMENTUM_LANGUAGE')
            breakdown['momentum'] = min(momentum_count * 12, 18)
        
        # Attention/Setup signals
        attention_phrases = [
            'paying attention', 'start paying', 'pay attention',
            'this setup', 'running this', 'running the', 'my setup'
        ]
        if any(phrase in text for phrase in attention_phrases):
            score += 12
            flags.append('PRE_MOMENTUM_SIGNAL')
            breakdown['attention'] = 12
        
        # Relative valuation language
        relative_val = ['still low', 'steal', 'undervalued', 'slept on']
        if any(phrase in text for phrase in relative_val):
            score += 12
            flags.append('RELATIVE_VALUATION')
            breakdown['relative_val'] = 12
        
        # ===================================================================
        # ACTION & ENTRY SIGNALS (10-15 points)
        # ===================================================================
        
        # Direct action words
        action_words = [
            'bought', 'buying', 'just bought', 'ape', 'aped', 'call', 'shill'
        ]
        if any(word in text for word in action_words):
            score += 15
            flags.append('ACTION_TAKEN')
            breakdown['action'] = 15
        
        # Entry point specificity
        entry_phrases = ['entry', 'entered at', 'got in at', 'picked up at']
        if any(phrase in text for phrase in entry_phrases):
            score += 10
            flags.append('ENTRY_DISCLOSED')
            breakdown['entry'] = 10
        
        # ===================================================================
        # NARRATIVE & COMMUNITY SIGNALS (8-15 points)
        # ===================================================================
        
        # Tribal language
        tribal_signals = [
            'cult', 'community', 'holders', 'diamond hands', 
            'not fading', 'not selling', 'lfg', 'wagmi'
        ]
        if any(signal in text for signal in tribal_signals):
            score += 10
            flags.append('TRIBAL_LANGUAGE')
            breakdown['tribal'] = 10
        
        # Community growth metrics
        if re.search(r'\d+[kK]?\s*(holders|members|community)', text):
            score += 12
            flags.append('COMMUNITY_METRICS')
            breakdown['community_metrics'] = 12
        
        # Catalyst identification
        catalyst_words = ['when', 'after', 'once', 'news', 'announcement', 'launch']
        if any(word in text for word in catalyst_words):
            score += 8
            flags.append('CATALYST_IDENTIFIED')
            breakdown['catalyst'] = 8
        
        # ===================================================================
        # TIMING BONUS (Earlier = Better)
        # ===================================================================
        
        if time_to_rally < 0:
            # Pre-rally tweet - exponential bonus for earlier signals
            timing_bonus = min(abs(time_to_rally) * 0.5, 20)
            score += timing_bonus
            flags.append('PRE_RALLY')
            breakdown['timing_bonus'] = round(timing_bonus, 1)
        
        # ===================================================================
        # QUALITY FILTERS
        # ===================================================================
        
        # Engagement quality
        engagement_score = (
            likes * 0.1 +
            retweets * 0.5 +
            tweet.get('replies', 0) * 0.3
        )
        score += min(engagement_score, 10)
        breakdown['engagement'] = round(min(engagement_score, 10), 1)
        
        # ===================================================================
        # FINAL DECISION
        # ===================================================================
        
        # Determine confidence level
        if score >= 60:
            confidence = 'high'
            accept = True
        elif score >= 35:
            confidence = 'medium'
            accept = True
        elif score >= 20:
            confidence = 'low'
            accept = True
        else:
            confidence = 'very_low'
            accept = False
        
        return {
            'accept': accept,
            'total_score': round(score, 1),
            'confidence': confidence,
            'flags': flags,
            'breakdown': breakdown
        }
    
    def batch_score_tweets(self, tweets: List[Dict]) -> List[Dict]:
        """
        Score multiple tweets and return sorted by score
        
        Args:
            tweets: List of tweet dictionaries
        
        Returns:
            List of scored tweets, sorted by score (descending)
        """
        scored = []
        
        for tweet in tweets:
            score_result = self.score_tweet(tweet)
            
            if score_result['accept']:
                scored.append({
                    'tweet': tweet,
                    'score': score_result
                })
        
        # Sort by total score
        scored.sort(key=lambda x: x['score']['total_score'], reverse=True)
        
        return scored
    
    def analyze_tweet_quality(self, tweets: List[Dict]) -> Dict:
        """
        Analyze overall quality of tweet batch
        
        Args:
            tweets: List of tweets
        
        Returns:
            Quality analysis dictionary
        """
        if not tweets:
            return {
                'total': 0,
                'high_confidence': 0,
                'medium_confidence': 0,
                'low_confidence': 0,
                'rejected': 0,
                'avg_score': 0,
                'rejection_reasons': {}
            }
        
        scores = [self.score_tweet(t) for t in tweets]
        
        high = sum(1 for s in scores if s['confidence'] == 'high')
        medium = sum(1 for s in scores if s['confidence'] == 'medium')
        low = sum(1 for s in scores if s['confidence'] == 'low')
        rejected = sum(1 for s in scores if not s['accept'])
        
        # Count rejection reasons
        rejection_reasons = {}
        for s in scores:
            if not s['accept'] and 'reason' in s:
                reason = s['reason'].split('(')[0].strip()
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        
        total_scores = [s['total_score'] for s in scores if s['accept']]
        avg_score = sum(total_scores) / len(total_scores) if total_scores else 0
        
        return {
            'total': len(tweets),
            'high_confidence': high,
            'medium_confidence': medium,
            'low_confidence': low,
            'rejected': rejected,
            'avg_score': round(avg_score, 1),
            'acceptance_rate': round((len(tweets) - rejected) / len(tweets) * 100, 1),
            'rejection_reasons': rejection_reasons
        }


# Testing
if __name__ == "__main__":
    # Example token profile
    token_profile = {
        'ticker': 'PENGUIN',
        'name': 'Nietzschean Penguin',
        'contract_address': '8Jx8AAHj86wbQgUTjGuj6GTTL5Ps3cqxKRTvpaJApump',
        'chain': 'solana'
    }
    
    scorer = NLPDisambiguator(token_profile)
    
    # Test tweets
    test_tweets = [
        {
            'text': 'Just bought $PENGUIN at 500k mc. Dev has insane github. This will trade at millions when news hits. 8Jx8AAHj86wbQgUTjGuj6GTTL5Ps3cqxKRTvpaJApump',
            'time_to_rally_minutes': -15,
            'likes': 25,
            'retweets': 8,
            'replies': 3
        },
        {
            'text': 'bought some at 3M on dexscreener, adding more on dips',
            'time_to_rally_minutes': -8,
            'likes': 12,
            'retweets': 2,
            'replies': 1
        },
        {
            'text': 'Club Penguin Solana $CP going from 41K → 87.8K nice 2x',
            'time_to_rally_minutes': -5,
            'likes': 5,
            'retweets': 1,
            'replies': 0
        },
        {
            'text': 'The loneliest penguin in the world, filmed in 2007',
            'time_to_rally_minutes': -2,
            'likes': 100,
            'retweets': 20,
            'replies': 5
        },
        {
            'text': '$PENGUIN 这波洗盘结束了吗？ 🤔',
            'time_to_rally_minutes': -3,
            'likes': 5,
            'retweets': 2,
            'replies': 0
        },
        {
            'text': 'This happened 3 days ago - someone bought $PENGUIN at 20k and made $500k',
            'time_to_rally_minutes': 5000,
            'likes': 50,
            'retweets': 10,
            'replies': 2
        }
    ]
    
    print("NLP DISAMBIGUATOR TEST\n" + "="*80)
    
    for i, tweet in enumerate(test_tweets, 1):
        result = scorer.score_tweet(tweet)
        
        print(f"\nTweet #{i}:")
        print(f"Text: {tweet['text'][:60]}...")
        print(f"Accept: {result['accept']}")
        print(f"Score: {result['total_score']}")
        print(f"Confidence: {result['confidence']}")
        if not result['accept']:
            print(f"Rejection Reason: {result.get('reason', 'N/A')}")
        else:
            print(f"Flags: {', '.join(result['flags'][:5])}")
    
    print("\n" + "="*80)
    
    quality = scorer.analyze_tweet_quality(test_tweets)
    print(f"\nQuality Analysis:")
    print(f"  Total: {quality['total']}")
    print(f"  High confidence: {quality['high_confidence']}")
    print(f"  Medium confidence: {quality['medium_confidence']}")
    print(f"  Low confidence: {quality['low_confidence']}")
    print(f"  Rejected: {quality['rejected']}")
    print(f"  Avg score: {quality['avg_score']}")
    print(f"  Acceptance rate: {quality['acceptance_rate']}%")
    print(f"\n  Rejection Reasons:")
    for reason, count in quality['rejection_reasons'].items():
        print(f"    - {reason}: {count}")