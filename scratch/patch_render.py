import sys
import os

with open("app/vision/render.py", "r", encoding="utf-8") as f:
    content = f.read()

import_target = """import cv2
import numpy as np"""
import_replace = """import cv2
import numpy as np
import os
import random
import math"""
content = content.replace(import_target, import_replace)

init_target = """    def __init__(self, zones: list[ConflictZone] | None = None) -> None:
        self.zones = zones or []"""
init_replace = """    def __init__(self, zones: list[ConflictZone] | None = None) -> None:
        self.zones = zones or []
        self.sprites = {}
        self.load_sprites()
        self.ped_frame = 0

    def load_sprites(self):
        sprite_dir = "app/assets/sprites"
        if not os.path.exists(sprite_dir):
            return
        
        for file in os.listdir(sprite_dir):
            if file.endswith(".png"):
                name = file[:-4]
                img = cv2.imread(os.path.join(sprite_dir, file), cv2.IMREAD_UNCHANGED)
                if img is not None:
                    self.sprites[name] = img"""
content = content.replace(init_target, init_replace)

draw_box_target = """    def _draw_box(self, frame: np.ndarray, obj: TrackedObject) -> None:
        \"\"\"Draw a bounding box with label text.\"\"\"
        colour = CLASS_COLOURS.get(obj.label, (200, 200, 200))
        x1, y1, x2, y2 = int(obj.bbox[0]), int(obj.bbox[1]), int(obj.bbox[2]), int(obj.bbox[3])
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
        label = f"#{obj.track_id} {obj.label} {obj.conf:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), colour, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)"""

draw_box_replace = """    def _draw_box(self, frame: np.ndarray, obj: TrackedObject) -> None:
        \"\"\"Draw a bounding box with label text.\"\"\"
        # Get sprite
        sprite_name = None
        is_braking = False
        if obj.category == "vehicle" and hasattr(obj, "vx") and hasattr(obj, "vy"):
            speed = math.hypot(obj.vx, obj.vy)
            if hasattr(obj, "last_speed"):
                if speed < getattr(obj, "last_speed") - 0.5:
                    is_braking = True
            setattr(obj, "last_speed", speed)
            
        if obj.label == "car":
            color_idx = obj.track_id % 3
            sprite_name = f"car_{color_idx}_brake" if is_braking else f"car_{color_idx}"
        elif obj.label == "bus":
            sprite_name = "bus_brake" if is_braking else "bus"
        elif obj.label == "truck":
            sprite_name = "truck_brake" if is_braking else "truck"
        elif obj.label == "motorcycle":
            sprite_name = "motorcycle_brake" if is_braking else "motorcycle"
        elif obj.label == "bicycle":
            sprite_name = "bicycle"
        elif obj.label == "person":
            color_idx = obj.track_id % 4
            speed = math.hypot(obj.vx, obj.vy) if hasattr(obj, "vx") else 0
            if speed > 10:
                frame_idx = (int(obj.ts * 5) + obj.track_id) % 3
            else:
                frame_idx = 0
            sprite_name = f"person_{color_idx}_f{frame_idx}"

        sprite = self.sprites.get(sprite_name)
        if sprite is not None:
            # compute heading
            heading = 0
            if hasattr(obj, "vx") and hasattr(obj, "vy") and math.hypot(obj.vx, obj.vy) > 1.0:
                heading = math.degrees(math.atan2(obj.vy, obj.vx))
            elif hasattr(obj, "last_heading"):
                heading = getattr(obj, "last_heading")
            setattr(obj, "last_heading", heading)
            
            # rotate sprite
            h, w = sprite.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, heading, 1.0)
            rotated = cv2.warpAffine(sprite, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0,0,0,0))
            
            # blend
            cx, cy = int(obj.cx), int(obj.cy)
            rx1 = cx - w // 2
            ry1 = cy - h // 2
            rx2 = rx1 + w
            ry2 = ry1 + h
            
            # bounds check
            if rx1 >= 0 and ry1 >= 0 and rx2 < frame.shape[1] and ry2 < frame.shape[0]:
                alpha = rotated[:, :, 3] / 255.0
                for c in range(3):
                    frame[ry1:ry2, rx1:rx2, c] = alpha * rotated[:, :, c] + (1 - alpha) * frame[ry1:ry2, rx1:rx2, c]

        # Draw bbox if needed
        colour = CLASS_COLOURS.get(obj.label, (200, 200, 200))
        x1, y1, x2, y2 = int(obj.bbox[0]), int(obj.bbox[1]), int(obj.bbox[2]), int(obj.bbox[3])
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 1)
        label = f"{obj.label}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.35, 1)
        cv2.rectangle(frame, (x1, y1 - th - 4), (x1 + tw + 2, y1), colour, -1)
        cv2.putText(frame, label, (x1 + 1, y1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)"""
content = content.replace(draw_box_target, draw_box_replace)

with open("app/vision/render.py", "w", encoding="utf-8") as f:
    f.write(content)
