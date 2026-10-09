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
    # Setup route (approx 1.1km)
    waypoints = [
        (20.000, 78.0),
        (20.010, 78.0) 
    ]
    route_signals = [
        {"signal_id": 1, "seq": 1, "approach": "NS", "lat": 20.005, "lon": 78.0}
    ]
    
    # Setup controller
    ctrl = SignalController()
    phases = [
        Phase(1, "NS Green", "NS", 10),
        Phase(2, "EW Green", "EW", 40)
    ]
    # At t=50s (arrival time), NS will be red if offset=0
    ctrl.add_signal(1, phases, initial_offset_s=0) 
    
    baseline = simulate_run(
        waypoints, route_signals, ctrl, 
        mode="baseline", cruise_kmh=40, sim_speed=10, trigger_distance_m=250
    )
    
    priority = simulate_run(
        waypoints, route_signals, ctrl, 
        mode="priority", cruise_kmh=40, sim_speed=10, trigger_distance_m=250
    )
    
    assert priority.duration_s < baseline.duration_s
    assert priority.stops_count <= baseline.stops_count
    assert priority.stops_count == 0
