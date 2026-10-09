"""Fetch a sample junction video for testing the YOLO pipeline.

Run this script to download a sample traffic camera video.
"""

import sys
import urllib.request
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# A small, public domain / CC-0 traffic video URL (or a placeholder text)
# For the hackathon, we assume the user provides their own, but this helps setup.
SAMPLE_URL = "https://github.com/ultralytics/yolov5/releases/download/v1.0/traffic.mp4"
TARGET = DATA_DIR / "sample_junction.mp4"

def main():
    print(f"Downloading sample video to {TARGET}...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        urllib.request.urlretrieve(SAMPLE_URL, TARGET)
        print("Download complete!")
        print("You can now switch CityPulse to 'Video' mode in the dashboard.")
        print("Note: The conflict zones in the database are tuned for the simulator.")
        print("To use them with this video, you would normally update the polygon_json")
        print("in the conflict_zones table.")
    except Exception as e:
        print(f"Failed to download: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
