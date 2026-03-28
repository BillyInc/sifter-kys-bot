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
