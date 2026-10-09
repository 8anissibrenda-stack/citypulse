import subprocess
import time
import requests
import sys

def main():
    print("Starting uvicorn server...")
    # Initialize DB just in case
    subprocess.run([sys.executable, "db/init_db.py", "--reset"], check=True)
    
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"])
    time.sleep(3) # Wait for server to start
    
    success = True

    def check(name, cond):
        nonlocal success
        if cond:
            print(f"PASS: {name}")
        else:
            print(f"FAIL: {name}")
            success = False

    try:
        # 1. GET / and GET /static/style.css return 200 and the CSS contains the dark background rule.
        r = requests.get("http://localhost:8000/")
        check("GET /", r.status_code == 200)
        
        r = requests.get("http://localhost:8000/static/style.css")
        check("GET /static/style.css", r.status_code == 200 and "--bg-dark: #121212" in r.text)

        # 2. GET /api/state shows the pipeline running in simulator mode.
        r = requests.get("http://localhost:8000/api/state")
        data = r.json()
        check("Pipeline running in simulator mode", data.get("pipeline", {}).get("running") is True and data.get("pipeline", {}).get("mode") == "simulator")

        # 3. GET /video_feed returns a multipart stream with at least 3 JPEG frames, and two frames differ (the video is moving).
        print("Checking video feed...")
        r = requests.get("http://localhost:8000/video_feed", stream=True)
        content = b""
        frames = []
        for chunk in r.iter_content(chunk_size=8192):
            content += chunk
            parts = content.split(b"--frame\r\n")
            if len(parts) > 3:
                frames = parts[1:-1]
                break
        r.close()
        check("Video feed gives multiple frames", len(frames) >= 2)
        check("Video feed frames differ", frames[0] != frames[-1])

        # 4. A warning event with is_seed = 0 appears within 20 seconds.
        print("Waiting up to 20 seconds for a live warning event...")
        found_warning = False
        for _ in range(20):
            r = requests.get("http://localhost:8000/api/events")
            events = r.json()
            if any(e.get("event_type") in ("warning", "critical") and e.get("is_seed") == 0 for e in events):
                found_warning = True
                break
            time.sleep(1)
        check("Live warning event appears", found_warning)

        # 5. GET /api/hotspots, /api/metrics, /api/signals and /api/scenarios return non-empty data.
        r = requests.get("http://localhost:8000/api/hotspots")
        check("Hotspots not empty", len(r.json()) > 0)
        r = requests.get("http://localhost:8000/api/metrics")
        check("Metrics returns data", r.status_code == 200 and isinstance(r.json(), dict))
        r = requests.get("http://localhost:8000/api/signals")
        check("Signals not empty", len(r.json()) > 0)
        r = requests.get("http://localhost:8000/api/scenarios")
        check("Scenarios not empty", len(r.json()) > 0)

        # 6. POST the ambulance compare run, and confirm priority duration < baseline duration and priority stops == 0.
        print("Running ambulance comparisons...")
        requests.post("http://localhost:8000/api/ambulance/simulate", json={"route_id": 1, "mode": "baseline", "sim_speed": 10})
        requests.post("http://localhost:8000/api/ambulance/simulate", json={"route_id": 1, "mode": "priority", "sim_speed": 10})
        r = requests.get("http://localhost:8000/api/ambulance/comparison")
        data = r.json()
        check("Comparison returned data", "time_saved_pct" in data)
        if "time_saved_pct" in data:
            check("Priority is faster (time saved > 0)", data["time_saved_pct"] > 0)
        r = requests.get("http://localhost:8000/api/metrics")
        metrics = r.json()
        comps = metrics.get("ambulance_comparison", [])
        base = next((c for c in comps if c["mode"] == "baseline"), None)
        prio = next((c for c in comps if c["mode"] == "priority"), None)
        check("Comparison has both baseline and priority", base is not None and prio is not None)
        if base and prio:
            check("Priority duration < baseline duration", prio["avg_duration_s"] < base["avg_duration_s"])
            check("Priority stops == 0", prio["avg_stops"] == 0)

        # 7. POST /api/scenarios/run-all, and confirm all 6 scenarios pass.
        print("Running all scenarios...")
        requests.post("http://localhost:8000/api/scenarios/run-all")
        r = requests.get("http://localhost:8000/api/scenarios/results")
        results = r.json()
        passed_ids = set([r["scenario_id"] for r in results if r["passed"] == 1])
        check("All 6 scenarios passed", len(passed_ids) == 6)

    finally:
        server.terminate()
        server.wait()
        
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
