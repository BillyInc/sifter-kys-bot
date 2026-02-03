"""Health check routes."""
from flask import Blueprint, jsonify

from config import Config

health_bp = Blueprint('health', __name__)


@health_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'version': '5.1.0',
        'twitter_configured': Config.is_twitter_configured(),
        'birdeye_configured': Config.is_birdeye_configured(),
        'rate_limiting': True
    })
