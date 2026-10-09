"""Generate realistic historical events for the demo."""

import argparse
import json
import logging
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to sys.path so we can import app
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from app import db

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def generate_events(count: int, reset: bool = False) -> None:
    """Generate and insert historical events."""
    if reset:
        db.execute("DELETE FROM events WHERE is_seed = 1")
        logger.info("Deleted existing seed events.")
        
    now = datetime.now(timezone.utc)
    
    # Distributions
    types = [("warning", 0.60), ("critical", 0.25), ("near_miss", 0.15)]
    zones = [("Zebra crossing", 0.70), ("Junction box", 0.30)]
    vrus = [("person", 0.70), ("bicycle", 0.30)]
    vehicles = [("car", 0.60), ("motorcycle", 0.20), ("truck", 0.15), ("bus", 0.05)]
    
    def weighted_choice(choices):
        r = random.random()
        cum = 0.0
        for item, weight in choices:
            cum += weight
            if r <= cum:
                return item
        return choices[-1][0]
        
    # Rush hours: 08-10, 17-20
    def random_rush_hour_time():
        days_ago = random.randint(0, 14)
        is_morning = random.choice([True, False])
        hour = random.randint(8, 9) if is_morning else random.randint(17, 19)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        
        dt = now - timedelta(days=days_ago)
        return dt.replace(hour=hour, minute=minute, second=second)

    events_to_insert = []
    
    for _ in range(count):
        ts = random_rush_hour_time()
        ev_type = weighted_choice(types)
        zone = weighted_choice(zones)
        vru = weighted_choice(vrus)
        veh = weighted_choice(vehicles)
        
        # Plausible values
        if ev_type == "warning":
            sev = 2
            ttc = random.uniform(1.6, 3.0)
            dist = random.uniform(1.0, 1.5)
        elif ev_type == "critical":
            sev = 3
            ttc = random.uniform(0.5, 1.5)
            dist = random.uniform(0.5, 1.0)
        else: # near miss
            sev = 3
            ttc = random.uniform(0.1, 1.0)
            dist = random.uniform(0.3, 1.2)
            
        conf = random.uniform(0.70, 0.95)
        latency = random.uniform(55.0, 130.0)
        
        details = json.dumps({"seed": True, "generated": True})
        
        events_to_insert.append((
            1, # camera_id
            ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            ev_type, sev, round(ttc, 2), round(dist, 2),
            vru, veh,
            random.randint(100, 999), random.randint(100, 999), # fake track ids
            round(conf, 2), zone, round(latency, 1), 1, details
        ))
        
    # Insert in batch
    db.execute_many(
        """INSERT INTO events 
           (camera_id, ts, event_type, severity, ttc_s, min_distance_m, 
            vru_class, vehicle_class, vru_track_id, vehicle_track_id, 
            confidence, zone_name, latency_ms, is_seed, details_json) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        events_to_insert
    )
    
    logger.info("Inserted %d generated demo events.", count)


def main():
    parser = argparse.ArgumentParser(description="Seed realistic demo events.")
    parser.add_argument("--count", type=int, default=300, help="Number of events to generate")
    parser.add_argument("--reset-seed-events", action="store_true", help="Delete existing seed events first")
    args = parser.parse_args()
    
    generate_events(args.count, args.reset_seed_events)


if __name__ == "__main__":
    main()
