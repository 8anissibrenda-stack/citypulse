PRAGMA foreign_keys = ON;

CREATE TABLE junctions (
  id          INTEGER PRIMARY KEY,
  code        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  description TEXT
);

CREATE TABLE cameras (
  id               INTEGER PRIMARY KEY,
  junction_id      INTEGER NOT NULL REFERENCES junctions(id),
  name             TEXT NOT NULL,
  source_type      TEXT NOT NULL CHECK (source_type IN ('simulator','file','rtsp','webcam')),
  source_uri       TEXT,
  frame_width      INTEGER NOT NULL DEFAULT 1280,
  frame_height     INTEGER NOT NULL DEFAULT 720,
  fps              REAL    NOT NULL DEFAULT 15,
  pixels_per_meter REAL    NOT NULL DEFAULT 25,
  active           INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE conflict_zones (
  id           INTEGER PRIMARY KEY,
  camera_id    INTEGER NOT NULL REFERENCES cameras(id),
  name         TEXT NOT NULL,
  zone_type    TEXT NOT NULL CHECK (zone_type IN ('crossing','junction_box','vehicle_lane')),
  polygon_json TEXT NOT NULL
);

CREATE TABLE detection_classes (
  coco_id           INTEGER PRIMARY KEY,
  label             TEXT NOT NULL,
  category          TEXT NOT NULL CHECK (category IN ('vru','vehicle')),
  risk_weight       REAL NOT NULL,
  typical_speed_mps REAL NOT NULL,
  display_color     TEXT NOT NULL
);

CREATE TABLE risk_config (
  key         TEXT PRIMARY KEY,
  value       REAL NOT NULL,
  description TEXT
);

CREATE TABLE traffic_signals (
  id               INTEGER PRIMARY KEY,
  junction_id      INTEGER NOT NULL REFERENCES junctions(id),
  code             TEXT NOT NULL UNIQUE,
  name             TEXT NOT NULL,
  yellow_s         REAL NOT NULL DEFAULT 3,
  all_red_s        REAL NOT NULL DEFAULT 2,
  min_green_s      REAL NOT NULL DEFAULT 8,
  max_preempt_hold REAL NOT NULL DEFAULT 30,
  initial_offset_s REAL NOT NULL DEFAULT 0
);

CREATE TABLE signal_phases (
  id             INTEGER PRIMARY KEY,
  signal_id      INTEGER NOT NULL REFERENCES traffic_signals(id),
  phase_order    INTEGER NOT NULL,
  phase_name     TEXT NOT NULL,
  green_approach TEXT NOT NULL CHECK (green_approach IN ('NS','EW')),
  duration_s     REAL NOT NULL,
  UNIQUE (signal_id, phase_order)
);

CREATE TABLE hospitals (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  lat  REAL NOT NULL,
  lon  REAL NOT NULL
);

CREATE TABLE ambulances (
  id               INTEGER PRIMARY KEY,
  call_sign        TEXT NOT NULL UNIQUE,
  status           TEXT NOT NULL DEFAULT 'idle' CHECK (status IN ('idle','dispatched','en_route','arrived')),
  lat              REAL NOT NULL,
  lon              REAL NOT NULL,
  speed_kmh        REAL NOT NULL DEFAULT 0,
  heading_deg      REAL NOT NULL DEFAULT 0,
  emergency_active INTEGER NOT NULL DEFAULT 0,
  last_update      TEXT
);

CREATE TABLE routes (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  hospital_id INTEGER NOT NULL REFERENCES hospitals(id)
);

CREATE TABLE route_waypoints (
  route_id INTEGER NOT NULL REFERENCES routes(id),
  seq      INTEGER NOT NULL,
  lat      REAL NOT NULL,
  lon      REAL NOT NULL,
  PRIMARY KEY (route_id, seq)
);

CREATE TABLE route_signals (
  route_id  INTEGER NOT NULL REFERENCES routes(id),
  seq       INTEGER NOT NULL,
  signal_id INTEGER NOT NULL REFERENCES traffic_signals(id),
  approach  TEXT NOT NULL CHECK (approach IN ('NS','EW')),
  PRIMARY KEY (route_id, seq)
);

CREATE TABLE ambulance_runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ambulance_id INTEGER NOT NULL REFERENCES ambulances(id),
  route_id     INTEGER NOT NULL REFERENCES routes(id),
  mode         TEXT NOT NULL CHECK (mode IN ('baseline','priority')),
  started_at   TEXT NOT NULL,
  ended_at     TEXT,
  duration_s   REAL,
  stops_count  INTEGER,
  total_wait_s REAL,
  sim_speed    REAL NOT NULL DEFAULT 1,
  is_seed      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE ambulance_run_signal_log (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id         INTEGER NOT NULL REFERENCES ambulance_runs(id) ON DELETE CASCADE,
  signal_id      INTEGER NOT NULL REFERENCES traffic_signals(id),
  arrival_s      REAL NOT NULL,
  phase_on_arrival TEXT NOT NULL,
  wait_s         REAL NOT NULL DEFAULT 0,
  preempted      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE events (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  camera_id      INTEGER NOT NULL REFERENCES cameras(id),
  ts             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  event_type     TEXT NOT NULL CHECK (event_type IN ('warning','critical','near_miss')),
  severity       INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 3),
  ttc_s          REAL,
  min_distance_m REAL,
  vru_class      TEXT NOT NULL,
  vehicle_class  TEXT NOT NULL,
  vru_track_id   INTEGER,
  vehicle_track_id INTEGER,
  confidence     REAL,
  zone_name      TEXT,
  latency_ms     REAL,
  acknowledged   INTEGER NOT NULL DEFAULT 0,
  is_seed        INTEGER NOT NULL DEFAULT 0,
  details_json   TEXT
);
CREATE INDEX idx_events_ts   ON events(ts);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_zone ON events(zone_name);

CREATE TABLE test_scenarios (
  id               INTEGER PRIMARY KEY,
  code             TEXT NOT NULL UNIQUE,
  name             TEXT NOT NULL,
  description      TEXT,
  scenario_type    TEXT NOT NULL CHECK (scenario_type IN ('road_safety','ambulance')),
  expected_outcome TEXT NOT NULL CHECK (expected_outcome IN ('alert','critical_alert','no_alert','priority_granted')),
  params_json      TEXT NOT NULL
);

CREATE TABLE scenario_results (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  scenario_id INTEGER NOT NULL REFERENCES test_scenarios(id),
  run_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  detected    INTEGER NOT NULL DEFAULT 0,
  alerted     INTEGER NOT NULL DEFAULT 0,
  false_alert INTEGER NOT NULL DEFAULT 0,
  response_ms REAL,
  passed      INTEGER NOT NULL DEFAULT 0,
  notes       TEXT
);

CREATE TABLE warning_units (
  id          INTEGER PRIMARY KEY,
  junction_id INTEGER NOT NULL REFERENCES junctions(id),
  name        TEXT NOT NULL,
  unit_type   TEXT NOT NULL CHECK (unit_type IN ('web','led')),
  active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE system_settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE VIEW v_event_summary AS
  SELECT date(ts) AS day, event_type, COUNT(*) AS n
  FROM events GROUP BY date(ts), event_type;

CREATE VIEW v_hotspots AS
  SELECT c.name AS camera, e.zone_name, COUNT(*) AS n_events,
         SUM(CASE WHEN e.event_type='near_miss' THEN 1 ELSE 0 END) AS near_misses,
         ROUND(AVG(e.ttc_s),2) AS avg_ttc_s
  FROM events e JOIN cameras c ON c.id = e.camera_id
  GROUP BY c.name, e.zone_name;

CREATE VIEW v_ambulance_comparison AS
  SELECT mode, COUNT(*) AS runs,
         ROUND(AVG(duration_s),1)  AS avg_duration_s,
         ROUND(AVG(stops_count),2) AS avg_stops,
         ROUND(AVG(total_wait_s),1) AS avg_wait_s
  FROM ambulance_runs WHERE ended_at IS NOT NULL GROUP BY mode;
