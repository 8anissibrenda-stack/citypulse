"""Ambulance engine for CityPulse.

Provides geo-math utilities (haversine, bearing, route projection),
look-ahead signal selection, and simulated ambulance runs (baseline vs priority).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.signals.controller import Phase, SignalController

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Geo-math
# ---------------------------------------------------------------------------

_R_EARTH = 6_371_000  # Earth radius in metres


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in metres between two points."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return _R_EARTH * 2 * math.asin(math.sqrt(a))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the initial bearing in degrees from point 1 to point 2."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlon = rlon2 - rlon1
    x = math.sin(dlon) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def interpolate(lat1: float, lon1: float, lat2: float, lon2: float, frac: float) -> tuple[float, float]:
    """Linearly interpolate between two GPS points. ``frac`` in [0, 1]."""
    return lat1 + (lat2 - lat1) * frac, lon1 + (lon2 - lon1) * frac


def project_on_route(
    lat: float, lon: float, waypoints: list[tuple[float, float]]
) -> tuple[float, int]:
    """Project a GPS point onto a route polyline.

    Returns:
        (distance_along_route_m, nearest_segment_index)
    """
    best_dist = float("inf")
    best_along = 0.0
    cumulative = 0.0
    best_seg = 0

    for i in range(len(waypoints) - 1):
        a_lat, a_lon = waypoints[i]
        b_lat, b_lon = waypoints[i + 1]
        seg_len = haversine(a_lat, a_lon, b_lat, b_lon)

        # Project onto segment
        if seg_len < 0.01:
            t = 0.0
        else:
            # Use a simplified flat-earth projection for the fraction
            dx = (b_lon - a_lon) * math.cos(math.radians(a_lat))
            dy = b_lat - a_lat
            px = (lon - a_lon) * math.cos(math.radians(a_lat))
            py = lat - a_lat
            seg_sq = dx * dx + dy * dy
            t = max(0.0, min(1.0, (px * dx + py * dy) / seg_sq if seg_sq > 0 else 0.0))

        proj_lat, proj_lon = interpolate(a_lat, a_lon, b_lat, b_lon, t)
        dist = haversine(lat, lon, proj_lat, proj_lon)

        if dist < best_dist:
            best_dist = dist
            best_along = cumulative + seg_len * t
            best_seg = i

        cumulative += seg_len

    return best_along, best_seg


def route_total_distance(waypoints: list[tuple[float, float]]) -> float:
    """Return the total route distance in metres."""
    total = 0.0
    for i in range(len(waypoints) - 1):
        total += haversine(*waypoints[i], *waypoints[i + 1])
    return total


# ---------------------------------------------------------------------------
# Look-ahead
# ---------------------------------------------------------------------------

@dataclass
class SignalOnRoute:
    """A signal on the ambulance's route with its distance."""
    signal_id: int
    approach: str
    distance_m: float  # distance from ambulance to signal along route


def look_ahead(
    ambulance_along_m: float,
    route_waypoints: list[tuple[float, float]],
    route_signals: list[dict],  # [{signal_id, seq, approach, lat, lon}]
    trigger_distance_m: float = 250.0,
) -> list[SignalOnRoute]:
    """Find upcoming signals within trigger distance ahead of the ambulance.

    Args:
        ambulance_along_m: Ambulance position along route in metres.
        route_waypoints: Ordered route waypoints.
        route_signals: Signals on the route with their positions.
        trigger_distance_m: How far ahead to look.

    Returns:
        Signals ahead of the ambulance within the trigger distance,
        sorted by distance (nearest first).
    """
    results: list[SignalOnRoute] = []

    for rs in route_signals:
        sig_lat = rs.get("lat")
        sig_lon = rs.get("lon")
        if sig_lat is None or sig_lon is None:
            continue

        sig_along, _ = project_on_route(sig_lat, sig_lon, route_waypoints)
        dist_ahead = sig_along - ambulance_along_m

        if 0 < dist_ahead <= trigger_distance_m:
            results.append(SignalOnRoute(
                signal_id=rs["signal_id"],
                approach=rs["approach"],
                distance_m=dist_ahead,
            ))

    results.sort(key=lambda s: s.distance_m)
    return results


# ---------------------------------------------------------------------------
# Simulated ambulance run
# ---------------------------------------------------------------------------

def _build_local_controller(offsets: list[float]) -> SignalController:
    ctrl = SignalController()
    for i, sig_id in enumerate([1, 2, 3]):
        ctrl.add_signal(
            signal_id=sig_id,
            phases=[
                Phase(1, "North-South green", "NS", 25.0),
                Phase(2, "East-West green", "EW", 20.0),
            ],
            yellow_s=3.0,
            all_red_s=2.0,
            initial_offset_s=offsets[i],
        )
    return ctrl


def simulate_run(mode: str, offsets: list[float] = None) -> dict:
    """Simulate an ambulance run pixel-by-pixel for the UI."""
    if offsets is None:
        offsets = [0.0, 0.0, 0.0]
    ctrl = _build_local_controller(offsets)
    dt = 0.1
    y = 620.0
    clock_s = 0.0
    stops = 0
    wait_s = 0.0
    tick_idx = 0
    was_blocked = False
    released = set()
    ticks = []

    sig_y = [470, 320, 180]

    while True:
        # 1. advance the signal controllers by dt
        ctrl.tick(dt)

        # 2. (priority mode only) issue/hold/release pre-emption requests
        if mode == "priority":
            for i, sy in enumerate(sig_y):
                sig_id = i + 1
                dist = y - sy
                if -40 <= dist <= 400:
                    ctrl.request_priority(sig_id, "NS", dist / 60.0 if dist > 0 else 0)
                elif dist < -40 and sig_id not in released:
                    ctrl.release_priority(sig_id)
                    released.add(sig_id)

        # 3. decide whether the ambulance may move
        blocked = False
        for i, sy in enumerate(sig_y):
            dist = y - sy
            if 0 <= dist <= 3.0:
                if ctrl.get_colour(i + 1, "NS").value != "green":
                    blocked = True
                    break

        # 4. move the ambulance unless blocked
        if not blocked:
            y -= 60.0 * dt
        else:
            if not was_blocked:
                stops += 1
            wait_s += dt
        was_blocked = blocked
        clock_s += dt

        # 5. append ONE snapshot
        route_fraction = 1.0 - ((y - 125.0) / (620.0 - 125.0))
        signals = []
        priority_active = []
        for i in range(3):
            val = ctrl.get_colour(i + 1, "NS").value
            signals.append("amber" if val == "yellow" else val)
            priority_active.append(ctrl._signals[i + 1].preempt_active)

        done = (y <= 125.0)
        snapshot = {
            "i": tick_idx,
            "t": round(clock_s, 1),
            "y_px": round(y, 1),
            "route_fraction": round(max(0.0, min(1.0, route_fraction)), 3),
            "signals": signals,
            "priority_active": priority_active,
            "blocked": blocked,
            "stops": stops,
            "wait_s": round(wait_s, 1),
            "clock_s": round(clock_s, 1),
            "done": done
        }
        ticks.append(snapshot)

        if done:
            break
        tick_idx += 1

    # Assert rules
    for tick in ticks:
        if mode == "baseline":
            assert not any(tick["priority_active"]), "Baseline has pre-emption!"
        
        # ambulance is never past a signal's stop line while that signal's NS state is red or amber
        for i, sy in enumerate(sig_y):
            if (sy - 40) <= tick["y_px"] < sy:
                assert tick["signals"][i] == "green", f"Crossed signal {i+1} on red/amber!"

    return {
        "ticks": ticks,
        "summary": {
            "duration_s": round(clock_s, 1),
            "stops": stops,
            "wait_s": round(wait_s, 1)
        }
    }
