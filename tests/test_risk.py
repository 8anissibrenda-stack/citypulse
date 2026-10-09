"""Test risk engine."""

import pytest
from app.vision.types import TrackedObject, ConflictZone
from app.risk.engine import RiskEngine, RiskConfig


@pytest.fixture
def config():
    return RiskConfig(
        ttc_warning_s=3.0,
        ttc_critical_s=1.5,
        prediction_horizon_s=5.0,
        collision_radius_m=1.5,
        min_consecutive_frames=2,  # easy for tests
        alert_cooldown_s=2.0,
        pixels_per_meter=25.0
    )


@pytest.fixture
def zones():
    return [
        ConflictZone(1, 1, "Crossing", "crossing", [(0,0), (100,0), (100,100), (0,100)])
    ]


@pytest.fixture
def engine(config, zones):
    return RiskEngine(config, zones)


def make_track(tid: int, cat: str, cx: float, cy: float, ts: float) -> TrackedObject:
    return TrackedObject(
        track_id=tid, cls_id=0, label="dummy", category=cat,
        bbox=(cx-10, cy-10, cx+10, cy+10), conf=0.9, cx=cx, cy=cy, ts=ts
    )


def test_head_on_collision_course(engine):
    """VRU and vehicle on a direct collision course."""
    # Frame 0
    engine.update([
        make_track(1, "vru", 1000, 50, 0.0),
        make_track(2, "vehicle", 0, 50, 0.0)
    ], 0.0)
    
    # Frame 1 - dt=0.1s
    # VRU moves left at 1 m/s (2.5 px/frame), Vehicle moves right at 10 m/s (25 px/frame)
    engine.update([
        make_track(1, "vru", 997.5, 50, 0.1),
        make_track(2, "vehicle", 25, 50, 0.1)
    ], 0.1)
    
    # Frame 2 - need 3 frames for velocity
    engine.update([
        make_track(1, "vru", 995, 50, 0.2),
        make_track(2, "vehicle", 50, 50, 0.2)
    ], 0.2)
    
    # They are 945 px apart = 37.8 m. Rel speed = 11 m/s. TTC ~ 3.4s -> No alert (above 3.0s warning)
    alerts = engine.update([
        make_track(1, "vru", 992.5, 50, 0.3),
        make_track(2, "vehicle", 75, 50, 0.3)
    ], 0.3)
    assert len(alerts) == 0
    
    # Fast forward frame by frame to maintain consistent velocity
    # Let's run 15 more frames (1.5 seconds).
    # TTC at t=0.3 was 3.4s. After 1.5s, at t=1.8, TTC should be 1.9s.
    # After 2.0s, at t=2.3, TTC should be 1.4s (Critical).
    for i in range(4, 25):
        ts = i * 0.1
        vru_x = 1000 - (i * 2.5)
        veh_x = 0 + (i * 25)
        alerts = engine.update([
            make_track(1, "vru", vru_x, 50, ts),
            make_track(2, "vehicle", veh_x, 50, ts)
        ], ts)
        
        if ts >= 2.2:  # TTC becomes < 1.5s around here
            # Wait for debounce (min 2 frames)
            if len(alerts) == 1:
                assert alerts[0].event_type == "critical"
                assert alerts[0].severity == 3
                return
                
    assert False, "Did not get critical alert"


def test_parallel_motion(engine):
    """VRU and vehicle moving parallel, never intersecting."""
    for i in range(5):
        ts = i * 0.1
        alerts = engine.update([
            make_track(1, "vru", 100, 50 + (i*10), ts),
            make_track(2, "vehicle", 500, 50 + (i*50), ts)
        ], ts)
    assert len(alerts) == 0


def test_stationary_vehicle(engine):
    """Vehicle is not moving, should not raise alert even if VRU approaches."""
    for i in range(5):
        ts = i * 0.1
        alerts = engine.update([
            make_track(1, "vru", 100 - (i*10), 50, ts),
            make_track(2, "vehicle", 50, 50, ts) # x=50, y=50 stationary
        ], ts)
    assert len(alerts) == 0


def test_near_miss(engine):
    """Conflict occurs, but they separate without collision."""
    # Move towards each other
    for i in range(4):
        ts = i * 0.1
        engine.update([
            make_track(1, "vru", 500 - (i*5), 50, ts),
            make_track(2, "vehicle", 400 + (i*20), 50, ts)
        ], ts)
        
    # Then separate abruptly (VRU jumps out of way)
    alerts = engine.update([
        make_track(1, "vru", 500, 200, 0.4), # Jumped in Y
        make_track(2, "vehicle", 480, 50, 0.4)
    ], 0.4)
    
    # Must wait one frame to confirm separation
    alerts = engine.update([
        make_track(1, "vru", 505, 205, 0.5),
        make_track(2, "vehicle", 500, 50, 0.5)
    ], 0.5)
    
    assert len(alerts) == 1
    assert alerts[0].event_type == "near_miss"
