"""Scenario API routes for running test scenarios and viewing results."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app import db
from app.risk.engine import RiskConfig, RiskEngine
from app.vision.types import ConflictZone, TrackedObject
from app.vision.simulator import JunctionSimulator
from app.signals.controller import Phase, SignalController
from app.ambulance.engine import simulate_run

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _load_risk_config() -> RiskConfig:
    """Load risk configuration from the database."""
    rows = db.query_all("SELECT key, value FROM risk_config")
    cfg = {r["key"]: r["value"] for r in rows}
    camera = db.query_one("SELECT pixels_per_meter FROM cameras WHERE id = 1")
    ppm = camera["pixels_per_meter"] if camera else 25.0
    return RiskConfig(
        ttc_warning_s=cfg.get("ttc_warning_s", 3.0),
        ttc_critical_s=cfg.get("ttc_critical_s", 1.5),
        prediction_horizon_s=cfg.get("prediction_horizon_s", 5.0),
        collision_radius_m=cfg.get("collision_radius_m", 1.5),
        min_confidence=cfg.get("min_confidence", 0.45),
        min_consecutive_frames=int(cfg.get("min_consecutive_frames", 3)),
        alert_cooldown_s=cfg.get("alert_cooldown_s", 4.0),
        near_miss_ttc_s=cfg.get("near_miss_ttc_s", 1.0),
        near_miss_distance_m=cfg.get("near_miss_distance_m", 1.2),
        min_vehicle_speed_mps=cfg.get("min_vehicle_speed_mps", 1.5),
        velocity_smoothing_alpha=cfg.get("velocity_smoothing_alpha", 0.4),
        vru_stationary_speed_mps=cfg.get("vru_stationary_speed_mps", 0.3),
        pixels_per_meter=ppm,
    )


def _load_zones(camera_id: int = 1) -> list[ConflictZone]:
    """Load conflict zones for a camera."""
    rows = db.query_all("SELECT * FROM conflict_zones WHERE camera_id = ?", (camera_id,))
    zones: list[ConflictZone] = []
    for r in rows:
        poly = json.loads(r["polygon_json"])
        zones.append(ConflictZone(
            id=r["id"], camera_id=r["camera_id"],
            name=r["name"], zone_type=r["zone_type"],
            polygon=[tuple(p) for p in poly],
        ))
    return zones


def _build_signal_controller() -> SignalController:
    """Build a fresh signal controller from the database."""
    ctrl = SignalController()
    signals = db.query_all("SELECT * FROM traffic_signals")
    for sig in signals:
        phases_raw = db.query_all(
            "SELECT * FROM signal_phases WHERE signal_id = ? ORDER BY phase_order",
            (sig["id"],),
        )
        phases = [
            Phase(
                phase_order=p["phase_order"],
                phase_name=p["phase_name"],
                green_approach=p["green_approach"],
                duration_s=p["duration_s"],
            )
            for p in phases_raw
        ]
        ctrl.add_signal(
            signal_id=sig["id"],
            phases=phases,
            yellow_s=sig["yellow_s"],
            all_red_s=sig["all_red_s"],
            min_green_s=sig["min_green_s"],
            max_preempt_hold=sig["max_preempt_hold"],
            initial_offset_s=sig["initial_offset_s"],
        )
    return ctrl


def run_road_safety_scenario(scenario: dict) -> dict:
    """Run a road-safety scenario and return results."""
    params = json.loads(scenario["params_json"]) if isinstance(scenario["params_json"], str) else scenario["params_json"]
    duration_s = params["duration_s"]
    expected = scenario["expected_outcome"]

    config = _load_risk_config()
    zones = _load_zones()
    engine = RiskEngine(config, zones)
    sim = JunctionSimulator(fps=15.0, pixels_per_meter=config.pixels_per_meter, seed=42)
    sim.load_scenario(scenario["params_json"])

    all_alerts: list[dict] = []
    detected_tracks: set[int] = set()
    start_time = time.monotonic()

    dt = 1.0 / 15.0
    while not sim.is_scenario_done():
        _, objects = sim.step(dt)
        for obj in objects:
            detected_tracks.add(obj.track_id)

        alerts = engine.update(objects, sim.current_time)
        for a in alerts:
            all_alerts.append({
                "event_type": a.event_type,
                "severity": a.severity,
                "ttc_s": a.ttc_s,
            })

    elapsed_ms = (time.monotonic() - start_time) * 1000
    n_actors = len(params["actors"])
    detected = len(detected_tracks) >= n_actors

    has_warning = any(a["event_type"] in ("warning", "critical") for a in all_alerts)
    has_critical = any(a["event_type"] == "critical" for a in all_alerts)

    if expected == "alert":
        passed = has_warning
        alerted = has_warning
        false_alert = False
    elif expected == "critical_alert":
        passed = has_critical
        alerted = has_critical
        false_alert = False
    elif expected == "no_alert":
        passed = not has_warning and not has_critical
        alerted = has_warning or has_critical
        false_alert = alerted
    else:
        passed = False
        alerted = False
        false_alert = False

    return {
        "scenario_id": scenario["id"],
        "detected": detected,
        "alerted": alerted,
        "false_alert": false_alert,
        "response_ms": round(elapsed_ms, 1),
        "passed": passed,
        "notes": f"Alerts: {len(all_alerts)}, Types: {[a['event_type'] for a in all_alerts]}",
    }


def run_ambulance_scenario(scenario: dict) -> dict:
    """Run an ambulance scenario and return results."""
    params = json.loads(scenario["params_json"]) if isinstance(scenario["params_json"], str) else scenario["params_json"]
    route_id = params["route_id"]
    max_stops = params.get("max_allowed_stops", 0)

    # Load route data
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

    start_time = time.monotonic()

    # Run baseline
    offsets = [s["initial_offset_s"] for s in db.query_all("SELECT initial_offset_s FROM traffic_signals ORDER BY id")]
    if len(offsets) < 3:
        offsets = [0.0, 48.0, 40.0]
        
    baseline = simulate_run("baseline", offsets)
    priority = simulate_run("priority", offsets)

    elapsed_ms = (time.monotonic() - start_time) * 1000
    
    b_dur = baseline["summary"]["duration_s"]
    p_dur = priority["summary"]["duration_s"]
    b_stops = baseline["summary"]["stops"]
    p_stops = priority["summary"]["stops"]

    passed = (
        p_stops <= max_stops
        and p_dur < b_dur
    )

    return {
        "scenario_id": scenario["id"],
        "detected": True,
        "alerted": True,
        "false_alert": False,
        "response_ms": round(elapsed_ms, 1),
        "passed": passed,
        "notes": (
            f"Baseline: {b_dur}s/{b_stops} stops, "
            f"Priority: {p_dur}s/{p_stops} stops"
        ),
    }


@router.get("")
async def list_scenarios() -> list[dict]:
    """Return all test scenarios."""
    return db.query_all("SELECT * FROM test_scenarios ORDER BY id")


@router.post("/{code}/run")
async def run_scenario(code: str) -> dict:
    """Run a single scenario by code."""
    scenario = db.query_one("SELECT * FROM test_scenarios WHERE code = ?", (code,))
    if scenario is None:
        raise HTTPException(404, f"Scenario {code} not found")

    if scenario["scenario_type"] == "road_safety":
        result = run_road_safety_scenario(scenario)
    elif scenario["scenario_type"] == "ambulance":
        result = run_ambulance_scenario(scenario)
    else:
        raise HTTPException(400, f"Unknown scenario type: {scenario['scenario_type']}")

    # Store result
    db.execute(
        """INSERT INTO scenario_results
           (scenario_id, detected, alerted, false_alert, response_ms, passed, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (result["scenario_id"], result["detected"], result["alerted"],
         result["false_alert"], result["response_ms"], result["passed"], result["notes"]),
    )

    return result


@router.post("/run-all")
async def run_all_scenarios() -> dict:
    """Run all scenarios and return results."""
    scenarios = db.query_all("SELECT * FROM test_scenarios ORDER BY id")
    results = []
    for scenario in scenarios:
        if scenario["scenario_type"] == "road_safety":
            result = run_road_safety_scenario(scenario)
        elif scenario["scenario_type"] == "ambulance":
            result = run_ambulance_scenario(scenario)
        else:
            continue

        db.execute(
            """INSERT INTO scenario_results
               (scenario_id, detected, alerted, false_alert, response_ms, passed, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (result["scenario_id"], result["detected"], result["alerted"],
             result["false_alert"], result["response_ms"], result["passed"], result["notes"]),
        )
        results.append(result)

    return {"results": results}


@router.get("/results")
async def get_results() -> list[dict]:
    """Return scenario results."""
    return db.query_all(
        """SELECT sr.*, ts.code, ts.name, ts.expected_outcome
           FROM scenario_results sr
           JOIN test_scenarios ts ON ts.id = sr.scenario_id
           ORDER BY sr.run_at DESC"""
    )
