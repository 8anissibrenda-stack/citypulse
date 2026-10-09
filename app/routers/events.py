"""Events API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import db
from app.services.metrics import get_live_metrics, get_hotspots

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def list_events(
    limit: int = Query(50, ge=1, le=500),
    event_type: str | None = None,
    include_seed: bool = True,
) -> list[dict[str, Any]]:
    """Return recent events with optional filtering."""
    conditions = []
    params: list = []

    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if not include_seed:
        conditions.append("is_seed = 0")

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM events {where} ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


@router.get("/events/{event_id}")
async def get_event(event_id: int) -> dict[str, Any]:
    """Return a single event by ID."""
    event = db.query_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if event is None:
        raise HTTPException(404, "Event not found")
    return event


@router.post("/events/{event_id}/ack")
async def acknowledge_event(event_id: int) -> dict:
    """Acknowledge an event."""
    event = db.query_one("SELECT id FROM events WHERE id = ?", (event_id,))
    if event is None:
        raise HTTPException(404, "Event not found")
    db.execute("UPDATE events SET acknowledged = 1 WHERE id = ?", (event_id,))
    return {"status": "acknowledged", "event_id": event_id}


@router.get("/hotspots")
async def hotspots() -> list[dict[str, Any]]:
    """Return hotspot data from the v_hotspots view."""
    return get_hotspots()


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    """Return aggregate metrics."""
    return get_live_metrics()
