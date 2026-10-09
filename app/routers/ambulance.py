"""Ambulance API routes."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app import db
from app.schemas import GPSUpdate, SimulateRequest
from app.ambulance.engine import (
    haversine, bearing, project_on_route, look_ahead,
    simulate_run, route_total_distance, SignalOnRoute,
)
from app.signals.controller import Phase, SignalController

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ambulance", tags=["ambulance"])


def _get_route_data(route_id: int) -> tuple[list[tuple[float, float]], list[dict]]:
    """Load route waypoints and signal associations."""
    waypoints_raw = db.query_all(
        "SELECT lat, lon FROM route_waypoints WHERE route_id = ? ORDER BY seq", (route_id,)
    )
    waypoints = [(w["lat"], w["lon"]) for w in waypoints_raw]

    route_signals_raw = db.query_all(
        """SELECT rs.signal_id, rs.seq, rs.approach, j.lat, j.lon
           FROM route_signals rs
           JOIN traffic_signals ts ON ts.id = rs.signal_id
           JOIN junctions j ON j.id = ts.junction_id
           WHERE rs.route_id = ? ORDER BY rs.seq""",
        (route_id,),
    )

    return waypoints, route_signals_raw


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


@router.get("")
async def get_ambulances() -> list[dict]:
    """Return all ambulances."""
    return db.query_all("SELECT * FROM ambulances")


@router.post("/gps")
async def update_gps(body: GPSUpdate, request: Request) -> dict:
    """Update ambulance GPS position."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    status = "en_route" if body.emergency else "idle"

    db.execute(
        """UPDATE ambulances SET lat=?, lon=?, speed_kmh=?, heading_deg=?,
           emergency_active=?, status=?, last_update=? WHERE id=?""",
        (body.lat, body.lon, body.speed_kmh, body.heading_deg,
         1 if body.emergency else 0, status, now, body.ambulance_id),
    )

    result: dict[str, Any] = {
        "status": "updated",
        "ambulance_id": body.ambulance_id,
        "emergency": body.emergency,
    }

    # Look-ahead and signal priority if emergency
    if body.emergency:
        route = db.query_one("SELECT * FROM routes LIMIT 1")
        if route:
            waypoints, route_signals = _get_route_data(route["id"])
            along, _ = project_on_route(body.lat, body.lon, waypoints)

            trigger_dist = float(
                db.query_one("SELECT value FROM system_settings WHERE key='priority_trigger_distance_m'")["value"]
            )

            upcoming = look_ahead(along, waypoints, route_signals, trigger_dist)
            result["signals_ahead"] = len(upcoming)

            ctrl = request.app.state.signal_controller
            if ctrl and upcoming:
                for sig in upcoming:
                    speed_mps = max(body.speed_kmh / 3.6, 5.0 / 3.6)
                    eta = sig.distance_m / speed_mps
                    ctrl.request_priority(sig.signal_id, sig.approach, eta)

    # Broadcast position
    ws = request.app.state.ws_manager
    if ws:
        import asyncio
        await ws.broadcast({
            "type": "ambulance_update",
            "ambulance_id": body.ambulance_id,
            "lat": body.lat,
            "lon": body.lon,
            "speed_kmh": body.speed_kmh,
            "emergency": body.emergency,
        })

    return result


@router.post("/simulate")
async def simulate(body: SimulateRequest, request: Request) -> dict:
    """Run a simulated ambulance run."""
    waypoints, route_signals = _get_route_data(body.route_id)
    if not waypoints:
        raise HTTPException(404, "Route not found or has no waypoints")

    ctrl = _build_signal_controller()

    result = simulate_run(
        route_waypoints=waypoints,
        route_signals=route_signals,
        signal_controller=ctrl,
        mode=body.mode,
        cruise_kmh=float(
            db.query_one("SELECT value FROM system_settings WHERE key='ambulance_cruise_kmh'")["value"]
        ),
        sim_speed=body.sim_speed,
        trigger_distance_m=float(
            db.query_one("SELECT value FROM system_settings WHERE key='priority_trigger_distance_m'")["value"]
        ),
    )

    # Store in database
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    run_id = db.execute(
        """INSERT INTO ambulance_runs
           (ambulance_id, route_id, mode, started_at, ended_at, duration_s,
            stops_count, total_wait_s, sim_speed, is_seed)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (body.route_id, body.mode, now, now, result.duration_s,
         result.stops_count, result.total_wait_s, body.sim_speed),
    )

    # Store signal log
    for entry in result.signal_log:
        db.execute(
            """INSERT INTO ambulance_run_signal_log
               (run_id, signal_id, arrival_s, phase_on_arrival, wait_s, preempted)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, entry["signal_id"], entry["arrival_s"],
             entry["phase_on_arrival"], entry["wait_s"], entry.get("preempted", 0)),
        )

    # Broadcast ambulance updates
    ws = request.app.state.ws_manager
    if ws:
        for pos in result.positions[::max(1, len(result.positions) // 20)]:
            await ws.broadcast({
                "type": "ambulance_update",
                "ambulance_id": 1,
                "lat": pos["lat"],
                "lon": pos["lon"],
                "speed_kmh": pos["speed_kmh"],
                "emergency": body.mode == "priority",
                "sim_time": pos["t"],
            })

    return {
        "run_id": run_id,
        "mode": result.mode,
        "duration_s": result.duration_s,
        "stops_count": result.stops_count,
        "total_wait_s": result.total_wait_s,
        "signal_log": result.signal_log,
    }


@router.get("/runs")
async def get_runs() -> list[dict]:
    """Return all ambulance runs."""
    return db.query_all("SELECT * FROM ambulance_runs ORDER BY started_at DESC")


@router.get("/comparison")
async def comparison() -> dict:
    """Return baseline vs priority comparison."""
    data = db.query_all("SELECT * FROM v_ambulance_comparison")
    baseline = next((d for d in data if d["mode"] == "baseline"), {})
    priority = next((d for d in data if d["mode"] == "priority"), {})

    b_dur = baseline.get("avg_duration_s", 0) or 0
    p_dur = priority.get("avg_duration_s", 0) or 0
    saved = round((b_dur - p_dur) / b_dur * 100, 1) if b_dur > 0 else 0

    return {
        "baseline": baseline,
        "priority": priority,
        "time_saved_pct": saved,
        "runs": db.query_all("SELECT * FROM ambulance_runs ORDER BY started_at DESC"),
    }
