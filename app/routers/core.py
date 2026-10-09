"""Core API routes: health, state, pipeline control, video feed, config."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import db
from app.schemas import HealthResponse, PipelineStartRequest, RiskConfigUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["core"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    try:
        db.query_one("SELECT 1")
        return HealthResponse(status="ok", db_ok=True)
    except Exception:
        return HealthResponse(status="degraded", db_ok=False)


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    """Return current system state."""
    app = request.app
    pipeline = app.state.pipeline
    signal_ctrl = app.state.signal_controller

    return {
        "pipeline": {
            "running": pipeline.running if pipeline else False,
            "mode": pipeline.mode if pipeline else "simulator",
            "fps": pipeline.fps if pipeline else 0,
            "latency_ms": pipeline.latency_ms if pipeline else 0,
            "active_alerts": len(pipeline.active_alerts) if pipeline else 0,
        },
        "signals": signal_ctrl.get_all_states() if signal_ctrl else [],
        "ambulance": db.query_all(
            "SELECT id, call_sign, status, lat, lon, speed_kmh, emergency_active FROM ambulances"
        ),
        "counters": {
            "live_events": db.query_one("SELECT COUNT(*) as n FROM events WHERE is_seed=0")["n"],
            "seed_events": db.query_one("SELECT COUNT(*) as n FROM events WHERE is_seed=1")["n"],
        },
        "ws_clients": app.state.ws_manager.client_count if hasattr(app.state, "ws_manager") else 0,
    }


@router.post("/pipeline/start")
async def start_pipeline(body: PipelineStartRequest, request: Request) -> dict:
    """Start the vision pipeline."""
    app = request.app
    pipeline = app.state.pipeline

    if pipeline is None:
        raise HTTPException(500, "Pipeline not initialised")

    # Look up camera
    camera = db.query_one("SELECT * FROM cameras WHERE id = ?", (body.camera_id,))
    if camera is None:
        raise HTTPException(404, f"Camera {body.camera_id} not found")

    mode = body.mode or camera["source_type"]
    source_uri = camera.get("source_uri")

    # For video mode, check if file exists
    if mode == "video" or mode == "file":
        mode = "video"
        if source_uri and not __import__("pathlib").Path(source_uri).exists():
            raise HTTPException(
                400,
                f"Video file not found: {source_uri}. "
                "Place a video at data/sample_junction.mp4 or switch to simulator mode."
            )

    pipeline.start(mode=mode, source_uri=source_uri)

    # Update system_settings
    db.execute("UPDATE system_settings SET value = ? WHERE key = 'active_camera_id'", (str(body.camera_id),))
    db.execute("UPDATE system_settings SET value = ? WHERE key = 'pipeline_mode'", (mode,))

    return {"status": "started", "mode": mode, "camera_id": body.camera_id}


@router.post("/pipeline/stop")
async def stop_pipeline(request: Request) -> dict:
    """Stop the vision pipeline."""
    pipeline = request.app.state.pipeline
    if pipeline:
        pipeline.stop()
    return {"status": "stopped"}


@router.get("/config/risk")
async def get_risk_config() -> list[dict]:
    """Return all risk configuration values."""
    return db.query_all("SELECT * FROM risk_config ORDER BY key")


@router.put("/config/risk")
async def update_risk_config(body: RiskConfigUpdate, request: Request) -> dict:
    """Update risk configuration values."""
    valid_keys = {r["key"] for r in db.query_all("SELECT key FROM risk_config")}

    for key, value in body.values.items():
        if key not in valid_keys:
            raise HTTPException(400, f"Unknown config key: {key}")
        if not isinstance(value, (int, float)):
            raise HTTPException(400, f"Value for {key} must be a number")
        if value < 0:
            raise HTTPException(400, f"Value for {key} must be non-negative")
        db.execute("UPDATE risk_config SET value = ? WHERE key = ?", (value, key))

    # Hot-reload risk config in pipeline
    pipeline = request.app.state.pipeline
    if pipeline:
        from app.risk.engine import RiskConfig
        rows = db.query_all("SELECT key, value FROM risk_config")
        cfg_dict = {r["key"]: r["value"] for r in rows}
        pipeline.update_risk_config(RiskConfig(
            ttc_warning_s=cfg_dict.get("ttc_warning_s", 3.0),
            ttc_critical_s=cfg_dict.get("ttc_critical_s", 1.5),
            prediction_horizon_s=cfg_dict.get("prediction_horizon_s", 5.0),
            collision_radius_m=cfg_dict.get("collision_radius_m", 1.5),
            min_confidence=cfg_dict.get("min_confidence", 0.45),
            min_consecutive_frames=int(cfg_dict.get("min_consecutive_frames", 3)),
            alert_cooldown_s=cfg_dict.get("alert_cooldown_s", 4.0),
            near_miss_ttc_s=cfg_dict.get("near_miss_ttc_s", 1.0),
            near_miss_distance_m=cfg_dict.get("near_miss_distance_m", 1.2),
            min_vehicle_speed_mps=cfg_dict.get("min_vehicle_speed_mps", 1.5),
            velocity_smoothing_alpha=cfg_dict.get("velocity_smoothing_alpha", 0.4),
            vru_stationary_speed_mps=cfg_dict.get("vru_stationary_speed_mps", 0.3),
            pixels_per_meter=pipeline.pixels_per_meter,
        ))

    return {"status": "updated", "values": body.values}


def video_feed_generator(request: Request):
    """Generator for MJPEG stream."""
    pipeline = request.app.state.pipeline
    while True:
        if pipeline is None or not pipeline.running:
            import time
            time.sleep(0.1)
            continue
        frame = pipeline.get_latest_frame()
        if frame is None:
            import time
            time.sleep(0.05)
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )


@router.get("/junctions")
async def get_junctions() -> list[dict]:
    """Return all junctions."""
    return db.query_all("SELECT * FROM junctions")


@router.get("/signals")
async def get_signals(request: Request) -> list[dict]:
    """Return all signals with current state."""
    signals = db.query_all(
        "SELECT ts.*, j.code as junction_code, j.lat, j.lon FROM traffic_signals ts JOIN junctions j ON j.id = ts.junction_id"
    )
    ctrl = request.app.state.signal_controller
    if ctrl:
        states = {s["signal_id"]: s for s in ctrl.get_all_states()}
        for sig in signals:
            state = states.get(sig["id"], {})
            sig["ns_colour"] = state.get("ns_colour", "red")
            sig["ew_colour"] = state.get("ew_colour", "red")
            sig["preempt_active"] = state.get("preempt_active", False)
    return signals
