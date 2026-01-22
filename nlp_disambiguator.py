from datetime import datetime, timedelta

class NLPDisambiguator:
    def __init__(self, token_profile):
        """
        Initialize NLP scorer with token context
        
        Args:
            token_profile: Dictionary with token metadata
                {
                    'ticker': 'BONK',
                    'name': 'Bonk Inu',
                    'contract_address': 'So111...',
                    'chain': 'solana',
                    'dex': 'raydium'
                }
        """
        self.profile = token_profile
        
        # Scoring weights
        self.WEIGHTS = {
            'ticker_match': 30,
            'chain_context': 25,
            'action_intent': 20,
            'platform_context': 15,
            'momentum_signals': 10,
            'contract_address': 100,
        }
        
        # Keyword dictionaries
        self.CHAIN_KEYWORDS = {
            'solana': ['sol', 'solana', 'raydium', 'pumpfun', 'pump.fun', 'jupiter', 'jup', 'orca'],
            'base': ['base', 'basechain', 'uniswap'],
            'ethereum': ['eth', 'ethereum', 'uniswap', 'v3'],
            'bsc': ['bnb', 'bsc', 'binance', 'pancakeswap'],
            'arbitrum': ['arb', 'arbitrum'],
            'polygon': ['matic', 'polygon'],
        }
        
        self.ACTION_KEYWORDS = {
            'strong_buy': ['aped', 'aping', 'bought', 'buying', 'filled', 'entry', 'bid', 'bidding'],
            'holding': ['hold', 'holding', 'bags', 'bagging', 'diamond', 'hodl'],
            'selling': ['sold', 'selling', 'exit', 'exited', 'jeet', 'jeeting', 'dump', 'dumping'],
            'intent': ['watching', 'eyeing', 'looking at', 'checking', 'monitoring'],
        }
        
        self.MOMENTUM_KEYWORDS = {
            'bullish': ['moon', 'mooning', 'pump', 'pumping', 'send', 'sending', 'lfg', 
                       'cook', 'cooking', 'runner', 'running', 'breakout', 'rip', 'ripping'],
            'hype': ['free money', 'lock in', 'based', 'chad', 'organic', 'legit', 'real'],
            'volume': ['trending', 'volume', 'vol', 'liquidity', 'liq', 'boosts'],
        }
        
        self.PLATFORM_KEYWORDS = ['bonded', 'bonding', 'creator rewards', 'graduated', 'pumpfun', 'pump.fun']
        
        self.NEGATIVE_KEYWORDS = ['scam', 'rug', 'rugged', 'avoid', 'warning', 'dead', 'ded']
    
    def score_tweet(self, tweet_data):
        """
        Score a single tweet for relevance to target token
        
        Args:
            tweet_data: Dictionary with tweet info
            
        Returns:
            {
                'total_score': int,
                'confidence': str,
                'breakdown': dict,
                'flags': list
            }
        """
        tweet_text = tweet_data['text']
        tweet_lower = tweet_text.lower()
        
        score_breakdown = {
            'ticker_match': 0,
            'chain_context': 0,
            'action_intent': 0,
            'platform_context': 0,
            'momentum_signals': 0,
            'contract_address': 0,
        }
        
        flags = []
        
        # 1. TICKER MATCH
        ticker = self.profile['ticker']
        
        if f"${ticker.lower()}" in tweet_lower or f"${ticker.upper()}" in tweet_lower:
            score_breakdown['ticker_match'] = 30
            flags.append('EXACT_TICKER_WITH_DOLLAR')
        elif ticker.lower() in tweet_lower.split():
            score_breakdown['ticker_match'] = 25
            flags.append('EXACT_TICKER_NO_DOLLAR')
        elif self.profile['name'].lower() in tweet_lower:
            score_breakdown['ticker_match'] = 20
            flags.append('NAME_MATCH')
        else:
            # No ticker match = reject immediately
            return self._format_result(0, 'rejected', score_breakdown, ['NO_TICKER_MATCH'])
        
        # 2. CHAIN CONTEXT
        chain = self.profile['chain'].lower()
        chain_keywords = self.CHAIN_KEYWORDS.get(chain, [chain])
        
        for keyword in chain_keywords:
            if keyword in tweet_lower:
                score_breakdown['chain_context'] = 25
                flags.append(f'CHAIN_MATCH:{keyword.upper()}')
                break
        
        # 3. ACTION INTENT
        for keyword in self.ACTION_KEYWORDS['strong_buy']:
            if keyword in tweet_lower:
                score_breakdown['action_intent'] = 20
                flags.append(f'STRONG_BUY:{keyword.upper()}')
                break
        
        if score_breakdown['action_intent'] == 0:
            for keyword in self.ACTION_KEYWORDS['holding']:
                if keyword in tweet_lower:
                    score_breakdown['action_intent'] = 15
                    flags.append(f'HOLDING:{keyword.upper()}')
                    break
        
        if score_breakdown['action_intent'] == 0:
            for keyword in self.ACTION_KEYWORDS['intent']:
                if keyword in tweet_lower:
                    score_breakdown['action_intent'] = 8
                    flags.append(f'INTENT:{keyword.upper()}')
                    break
        
        # 4. PLATFORM CONTEXT
        for keyword in self.PLATFORM_KEYWORDS:
            if keyword in tweet_lower:
                score_breakdown['platform_context'] = 15
                flags.append(f'PLATFORM:{keyword.upper()}')
                break
        
        # 5. MOMENTUM SIGNALS
        momentum_score = 0
        
        for keyword in self.MOMENTUM_KEYWORDS['bullish']:
            if keyword in tweet_lower:
                momentum_score += 5
                flags.append(f'BULLISH:{keyword.upper()}')
                break
        
        for keyword in self.MOMENTUM_KEYWORDS['hype']:
            if keyword in tweet_lower:
                momentum_score += 3
                flags.append(f'HYPE:{keyword.upper()}')
                break
        
        if '🚀' in tweet_text or '📈' in tweet_text or '💎' in tweet_text or '🔥' in tweet_text:
            momentum_score += 3
            flags.append('EMOJI_BULLISH')
        
        score_breakdown['momentum_signals'] = min(momentum_score, 10)
        
        # 6. CONTRACT ADDRESS (jackpot)
        if self.profile['contract_address'] in tweet_text:
            score_breakdown['contract_address'] = 100
            flags.append('CONTRACT_ADDRESS_CONFIRMED')
        
        # 7. NEGATIVE FILTERS
        negative_penalty = 0
        for keyword in self.NEGATIVE_KEYWORDS:
            if keyword in tweet_lower:
                negative_penalty += 30
                flags.append(f'NEGATIVE:{keyword.upper()}')
        
        # 8. ENGAGEMENT BOOST (high engagement = more credible)
        engagement_boost = 0
        likes = tweet_data.get('likes', 0)
        retweets = tweet_data.get('retweets', 0)
        
        if likes >= 10 or retweets >= 5:
            engagement_boost = 5
            flags.append('HIGH_ENGAGEMENT')
        
        # Calculate total
        total_score = sum(score_breakdown.values()) + engagement_boost - negative_penalty
        
        # Determine confidence
        confidence = self._determine_confidence(total_score, score_breakdown, flags)
        
        return self._format_result(total_score, confidence, score_breakdown, flags)
    
    def _determine_confidence(self, total_score, breakdown, flags):
        """Determine confidence level"""
        
        # Contract address = instant high
        if breakdown['contract_address'] >= 50:
            return 'high'
        
        # High confidence
        if total_score >= 70:
            if breakdown['chain_context'] > 0 or breakdown['action_intent'] > 0:
                return 'high'
        
        # Medium confidence
        if total_score >= 45:
            if breakdown['ticker_match'] > 0:
                other_signals = breakdown['chain_context'] + breakdown['action_intent']
                if other_signals > 0:
                    return 'medium'
        
        # Low confidence
        if total_score >= 25:
            return 'low'
        
        return 'rejected'
    
    def _format_result(self, total_score, confidence, breakdown, flags):
        """Format scoring result"""
        return {
            'total_score': total_score,
            'confidence': confidence,
            'breakdown': breakdown,
            'flags': flags,
            'accept': confidence in ['high', 'medium']
        }