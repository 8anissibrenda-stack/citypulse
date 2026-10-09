"""Test ambulance engine."""

import pytest
from app.ambulance.engine import haversine, project_on_route, simulate_run
from app.signals.controller import SignalController, Phase

def test_haversine():
    """Test distance calculation."""
    # Paris to London approx 344km
    dist = haversine(48.8566, 2.3522, 51.5074, -0.1278)
    assert 340000 < dist < 350000

def test_project_on_route():
    """Test route projection."""
    waypoints = [
        (0.0, 0.0),
        (0.0, 1.0), # 1 deg lon is approx 111km at equator
    ]
    # Point exactly in middle
    along, seg = project_on_route(0.0, 0.5, waypoints)
    assert seg == 0
    
    total = haversine(0.0, 0.0, 0.0, 1.0)
    assert abs(along - (total / 2)) < 1000  # within 1km tolerance

def test_simulate_priority_is_faster():
    """Priority run should be faster and have fewer stops than baseline."""
    offsets = [0.0, 48.0, 40.0]
    
    baseline = simulate_run("baseline", offsets)
    priority = simulate_run("priority", offsets)
    
    b_dur = baseline["summary"]["duration_s"]
    p_dur = priority["summary"]["duration_s"]
    b_stops = baseline["summary"]["stops"]
    p_stops = priority["summary"]["stops"]
    
    assert p_dur < b_dur
    assert p_stops <= b_stops
    assert p_stops == 0
