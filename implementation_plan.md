# CityPulse Implementation Plan

## Goal Description

Build **CityPulse**, a real-time urban road-safety and mobility platform for the Zéphyr 2026 AI Hackathon. The system has two parallel flows:

1. **Road Safety Flow**: Camera frames → YOLO/Simulator detection → Multi-frame tracking → TTC/CPA risk analysis → Real-time warnings → Event logging
2. **Ambulance Flow**: GPS ingestion → Route look-ahead → Signal pre-emption → Emergency passage → Journey comparison

The deliverable is a complete, runnable prototype with FastAPI backend, SQLite database, vision pipeline (simulator + YOLO), risk engine, traffic signal state machine, ambulance engine, web dashboard, driver warning display, phone GPS sender, scenario runner, and full test suite.

## Environment Notes

> [!NOTE]
> Python 3.14.6 is available on this machine. While the spec mentions 3.10–3.12, 3.14 is backward-compatible. We'll note compatibility as "Python 3.10+" in the README and `requirements.txt`.

## Proposed Changes

The build follows the exact repository structure from the spec. I'll build in the prescribed order, creating ~35 files total.

---

### Phase 1: Project Skeleton & Configuration

#### [NEW] `requirements.txt`
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
opencv-python>=4.8.0
numpy>=1.24.0
ultralytics>=8.1.0
httpx>=0.25.0
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

#### [NEW] `.env.example`
```env
CITYPULSE_HOST=0.0.0.0
CITYPULSE_PORT=8000
CITYPULSE_LOG_LEVEL=INFO
CITYPULSE_DB_PATH=data/citypulse.db
CITYPULSE_PIPELINE_MODE=simulator
CITYPULSE_ACTIVE_CAMERA_ID=1
```

#### [NEW] `.gitignore`
Standard Python gitignore + `data/*.db`, `data/*.mp4`, `data/snapshots/`, `*.pt`

#### [NEW] `app/config.py`
Pydantic `BaseSettings` class reading from `.env` with sensible defaults:
- `host`, `port`, `log_level`, `db_path`, `pipeline_mode`, `active_camera_id`

#### [NEW] `data/.gitkeep`
Empty file to ensure the data directory exists in git.

---

### Phase 2: Database Layer

#### [NEW] `db/schema.sql`
Exact schema from spec section 5.1 — 20+ tables including `junctions`, `cameras`, `conflict_zones`, `detection_classes`, `risk_config`, `traffic_signals`, `signal_phases`, `hospitals`, `ambulances`, `routes`, `route_waypoints`, `route_signals`, `ambulance_runs`, `ambulance_run_signal_log`, `events`, `test_scenarios`, `scenario_results`, `warning_units`, `system_settings`, plus 3 views.

#### [NEW] `db/seed.sql`
Exact seed data from spec section 5.2 — Demo City with 3 junctions, 2 cameras, 6 conflict zones, 6 detection classes, 14 risk config entries, 3 signals with phases, 1 hospital, 2 ambulances, 1 route with 13 waypoints and 3 signal links, 6 test scenarios, 12 seed events, 6 seed ambulance runs.

#### [NEW] `db/init_db.py`
- CLI script with `--reset` flag
- Creates `data/` directory if needed
- Reads and executes `schema.sql` then `seed.sql`
- `--reset` deletes existing DB first
- Called automatically by app startup if DB doesn't exist

#### [NEW] `app/db.py`
- `get_conn()` → `sqlite3.Connection` with `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON`, `PRAGMA journal_mode=WAL`
- `query_all(sql, params)` → list of dicts
- `query_one(sql, params)` → dict or None
- `execute(sql, params)` → lastrowid
- Context manager for transactions
- Thread-safe connection management (pipeline thread gets its own connection)

---

### Phase 3: Risk Engine (pure logic, testable)

#### [NEW] `app/vision/types.py`
```python
@dataclass
class TrackedObject:
    track_id: int
    cls_id: int
    label: str
    category: Literal['vru', 'vehicle']
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    conf: float
    cx: float  # bottom-centre x
    cy: float  # bottom-centre y
    ts: float  # monotonic seconds
```

#### [NEW] `app/risk/engine.py`
Core risk analysis — pure functions + a `RiskEngine` class:

- **Velocity estimation**: Maintain last ~10 positions per track. Compute pixel displacement / dt / pixels_per_meter. Smooth with EMA (alpha from config).
- **Filtering**: Skip vehicles below `min_vehicle_speed_mps`. Mark VRUs below `vru_stationary_speed_mps` as standing (but still check if inside crossing zone).
- **CPA/TTC computation**: For each VRU–vehicle pair:
  - `r = p_vru - p_veh`, `v = v_vru - v_veh`
  - `t_cpa = -(r·v) / (v·v)` (skip if v·v ≈ 0)
  - `d_cpa = |r + v * t_cpa|`
  - Conflict if `0 < t_cpa ≤ prediction_horizon_s` and `d_cpa ≤ collision_radius_m`
  - Additional zone-based conflict check
- **Alert levels**: CRITICAL (TTC ≤ 1.5s, severity 3), WARNING (TTC ≤ 3.0s, severity 2)
- **Risk score**: 0–100 = `(1 - ttc/horizon) * 40 + (speed/max_speed) * 25 + risk_weight * 20 + confidence * 15`
- **Debounce**: Require `min_consecutive_frames` (3) consecutive detections, tolerate 1 gap
- **Cooldown**: Same pair not re-alerted for `alert_cooldown_s` (4s) unless severity escalates
- **Near-miss detection**: When pair separates after conflict, if min TTC < `near_miss_ttc_s` or min distance < `near_miss_distance_m`, emit one `near_miss` event

#### [NEW] `tests/test_risk.py`
7 test cases:
1. Head-on collision course → CRITICAL
2. Parallel motion → no alert
3. Stationary vehicle → ignored
4. Single-frame blip → debounced (no alert)
5. Cooldown prevents duplicate alerts
6. Near-miss emitted exactly once when pair separates
7. Low-confidence detection → ignored

---

### Phase 4: Signal Controller

#### [NEW] `app/signals/controller.py`
`SignalController` class:
- State machine per signal cycling through phases: GREEN → YELLOW → ALL_RED → next phase
- `initial_offset_s` shifts the starting position in the cycle
- `tick(dt)` advances all signals by `dt` seconds
- `simulate_until(t)` for deterministic testing
- `get_state(signal_id)` → current phase, colour per approach (NS/EW), time remaining
- `request_priority(signal_id, approach, eta_s)` → pre-emption logic:
  - If approach already green: extend/hold (up to `max_preempt_hold`)
  - If approach red: complete current yellow + all_red, respect `min_green_s`, then switch
  - Never two greens simultaneously
  - Release after ambulance passes or hold expires
- Broadcasts `signal_update` via callback

#### [NEW] `tests/test_signals.py`
4 test cases:
1. Never green for both approaches simultaneously
2. Yellow + all_red clearance always respected
3. Pre-emption grants green when ETA sufficient, reports `late` when not
4. Normal cycle resumes after release

---

### Phase 5: Simulator & Renderer

#### [NEW] `app/vision/simulator.py`
`JunctionSimulator` class:
- Renders 1280×720 top-down junction using OpenCV drawing primitives:
  - Green grass background
  - Grey road band y=330–490
  - White zebra stripes x=560–700, y=230–590
  - Faint junction box outline
- **Scenario playback mode**: Actors from `params_json` with deterministic positions
- **Continuous random traffic mode**:
  - Cars: spawn every 3–6s, speed 6–12 m/s, from left (and some from right)
  - Pedestrians: spawn every 5–9s at crossing edges, 1.2–1.6 m/s
  - Cyclists: every 15–25s, 3.5–5.5 m/s
  - 1-in-6 VRUs intentionally enter road when car within 25m
- Output: rendered frame + list of `TrackedObject` with persistent IDs
- Simulated noise: confidence 0.6–0.95, 1–2px jitter, 3% random dropout
- Target 15 FPS

#### [NEW] `app/vision/render.py`
`FrameRenderer` class:
- Draw bounding boxes in class colour with `#id label conf`
- Draw conflict zones as translucent polygons
- Draw conflict lines (yellow=warning, red=critical) with TTC text
- HUD overlay: FPS, mode, active alerts count, signal state
- JPEG encoding at quality 80 for MJPEG stream

---

### Phase 6: YOLO Detector & Video Mode

#### [NEW] `app/vision/detector_yolo.py`
`YOLODetector` class:
- Load `yolov8n.pt` (auto-downloads on first run)
- `detect(frame)` → list of `TrackedObject`
- Uses `model.track(frame, persist=True, tracker="bytetrack.yaml", classes=[...], conf=min_confidence, verbose=False)`
- Maps COCO class IDs via `detection_classes` table
- Supports file path, webcam index, RTSP URL
- Loops video files when they end
- Resizes frames to camera dimensions

---

### Phase 7: Pipeline Service & WebSocket

#### [NEW] `app/ws.py`
`ConnectionManager` class:
- Manage WebSocket connections
- `broadcast(message: dict)` → send JSON to all connected clients
- Handle connect/disconnect gracefully

#### [NEW] `app/services/pipeline.py`
`PipelineService` class (runs in a background thread):
- Loop: read frame/objects → risk analysis → render annotated frame → insert events → broadcast alerts
- Shared latest-frame buffer for `/video_feed`
- Start/stop/switch mode via methods
- Exposes current FPS and latency
- Clean shutdown on app stop
- Auto-clear warnings on driver display 3s after last conflict ends

#### [NEW] `app/services/metrics.py`
- `get_live_metrics(conn)` → detection stats, alert counts, mean/p95 latency
- Separates seed vs live data
- Ambulance comparison stats

---

### Phase 8: Ambulance Engine

#### [NEW] `app/ambulance/engine.py`
- `haversine(lat1, lon1, lat2, lon2)` → distance in meters
- `bearing(lat1, lon1, lat2, lon2)` → degrees
- `project_on_route(lat, lon, waypoints)` → distance along route
- `look_ahead(position, route, signals, trigger_distance)` → list of upcoming signals with ETAs
- Simulated run logic: move virtual ambulance along waypoints at cruise speed
  - Baseline: stops at red signals
  - Priority: issues pre-emption requests, passes through
  - Records `ambulance_runs` and `ambulance_run_signal_log`
- Compare endpoint: runs baseline then priority, returns percentage time saved

#### [NEW] `tests/test_ambulance.py`
3 test cases:
1. Haversine distance correctness
2. Route projection and look-ahead signal selection
3. Priority run faster than baseline with fewer stops

---

### Phase 9: API Routers

#### [NEW] `app/schemas.py`
Pydantic v2 models for all request/response types:
- `PipelineStartRequest`, `GPSUpdate`, `SimulateRequest`
- `EventResponse`, `MetricsResponse`, `SignalState`, etc.

#### [NEW] `app/routers/core.py`
- `GET /api/health`, `GET /api/state`
- `POST /api/pipeline/start`, `POST /api/pipeline/stop`
- `GET /video_feed` (MJPEG StreamingResponse)
- `GET /api/config/risk`, `PUT /api/config/risk`

#### [NEW] `app/routers/events.py`
- `GET /api/events`, `GET /api/events/{id}`, `POST /api/events/{id}/ack`
- `GET /api/hotspots`, `GET /api/metrics`

#### [NEW] `app/routers/ambulance.py`
- `GET /api/ambulance`, `POST /api/ambulance/gps`
- `POST /api/ambulance/simulate`, `GET /api/ambulance/runs`
- `GET /api/ambulance/comparison`

#### [NEW] `app/routers/signals.py`
- `GET /api/junctions`, `GET /api/signals`

#### [NEW] `app/routers/scenarios.py`
- `GET /api/scenarios`, `POST /api/scenarios/{code}/run`
- `POST /api/scenarios/run-all`, `GET /api/scenarios/results`

#### [NEW] `app/main.py`
- FastAPI app with lifespan (startup/shutdown)
- Auto-init DB if not exists
- Mount static files
- Include all routers
- WebSocket endpoint at `/ws`
- Start retention background task

#### [NEW] `tests/test_api.py`
4 test areas:
1. Health and state endpoints
2. Events filtering (seed vs live)
3. Config validation (reject invalid ranges)
4. GPS ingestion and scenario run endpoints

---

### Phase 10: Frontend

#### [NEW] `app/static/style.css`
Dark theme CSS with:
- CSS custom properties for colors, spacing, typography
- Responsive grid layout
- Card components with glassmorphism effects
- Alert feed styling (color-coded by severity)
- Animated status indicators
- Mobile-responsive breakpoints
- Google Fonts (Inter)

#### [NEW] `app/static/app.js`
Vanilla JS application:
- WebSocket connection with auto-reconnect
- MJPEG video display
- Alert feed (auto-updating, color-coded)
- Leaflet map initialization with junctions, signals, route, ambulance marker
- Ambulance control (run buttons, Chart.js bar chart)
- Metrics cards (auto-refreshing)
- Hotspot table
- Scenario panel with run buttons and pass/fail badges
- Settings drawer with risk threshold sliders
- Pipeline mode switch and start/stop controls

#### [NEW] `app/static/index.html`
Dashboard page — responsive dark-theme layout:
- Header: CityPulse branding, team badge, mode switch, start/stop
- Main content: video panel, alert feed, map, ambulance controls, metrics, hotspots, scenarios, settings
- CDN links: Leaflet, Chart.js, Google Fonts

#### [NEW] `app/static/warning.html`
Full-screen driver warning display:
- Big high-contrast text
- States: green "ROAD CLEAR", amber "CAUTION", red flashing "SLOW DOWN", blue "EMERGENCY VEHICLE"
- WebSocket-driven state changes
- Auto-clear 3s after last conflict

#### [NEW] `app/static/phone.html`
Mobile GPS sender page:
- "Start sharing location" button
- Uses `navigator.geolocation.watchPosition`
- Posts to `/api/ambulance/gps` every second
- Emergency toggle
- Shows what's being sent
- Note about HTTPS requirement

---

### Phase 11: Scripts

#### [NEW] `scripts/seed_demo_events.py`
- Generates ~300 historical events (`is_seed=1`) across last 14 days
- Rush-hour peaks (08–10, 17–20)
- Zone distribution: 70% Zebra crossing, 30% Junction box
- Type distribution: 60% warning, 25% critical, 15% near_miss
- Plausible TTC and distance values per type
- VRU: 70% person, 30% bicycle
- Vehicle: weighted car > motorcycle > truck > bus
- Latency: 55–130ms
- CLI: `--count` and `--reset-seed-events` flags

#### [NEW] `scripts/run_scenarios.py`
- Runs all 6 scenarios headless
- Road-safety: checks detection, alerting, false alerts, response time
- Ambulance: checks stops and journey time improvement
- Prints formatted metrics table
- Saves results to `scenario_results` table

#### [NEW] `scripts/fetch_sample_video.py`
- Instructions for obtaining a sample junction video
- Explains placement at `data/sample_junction.mp4`

---

### Phase 12: Scenarios Test

#### [NEW] `tests/test_scenarios.py`
- Runs all 6 seeded scenarios programmatically
- Verifies each matches expected outcome
- SC01: Approaching pedestrian → alert ✓
- SC02: Approaching cyclist → alert ✓
- SC03: Safe crossing → no_alert ✓
- SC04: High-risk crossing → critical_alert ✓
- SC05: Ambulance priority → priority_granted ✓
- SC06: Ambulance with queue → priority_granted ✓

---

### Phase 13: README

#### [NEW] `README.md`
Complete documentation per spec section 10, with all 16 subsections including Mermaid architecture diagram, quick start for both Windows and macOS/Linux, API reference table, ER diagram, validation results, and assumptions.

---

## Key Design Decisions

### 1. Thread Safety
The vision pipeline runs in a background thread. SQLite connections are per-thread. The pipeline communicates with the async FastAPI event loop via `asyncio.run_coroutine_threadsafe` for WebSocket broadcasts and uses a thread-safe shared buffer for the latest annotated frame.

### 2. Simulator as Default
The simulator is the default mode so the demo always works without any external video file or camera. It generates realistic `TrackedObject` instances with noise and dropout to exercise the full risk engine pipeline.

### 3. Risk Engine Purity
The risk engine is pure computation — no I/O, no database access. It receives objects and config, returns alerts. This makes it fully unit-testable and deterministic for scenarios.

### 4. Signal Controller Determinism
The signal controller supports `simulate_until(t)` for deterministic testing and accelerated ambulance runs (10x speed). No real-time delays in the controller itself.

### 5. Scenario Geometry Tuning
The scenario geometries are designed so that:
- SC01/SC02/SC04: VRU and vehicle trajectories converge at the crossing within the prediction horizon
- SC03: The car is fast enough to clear the crossing before the pedestrian arrives
- SC05/SC06: Signal offsets ensure baseline runs encounter red lights

If any scenario fails initial testing, I'll tune the starting positions and velocities (not the test logic) to produce the intended behavior.

### 6. Privacy
- No raw video storage by default
- No face/plate recognition
- Snapshots blurred if enabled
- Only derived metrics stored

---

## Verification Plan

### Automated Tests
```bash
# Run full test suite
pytest tests/ -v

# Run scenarios specifically
python scripts/run_scenarios.py
```

### Manual Verification (Browser)
1. **App startup**: `uvicorn app.main:app` starts without errors
2. **Dashboard** (`/`): Shows live simulator video, alerts appear within 60s
3. **Ambulance compare**: "Compare both" produces chart showing priority is faster
4. **Warning display** (`/warning`): Reacts to alerts in real-time
5. **Phone page** (`/phone`): GPS posting works (verified with curl)
6. **Signal safety**: Map signals never show green for both approaches
7. **Seed data labeling**: Demo data clearly marked throughout

### Acceptance Criteria Checklist
| # | Criterion | Verification Method |
|---|-----------|-------------------|
| 1 | Clean install + start | Run commands from README |
| 2 | Live warnings within 60s | Watch dashboard |
| 3 | TTC matches thresholds | Check event values |
| 4 | Ambulance comparison works | Run compare, check chart |
| 5 | Warning/phone pages work | Open pages, verify WebSocket |
| 6 | All 6 scenarios pass | `run_scenarios.py` output |
| 7 | pytest passes | `pytest tests/ -v` |
| 8 | Video mode graceful fallback | Check without sample video |
| 9 | Seed data labeled | Visual inspection |
| 10 | README complete | Review all sections |

---

## Estimated File Count: ~35 files
## Estimated Total Lines: ~5,000–7,000 lines of code
