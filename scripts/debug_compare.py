import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.routers.scenarios import _build_signal_controller
from app.ambulance.engine import simulate_run
from app import db
import json

def run_debug():
    # Setup test params based on scenario 2 (ambulance)
    # Using route_id 1
    route_id = 1
    
    waypoints_raw = db.query_all(
        "SELECT lat, lon FROM route_waypoints WHERE route_id = ? ORDER BY seq", (route_id,)
    )
    waypoints = [(w["lat"], w["lon"]) for w in waypoints_raw]
    route_signals = db.query_all(
        """SELECT rs.signal_id, rs.seq, rs.approach, j.lat, j.lon
           FROM route_signals rs
           JOIN traffic_signals ts ON ts.id = rs.signal_id
           JOIN junctions j ON j.id = ts.junction_id
           WHERE rs.route_id = ? ORDER BY rs.seq""",
        (route_id,),
    )
    
    cruise_kmh = float(db.query_one("SELECT value FROM system_settings WHERE key='ambulance_cruise_kmh'")["value"])
    trigger_dist = float(db.query_one("SELECT value FROM system_settings WHERE key='priority_trigger_distance_m'")["value"])

    ctrl_b = _build_signal_controller()
    baseline = simulate_run(
        route_waypoints=waypoints,
        route_signals=route_signals,
        signal_controller=ctrl_b,
        mode="baseline",
        cruise_kmh=cruise_kmh,
        sim_speed=10,
        trigger_distance_m=trigger_dist,
    )
    
    ctrl_p = _build_signal_controller()
    priority = simulate_run(
        route_waypoints=waypoints,
        route_signals=route_signals,
        signal_controller=ctrl_p,
        mode="priority",
        cruise_kmh=cruise_kmh,
        sim_speed=10,
        trigger_distance_m=trigger_dist,
    )

    print("\n--- BASELINE TIMELINE ---")
    for p in baseline.positions:
        if p["t"] % 1.0 == 0.0 or p == baseline.positions[-1]:
            print(f"t={p['t']:5.1f} frac={p['route_fraction']:.2f} S1={p['signals'].get('S1')} S2={p['signals'].get('S2')} S3={p['signals'].get('S3')}")

    print("\n--- PRIORITY TIMELINE ---")
    for p in priority.positions:
        if p["t"] % 1.0 == 0.0 or p == priority.positions[-1]:
            print(f"t={p['t']:5.1f} frac={p['route_fraction']:.2f} S1={p['signals'].get('S1')} S2={p['signals'].get('S2')} S3={p['signals'].get('S3')} PriS2={p['priority_active'].get('S2')} PriS3={p['priority_active'].get('S3')}")

if __name__ == "__main__":
    run_debug()
