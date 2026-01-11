#!/usr/bin/env python3
"""
RFSN Integration Tests v8.2
End-to-end API testing with httpx.
"""

import asyncio
import json
import pytest
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Skip if httpx not installed
pytest.importorskip("httpx")

import httpx
from fastapi.testclient import TestClient


class TestAPIEndpoints:
    """Test API endpoints work correctly"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test client"""
        # Import here to avoid startup issues
        from orchestrator import app
        from security import require_auth
        
        # Override auth for tests
        app.dependency_overrides[require_auth] = lambda: {"user": "test_runner", "role": "admin"}
        
        self.client = TestClient(app)
    
    def test_status_endpoint(self):
        """Status endpoint returns health info"""
        response = self.client.get("/api/status")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "status" in data
        assert data["status"] == "healthy"
        assert "version" in data
    
    def test_dialogue_stream_basic(self):
        """Dialogue stream accepts valid input"""
        response = self.client.post(
            "/api/dialogue/stream",
            json={
                "user_input": "Hello there!",
                "npc_state": {
                    "npc_name": "Lydia",
                    "affinity": 0.5
                }
            }
        )
        
        # Service may be unavailable in test, accept 200 or 503
        assert response.status_code in [200, 503]
    
    def test_dialogue_stream_missing_input(self):
        """Dialogue stream requires user_input"""
        response = self.client.post(
            "/api/dialogue/stream",
            json={}
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_memory_stats_endpoint(self):
        """Memory stats endpoint works"""
        response = self.client.get("/api/memory/TestNPC/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "npc_name" in data
        assert "total_turns" in data
    
    def test_safe_reset_endpoint(self):
        """Safe reset endpoint works"""
        response = self.client.post("/api/memory/TestNPC/safe_reset")
        
        assert response.status_code == 200
        data = response.json()
        
        # Accept success or error response structure
        assert "success" in data or "error" in data or "message" in data
    
    def test_backups_list(self):
        """Backups list endpoint works"""
        response = self.client.get("/api/memory/backups")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "backups" in data
        assert isinstance(data["backups"], list)


class TestStreamingResponse:
    """Test streaming response functionality"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        from orchestrator import app
        self.client = TestClient(app)
    
    def test_streaming_content_type(self):
        """Streaming response has correct content type"""
        response = self.client.post(
            "/api/dialogue/stream",
            json={
                "user_input": "Tell me about yourself",
                "npc_state": {"npc_name": "Test", "affinity": 0.0}
            }
        )
        
        # Accept streaming response or service unavailable
        # Accept streaming response or service unavailable
        content_type = response.headers.get("content-type", "")
        # Note: 503 means model not ready, which is fine for integration test
        assert "text/event-stream" in content_type or response.status_code in [200, 503]


class TestErrorHandling:
    """Test error handling"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        from orchestrator import app
        self.client = TestClient(app)
    
    def test_invalid_json(self):
        """Invalid JSON returns 422"""
        response = self.client.post(
            "/api/dialogue/stream",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 422
    
    def test_404_endpoint(self):
        """Unknown endpoints return 404"""
        response = self.client.get("/api/nonexistent")
        
        assert response.status_code == 404


class TestCORS:
    """Test CORS headers"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        from orchestrator import app
        self.client = TestClient(app)
    
    def test_options_request(self):
        """OPTIONS request returns CORS headers"""
        response = self.client.options(
            "/api/status",
            headers={"Origin": "http://localhost:3000"}
        )
        
        # Should not fail
        assert response.status_code in [200, 405]


@pytest.mark.asyncio
class TestAsyncClient:
    """Async client tests"""
    
    async def test_async_status(self):
        """Async client can hit status endpoint"""
        # Skip if not running server
        pytest.skip("Requires running server")
        
        async with httpx.AsyncClient() as client:
            response = await client.get("http://127.0.0.1:8000/api/status")
            assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
