"""Pydantic v2 models for CityPulse API requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class PipelineStartRequest(BaseModel):
    """Start the vision pipeline."""
    camera_id: int = 1
    mode: str = "simulator"


class GPSUpdate(BaseModel):
    """Ambulance GPS update from the phone page."""
    ambulance_id: int = 1
    lat: float
    lon: float
    speed_kmh: float = 0.0
    heading_deg: float = 0.0
    emergency: bool = False


class SimulateRequest(BaseModel):
    """Request to simulate an ambulance run."""
    route_id: int = 1
    mode: str = "baseline"
    sim_speed: float = 10.0


class RiskConfigUpdate(BaseModel):
    """Update risk configuration values."""
    values: dict[str, float]


class ScenarioRunRequest(BaseModel):
    """Run a specific scenario."""
    pass


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "1.0.0"
    db_ok: bool = True


class EventResponse(BaseModel):
    """An event record."""
    id: int
    camera_id: int
    ts: str
    event_type: str
    severity: int
    ttc_s: float | None = None
    min_distance_m: float | None = None
    vru_class: str
    vehicle_class: str
    vru_track_id: int | None = None
    vehicle_track_id: int | None = None
    confidence: float | None = None
    zone_name: str | None = None
    latency_ms: float | None = None
    acknowledged: int = 0
    is_seed: int = 0
    details_json: str | None = None


class MetricsResponse(BaseModel):
    """Aggregate metrics."""
    total_events: int = 0
    warnings: int = 0
    criticals: int = 0
    near_misses: int = 0
    false_alerts: int = 0
    mean_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    ambulance_comparison: list[dict[str, Any]] = []
    seed_events: int = 0


class AmbulanceRunResponse(BaseModel):
    """Result of a simulated ambulance run."""
    run_id: int
    mode: str
    duration_s: float
    stops_count: int
    total_wait_s: float
    signal_log: list[dict[str, Any]] = []


class ComparisonResponse(BaseModel):
    """Comparison of baseline vs priority runs."""
    baseline: dict[str, Any]
    priority: dict[str, Any]
    time_saved_pct: float
    runs: list[dict[str, Any]] = []
