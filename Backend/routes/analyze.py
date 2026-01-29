"""Token analysis routes."""
from flask import Blueprint, request, jsonify

from services.token_analyzer import TokenAnalyzerService
from config import Config

analyze_bp = Blueprint('analyze', __name__, url_prefix='/api')


@analyze_bp.route('/analyze', methods=['POST'])
def analyze_tokens():
    """
    Analyze multiple tokens for pump patterns and Twitter callers.

    Rate limited: 5 per hour, 20 per day (applied in app.py)
    """
    data = request.json

    if not data or not data.get('tokens'):
        return jsonify({'error': 'tokens array required'}), 400

    tokens = data['tokens']

    print(f"\n{'='*100}")
    print(f"MULTI-TOKEN ANALYSIS: {len(tokens)} tokens")
    print(f"{'='*100}\n")

    analyzer = TokenAnalyzerService()
    all_results = []
    all_top_accounts = {}

    # Analyze each token
    for idx, token in enumerate(tokens, 1):
        print(f"\n{'-'*100}")
        print(f"[{idx}/{len(tokens)}] Analyzing {token['ticker']} ({token['name']})")
        print(f"{'-'*100}")

        result = analyzer.analyze_single_token(token, idx, len(tokens))
        all_results.append(result)

        # Aggregate cross-token account data
        account_data = result.pop('_account_data', {})
        for author_id, data in account_data.items():
            if author_id not in all_top_accounts:
                all_top_accounts[author_id] = {
                    'author_id': author_id,
                    'tokens_called': [],
                    'total_influence': 0
                }
            all_top_accounts[author_id]['tokens_called'].extend(data['tokens_called'])
            all_top_accounts[author_id]['total_influence'] += data['total_influence']

    # Calculate cross-token overlap
    multi_token_accounts = [
        {
            'author_id': author_id,
            'tokens_count': len(data['tokens_called']),
            'tokens_called': data['tokens_called'],
            'total_influence': round(data['total_influence'], 1)
        }
        for author_id, data in all_top_accounts.items()
        if len(data['tokens_called']) >= 2
    ]
    multi_token_accounts.sort(key=lambda x: x['tokens_count'], reverse=True)

    # Build response
    successful = sum(1 for r in all_results if r['success'])
    failed = sum(1 for r in all_results if not r['success'])
    total_pumps = sum(r.get('rallies', 0) for r in all_results)

    response = {
        'success': True,
        'summary': {
            'total_tokens': len(tokens),
            'successful_analyses': successful,
            'failed_analyses': failed,
            'total_pumps': total_pumps,
            'cross_token_accounts': len(multi_token_accounts)
        },
        'results': all_results,
        'cross_token_overlap': multi_token_accounts[:10]
    }

    print(f"\n{'='*100}")
    print(f"ANALYSIS COMPLETE")
    print(f"  Total: {len(tokens)} tokens")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")
    print(f"  Total Pumps: {total_pumps}")
    print(f"  Cross-token accounts: {len(multi_token_accounts)}")
    print(f"{'='*100}\n")

    return jsonify(response), 200


@analyze_bp.route('/key_pool/status', methods=['GET'])
def get_key_pool_status():
    """Get Twitter API configuration status."""
    is_configured = Config.is_twitter_configured()

    return jsonify({
        'success': True,
        'pool_status': {
            'configured': is_configured,
            'type': 'bearer_token' if is_configured else 'not_configured',
            'active': is_configured
        }
    }), 200
