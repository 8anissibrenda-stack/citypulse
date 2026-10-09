"""Frame renderer for the CityPulse vision pipeline.

Draws bounding boxes, conflict zones, risk lines, and a HUD onto frames.
Encodes as JPEG for the MJPEG stream.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.vision.types import ConflictZone, RiskAlert, TrackedObject

# Colour look-up for class labels (BGR)
CLASS_COLOURS: dict[str, tuple[int, int, int]] = {
    "person":     (0, 152, 255),
    "bicycle":    (0, 193, 255),
    "car":        (255, 150, 33),
    "motorcycle": (180, 39, 156),
    "bus":        (75, 81, 63),
    "truck":      (139, 125, 96),
}


class FrameRenderer:
    """Annotates a camera frame with detections, zones, risk lines and HUD."""

    def __init__(self, zones: list[ConflictZone] | None = None) -> None:
        self.zones = zones or []

    def render(
        self,
        frame: np.ndarray,
        objects: list[TrackedObject],
        alerts: list[RiskAlert] | None = None,
        fps: float = 0.0,
        mode: str = "simulator",
        active_alert_count: int = 0,
        signal_states: list[dict] | None = None,
    ) -> np.ndarray:
        """Draw all overlays onto a copy of the frame and return it.

        Args:
            frame: The raw BGR frame.
            objects: Detected/tracked objects this frame.
            alerts: Active risk alerts this frame.
            fps: Current pipeline FPS for HUD.
            mode: Pipeline mode string for HUD.
            active_alert_count: Number of active alerts for HUD.
            signal_states: Signal state dicts for HUD.
        """
        out = frame.copy()

        # 1. Draw conflict zones (translucent)
        self._draw_zones(out)

        # 2. Draw bounding boxes
        for obj in objects:
            self._draw_box(out, obj)

        # 3. Draw risk lines
        if alerts:
            for alert in alerts:
                self._draw_risk_line(out, alert)

        # 4. HUD
        self._draw_hud(out, fps, mode, active_alert_count, signal_states)

        return out

    def encode_jpeg(self, frame: np.ndarray, quality: int = 80) -> bytes:
        """Encode a frame as JPEG bytes."""
        params = [cv2.IMWRITE_JPEG_QUALITY, quality]
        _, buf = cv2.imencode(".jpg", frame, params)
        return buf.tobytes()

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_zones(self, frame: np.ndarray) -> None:
        """Draw conflict zones as translucent polygons."""
        overlay = frame.copy()
        for zone in self.zones:
            pts = np.array(zone.polygon, dtype=np.int32)
            if zone.zone_type == "crossing":
                colour = (0, 200, 200)
            elif zone.zone_type == "junction_box":
                colour = (200, 200, 0)
            else:
                colour = (200, 100, 100)
            cv2.fillPoly(overlay, [pts], colour)
            cv2.polylines(frame, [pts], True, colour, 2)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)

    def _draw_box(self, frame: np.ndarray, obj: TrackedObject) -> None:
        """Draw a bounding box with label text."""
        colour = CLASS_COLOURS.get(obj.label, (200, 200, 200))
        x1, y1, x2, y2 = int(obj.bbox[0]), int(obj.bbox[1]), int(obj.bbox[2]), int(obj.bbox[3])
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
        label = f"#{obj.track_id} {obj.label} {obj.conf:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), colour, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    def _draw_risk_line(self, frame: np.ndarray, alert: RiskAlert) -> None:
        """Draw a line between the VRU and vehicle with TTC text."""
        if alert.event_type == "critical" or alert.event_type == "near_miss":
            colour = (0, 0, 255)  # red
            thickness = 3
        else:
            colour = (0, 220, 255)  # yellow
            thickness = 2

        p1 = (int(alert.vru.cx), int(alert.vru.cy))
        p2 = (int(alert.vehicle.cx), int(alert.vehicle.cy))
        cv2.line(frame, p1, p2, colour, thickness)

        # TTC label at midpoint
        mx = (p1[0] + p2[0]) // 2
        my = (p1[1] + p2[1]) // 2
        ttc_text = f"TTC {alert.ttc_s:.1f}s"
        cv2.putText(frame, ttc_text, (mx + 5, my - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2)

    def _draw_hud(
        self,
        frame: np.ndarray,
        fps: float,
        mode: str,
        active_alerts: int,
        signal_states: list[dict] | None,
    ) -> None:
        """Draw the heads-up display overlay."""
        # Semi-transparent black bar at top
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (frame.shape[1], 38), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        y = 26
        cv2.putText(frame, f"CityPulse | {mode.upper()}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 1)
        cv2.putText(frame, f"FPS: {fps:.0f}", (350, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        if active_alerts > 0:
            alert_colour = (0, 0, 255)
            cv2.putText(frame, f"ALERTS: {active_alerts}", (460, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, alert_colour, 2)
        else:
            cv2.putText(frame, "NO ALERTS", (460, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)

        # Signal states
        if signal_states:
            sx = 650
            for s in signal_states:
                ns_c = self._colour_for(s.get("ns_colour", "red"))
                ew_c = self._colour_for(s.get("ew_colour", "red"))
                code = f"S{s['signal_id']}"
                cv2.putText(frame, code, (sx, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
                cv2.circle(frame, (sx + 35, y - 5), 6, ns_c, -1)
                cv2.circle(frame, (sx + 50, y - 5), 6, ew_c, -1)
                sx += 80

    @staticmethod
    def _colour_for(colour_name: str) -> tuple[int, int, int]:
        """Convert a colour name to BGR."""
        return {
            "green":  (0, 200, 0),
            "yellow": (0, 220, 255),
            "red":    (0, 0, 220),
        }.get(colour_name, (128, 128, 128))
