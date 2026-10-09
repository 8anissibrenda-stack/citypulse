"""YOLO + ByteTrack detector wrapper for CityPulse.

Loads ``yolov8n.pt`` (auto-downloads on first run) and maps COCO detections
to the CityPulse ``TrackedObject`` type.  Supports video files, webcams, and
RTSP streams.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from app.vision.types import TrackedObject

logger = logging.getLogger(__name__)

# COCO class mapping (subset matching detection_classes table)
_CLASS_INFO: dict[int, dict] = {
    0:  {"label": "person",     "category": "vru"},
    1:  {"label": "bicycle",    "category": "vru"},
    2:  {"label": "car",        "category": "vehicle"},
    3:  {"label": "motorcycle", "category": "vehicle"},
    5:  {"label": "bus",        "category": "vehicle"},
    7:  {"label": "truck",      "category": "vehicle"},
}

TRACKED_COCO_IDS = list(_CLASS_INFO.keys())


class YOLODetector:
    """Wraps Ultralytics YOLOv8 with ByteTrack for real-time detection + tracking.

    Attributes:
        model: The loaded YOLO model instance.
    """

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        min_confidence: float = 0.45,
        frame_width: int = 1280,
        frame_height: int = 720,
    ) -> None:
        """
        Args:
            model_path: Path to the YOLO weights file (auto-downloads if needed).
            min_confidence: Minimum detection confidence.
            frame_width: Target frame width.
            frame_height: Target frame height.
        """
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.min_confidence = min_confidence
        self._start_time = time.monotonic()

        try:
            from ultralytics import YOLO
            self.model = YOLO(model_path)
            logger.info("YOLO model loaded from %s", model_path)
        except Exception as exc:
            logger.error(
                "Failed to load YOLO model from '%s'. "
                "Ensure you have internet access for the first download, "
                "or place yolov8n.pt in the project root. Error: %s",
                model_path, exc,
            )
            raise

    def detect(self, frame: np.ndarray) -> list[TrackedObject]:
        """Run detection + tracking on a single frame.

        Args:
            frame: BGR image (numpy array).

        Returns:
            List of TrackedObject instances for this frame.
        """
        # Resize if needed
        h, w = frame.shape[:2]
        if w != self.frame_width or h != self.frame_height:
            frame = cv2.resize(frame, (self.frame_width, self.frame_height))

        ts = time.monotonic() - self._start_time

        results = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=TRACKED_COCO_IDS,
            conf=self.min_confidence,
            verbose=False,
        )

        objects: list[TrackedObject] = []
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for box in boxes:
                cls_id = int(box.cls[0])
                if cls_id not in _CLASS_INFO:
                    continue
                info = _CLASS_INFO[cls_id]
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                track_id = int(box.id[0]) if box.id is not None else -1

                cx = (x1 + x2) / 2
                cy = y2  # bottom-centre = ground contact

                objects.append(TrackedObject(
                    track_id=track_id,
                    cls_id=cls_id,
                    label=info["label"],
                    category=info["category"],
                    bbox=(x1, y1, x2, y2),
                    conf=round(conf, 2),
                    cx=cx,
                    cy=cy,
                    ts=ts,
                ))

        return objects


class VideoSource:
    """Manages a video source (file, webcam, or RTSP) with looping support.

    Attributes:
        cap: The OpenCV VideoCapture instance.
    """

    def __init__(
        self,
        source: str | int,
        frame_width: int = 1280,
        frame_height: int = 720,
        loop: bool = True,
    ) -> None:
        """
        Args:
            source: File path, webcam index, or RTSP URL.
            frame_width: Target frame width.
            frame_height: Target frame height.
            loop: Whether to loop video files at the end.
        """
        self.source = source
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.loop = loop
        self.cap: cv2.VideoCapture | None = None
        self._open()

    def _open(self) -> None:
        """Open the video source."""
        if isinstance(self.source, int):
            self.cap = cv2.VideoCapture(self.source)
        else:
            self.cap = cv2.VideoCapture(str(self.source))

        if not self.cap.isOpened():
            raise IOError(f"Cannot open video source: {self.source}")
        logger.info("Opened video source: %s", self.source)

    def read(self) -> np.ndarray | None:
        """Read the next frame, looping if needed. Returns None on failure."""
        if self.cap is None:
            return None

        ret, frame = self.cap.read()
        if not ret:
            if self.loop and isinstance(self.source, str):
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()
                if not ret:
                    return None
            else:
                return None

        h, w = frame.shape[:2]
        if w != self.frame_width or h != self.frame_height:
            frame = cv2.resize(frame, (self.frame_width, self.frame_height))

        return frame

    def release(self) -> None:
        """Release the video source."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    @property
    def fps(self) -> float:
        """Return the source FPS."""
        if self.cap is not None:
            return self.cap.get(cv2.CAP_PROP_FPS) or 15.0
        return 15.0
