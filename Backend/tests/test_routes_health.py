"""Tests for routes/health.py — Health check endpoint."""

import pytest
from unittest.mock import patch, MagicMock


class TestHealthCheck:
    """Tests for GET /health."""

    def test_healthy_when_all_connected(self, client):
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_ch = MagicMock()
        mock_supa = MagicMock()
        mock_supa.schema.return_value.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock()

        with patch("services.redis_pool.get_redis_client", return_value=mock_redis), \
             patch("services.clickhouse_client.get_clickhouse_client", return_value=mock_ch), \
             patch("services.supabase_client.get_supabase_client", return_value=mock_supa), \
             patch("services.supabase_client.SCHEMA_NAME", "test"), \
             patch("config.Config.is_birdeye_configured", return_value=True), \
             patch("config.Config.is_twitter_configured", return_value=True):
            resp = client.get("/health")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert data["redis"] == "connected"
        assert data["clickhouse"] == "connected"
        assert data["supabase"] == "connected"

    def test_degraded_when_redis_down(self, client):
        mock_ch = MagicMock()
        mock_supa = MagicMock()
        mock_supa.schema.return_value.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock()

        with patch("services.redis_pool.get_redis_client", side_effect=Exception("down")), \
             patch("services.clickhouse_client.get_clickhouse_client", return_value=mock_ch), \
             patch("services.supabase_client.get_supabase_client", return_value=mock_supa), \
             patch("services.supabase_client.SCHEMA_NAME", "test"), \
             patch("config.Config.is_birdeye_configured", return_value=True), \
             patch("config.Config.is_twitter_configured", return_value=True):
            resp = client.get("/health")

        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "degraded"
        assert data["redis"] == "disconnected"

    def test_degraded_when_supabase_down(self, client):
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_ch = MagicMock()

        with patch("services.redis_pool.get_redis_client", return_value=mock_redis), \
             patch("services.clickhouse_client.get_clickhouse_client", return_value=mock_ch), \
             patch("services.supabase_client.get_supabase_client", side_effect=Exception("down")), \
             patch("config.Config.is_birdeye_configured", return_value=False), \
             patch("config.Config.is_twitter_configured", return_value=False):
            resp = client.get("/health")

        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "degraded"
        assert data["supabase"] == "disconnected"

    def test_includes_version(self, client):
        with patch("services.redis_pool.get_redis_client", side_effect=Exception), \
             patch("services.clickhouse_client.get_clickhouse_client", side_effect=Exception), \
             patch("services.supabase_client.get_supabase_client", side_effect=Exception), \
             patch("config.Config.is_birdeye_configured", return_value=False), \
             patch("config.Config.is_twitter_configured", return_value=False):
            resp = client.get("/health")

        data = resp.get_json()
        assert "version" in data

    def test_clickhouse_disconnected_does_not_degrade(self, client):
        """ClickHouse disconnect should not set status to degraded (it's optional)."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_supa = MagicMock()
        mock_supa.schema.return_value.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock()

        with patch("services.redis_pool.get_redis_client", return_value=mock_redis), \
             patch("services.clickhouse_client.get_clickhouse_client", side_effect=Exception("down")), \
             patch("services.supabase_client.get_supabase_client", return_value=mock_supa), \
             patch("services.supabase_client.SCHEMA_NAME", "test"), \
             patch("config.Config.is_birdeye_configured", return_value=True), \
             patch("config.Config.is_twitter_configured", return_value=True):
            resp = client.get("/health")

        data = resp.get_json()
        assert data["clickhouse"] == "disconnected"
        # ClickHouse down does NOT degrade overall status (per source code)
        assert data["status"] == "healthy"
