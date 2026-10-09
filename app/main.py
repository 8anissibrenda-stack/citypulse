"""Main FastAPI application for CityPulse."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import settings
from app.routers import ambulance, core, events, scenarios, signals
from app.services.pipeline import PipelineService
from app.signals.controller import Phase, SignalController
from app.vision.types import ConflictZone
from app.risk.engine import RiskConfig
from app.ws import ConnectionManager

logging.basicConfig(level=settings.log_level, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("citypulse")

# ---------------------------------------------------------------------------
# Setup & Lifespan
# ---------------------------------------------------------------------------

def _load_risk_config() -> RiskConfig:
    """Load risk configuration from the database."""
    rows = db.query_all("SELECT key, value FROM risk_config")
    cfg = {r["key"]: r["value"] for r in rows}
    
    # Get active camera's pixels_per_meter
    cam_id = int(db.query_one("SELECT value FROM system_settings WHERE key='active_camera_id'")["value"])
    camera = db.query_one("SELECT pixels_per_meter FROM cameras WHERE id = ?", (cam_id,))
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

def _load_zones(camera_id: int) -> list[ConflictZone]:
    """Load conflict zones for the active camera."""
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

def _build_signal_controller(ws_manager: ConnectionManager, event_loop: asyncio.AbstractEventLoop) -> SignalController:
    """Build and initialize the signal controller."""
    def on_update(signal_id: int, state: dict):
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast({"type": "signal_update", "state": state}),
            event_loop
        )

    ctrl = SignalController(on_update=on_update)
    signals_data = db.query_all("SELECT * FROM traffic_signals")
    for sig in signals_data:
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

async def signal_ticker(app: FastAPI):
    """Background task to tick the signal controller in real-time."""
    while True:
        await asyncio.sleep(1.0)
        if hasattr(app.state, "signal_controller") and app.state.signal_controller:
            app.state.signal_controller.tick(1.0)

async def retention_job():
    """Background task to delete old snapshots and non-seed events."""
    while True:
        try:
            retention_days = float(db.query_one("SELECT value FROM risk_config WHERE key='event_retention_days'")["value"])
            # Keep seed data
            db.execute(
                f"DELETE FROM events WHERE is_seed = 0 AND ts < datetime('now', '-{retention_days} days')"
            )
        except Exception as e:
            logger.error("Retention job failed: %s", e)
        # Run hourly
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Ensure DB exists
    db_path = Path(settings.db_path)
    if not db_path.exists():
        from db.init_db import init_db
        init_db()

    # Load initial config
    cam_id = int(db.query_one("SELECT value FROM system_settings WHERE key='active_camera_id'")["value"])
    mode = db.query_one("SELECT value FROM system_settings WHERE key='pipeline_mode'")["value"]
    
    # Initialize components
    event_loop = asyncio.get_running_loop()
    ws_manager = ConnectionManager()
    signal_controller = _build_signal_controller(ws_manager, event_loop)
    
    app.state.ws_manager = ws_manager
    app.state.signal_controller = signal_controller
    
    # Initialize pipeline
    def db_insert(**kwargs):
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        db.execute(f"INSERT INTO events ({cols}) VALUES ({placeholders})", tuple(kwargs.values()))
        
    pipeline = PipelineService(
        risk_config=_load_risk_config(),
        zones=_load_zones(cam_id),
        camera_fps=15.0, # Target FPS for pipeline processing
        pixels_per_meter=_load_risk_config().pixels_per_meter,
        broadcast_fn=ws_manager.broadcast,
        event_loop=event_loop,
        db_insert_fn=db_insert,
        signal_states_fn=signal_controller.get_all_states,
        camera_id=cam_id,
    )
    
    app.state.pipeline = pipeline
    
    camera = db.query_one("SELECT * FROM cameras WHERE id = ?", (cam_id,))
    source_uri = camera.get("source_uri") if camera else None
    
    # Start pipeline
    pipeline.start(mode=mode, source_uri=source_uri)
    
    # Start background tasks
    task_ticker = asyncio.create_task(signal_ticker(app))
    task_retention = asyncio.create_task(retention_job())

    yield
    
    # Shutdown
    task_ticker.cancel()
    task_retention.cancel()
    pipeline.stop()

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = FastAPI(title="CityPulse API", lifespan=lifespan)

# Include routers
app.include_router(core.router)
app.include_router(events.router)
app.include_router(ambulance.router)
app.include_router(signals.router)
app.include_router(scenarios.router)

# Mount video feed (from core router's generator)
@app.get("/video_feed")
async def video_feed(request: Request):
    return StreamingResponse(
        core.video_feed_generator(request),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# WebSocket
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    ws_manager: ConnectionManager = websocket.app.state.ws_manager
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# HTML Pages
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return Path("app/static/index.html").read_text(encoding="utf-8")

@app.get("/warning", response_class=HTMLResponse)
async def serve_warning():
    return Path("app/static/warning.html").read_text(encoding="utf-8")

@app.get("/phone", response_class=HTMLResponse)
async def serve_phone():
    return Path("app/static/phone.html").read_text(encoding="utf-8")
