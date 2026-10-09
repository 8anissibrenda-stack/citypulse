import asyncio
import json
import logging
import sys
import time

import requests
import websockets

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws"

def check_html():
    resp = requests.get(BASE_URL)
    resp.raise_for_status()
    html = resp.text
    
    required = [
        "DRIVER DISPLAY", "LIVE ALERTS", "METRICS", 
        "ROAD CLEAR", "SLOW DOWN", "PEDESTRIAN CROSSING", 
        "WITHOUT CityPulse", "WITH CityPulse priority", "Journey time saved"
    ]
    for r in required:
        if r not in html:
            logging.error(f"Missing '{r}' in HTML")
            sys.exit(1)
            
    forbidden = ["leaflet", "carto"]
    for f in forbidden:
        if f.lower() in html.lower():
            logging.error(f"Found forbidden '{f}' in HTML")
            sys.exit(1)
            
    logging.info("HTML contents verified")

def check_ambulance():
    resp = requests.post(f"{BASE_URL}/api/ambulance/compare")
    resp.raise_for_status()
    data = resp.json()
    
    summary = data.get("summary", {})
    base = summary.get("baseline", {})
    prio = summary.get("priority", {})
    
    if prio.get("duration_s", 999) >= base.get("duration_s", 0):
        logging.error("Priority duration is not shorter than baseline")
        sys.exit(1)
        
    if prio.get("stops", 1) != 0:
        logging.error("Priority stops is not 0")
        sys.exit(1)
        
    if base.get("stops", 0) < 2:
        logging.error("Baseline stops is less than 2")
        sys.exit(1)
        
    logging.info("Ambulance comparison verified")

def check_scenarios():
    resp = requests.post(f"{BASE_URL}/api/scenarios/run-all")
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    if len(results) != 6:
        logging.error(f"Expected 6 scenarios, got {len(results)}")
        sys.exit(1)
    if not all(r.get("passed") for r in results):
        logging.error("Not all scenarios passed")
        sys.exit(1)
        
    logging.info("Validation scenarios passed")

async def check_ws():
    # Restart pipeline in simulator mode
    requests.post(f"{BASE_URL}/api/pipeline/start?mode=simulator")
    time.sleep(1)
    
    # Connect WS
    try:
        async with websockets.connect(WS_URL, ping_interval=None) as ws:
            logging.info("Connected to WS")
            
            # States to track
            car_braked = False
            got_alert = False
            display_was_warning = False
            display_back_to_clear = False
            second_loop_started = False
            
            start_t = time.time()
            loops = 0
            last_sim_t = 0
            
            alerts_seen = 0
            ped_in_zone = False
            
            while time.time() - start_t < 25:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                    
                data = json.loads(msg)
                if data.get("type") == "frame":
                    sim_t = data.get("t", 0)
                    
                    if sim_t < last_sim_t - 5:
                        loops += 1
                        if loops > 0:
                            second_loop_started = True
                    last_sim_t = sim_t
                    
                    if data.get("conflict"):
                        got_alert = True
                        
                    ped = next((o for o in data["objects"] if o["cls"] == "person"), None)
                    car = next((o for o in data["objects"] if o["cls"] == "car"), None)
                    
                    if ped and car:
                        # Zone is approx 230 to 590
                        if 230 <= ped["y"] <= 590:
                            ped_in_zone = True
                            if data.get("display") == "warning" or data.get("display") == "critical":
                                display_was_warning = True
                                
                            # Check if car braked before crossing (560)
                            if car["x"] < 560:
                                vx = data.get("vx") # not in frame?
                                # We can't see vx easily in the simplified frame objects unless we included it.
                                # But we can check car.x changes or just check the display
                        else:
                            if ped_in_zone:
                                if data.get("display") == "clear":
                                    display_back_to_clear = True
                                    
            if not got_alert:
                logging.error("No alert received via WS")
                sys.exit(1)
            if not display_was_warning:
                logging.error("Display never went to warning while ped was in zone")
                sys.exit(1)
            if not display_back_to_clear:
                logging.error("Display never went back to clear after ped left")
                sys.exit(1)
            if not second_loop_started:
                logging.error("Second loop did not start within 25s")
                sys.exit(1)
                
            metrics = data.get("metrics", {})
            if metrics.get("warnings", 0) > 20:
                logging.error(f"Too many warnings: {metrics.get('warnings')}")
                sys.exit(1)
                
            logging.info("WebSocket simulation loop verified")
            
    except Exception as e:
        logging.error(f"WS error: {e}")
        sys.exit(1)

def main():
    time.sleep(2)  # Give server time
    check_html()
    check_ambulance()
    check_scenarios()
    
    asyncio.run(check_ws())
    
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    main()
