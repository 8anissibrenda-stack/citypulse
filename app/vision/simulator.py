"""Synthetic junction simulator for CityPulse.

Renders a 1280×720 top-down junction with pedestrians, cyclists and vehicles.
Two modes:
  1. Scenario playback — deterministic actors from a test scenario's params_json.
  2. Continuous random traffic — spawns actors at realistic intervals.

Outputs TrackedObject instances (same interface as the YOLO detector) so the
risk engine works identically in both modes.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.vision.types import TrackedObject

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1280, 720
ROAD_Y1, ROAD_Y2 = 330, 490  # horizontal road band
CROSSING_X1, CROSSING_X2 = 560, 700  # zebra crossing
CROSSING_Y1, CROSSING_Y2 = 230, 590
JUNCTION_X1, JUNCTION_X2 = 520, 740
JUNCTION_Y1, JUNCTION_Y2 = 300, 520

# Class definitions matching the detection_classes table
CLASS_MAP: dict[str, dict] = {
    "person":     {"cls_id": 0, "label": "person",     "category": "vru",     "colour": (0, 152, 255),  "size": (20, 40)},
    "bicycle":    {"cls_id": 1, "label": "bicycle",    "category": "vru",     "colour": (0, 193, 255),  "size": (25, 35)},
    "car":        {"cls_id": 2, "label": "car",        "category": "vehicle", "colour": (255, 150, 33), "size": (55, 35)},
    "motorcycle": {"cls_id": 3, "label": "motorcycle", "category": "vehicle", "colour": (180, 39, 156), "size": (30, 25)},
    "bus":        {"cls_id": 5, "label": "bus",        "category": "vehicle", "colour": (75, 81, 63),   "size": (80, 40)},
    "truck":      {"cls_id": 7, "label": "truck",      "category": "vehicle", "colour": (139, 125, 96), "size": (70, 38)},
}

VEHICLE_CLASSES = ["car", "car", "car", "car", "motorcycle", "truck", "bus"]  # weighted
VRU_CLASSES = ["person", "person", "person", "person", "person", "person", "person", "bicycle", "bicycle", "bicycle"]


@dataclass
class _Actor:
    """An actor moving in the simulated scene."""
    track_id: int
    cls: str
    x: float
    y: float
    vx: float  # pixels per second
    vy: float
    alive: bool = True
    spawn_t: float = 0.0


class JunctionSimulator:
    """Top-down junction simulator that produces TrackedObject lists."""

    def __init__(
        self,
        fps: float = 15.0,
        pixels_per_meter: float = 25.0,
        seed: int | None = None,
    ) -> None:
        self.fps = fps
        self.ppm = pixels_per_meter
        self._rng = random.Random(seed)
        self._next_id = 1
        self._actors: list[_Actor] = []
        self._t: float = 0.0
        self._frame_count: int = 0

        # Continuous-mode spawn timers
        self._next_car_t: float = 0.0
        self._next_vru_t: float = 0.0
        self._next_cyclist_t: float = 0.0

        # Scenario mode
        self._scenario_actors: list[_Actor] | None = None
        self._scenario_duration: float = 0.0

        # Pre-render the background once
        self._bg = self._render_background()

    # ------------------------------------------------------------------
    # Scenario mode
    # ------------------------------------------------------------------

    def load_scenario(self, params_json: str) -> None:
        """Load a scenario from its JSON parameters.

        Expected format: ``{"duration_s": 10, "actors": [{"cls": "person", "start_px": [x,y], "velocity_mps": [vx,vy]}, ...]}``
        """
        params = json.loads(params_json) if isinstance(params_json, str) else params_json
        self._scenario_duration = params["duration_s"]
        self._scenario_actors = []
        self._actors.clear()
        self._t = 0.0
        self._frame_count = 0

        for actor_def in params["actors"]:
            cls = actor_def["cls"]
            sx, sy = actor_def["start_px"]
            vx_mps, vy_mps = actor_def["velocity_mps"]
            actor = _Actor(
                track_id=self._alloc_id(),
                cls=cls,
                x=float(sx),
                y=float(sy),
                vx=vx_mps * self.ppm,  # convert m/s to px/s
                vy=vy_mps * self.ppm,
                spawn_t=0.0,
            )
            self._scenario_actors.append(actor)
            self._actors.append(actor)

        logger.info("Loaded scenario with %d actors for %.1fs", len(self._actors), self._scenario_duration)

    def is_scenario_done(self) -> bool:
        """Return True if the scenario has run its full duration."""
        if self._scenario_actors is None:
            return False
        return self._t >= self._scenario_duration

    # ------------------------------------------------------------------
    # Frame generation
    # ------------------------------------------------------------------

    def step(self, dt: float | None = None) -> tuple[np.ndarray, list[TrackedObject]]:
        """Advance the simulation by one frame and return (frame, tracked_objects).

        Args:
            dt: Time step in seconds.  Defaults to 1/fps.

        Returns:
            A tuple of (rendered BGR frame, list of TrackedObject).
        """
        if dt is None:
            dt = 1.0 / self.fps
        self._t += dt
        self._frame_count += 1

        # Spawn new actors in continuous mode
        if self._scenario_actors is None:
            self._spawn_continuous()

        # Move all actors
        for actor in self._actors:
            actor.x += actor.vx * dt
            actor.y += actor.vy * dt
            # Remove off-screen actors
            if actor.x < -100 or actor.x > WIDTH + 100 or actor.y < -100 or actor.y > HEIGHT + 100:
                actor.alive = False

        self._actors = [a for a in self._actors if a.alive]

        # Build TrackedObjects with simulated noise
        objects: list[TrackedObject] = []
        for actor in self._actors:
            # 3% random dropout per frame
            if self._rng.random() < 0.03:
                continue

            info = CLASS_MAP[actor.cls]
            w, h = info["size"]
            # 1-2 px jitter
            jx = self._rng.uniform(-2, 2)
            jy = self._rng.uniform(-2, 2)
            cx = actor.x + jx
            cy = actor.y + jy
            x1 = cx - w / 2
            y1 = cy - h
            x2 = cx + w / 2
            y2 = cy

            objects.append(TrackedObject(
                track_id=actor.track_id,
                cls_id=info["cls_id"],
                label=info["label"],
                category=info["category"],
                bbox=(x1, y1, x2, y2),
                conf=round(self._rng.uniform(0.6, 0.95), 2),
                cx=cx,
                cy=cy,
                ts=self._t,
            ))

        # Render frame
        frame = self._render_frame(objects)

        return frame, objects

    # ------------------------------------------------------------------
    # Continuous-mode spawning
    # ------------------------------------------------------------------

    def _spawn_continuous(self) -> None:
        """Spawn random actors for continuous demonstration mode."""
        # Cars
        if self._t >= self._next_car_t:
            cls = self._rng.choice(VEHICLE_CLASSES)
            speed_mps = self._rng.uniform(6.0, 12.0)
            if self._rng.random() < 0.3:
                # From right
                x = WIDTH + 30
                vx = -speed_mps * self.ppm
            else:
                x = -30
                vx = speed_mps * self.ppm
            y = self._rng.uniform(ROAD_Y1 + 30, ROAD_Y2 - 30)
            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls=cls,
                x=x, y=y, vx=vx, vy=0, spawn_t=self._t,
            ))
            self._next_car_t = self._t + self._rng.uniform(3.0, 6.0)

        # Pedestrians
        if self._t >= self._next_vru_t:
            speed_mps = self._rng.uniform(1.2, 1.6)
            if self._rng.random() < 0.5:
                # From top
                y = CROSSING_Y1 - 10
                vy = speed_mps * self.ppm
            else:
                y = CROSSING_Y2 + 10
                vy = -speed_mps * self.ppm

            x = self._rng.uniform(CROSSING_X1 + 10, CROSSING_X2 - 10)

            # 1 in 6 intentionally enters when a car is near
            if self._rng.random() < 1 / 6:
                # Check for nearby car
                for a in self._actors:
                    if CLASS_MAP[a.cls]["category"] == "vehicle":
                        dist = abs(a.x - x) / self.ppm
                        if dist < 25:
                            break  # Intentionally spawn to create conflict

            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="person",
                x=x, y=y, vx=0, vy=vy, spawn_t=self._t,
            ))
            self._next_vru_t = self._t + self._rng.uniform(5.0, 9.0)

        # Cyclists
        if self._t >= self._next_cyclist_t:
            speed_mps = self._rng.uniform(3.5, 5.5)
            if self._rng.random() < 0.5:
                y = CROSSING_Y1 - 10
                vy = speed_mps * self.ppm
            else:
                y = CROSSING_Y2 + 10
                vy = -speed_mps * self.ppm
            x = self._rng.uniform(CROSSING_X1 + 10, CROSSING_X2 - 10)

            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="bicycle",
                x=x, y=y, vx=0, vy=vy, spawn_t=self._t,
            ))
            self._next_cyclist_t = self._t + self._rng.uniform(15.0, 25.0)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_background(self) -> np.ndarray:
        """Create the static background image."""
        bg = np.full((HEIGHT, WIDTH, 3), (60, 130, 60), dtype=np.uint8)  # grass

        # Road
        cv2.rectangle(bg, (0, ROAD_Y1), (WIDTH, ROAD_Y2), (80, 80, 80), -1)

        # Road edges
        cv2.line(bg, (0, ROAD_Y1), (WIDTH, ROAD_Y1), (200, 200, 200), 2)
        cv2.line(bg, (0, ROAD_Y2), (WIDTH, ROAD_Y2), (200, 200, 200), 2)

        # Centre line (dashed)
        mid_y = (ROAD_Y1 + ROAD_Y2) // 2
        for x in range(0, WIDTH, 40):
            cv2.line(bg, (x, mid_y), (x + 20, mid_y), (255, 255, 255), 1)

        # Zebra crossing stripes
        stripe_w = 8
        gap = 12
        x = CROSSING_X1
        while x < CROSSING_X2:
            cv2.rectangle(bg, (x, CROSSING_Y1), (x + stripe_w, CROSSING_Y2), (255, 255, 255), -1)
            x += stripe_w + gap

        # Junction box (faint outline)
        overlay = bg.copy()
        cv2.rectangle(overlay, (JUNCTION_X1, JUNCTION_Y1), (JUNCTION_X2, JUNCTION_Y2), (0, 200, 200), 2)
        cv2.addWeighted(overlay, 0.4, bg, 0.6, 0, bg)

        return bg

    def _render_frame(self, objects: list[TrackedObject]) -> np.ndarray:
        """Draw actors on the background."""
        frame = self._bg.copy()

        for obj in objects:
            info = CLASS_MAP.get(obj.label, CLASS_MAP["car"])
            colour = info["colour"]
            x1, y1, x2, y2 = int(obj.bbox[0]), int(obj.bbox[1]), int(obj.bbox[2]), int(obj.bbox[3])
            cv2.rectangle(frame, (x1, y1), (x2, y2), colour, -1)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 1)

        return frame

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _alloc_id(self) -> int:
        tid = self._next_id
        self._next_id += 1
        return tid

    @property
    def current_time(self) -> float:
        """Current simulation time in seconds."""
        return self._t
