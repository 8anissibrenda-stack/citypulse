"""Test API endpoints."""

import pytest
from fastapi.testclient import TestClient

# We need to patch db connection for testing, but for this prototype
# we'll just test the routers that don't strictly require live pipeline state
# or we mock the app state.

@pytest.fixture
def client():
    # Lazy import to avoid loading everything at module level
    from app.main import app
    
    # Provide mock state so endpoints don't crash
    class MockPipeline:
        running = False
        mode = "simulator"
        fps = 0
        latency_ms = 0
        active_alerts = []
        
    class MockSignalCtrl:
        def get_all_states(self): return []
        def request_priority(self, *args): pass
        
    class MockWS:
        client_count = 0
        async def broadcast(self, *args): pass
        
    app.state.pipeline = MockPipeline()
    app.state.signal_controller = MockSignalCtrl()
    app.state.ws_manager = MockWS()
    
    # Use TestClient (this does not run the lifespan events by default)
    with TestClient(app) as client:
        yield client

def test_health(client):
    """Test health endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_state(client):
    """Test state endpoint."""
    response = client.get("/api/state")
    assert response.status_code == 200
    data = response.json()
    assert "pipeline" in data
    assert "signals" in data

def test_events_list(client):
    """Test events listing."""
    response = client.get("/api/events?limit=5")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_config_validation(client):
    """Test config update validation."""
    # Negative value
    res = client.put("/api/config/risk", json={"values": {"ttc_warning_s": -1}})
    assert res.status_code == 400
    
    # Unknown key
    res = client.put("/api/config/risk", json={"values": {"bad_key": 1}})
    assert res.status_code == 400
