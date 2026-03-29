"""Health check routes."""
from flask import Blueprint, jsonify

from config import Config

health_bp = Blueprint('health', __name__)


@health_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint with dependency connectivity checks."""
    checks = {'status': 'healthy', 'version': '5.1.0'}

    # Redis
    try:
        from services.redis_pool import get_redis_client
        r = get_redis_client()
        r.ping()
        checks['redis'] = 'connected'
    except Exception:
        checks['redis'] = 'disconnected'
        checks['status'] = 'degraded'

    # ClickHouse
    try:
        from services.clickhouse_client import get_clickhouse_client
        ch = get_clickhouse_client()
        ch.query('SELECT 1')
        checks['clickhouse'] = 'connected'
    except Exception:
        checks['clickhouse'] = 'disconnected'

    # Supabase
    try:
        from services.supabase_client import get_supabase_client, SCHEMA_NAME
        s = get_supabase_client()
        s.schema(SCHEMA_NAME).table('users').select('user_id').limit(1).execute()
        checks['supabase'] = 'connected'
    except Exception:
        checks['supabase'] = 'disconnected'
        checks['status'] = 'degraded'

    # Config
    checks['birdeye_configured'] = Config.is_birdeye_configured()
    checks['twitter_configured'] = Config.is_twitter_configured()
    checks['rate_limiting'] = True

    status_code = 200 if checks['status'] == 'healthy' else 503
    return jsonify(checks), status_code
