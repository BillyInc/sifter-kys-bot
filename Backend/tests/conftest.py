import pytest
from unittest.mock import MagicMock, patch
import os

# Ensure test env
os.environ.setdefault('SUPABASE_URL', 'https://test.supabase.co')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-key')
os.environ.setdefault('CLICKHOUSE_HOST', 'localhost')
os.environ.setdefault('CLICKHOUSE_PASSWORD', 'test')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')


@pytest.fixture
def mock_supabase():
    """Mock Supabase client."""
    client = MagicMock()
    client.schema.return_value.table.return_value.select.return_value.execute.return_value.data = []
    return client


@pytest.fixture
def mock_clickhouse():
    """Mock ClickHouse client."""
    client = MagicMock()
    client.query.return_value.named_results.return_value = []
    client.query.return_value.result_rows = []
    return client


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    return MagicMock()


@pytest.fixture
def app():
    """Create Flask test app."""
    from app import create_app
    with patch('app.init_scheduler', return_value=MagicMock()), \
         patch('app.Redis.from_url', return_value=MagicMock()), \
         patch('app.Queue', return_value=MagicMock()), \
         patch('app.preload_trending_cache'), \
         patch('app.start_wallet_monitoring'):
        app = create_app()
        app.config['TESTING'] = True
        yield app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
