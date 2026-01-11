import pytest
from fastapi.testclient import TestClient
from orchestrator import app

class TestDashboardUI:
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
    
    def test_dashboard_served_at_root(self):
        """Dashboard HTML should be served at /"""
        response = self.client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<title>RFSN Orchestrator v8.6 - Premium</title>" in response.text

    def test_controls_present(self):
        """Dashboard should contain tuning controls and premium elements"""
        response = self.client.get("/")
        assert response.status_code == 200
        # Check for premium elements
        assert 'id="latencySparkline"' in response.text
        assert 'class="toast-container"' in response.text
        assert 'backdrop-filter: blur' in response.text
        
        # Check for functional controls
        assert 'id="tempSlider"' in response.text
        assert 'onclick="applyTuning(this)"' in response.text
