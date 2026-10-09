"""Synthetic junction simulator for CityPulse.

Renders a 1280×720 top-down junction with pedestrians, cyclists and vehicles.
Two modes:
  1. Scenario playback — deterministic actors from a test scenario's params_json.
  2. Continuous looping demo — ONE car and ONE pedestrian.

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

from app.vision.types import TrackedObject, RiskAlert

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

CLASS_MAP: dict[str, dict] = {
    "person":     {"cls_id": 0, "label": "person",     "category": "vru",     "colour": (0, 152, 255),  "size": (20, 40)},
    "bicycle":    {"cls_id": 1, "label": "bicycle",    "category": "vru",     "colour": (0, 193, 255),  "size": (25, 35)},
    "car":        {"cls_id": 2, "label": "car",        "category": "vehicle", "colour": (255, 150, 33), "size": (55, 35)},
    "motorcycle": {"cls_id": 3, "label": "motorcycle", "category": "vehicle", "colour": (180, 39, 156), "size": (30, 25)},
    "bus":        {"cls_id": 5, "label": "bus",        "category": "vehicle", "colour": (75, 81, 63),   "size": (80, 40)},
    "truck":      {"cls_id": 7, "label": "truck",      "category": "vehicle", "colour": (139, 125, 96), "size": (70, 38)},
}

@dataclass
class _Actor:
    track_id: int
    cls: str
    x: float
    y: float
    vx: float
    vy: float
    alive: bool = True
    state: str = "cruise"
    reaction_timer: float = 0.0

class JunctionSimulator:
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
        self._scenario_actors: list[_Actor] | None = None
        self._scenario_duration: float = 0.0
        self._active_alerts: list[RiskAlert] = []
        
        # Continuous mode state
        self._loop_t: float = 0.0
        self._car: _Actor | None = None
        self._ped: _Actor | None = None
        self._car_braking = False

        self._bg = self._render_background()

    def set_active_alerts(self, alerts: list[RiskAlert]) -> None:
        self._active_alerts = alerts

    def load_scenario(self, params_json: str) -> None:
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
                track_id=self._alloc_id(), cls=cls, x=float(sx), y=float(sy),
                vx=vx_mps * self.ppm, vy=vy_mps * self.ppm
            )
            self._scenario_actors.append(actor)
            self._actors.append(actor)

    def is_scenario_done(self) -> bool:
        if self._scenario_actors is None:
            return False
        return self._t >= self._scenario_duration

    def _reset_demo_loop(self):
        self._actors.clear()
        self._car = _Actor(track_id=self._alloc_id(), cls="car", x=-50, y=450, vx=150, vy=0)
        self._ped = _Actor(track_id=self._alloc_id(), cls="person", x=630, y=300, vx=0, vy=35)
        self._actors.extend([self._car, self._ped])
        self._loop_t = 0.0
        self._car_braking = False

    def step(self, dt: float | None = None) -> tuple[np.ndarray, list[TrackedObject]]:
        if dt is None:
            dt = 1.0 / self.fps
        self._t += dt
        self._frame_count += 1

        if self._scenario_actors is None:
            if not self._actors or self._loop_t > 14.5:
                self._reset_demo_loop()
            
            self._loop_t += dt
            
            if self._car and self._ped:
                # Driver model
                has_alert = any(a.vehicle.track_id == self._car.track_id for a in self._active_alerts)
                
                if has_alert and not self._car_braking:
                    self._car.reaction_timer += dt
                    if self._car.reaction_timer >= 0.8:
                        self._car_braking = True
                        
                if self._car_braking:
                    # Brake at 4 m/s^2 (100 px/s^2)
                    if self._car.vx > 0:
                        self._car.vx = max(0.0, self._car.vx - 100.0 * dt)
                
                # Pedestrian passed y>=520 and car has stopped
                if self._ped.y >= 520 and self._car.vx <= 0.1:
                    self._car_braking = False
                    self._car.state = "accelerating"
                    
                if self._car.state == "accelerating" and not self._car_braking:
                    # Accelerate at 3.2 m/s^2 (80 px/s^2) to 150 px/s
                    self._car.vx = min(150.0, self._car.vx + 80.0 * dt)
                
                # Move
                self._car.x += self._car.vx * dt
                self._ped.y += self._ped.vy * dt
        else:
            for actor in self._actors:
                actor.x += actor.vx * dt
                actor.y += actor.vy * dt

        objects: list[TrackedObject] = []
        for actor in self._actors:
            info = CLASS_MAP[actor.cls]
            w, h = info["size"]
            x1, y1 = actor.x - w / 2, actor.y - h
            x2, y2 = actor.x + w / 2, actor.y
            objects.append(TrackedObject(
                track_id=actor.track_id, cls_id=info["cls_id"], label=info["label"], category=info["category"],
                bbox=(x1, y1, x2, y2), conf=1.0, cx=actor.x, cy=actor.y, ts=self._t, vx=actor.vx, vy=actor.vy
            ))

        frame = self._render_frame(objects)
        return frame, objects

    def _render_background(self) -> np.ndarray:
        bg = np.full((HEIGHT, WIDTH, 3), (38, 52, 36), dtype=np.uint8)  # grass 
        # But wait! We don't render to MJPEG for simulator anymore! Only for video.
        # But for video mode, the background doesn't matter. For scenario headless testing, it doesn't matter.
        return bg

    def _render_frame(self, objects: list[TrackedObject]) -> np.ndarray:
        return self._bg

    def _alloc_id(self) -> int:
        tid = self._next_id
        self._next_id += 1
        return tid

    @property
    def current_time(self) -> float:
        return self._t
