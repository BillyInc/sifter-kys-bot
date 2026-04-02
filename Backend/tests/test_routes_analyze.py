"""Tests for routes/analyze.py — Token analysis and key pool endpoints."""

import pytest
import json
from unittest.mock import patch, MagicMock


# ===========================================================================
# POST /api/analyze
# ===========================================================================

class TestAnalyzeTokens:
    """Tests for POST /api/analyze."""

    def test_missing_tokens_returns_400(self, client):
        resp = client.post(
            "/api/analyze",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "tokens" in resp.get_json()["error"]

    def test_empty_tokens_returns_400(self, client):
        resp = client.post(
            "/api/analyze",
            data=json.dumps({"tokens": []}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @patch("routes.analyze.TokenAnalyzerService")
    def test_single_token_success(self, MockAnalyzer, client):
        instance = MockAnalyzer.return_value
        instance.analyze_single_token.return_value = {
            "success": True,
            "rallies": 2,
            "_account_data": {},
        }

        resp = client.post(
            "/api/analyze",
            data=json.dumps({
                "tokens": [{"ticker": "SOL", "name": "Solana"}]
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["summary"]["total_tokens"] == 1
        assert data["summary"]["successful_analyses"] == 1

    @patch("routes.analyze.TokenAnalyzerService")
    def test_multi_token_aggregation(self, MockAnalyzer, client):
        instance = MockAnalyzer.return_value
        instance.analyze_single_token.side_effect = [
            {
                "success": True, "rallies": 3,
                "_account_data": {
                    "author1": {
                        "tokens_called": [{"ticker": "A"}],
                        "total_influence": 5.0,
                    }
                },
            },
            {
                "success": True, "rallies": 1,
                "_account_data": {
                    "author1": {
                        "tokens_called": [{"ticker": "B"}],
                        "total_influence": 3.0,
                    }
                },
            },
        ]

        resp = client.post(
            "/api/analyze",
            data=json.dumps({
                "tokens": [
                    {"ticker": "A", "name": "Token A"},
                    {"ticker": "B", "name": "Token B"},
                ]
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["summary"]["total_tokens"] == 2
        assert data["summary"]["total_pumps"] == 4
        # author1 called 2 tokens → cross-token overlap
        assert data["summary"]["cross_token_accounts"] == 1
        assert len(data["cross_token_overlap"]) == 1
        assert data["cross_token_overlap"][0]["tokens_count"] == 2

    @patch("routes.analyze.TokenAnalyzerService")
    def test_failed_analysis_counted(self, MockAnalyzer, client):
        instance = MockAnalyzer.return_value
        instance.analyze_single_token.return_value = {
            "success": False, "rallies": 0, "_account_data": {},
        }

        resp = client.post(
            "/api/analyze",
            data=json.dumps({
                "tokens": [{"ticker": "FAIL", "name": "Fail Token"}]
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["summary"]["failed_analyses"] == 1
        assert data["summary"]["successful_analyses"] == 0

    @patch("routes.analyze.TokenAnalyzerService")
    def test_cross_token_overlap_limited_to_10(self, MockAnalyzer, client):
        """Cross-token overlap is capped at 10 entries."""
        # Create 12 authors each calling 2 tokens
        account_data_1 = {}
        account_data_2 = {}
        for i in range(12):
            aid = f"author_{i}"
            account_data_1[aid] = {"tokens_called": [{"ticker": "A"}], "total_influence": 1.0}
            account_data_2[aid] = {"tokens_called": [{"ticker": "B"}], "total_influence": 1.0}

        instance = MockAnalyzer.return_value
        instance.analyze_single_token.side_effect = [
            {"success": True, "rallies": 0, "_account_data": account_data_1},
            {"success": True, "rallies": 0, "_account_data": account_data_2},
        ]

        resp = client.post(
            "/api/analyze",
            data=json.dumps({
                "tokens": [
                    {"ticker": "A", "name": "A"},
                    {"ticker": "B", "name": "B"},
                ]
            }),
            content_type="application/json",
        )
        data = resp.get_json()
        assert len(data["cross_token_overlap"]) == 10


# ===========================================================================
# GET /api/key_pool/status
# ===========================================================================

class TestKeyPoolStatus:
    """Tests for GET /api/key_pool/status."""

    @patch("routes.analyze.Config")
    def test_configured(self, MockConfig, client):
        MockConfig.is_twitter_configured.return_value = True
        resp = client.get("/api/key_pool/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["pool_status"]["configured"] is True
        assert data["pool_status"]["type"] == "bearer_token"

    @patch("routes.analyze.Config")
    def test_not_configured(self, MockConfig, client):
        MockConfig.is_twitter_configured.return_value = False
        resp = client.get("/api/key_pool/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["pool_status"]["configured"] is False
        assert data["pool_status"]["type"] == "not_configured"
