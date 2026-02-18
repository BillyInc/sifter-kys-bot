"""
Token search and info routes.
FILE LOCATION: routes/token_routes.py
"""
from flask import Blueprint, request, jsonify
import requests
from config import Config

tokens_bp = Blueprint('tokens', __name__, url_prefix='/api/tokens')


@tokens_bp.route('/search', methods=['GET', 'OPTIONS'])
def search_tokens():
    """
    Proxy to SolanaTracker /search and normalize fields for frontend.

    SolanaTracker /search returns fields at the root item level:
        mint, symbol, name, liquidityUsd, lpBurn,
        mintAuthority, freezeAuthority, hasSocials, socials

    Frontend expects:
        address, ticker, name, liquidity, chain
    """
    if request.method == 'OPTIONS':
        return '', 204

    query = request.args.get('query', '').strip()
    if not query:
        return jsonify({'success': False, 'error': 'query required'}), 400

    try:
        url = "https://data.solanatracker.io/search"
        params = {
            'query': query,
            'limit': 20,
            'sortBy': 'liquidityUsd',
            'sortOrder': 'desc',
        }
        headers = {
            'accept': 'application/json',
            'x-api-key': Config.SOLANATRACKER_API_KEY
        }

        resp = requests.get(url, headers=headers, params=params, timeout=10)

        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'SolanaTracker error {resp.status_code}'}), 502

        raw = resp.json()
        # SolanaTracker /search returns either a bare list or {"data": [...]}
        items = raw if isinstance(raw, list) else raw.get('data', [])

        tokens = []
        for item in items:
            tokens.append({
                'address':          item.get('mint') or item.get('poolAddress'),
                'ticker':           item.get('symbol', ''),
                'name':             item.get('name', ''),
                'chain':            'solana',
                'liquidity':        item.get('liquidityUsd', 0),
                'volume_24h':       item.get('volume24h', 0),
                'price':            item.get('priceUsd', 0),
                'holders':          item.get('holders', 0),
                # Security — these are ROOT-level fields on /search results
                'lp_burn':          item.get('lpBurn', 0),           # integer 0-100
                'mint_authority':   item.get('mintAuthority'),       # null = revoked ✅
                'freeze_authority': item.get('freezeAuthority'),     # null = revoked ✅
                'has_socials':      item.get('hasSocials', False),
                'socials':          item.get('socials', {}),
                'risk_score':       item.get('riskScore', 0),
                'market':           item.get('market', ''),
            })

        return jsonify({'success': True, 'tokens': tokens}), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@tokens_bp.route('/info/<token_address>', methods=['GET', 'OPTIONS'])
def get_token_info(token_address):
    """
    Get detailed info for a single token via SolanaTracker /tokens/{address}.
    Security fields live under pool.security{} (not root) for this endpoint.
    """
    if request.method == 'OPTIONS':
        return '', 204

    try:
        url = f"https://data.solanatracker.io/tokens/{token_address}"
        headers = {
            'accept': 'application/json',
            'x-api-key': Config.SOLANATRACKER_API_KEY
        }

        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 404:
            return jsonify({'success': False, 'error': 'Token not found'}), 404
        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'SolanaTracker error {resp.status_code}'}), 502

        data = resp.json()
        pools = data.get('pools', [])
        token_meta = data.get('token', {})  # symbol/name live under data['token']

        primary_pool = (
            max(pools, key=lambda p: p.get('liquidity', {}).get('usd', 0))
            if pools else {}
        )
        # On /tokens/{address}, security fields are inside pool.security{}
        security_obj = primary_pool.get('security', {})

        return jsonify({
            'success': True,
            'token': {
                'address':          token_address,
                'ticker':           token_meta.get('symbol', ''),
                'name':             token_meta.get('name', ''),
                'chain':            'solana',
                'liquidity':        primary_pool.get('liquidity', {}).get('usd', 0),
                'price':            primary_pool.get('price', {}).get('usd', 0),
                'holders':          data.get('holders', 0),
                'lp_burn':          primary_pool.get('lpBurn', 0),
                'mint_authority':   security_obj.get('mintAuthority'),
                'freeze_authority': security_obj.get('freezeAuthority'),
                'has_socials':      bool(token_meta.get('strictSocials', {})),
                'socials':          token_meta.get('strictSocials', {}),
            }
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500