"""Data types for the vision pipeline."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TrackedObject:
    """A single detected and tracked object in a video frame.

    Attributes:
        track_id: Persistent tracker ID across frames.
        cls_id: COCO class ID.
        label: Human-readable class label (e.g. 'person', 'car').
        category: High-level category — 'vru' (vulnerable road user) or 'vehicle'.
        bbox: Bounding box as (x1, y1, x2, y2) in pixels.
        conf: Detection confidence in [0, 1].
        cx: Bottom-centre x coordinate (ground-contact point).
        cy: Bottom-centre y coordinate (ground-contact point).
        ts: Monotonic timestamp in seconds since pipeline start.
    """

    track_id: int
    cls_id: int
    label: str
    category: Literal["vru", "vehicle"]
    bbox: tuple[float, float, float, float]
    conf: float
    cx: float
    cy: float
    ts: float
    vx: float = 0.0
    vy: float = 0.0


@dataclass
class RiskAlert:
    """An alert emitted by the risk engine for a VRU-vehicle conflict.

    Attributes:
        event_type: 'warning', 'critical', or 'near_miss'.
        severity: 1 (low warning), 2 (warning), or 3 (critical / near-miss).
        ttc_s: Time-to-collision in seconds.
        min_distance_m: Predicted closest approach distance in metres.
        risk_score: Composite risk score 0–100.
        vru: The VRU TrackedObject.
        vehicle: The vehicle TrackedObject.
        zone_name: Name of the conflict zone the VRU is in, or None.
        latency_ms: Processing latency from frame capture to alert emission.
    """

    event_type: str
    severity: int
    ttc_s: float
    min_distance_m: float
    risk_score: float
    vru: TrackedObject
    vehicle: TrackedObject
    zone_name: str | None = None
    latency_ms: float = 0.0


@dataclass
class ConflictZone:
    """A polygonal conflict zone on the camera view.

    Attributes:
        id: Database ID.
        camera_id: Which camera this zone belongs to.
        name: Human-readable name (e.g. 'Zebra crossing').
        zone_type: 'crossing', 'junction_box', or 'vehicle_lane'.
        polygon: List of (x, y) vertex coordinates in pixels.
    """

    id: int
    camera_id: int
    name: str
    zone_type: str
    polygon: list[tuple[int, int]] = field(default_factory=list)
