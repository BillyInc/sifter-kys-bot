"""Shared Redis connection pool for the KYS backend.

Instead of creating a new Redis connection on every call, all modules
should use ``get_redis_client()`` which draws from a single
``ConnectionPool`` instance.
"""

import os

import redis

_pool = None


def get_redis_client() -> redis.Redis:
    """Return a Redis client backed by a shared connection pool."""
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            max_connections=20,
            decode_responses=True,
        )
    return redis.Redis(connection_pool=_pool)
