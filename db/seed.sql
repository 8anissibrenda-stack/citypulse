INSERT INTO junctions (id, code, name, lat, lon, description) VALUES
 (1,'J1','Demo Junction A',20.0030,78.0000,'Signalised junction, ambulance route'),
 (2,'J2','Demo Junction B (monitored)',20.0060,78.0000,'Camera-monitored junction with zebra crossing'),
 (3,'J3','Demo Junction C',20.0090,78.0000,'Signalised junction, ambulance route');

INSERT INTO cameras (id, junction_id, name, source_type, source_uri, frame_width, frame_height, fps, pixels_per_meter, active) VALUES
 (1,2,'J2 Simulator Camera','simulator',NULL,1280,720,15,25,1),
 (2,2,'J2 Video File Camera','file','data/sample_junction.mp4',1280,720,25,25,0);

INSERT INTO conflict_zones (id, camera_id, name, zone_type, polygon_json) VALUES
 (1,1,'Zebra crossing','crossing','[[560,230],[700,230],[700,590],[560,590]]'),
 (2,1,'Vehicle lane','vehicle_lane','[[0,330],[1280,330],[1280,490],[0,490]]'),
 (3,1,'Junction box','junction_box','[[520,300],[740,300],[740,520],[520,520]]'),
 (4,2,'Zebra crossing','crossing','[[560,230],[700,230],[700,590],[560,590]]'),
 (5,2,'Vehicle lane','vehicle_lane','[[0,330],[1280,330],[1280,490],[0,490]]'),
 (6,2,'Junction box','junction_box','[[520,300],[740,300],[740,520],[520,520]]');

INSERT INTO detection_classes (coco_id, label, category, risk_weight, typical_speed_mps, display_color) VALUES
 (0,'person','vru',1.0,1.4,'#FF9800'),
 (1,'bicycle','vru',1.0,4.5,'#FFC107'),
 (2,'car','vehicle',0.6,10.0,'#2196F3'),
 (3,'motorcycle','vehicle',0.8,12.0,'#9C27B0'),
 (5,'bus','vehicle',0.7,8.0,'#3F51B5'),
 (7,'truck','vehicle',0.7,8.0,'#607D8B');

INSERT INTO risk_config (key, value, description) VALUES
 ('ttc_warning_s',3.0,'Time-to-collision at or below this raises a WARNING'),
 ('ttc_critical_s',1.5,'Time-to-collision at or below this raises a CRITICAL alert'),
 ('prediction_horizon_s',5.0,'How far ahead trajectories are predicted'),
 ('collision_radius_m',1.5,'Predicted closest-approach distance below which a conflict exists'),
 ('min_confidence',0.45,'Detections below this confidence are ignored'),
 ('min_consecutive_frames',3,'Frames a conflict must persist before alerting (debounce)'),
 ('alert_cooldown_s',4.0,'Minimum seconds between alerts for the same VRU-vehicle pair'),
 ('near_miss_ttc_s',1.0,'Conflict with TTC below this that resolves without contact is a near miss'),
 ('near_miss_distance_m',1.2,'Closest approach below this is a near miss'),
 ('min_vehicle_speed_mps',1.5,'Vehicles slower than this are ignored as stopped/queued'),
 ('velocity_smoothing_alpha',0.4,'EMA factor for velocity smoothing'),
 ('vru_stationary_speed_mps',0.3,'VRUs slower than this are treated as standing'),
 ('snapshot_retention_days',7,'Delete stored snapshots older than this'),
 ('event_retention_days',30,'Delete events older than this (seed events excluded)');

INSERT INTO traffic_signals (id, junction_id, code, name, yellow_s, all_red_s, min_green_s, max_preempt_hold, initial_offset_s) VALUES
 (1,1,'S1','Signal J1',3,2,8,30,0),
 (2,2,'S2','Signal J2',3,2,8,30,48),
 (3,3,'S3','Signal J3',3,2,8,30,40);

INSERT INTO signal_phases (id, signal_id, phase_order, phase_name, green_approach, duration_s) VALUES
 (1,1,1,'North-South green','NS',25),(2,1,2,'East-West green','EW',20),
 (3,2,1,'North-South green','NS',25),(4,2,2,'East-West green','EW',20),
 (5,3,1,'North-South green','NS',25),(6,3,2,'East-West green','EW',20);

INSERT INTO hospitals (id, name, lat, lon) VALUES (1,'Demo City Hospital',20.0120,78.0000);

INSERT INTO ambulances (id, call_sign, status, lat, lon, speed_kmh, heading_deg, emergency_active, last_update) VALUES
 (1,'AMB-01','idle',20.0000,78.0000,0,0,0,NULL),
 (2,'AMB-02','idle',20.0000,78.0000,0,0,0,NULL);

INSERT INTO routes (id, name, hospital_id) VALUES (1,'Depot to Demo City Hospital (north)',1);

INSERT INTO route_waypoints (route_id, seq, lat, lon) VALUES
 (1,1,20.0000,78.0000),(1,2,20.0010,78.0000),(1,3,20.0020,78.0000),(1,4,20.0030,78.0000),
 (1,5,20.0040,78.0000),(1,6,20.0050,78.0000),(1,7,20.0060,78.0000),(1,8,20.0070,78.0000),
 (1,9,20.0080,78.0000),(1,10,20.0090,78.0000),(1,11,20.0100,78.0000),(1,12,20.0110,78.0000),
 (1,13,20.0120,78.0000);

INSERT INTO route_signals (route_id, seq, signal_id, approach) VALUES
 (1,1,1,'NS'),(1,2,2,'NS'),(1,3,3,'NS');

INSERT INTO warning_units (id, junction_id, name, unit_type, active) VALUES
 (1,2,'J2 Driver Display (web)','web',1),
 (2,2,'J2 LED Board (optional hardware)','led',0);

INSERT INTO system_settings (key, value) VALUES
 ('active_camera_id','1'),
 ('pipeline_mode','simulator'),
 ('store_snapshots','0'),
 ('blur_snapshots','1'),
 ('priority_trigger_distance_m','250'),
 ('ambulance_cruise_kmh','40'),
 ('driver_compliance_pct', '0.85');

INSERT INTO test_scenarios (id, code, name, description, scenario_type, expected_outcome, params_json) VALUES
 (1,'SC01','Approaching pedestrian','Pedestrian steps toward the crossing while a car approaches at moderate speed','road_safety','alert',
  '{"duration_s":10,"actors":[{"cls":"person","start_px":[630,250],"velocity_mps":[0,1.4]},{"cls":"car","start_px":[0,410],"velocity_mps":[6,0]}]}'),
 (2,'SC02','Approaching cyclist','Cyclist rides into the crossing as a car arrives','road_safety','alert',
  '{"duration_s":8,"actors":[{"cls":"bicycle","start_px":[630,200],"velocity_mps":[0,4.5]},{"cls":"car","start_px":[200,410],"velocity_mps":[10,0]}]}'),
 (3,'SC03','Safe crossing','Pedestrian crosses well after the car has passed; no alert expected','road_safety','no_alert',
  '{"duration_s":10,"actors":[{"cls":"person","start_px":[630,230],"velocity_mps":[0,1.4]},{"cls":"car","start_px":[0,410],"velocity_mps":[10,0]}]}'),
 (4,'SC04','High-risk crossing','Pedestrian and fast car on a collision course','road_safety','critical_alert',
  '{"duration_s":8,"actors":[{"cls":"person","start_px":[630,300],"velocity_mps":[0,1.4]},{"cls":"car","start_px":[0,410],"velocity_mps":[8,0]}]}'),
 (5,'SC05','Approaching ambulance at junction','Ambulance approaches a red signal; priority must turn it green in time','ambulance','priority_granted',
  '{"route_id":1,"mode":"priority","sim_speed":10,"max_allowed_stops":0}'),
 (6,'SC06','Multiple vehicles obstructing ambulance','Queued vehicles ahead of the junction; priority must clear the signal before the ambulance reaches the queue','ambulance','priority_granted',
  '{"route_id":1,"mode":"priority","sim_speed":10,"queue_vehicles_at_signal":2,"max_allowed_stops":0}');

INSERT INTO events (camera_id, ts, event_type, severity, ttc_s, min_distance_m, vru_class, vehicle_class, vru_track_id, vehicle_track_id, confidence, zone_name, latency_ms, is_seed, details_json) VALUES
 (1,'2026-10-01T08:15:22.000Z','warning',2,2.7,1.1,'person','car',12,7,0.82,'Zebra crossing',74,1,'{"seed":true}'),
 (1,'2026-10-01T08:42:10.000Z','critical',3,1.2,0.6,'person','motorcycle',19,15,0.77,'Zebra crossing',81,1,'{"seed":true}'),
 (1,'2026-10-01T09:05:48.000Z','near_miss',3,0.8,0.9,'bicycle','car',23,21,0.88,'Zebra crossing',69,1,'{"seed":true}'),
 (1,'2026-10-02T17:31:05.000Z','warning',2,2.9,1.3,'bicycle','truck',31,28,0.71,'Junction box',92,1,'{"seed":true}'),
 (1,'2026-10-02T18:02:44.000Z','critical',3,1.4,0.8,'person','car',35,33,0.85,'Zebra crossing',77,1,'{"seed":true}'),
 (1,'2026-10-03T07:55:30.000Z','warning',1,3.0,1.5,'person','bus',41,39,0.66,'Zebra crossing',88,1,'{"seed":true}'),
 (1,'2026-10-03T19:12:19.000Z','near_miss',3,0.7,0.7,'person','car',47,44,0.9,'Zebra crossing',71,1,'{"seed":true}'),
 (1,'2026-10-04T12:20:03.000Z','warning',2,2.5,1.0,'bicycle','car',52,50,0.79,'Junction box',83,1,'{"seed":true}'),
 (1,'2026-10-05T08:48:57.000Z','critical',3,1.3,0.7,'person','car',58,55,0.83,'Zebra crossing',76,1,'{"seed":true}'),
 (1,'2026-10-05T18:40:11.000Z','warning',2,2.8,1.2,'person','motorcycle',63,60,0.74,'Zebra crossing',90,1,'{"seed":true}'),
 (1,'2026-10-06T09:10:36.000Z','near_miss',3,0.9,1.0,'bicycle','truck',68,66,0.81,'Junction box',85,1,'{"seed":true}'),
 (1,'2026-10-07T17:55:02.000Z','warning',2,2.6,1.1,'person','car',73,70,0.87,'Zebra crossing',72,1,'{"seed":true}');

INSERT INTO ambulance_runs (ambulance_id, route_id, mode, started_at, ended_at, duration_s, stops_count, total_wait_s, sim_speed, is_seed) VALUES
 (1,1,'baseline','2026-10-02T10:00:00.000Z','2026-10-02T10:02:48.000Z',168.2,3,52.0,10,1),
 (1,1,'baseline','2026-10-02T10:10:00.000Z','2026-10-02T10:12:52.000Z',171.5,3,55.0,10,1),
 (1,1,'baseline','2026-10-02T10:20:00.000Z','2026-10-02T10:22:46.000Z',165.9,2,41.0,10,1),
 (1,1,'priority','2026-10-02T10:30:00.000Z','2026-10-02T10:32:04.000Z',124.0,0,0.0,10,1),
 (1,1,'priority','2026-10-02T10:40:00.000Z','2026-10-02T10:42:06.000Z',126.3,0,0.0,10,1),
 (1,1,'priority','2026-10-02T10:50:00.000Z','2026-10-02T10:52:03.000Z',123.1,0,0.0,10,1);
