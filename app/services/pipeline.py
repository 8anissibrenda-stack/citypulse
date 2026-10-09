"""Vision pipeline service for CityPulse.

Runs in a background thread:
  frame → detection/tracking → risk analysis → render → event storage → WebSocket broadcast.

The pipeline supports two input modes:
  - ``simulator``: built-in synthetic junction (always available).
  - ``video``: real video file or webcam via YOLO + ByteTrack.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from app.vision.types import ConflictZone, RiskAlert, TrackedObject
from app.vision.simulator import JunctionSimulator
from app.vision.render import FrameRenderer
from app.risk.engine import RiskConfig, RiskEngine

logger = logging.getLogger(__name__)


class PipelineService:
    """Background vision-processing loop.

    Attributes:
        running: Whether the pipeline is currently active.
        mode: Current input mode ('simulator' or 'video').
        fps: Measured frames per second.
        latency_ms: Latest processing latency in milliseconds.
        active_alerts: Currently active risk alerts.
    """

    def __init__(
        self,
        risk_config: RiskConfig,
        zones: list[ConflictZone],
        camera_fps: float = 15.0,
        pixels_per_meter: float = 25.0,
        broadcast_fn: callable = None,
        event_loop: asyncio.AbstractEventLoop | None = None,
        db_insert_fn: callable = None,
        signal_states_fn: callable = None,
        camera_id: int = 1,
    ) -> None:
        self.risk_config = risk_config
        self.zones = zones
        self.camera_fps = camera_fps
        self.pixels_per_meter = pixels_per_meter
        self._broadcast_fn = broadcast_fn
        self._event_loop = event_loop
        self._db_insert_fn = db_insert_fn
        self._signal_states_fn = signal_states_fn
        self.camera_id = camera_id

        self.running = False
        self.mode = "simulator"
        self.fps: float = 0.0
        self.latency_ms: float = 0.0
        self.active_alerts: list[RiskAlert] = []
        self._last_alert_time: float = 0.0

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._latest_frame: bytes | None = None  # JPEG bytes
        self._frame_lock = threading.Lock()

        self._risk_engine = RiskEngine(risk_config, zones)
        self._renderer = FrameRenderer(zones)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def start(self, mode: str = "simulator", source_uri: str | None = None) -> None:
        """Start the pipeline in the given mode.

        Args:
            mode: 'simulator' or 'video'.
            source_uri: Video file path / webcam index / RTSP URL (for video mode).
        """
        if self.running:
            self.stop()

        self.mode = mode
        self._stop_event.clear()
        self._risk_engine.reset()

        self._thread = threading.Thread(
            target=self._run_loop,
            args=(mode, source_uri),
            name="pipeline",
            daemon=True,
        )
        self._thread.start()
        self.running = True
        logger.info("Pipeline started in %s mode", mode)

    def stop(self) -> None:
        """Stop the pipeline cleanly."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self.running = False
        self.active_alerts.clear()
        logger.info("Pipeline stopped")

    def get_latest_frame(self) -> bytes | None:
        """Return the latest JPEG-encoded annotated frame."""
        with self._frame_lock:
            return self._latest_frame

    def update_risk_config(self, config: RiskConfig) -> None:
        """Hot-update risk configuration without restart."""
        self.risk_config = config
        self._risk_engine.cfg = config
        logger.info("Risk config updated")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run_loop(self, mode: str, source_uri: str | None) -> None:
        """Main pipeline loop running in a background thread."""
        simulator: JunctionSimulator | None = None
        detector = None
        video_source = None

        if mode == "simulator":
            simulator = JunctionSimulator(fps=self.camera_fps, pixels_per_meter=self.pixels_per_meter)
        elif mode == "video":
            try:
                from app.vision.detector_yolo import YOLODetector, VideoSource
                detector = YOLODetector(min_confidence=self.risk_config.min_confidence)
                source = source_uri or 0
                if isinstance(source, str) and source.isdigit():
                    source = int(source)
                video_source = VideoSource(source)
            except Exception as exc:
                logger.error("Failed to start video mode: %s", exc)
                self.running = False
                return

        frame_interval = 1.0 / self.camera_fps
        frame_count = 0
        fps_timer = time.monotonic()

        while not self._stop_event.is_set():
            loop_start = time.monotonic()

            # --- Get frame and objects ---
            frame: np.ndarray | None = None
            objects: list[TrackedObject] = []

            if mode == "simulator" and simulator is not None:
                frame, objects = simulator.step()
            elif mode == "video" and detector is not None and video_source is not None:
                raw_frame = video_source.read()
                if raw_frame is None:
                    logger.warning("Video source returned no frame, retrying...")
                    time.sleep(0.1)
                    continue
                frame = raw_frame
                objects = detector.detect(frame)

            if frame is None:
                time.sleep(0.01)
                continue

            # --- Risk analysis ---
            ts = time.monotonic()
            alerts = self._risk_engine.update(objects, simulator.current_time if simulator else ts)

            processing_time = (time.monotonic() - loop_start) * 1000
            self.latency_ms = round(processing_time, 1)

            # Set latency on alerts
            for alert in alerts:
                alert.latency_ms = self.latency_ms

            # Update active alerts
            if alerts:
                self.active_alerts = alerts
                self._last_alert_time = time.monotonic()
            elif time.monotonic() - self._last_alert_time > 3.0:
                # Auto-clear after 3 seconds
                if self.active_alerts:
                    self.active_alerts = []
                    self._broadcast("alert_clear", {"message": "All clear"})

            # --- Render annotated frame ---
            signal_states = self._signal_states_fn() if self._signal_states_fn else None
            annotated = self._renderer.render(
                frame, objects, self.active_alerts,
                fps=self.fps, mode=self.mode,
                active_alert_count=len(self.active_alerts),
                signal_states=signal_states,
            )
            jpeg = self._renderer.encode_jpeg(annotated)
            with self._frame_lock:
                self._latest_frame = jpeg

            # --- Store events ---
            for alert in alerts:
                self._store_event(alert)
                self._broadcast("alert", self._alert_to_dict(alert))

            # --- FPS ---
            frame_count += 1
            elapsed = time.monotonic() - fps_timer
            if elapsed >= 1.0:
                self.fps = round(frame_count / elapsed, 1)
                frame_count = 0
                fps_timer = time.monotonic()

            # --- Pace ---
            loop_elapsed = time.monotonic() - loop_start
            sleep_time = max(0, frame_interval - loop_elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        # Cleanup
        if video_source is not None:
            video_source.release()
        logger.info("Pipeline loop exited")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _store_event(self, alert: RiskAlert) -> None:
        """Insert an event into the database."""
        if self._db_insert_fn is None:
            return
        try:
            self._db_insert_fn(
                camera_id=self.camera_id,
                event_type=alert.event_type,
                severity=alert.severity,
                ttc_s=alert.ttc_s,
                min_distance_m=alert.min_distance_m,
                vru_class=alert.vru.label,
                vehicle_class=alert.vehicle.label,
                vru_track_id=alert.vru.track_id,
                vehicle_track_id=alert.vehicle.track_id,
                confidence=min(alert.vru.conf, alert.vehicle.conf),
                zone_name=alert.zone_name,
                latency_ms=alert.latency_ms,
            )
        except Exception as exc:
            logger.error("Failed to store event: %s", exc)

    def _broadcast(self, msg_type: str, data: dict) -> None:
        """Broadcast a message via WebSocket (thread-safe)."""
        if self._broadcast_fn is None or self._event_loop is None:
            return
        message = {"type": msg_type, **data}
        try:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_fn(message), self._event_loop
            )
        except Exception as exc:
            logger.debug("Broadcast failed: %s", exc)

    @staticmethod
    def _alert_to_dict(alert: RiskAlert) -> dict:
        """Convert a RiskAlert to a JSON-serialisable dict."""
        return {
            "event_type": alert.event_type,
            "severity": alert.severity,
            "ttc_s": alert.ttc_s,
            "min_distance_m": alert.min_distance_m,
            "risk_score": alert.risk_score,
            "vru_class": alert.vru.label,
            "vehicle_class": alert.vehicle.label,
            "vru_track_id": alert.vru.track_id,
            "vehicle_track_id": alert.vehicle.track_id,
            "zone_name": alert.zone_name,
            "latency_ms": alert.latency_ms,
            "is_seed": 0,
        }
