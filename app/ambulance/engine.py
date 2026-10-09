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

@dataclass
class RunResult:
    """Result of a simulated ambulance run."""
    mode: str
    duration_s: float
    stops_count: int
    total_wait_s: float
    signal_log: list[dict]
    positions: list[dict]  # for live broadcast


def simulate_run(
    route_waypoints: list[tuple[float, float]],
    route_signals: list[dict],  # [{signal_id, seq, approach}]
    signal_controller: SignalController,
    mode: str = "baseline",
    cruise_kmh: float = 40.0,
    sim_speed: float = 10.0,
    trigger_distance_m: float = 250.0,
    on_position: callable = None,
) -> RunResult:
    """Simulate an ambulance run along a route.

    In baseline mode, the ambulance stops at red signals.
    In priority mode, the ambulance requests pre-emption and passes through.

    Args:
        route_waypoints: Ordered (lat, lon) waypoints.
        route_signals: Signal definitions on the route.
        signal_controller: The signal controller instance.
        mode: 'baseline' or 'priority'.
        cruise_kmh: Cruising speed.
        sim_speed: Simulation speed factor.
        trigger_distance_m: Distance to start looking ahead.
        on_position: Callback(lat, lon, speed, t) for live updates.

    Returns:
        RunResult with timing and signal interaction data.
    """
    total_dist = route_total_distance(route_waypoints)
    cruise_mps = cruise_kmh / 3.6
    dt = 0.1  # simulation step in real seconds

    # Compute signal positions along route
    # Map junction positions to signals
    signal_positions: dict[int, float] = {}  # signal_id -> distance along route
    for rs in route_signals:
        sig_id = rs["signal_id"]
        if "lat" in rs and "lon" in rs:
            along, _ = project_on_route(rs["lat"], rs["lon"], route_waypoints)
            signal_positions[sig_id] = along

    sim_t = 0.0
    position_m = 0.0  # distance along route
    speed = cruise_mps
    stops = 0
    total_wait = 0.0
    signal_log: list[dict] = []
    positions: list[dict] = []
    passed_signals: set[int] = set()
    waiting_at: int | None = None

    # Reset signal controller
    signal_controller.reset()

    while position_m < total_dist:
        sim_t += dt
        signal_controller.tick(dt)

        # Check signals ahead
        if mode == "priority":
            for rs in route_signals:
                sig_id = rs["signal_id"]
                if sig_id in passed_signals:
                    continue
                sig_pos = signal_positions.get(sig_id, 0)
                dist_ahead = sig_pos - position_m
                if 0 < dist_ahead <= trigger_distance_m:
                    eta = dist_ahead / max(speed, 0.1)
                    signal_controller.request_priority(sig_id, "NS", eta)

        # Check if at a red signal
        at_red = False
        for rs in route_signals:
            sig_id = rs["signal_id"]
            if sig_id in passed_signals:
                continue
            sig_pos = signal_positions.get(sig_id, 0)
            dist_to_signal = sig_pos - position_m

            if dist_to_signal <= 2.0 and dist_to_signal > -5.0:
                # At the signal
                colour = signal_controller.get_colour(sig_id, "NS")
                if mode == "baseline" and colour.value != "green":
                    at_red = True
                    if waiting_at != sig_id:
                        waiting_at = sig_id
                        phase_name = colour.value
                        signal_log.append({
                            "signal_id": sig_id,
                            "arrival_s": round(sim_t, 1),
                            "phase_on_arrival": phase_name,
                            "wait_s": 0,
                            "preempted": 0,
                        })
                        stops += 1
                    else:
                        # Still waiting
                        signal_log[-1]["wait_s"] = round(signal_log[-1]["wait_s"] + dt, 1)
                        total_wait += dt
                elif colour.value == "green":
                    if waiting_at == sig_id:
                        waiting_at = None
                    if sig_id not in passed_signals:
                        if mode == "priority":
                            signal_log.append({
                                "signal_id": sig_id,
                                "arrival_s": round(sim_t, 1),
                                "phase_on_arrival": "green",
                                "wait_s": 0,
                                "preempted": 1,
                            })
                        passed_signals.add(sig_id)
                        if mode == "priority":
                            signal_controller.release_priority(sig_id)
                    break
            elif dist_to_signal < -5.0 and sig_id not in passed_signals:
                passed_signals.add(sig_id)

        # Move
        if not at_red:
            speed = cruise_mps
            position_m += speed * dt
            waiting_at = None
        else:
            speed = 0

        # Position on the route for broadcast
        frac = min(position_m / total_dist, 1.0)
        # Simple linear interpolation along waypoints
        cum = 0.0
        lat, lon = route_waypoints[0]
        for i in range(len(route_waypoints) - 1):
            seg = haversine(*route_waypoints[i], *route_waypoints[i + 1])
            if cum + seg >= position_m:
                seg_frac = (position_m - cum) / seg if seg > 0 else 0
                lat, lon = interpolate(*route_waypoints[i], *route_waypoints[i + 1], seg_frac)
                break
            cum += seg
        else:
            lat, lon = route_waypoints[-1]

        signals_state = {}
        priority_state = {}
        for sig_id in signal_controller._signals:
            key = f"S{4 - sig_id}"
            st = signal_controller.get_state(sig_id)
            signals_state[key] = st["ns_colour"]
            priority_state[key] = st["preempt_active"] and st["preempt_approach"] == "NS"

        pos_entry = {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "speed_kmh": round(speed * 3.6, 1),
            "t": round(sim_t, 1),
            "route_distance_m": position_m,
            "signals": signals_state,
            "priority_active": priority_state,
        }
        positions.append(pos_entry)

        if on_position:
            on_position(lat, lon, speed * 3.6, sim_t)

    return RunResult(
        mode=mode,
        duration_s=round(sim_t, 1),
        stops_count=stops,
        total_wait_s=round(total_wait, 1),
        signal_log=signal_log,
        positions=positions,
    )
