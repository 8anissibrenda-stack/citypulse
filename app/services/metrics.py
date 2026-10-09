"""Aggregate metrics from the CityPulse database."""

from __future__ import annotations

import logging
from typing import Any

from app import db

logger = logging.getLogger(__name__)


def get_live_metrics() -> dict[str, Any]:
    """Compute live metrics from non-seed events.

    Returns:
        Dict with total_events, warnings, criticals, near_misses,
        mean_latency_ms, p95_latency_ms, and ambulance_comparison.
    """
    # Live events only (is_seed = 0)
    live_counts = db.query_one(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN event_type='warning' THEN 1 ELSE 0 END) as warnings,
             SUM(CASE WHEN event_type='critical' THEN 1 ELSE 0 END) as criticals,
             SUM(CASE WHEN event_type='near_miss' THEN 1 ELSE 0 END) as near_misses
           FROM events WHERE is_seed = 0 AND date(ts) = date('now')"""
    ) or {}

    # Latency stats
    latency = db.query_one(
        """SELECT
             ROUND(AVG(latency_ms), 1) as mean_latency,
             ROUND(MAX(latency_ms), 1) as max_latency
           FROM events WHERE is_seed = 0 AND latency_ms IS NOT NULL"""
    ) or {}

    # P95 latency (approximate)
    p95_row = db.query_one(
        """SELECT latency_ms FROM events
           WHERE is_seed = 0 AND latency_ms IS NOT NULL
           ORDER BY latency_ms DESC
           LIMIT 1 OFFSET (
             SELECT CAST(COUNT(*) * 0.05 AS INTEGER)
             FROM events WHERE is_seed = 0 AND latency_ms IS NOT NULL
           )"""
    )
    p95 = p95_row["latency_ms"] if p95_row else 0

    # Seed event count
    seed_count = db.query_one("SELECT COUNT(*) as n FROM events WHERE is_seed = 1") or {}

    # Ambulance comparison
    comparison = db.query_all("SELECT * FROM v_ambulance_comparison")

    return {
        "total_events": live_counts.get("total") or 0,
        "warnings": live_counts.get("warnings") or 0,
        "criticals": live_counts.get("criticals") or 0,
        "near_misses": live_counts.get("near_misses") or 0,
        "false_alerts": 0,
        "mean_latency_ms": latency.get("mean_latency") or 0,
        "p95_latency_ms": p95 or 0,
        "seed_events": seed_count.get("n") or 0,
        "ambulance_comparison": comparison,
    }


def get_hotspots() -> list[dict[str, Any]]:
    """Return hotspot data from the v_hotspots view."""
    return db.query_all("SELECT * FROM v_hotspots")


def get_event_summary() -> list[dict[str, Any]]:
    """Return daily event summaries."""
    return db.query_all("SELECT * FROM v_event_summary ORDER BY day DESC LIMIT 30")
