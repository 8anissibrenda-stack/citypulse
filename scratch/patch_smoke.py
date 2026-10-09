import sys
import os
import time

with open("scripts/smoke_test.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """        # 4. A warning event with is_seed = 0 appears within 20 seconds.
        print("Waiting up to 20 seconds for a live warning event...")
        found_warning = False
        for _ in range(20):
            r = requests.get("http://localhost:8000/api/events")
            events = r.json()
            if any(e.get("event_type") in ("warning", "critical") and e.get("is_seed") == 0 for e in events):
                found_warning = True
                break
            time.sleep(1)
        check("Live warning event appears", found_warning)"""

replace = """        import os
        check("Sprites exist", os.path.exists("app/assets/sprites/car_0.png"))
        
        with open("app/static/index.html", "r") as f:
            idx = f.read()
        with open("app/static/app.js", "r") as f:
            ajs = f.read()
        check("No carto in index/app", "carto" not in idx.lower() and "carto" not in ajs.lower() and "basemap" not in idx.lower() and "basemap" not in ajs.lower())

        print("Checking simulator driver model...")
        sys.path.append(os.getcwd())
        from app.vision.simulator import JunctionSimulator
        sim = JunctionSimulator(fps=15, pixels_per_meter=25)
        
        found_yield = False
        accelerated_after = False
        yielded_vehicle_id = None
        
        for _ in range(60 * 15):
            _, objects = sim.step(1.0/15.0)
            vrus_in_crossing = False
            for o in objects:
                if o.category == 'vru' and 560 <= o.cx <= 700 and 230 <= o.cy <= 590:
                    vrus_in_crossing = True
                    break
            if vrus_in_crossing:
                for o in objects:
                    if o.category == 'vehicle' and hasattr(o, 'vx'):
                        if (o.vx**2 + getattr(o, 'vy', 0)**2)**0.5 < 1.0:
                            found_yield = True
                            yielded_vehicle_id = o.track_id
                            break
            if found_yield:
                break
                
        check("Simulator driver model yields to VRU", found_yield)
        
        if found_yield:
            for _ in range(30 * 15):
                _, objs = sim.step(1.0/15.0)
                for o in objs:
                    if o.track_id == yielded_vehicle_id and hasattr(o, 'vx'):
                        if (o.vx**2 + getattr(o, 'vy', 0)**2)**0.5 > 2.0:
                            accelerated_after = True
                            break
                if accelerated_after:
                    break
                    
        check("Simulator vehicle accelerates after yielding", accelerated_after)

        print("Waiting 60 seconds for live events check...")
        time.sleep(60)
        r = requests.get("http://localhost:8000/api/metrics")
        check("Fewer than 20 live events in 60s", r.json().get("total_events", 0) < 20)"""

content = content.replace(target, replace)

with open("scripts/smoke_test.py", "w", encoding="utf-8") as f:
    f.write(content)
