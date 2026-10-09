"""Risk analysis engine for CityPulse.

Pure computation — no I/O, no database access.  Receives tracked objects and
configuration, returns alerts.  Fully unit-testable and deterministic.

Risk-score formula (documented here and in-line):
    score = (1 - ttc / horizon) * 40        # urgency component
          + (vehicle_speed / 15) * 25        # speed component (15 m/s ≈ 54 km/h cap)
          + risk_weight * 20                 # class vulnerability component
          + confidence * 15                  # detection reliability component
    Clamped to [0, 100].
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from app.vision.types import ConflictZone, RiskAlert, TrackedObject

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (loaded from risk_config table at startup)
# ---------------------------------------------------------------------------

@dataclass
class RiskConfig:
    """All tuneable risk-engine parameters."""

    ttc_warning_s: float = 3.0
    ttc_critical_s: float = 1.5
    prediction_horizon_s: float = 5.0
    collision_radius_m: float = 1.5
    min_confidence: float = 0.45
    min_consecutive_frames: int = 3
    alert_cooldown_s: float = 4.0
    near_miss_ttc_s: float = 1.0
    near_miss_distance_m: float = 1.2
    min_vehicle_speed_mps: float = 1.5
    velocity_smoothing_alpha: float = 0.4
    vru_stationary_speed_mps: float = 0.3
    pixels_per_meter: float = 25.0


# ---------------------------------------------------------------------------
# Internal bookkeeping
# ---------------------------------------------------------------------------

@dataclass
class _TrackHistory:
    """Position history for a single track."""
    positions: list[tuple[float, float, float]] = field(default_factory=list)  # (cx, cy, ts)
    vx: float = 0.0  # smoothed velocity x (m/s)
    vy: float = 0.0  # smoothed velocity y (m/s)
    speed: float = 0.0  # |v| (m/s)


@dataclass
class _ConflictState:
    """State for debouncing a VRU-vehicle pair conflict."""
    consecutive_frames: int = 0
    missed_frames: int = 0
    alerted: bool = False
    last_alert_ts: float = 0.0
    last_alert_severity: int = 0
    min_ttc: float = float("inf")
    min_distance: float = float("inf")
    active: bool = True  # still in conflict this frame?


def _point_in_polygon(px: float, py: float, polygon: list[tuple[int, int]]) -> bool:
    """Ray-casting point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class RiskEngine:
    """Stateful per-frame risk analyser.

    Call ``update(objects, ts)`` each frame.  It returns a list of new alerts
    (warnings, criticals, near-misses) that should be broadcast / stored.
    """

    def __init__(self, config: RiskConfig, zones: list[ConflictZone] | None = None) -> None:
        self.cfg = config
        self.zones: list[ConflictZone] = zones or []
        self._tracks: dict[int, _TrackHistory] = defaultdict(lambda: _TrackHistory())
        self._conflicts: dict[tuple[int, int], _ConflictState] = {}  # (vru_id, veh_id)
        self._last_ts: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, objects: Sequence[TrackedObject], ts: float) -> list[RiskAlert]:
        """Process one frame of tracked objects and return new alerts.

        Args:
            objects: All tracked objects visible this frame.
            ts: Monotonic timestamp of this frame in seconds.

        Returns:
            A list of RiskAlert instances emitted this frame (may be empty).
        """
        self._last_ts = ts

        # 1. Update track histories & velocities
        for obj in objects:
            self._update_track(obj)

        # 2. Partition into VRUs and vehicles
        vrus = [o for o in objects if o.category == "vru" and o.conf >= self.cfg.min_confidence]
        vehicles = [o for o in objects if o.category == "vehicle" and o.conf >= self.cfg.min_confidence]

        # 3. Mark all conflict pairs as inactive; we'll reactivate those still in conflict
        for state in self._conflicts.values():
            state.active = False

        # 4. Check every VRU-vehicle pair
        alerts: list[RiskAlert] = []
        for vru in vrus:
            for veh in vehicles:
                alert = self._check_pair(vru, veh, ts)
                if alert is not None:
                    alerts.append(alert)

        # 5. Detect near-misses for pairs that have separated
        near_misses = self._detect_near_misses(ts)
        alerts.extend(near_misses)

        # 6. Clean up old conflicts
        self._cleanup_conflicts(ts)

        return alerts

    def reset(self) -> None:
        """Clear all state (e.g. when switching scenarios)."""
        self._tracks.clear()
        self._conflicts.clear()
        self._last_ts = 0.0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _update_track(self, obj: TrackedObject) -> None:
        """Add a position sample and update smoothed velocity for a track."""
        hist = self._tracks[obj.track_id]
        hist.positions.append((obj.cx, obj.cy, obj.ts))
        # Keep last 10 positions
        if len(hist.positions) > 10:
            hist.positions = hist.positions[-10:]

        if len(hist.positions) >= 2:
            (x0, y0, t0) = hist.positions[-2]
            (x1, y1, t1) = hist.positions[-1]
            dt = t1 - t0
            if dt > 0:
                ppm = self.cfg.pixels_per_meter
                raw_vx = (x1 - x0) / dt / ppm
                raw_vy = (y1 - y0) / dt / ppm
                alpha = self.cfg.velocity_smoothing_alpha
                hist.vx = alpha * raw_vx + (1 - alpha) * hist.vx
                hist.vy = alpha * raw_vy + (1 - alpha) * hist.vy
                hist.speed = math.hypot(hist.vx, hist.vy)

    def _has_velocity(self, track_id: int) -> bool:
        """Return True if we have enough samples for a reliable velocity."""
        return len(self._tracks[track_id].positions) >= 3

    def _get_zone(self, obj: TrackedObject) -> str | None:
        """Return the name of the conflict zone containing the object, or None."""
        for zone in self.zones:
            if _point_in_polygon(obj.cx, obj.cy, zone.polygon):
                return zone.name
        return None

    def _is_in_crossing(self, obj: TrackedObject) -> bool:
        """Return True if the object is inside any crossing zone."""
        for zone in self.zones:
            if zone.zone_type == "crossing" and _point_in_polygon(obj.cx, obj.cy, zone.polygon):
                return True
        return False

    def _vehicle_heading_toward_zone(self, veh: TrackedObject, zone: ConflictZone) -> bool:
        """Check if the vehicle's velocity vector points toward the zone centre."""
        h = self._tracks[veh.track_id]
        if h.speed < 0.1:
            return False
        # Zone centre
        zx = sum(p[0] for p in zone.polygon) / len(zone.polygon)
        zy = sum(p[1] for p in zone.polygon) / len(zone.polygon)
        # Direction to zone
        dx = (zx - veh.cx) / self.cfg.pixels_per_meter
        dy = (zy - veh.cy) / self.cfg.pixels_per_meter
        dist = math.hypot(dx, dy)
        if dist < 0.01:
            return True
        # Dot product of velocity and direction to zone
        dot = h.vx * dx + h.vy * dy
        return dot > 0

    def _check_pair(self, vru: TrackedObject, veh: TrackedObject, ts: float) -> RiskAlert | None:
        """Evaluate one VRU-vehicle pair for conflict. Returns an alert or None."""
        veh_hist = self._tracks[veh.track_id]
        vru_hist = self._tracks[vru.track_id]

        # Need velocity estimates
        if not self._has_velocity(vru.track_id) or not self._has_velocity(veh.track_id):
            return None

        # Ignore stopped/queued vehicles
        if veh_hist.speed < self.cfg.min_vehicle_speed_mps:
            return None

        # --- CPA / TTC computation ---
        ppm = self.cfg.pixels_per_meter
        # Positions in metres
        rx = (vru.cx - veh.cx) / ppm
        ry = (vru.cy - veh.cy) / ppm
        # Relative velocity in m/s
        dvx = vru_hist.vx - veh_hist.vx
        dvy = vru_hist.vy - veh_hist.vy
        v_dot_v = dvx * dvx + dvy * dvy

        t_cpa: float | None = None
        d_cpa: float = float("inf")

        if v_dot_v > 1e-6:
            r_dot_v = rx * dvx + ry * dvy
            t_cpa = -r_dot_v / v_dot_v
            if 0 < t_cpa <= self.cfg.prediction_horizon_s:
                cpx = rx + dvx * t_cpa
                cpy = ry + dvy * t_cpa
                d_cpa = math.hypot(cpx, cpy)
            else:
                t_cpa = None  # outside prediction horizon

        # --- Zone-based conflict check ---
        zone_conflict = False
        if t_cpa is None and self._is_in_crossing(vru):
            for zone in self.zones:
                if zone.zone_type == "crossing" and self._vehicle_heading_toward_zone(veh, zone):
                    # Estimate time for vehicle to reach crossing centre
                    zx = sum(p[0] for p in zone.polygon) / len(zone.polygon)
                    zy = sum(p[1] for p in zone.polygon) / len(zone.polygon)
                    dist_to_zone = math.hypot(
                        (zx - veh.cx) / ppm, (zy - veh.cy) / ppm
                    )
                    if veh_hist.speed > 0.1:
                        est_t = dist_to_zone / veh_hist.speed
                        if est_t <= self.cfg.prediction_horizon_s:
                            t_cpa = est_t
                            d_cpa = 0.5  # Assume close if VRU is in the crossing
                            zone_conflict = True
                    break

        # No conflict detected
        if t_cpa is None or d_cpa > self.cfg.collision_radius_m:
            pair_key = (vru.track_id, veh.track_id)
            if pair_key in self._conflicts:
                state = self._conflicts[pair_key]
                if state.alerted and self._is_in_crossing(vru):
                    state.active = True
                    return RiskAlert(
                        event_type="critical" if state.last_alert_severity == 3 else "warning",
                        severity=state.last_alert_severity,
                        ttc_s=round(state.min_ttc, 2),
                        min_distance_m=round(state.min_distance, 2),
                        risk_score=50.0,
                        vru=vru,
                        vehicle=veh,
                        zone_name=self._get_zone(vru),
                    )
            return None

        # --- Determine severity level ---
        ttc = t_cpa
        if ttc <= self.cfg.ttc_critical_s:
            event_type = "critical"
            severity = 3
        elif ttc <= self.cfg.ttc_warning_s:
            event_type = "warning"
            severity = 2
        else:
            # Within prediction horizon but TTC too large for an alert
            # Still track for near-miss detection
            pair_key = (vru.track_id, veh.track_id)
            state = self._conflicts.setdefault(pair_key, _ConflictState())
            state.active = True
            state.min_ttc = min(state.min_ttc, ttc)
            state.min_distance = min(state.min_distance, d_cpa)
            return None

        # --- Risk score ---
        risk_score = self._compute_risk_score(ttc, veh_hist.speed, veh, vru)

        # --- Debouncing ---
        pair_key = (vru.track_id, veh.track_id)
        state = self._conflicts.setdefault(pair_key, _ConflictState())
        state.active = True
        state.min_ttc = min(state.min_ttc, ttc)
        state.min_distance = min(state.min_distance, d_cpa)
        state.missed_frames = 0
        state.consecutive_frames += 1

        if state.consecutive_frames < self.cfg.min_consecutive_frames:
            return None

        # --- Cooldown ---
        if state.alerted:
            time_since_last = ts - state.last_alert_ts
            if time_since_last < self.cfg.alert_cooldown_s and severity <= state.last_alert_severity:
                return None

        # Emit alert
        state.alerted = True
        state.last_alert_ts = ts
        state.last_alert_severity = severity

        zone_name = self._get_zone(vru)

        return RiskAlert(
            event_type=event_type,
            severity=severity,
            ttc_s=round(ttc, 2),
            min_distance_m=round(d_cpa, 2),
            risk_score=round(risk_score, 1),
            vru=vru,
            vehicle=veh,
            zone_name=zone_name,
        )

    def _compute_risk_score(
        self, ttc: float, vehicle_speed: float, veh: TrackedObject, vru: TrackedObject
    ) -> float:
        """Compute composite risk score 0–100.

        Formula:
            score = (1 - ttc / horizon) * 40    # urgency
                  + (speed / 15) * 25            # speed (cap at 15 m/s ≈ 54 km/h)
                  + risk_weight * 20             # vulnerability
                  + confidence * 15              # detection reliability
        """
        urgency = max(0.0, 1.0 - ttc / self.cfg.prediction_horizon_s) * 40
        speed_component = min(vehicle_speed / 15.0, 1.0) * 25
        # Use VRU risk_weight (always 1.0 for VRUs, but we keep it generic)
        risk_weight = 1.0  # VRU weight
        weight_component = risk_weight * 20
        confidence = min(vru.conf, veh.conf)
        conf_component = confidence * 15
        return min(100.0, urgency + speed_component + weight_component + conf_component)

    def _detect_near_misses(self, ts: float) -> list[RiskAlert]:
        """Check for pairs that have separated and qualify as near-misses."""
        alerts: list[RiskAlert] = []
        to_remove: list[tuple[int, int]] = []

        for pair_key, state in self._conflicts.items():
            if state.active:
                continue  # Still in conflict
            # Pair separated — check if it was a near-miss
            state.missed_frames += 1
            if state.missed_frames <= 1:
                continue  # Tolerate 1 missed frame

            if state.alerted:
                # Already alerted — check for near-miss only if it was just a warning
                # and conditions are met
                pass

            is_near_miss = (
                state.min_ttc < self.cfg.near_miss_ttc_s
                or state.min_distance < self.cfg.near_miss_distance_m
            )

            if is_near_miss and state.consecutive_frames >= self.cfg.min_consecutive_frames:
                vru_id, veh_id = pair_key
                # We need the TrackedObjects — use last known from tracks
                vru_hist = self._tracks.get(vru_id)
                veh_hist = self._tracks.get(veh_id)
                if vru_hist and veh_hist and vru_hist.positions and veh_hist.positions:
                    # Create minimal TrackedObjects for the alert
                    vru_pos = vru_hist.positions[-1]
                    veh_pos = veh_hist.positions[-1]
                    # We don't have the full TrackedObject, so create a near-miss event
                    # with the pair_key info. The pipeline will fill in details.
                    alerts.append(RiskAlert(
                        event_type="near_miss",
                        severity=3,
                        ttc_s=round(state.min_ttc, 2),
                        min_distance_m=round(state.min_distance, 2),
                        risk_score=90.0,
                        vru=TrackedObject(
                            track_id=vru_id, cls_id=0, label="person", category="vru",
                            bbox=(0, 0, 0, 0), conf=0.8,
                            cx=vru_pos[0], cy=vru_pos[1], ts=vru_pos[2],
                        ),
                        vehicle=TrackedObject(
                            track_id=veh_id, cls_id=2, label="car", category="vehicle",
                            bbox=(0, 0, 0, 0), conf=0.8,
                            cx=veh_pos[0], cy=veh_pos[1], ts=veh_pos[2],
                        ),
                        zone_name=None,
                    ))

            to_remove.append(pair_key)

        for key in to_remove:
            del self._conflicts[key]

        return alerts

    def _cleanup_conflicts(self, ts: float) -> None:
        """Remove stale conflict entries that are long-inactive."""
        stale = [
            key for key, state in self._conflicts.items()
            if not state.active and state.missed_frames > 5
        ]
        for key in stale:
            del self._conflicts[key]

    # ------------------------------------------------------------------
    # Utility for the pipeline to store the latest objects per frame
    # ------------------------------------------------------------------

    _last_objects: list[TrackedObject] = []

    def set_last_objects(self, objects: list[TrackedObject]) -> None:
        """Store the latest frame's objects for reference by near-miss detection."""
        self._last_objects = list(objects)
