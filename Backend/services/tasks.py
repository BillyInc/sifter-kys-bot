"""Background tasks for wallet analysis using RQ."""
import json
import redis
from rq import get_current_job

from config import Config
from services.wallet_analyzer import WalletPumpAnalyzer

_analyzer = None

def get_wallet_analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = WalletPumpAnalyzer(
            solanatracker_api_key=Config.SOLANATRACKER_API_KEY,
            birdeye_api_key=Config.BIRDEYE_API_KEY,
            debug_mode=True
        )
    return _analyzer

def perform_wallet_analysis(data):
    """
    Perform wallet analysis based on input data.
    - If 'tokens' is a list with >1 items: batch analysis
    - If 'tokens' is a list with 1 item or 'token' present: single analysis
    Stores result in Redis for polling.
    """
    analyzer = get_wallet_analyzer()
    
    user_id = data.get('user_id', 'default_user')
    min_roi_multiplier = data.get('min_roi_multiplier', 3.0)
    
    tokens = data.get('tokens', [])
    if len(tokens) > 1:
        # Batch analysis for multiple tokens
        result = analyzer.batch_analyze_tokens(
            tokens=tokens,
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )
        mode = 'batch_tokens'
        summary = {
            'tokens_analyzed': len(tokens),
            'wallets_found': len(result),
            'mode': mode
        }
    elif len(tokens) == 1 or data.get('token'):
        # Single token analysis
        token = tokens[0] if tokens else data['token']
        result = analyzer.analyze_token_professional(
            token_address=token['address'],
            token_symbol=token.get('ticker', 'UNKNOWN'),
            min_roi_multiplier=min_roi_multiplier,
            user_id=user_id
        )
        mode = 'single_token'
        summary = {
            'token': token.get('ticker', 'UNKNOWN'),
            'wallets_found': len(result),
            'mode': mode
        }
    else:
        raise ValueError("Invalid data format: Must provide 'tokens' list or 'token' object")
    
    full_result = {
        'success': True,
        'result': result,
        'summary': summary
    }
    
    # Store result in Redis with job_id
    job = get_current_job()
    r = redis.Redis(host='localhost', port=6379)
    r.set(f"job_result:{job.id}", json.dumps(full_result), ex=3600)  # Expire after 1 hour
    
    return full_result