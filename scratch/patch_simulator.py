import sys

with open("app/vision/simulator.py", "r") as f:
    content = f.read()

# Add RiskAlert import
content = content.replace("from app.vision.types import TrackedObject", "from app.vision.types import TrackedObject, RiskAlert")

# Update _Actor
old_actor = """@dataclass
class _Actor:
    \"\"\"An actor moving in the simulated scene.\"\"\"
    track_id: int
    cls: str
    x: float
    y: float
    vx: float  # pixels per second
    vy: float
    alive: bool = True
    spawn_t: float = 0.0"""

new_actor = """@dataclass
class _Actor:
    \"\"\"An actor moving in the simulated scene.\"\"\"
    track_id: int
    cls: str
    x: float
    y: float
    vx: float  # pixels per second
    vy: float
    alive: bool = True
    spawn_t: float = 0.0
    target_speed: float = 0.0
    reaction_time: float = 0.0
    reaction_timer: float = 0.0
    compliance: bool = True
    state: str = "cruise\"\"\""""

content = content.replace(old_actor, new_actor)

# Add driver_compliance and _active_alerts
init_target = """        self._last_conflict_t = 8.0

        # Pre-render the background once"""

init_replace = """        self._last_conflict_t = 8.0
        self._active_alerts: list[RiskAlert] = []
        try:
            from app import db
            val = db.query_one("SELECT value FROM system_settings WHERE key='driver_compliance_pct'")
            self.driver_compliance = float(val["value"]) if val else 0.85
        except Exception:
            self.driver_compliance = 0.85

        # Pre-render the background once"""
content = content.replace(init_target, init_replace)

# Add set_active_alerts
set_alerts = """    def set_active_alerts(self, alerts: list[RiskAlert]) -> None:
        self._active_alerts = alerts

    # ------------------------------------------------------------------
    # Scenario mode"""
content = content.replace("    # ------------------------------------------------------------------\n    # Scenario mode", set_alerts)

# Update step logic
step_target = """        # Move all actors
        for actor in self._actors:
            actor.x += actor.vx * dt
            actor.y += actor.vy * dt
            # Remove off-screen actors
            if actor.x < -100 or actor.x > WIDTH + 100 or actor.y < -100 or actor.y > HEIGHT + 100:
                actor.alive = False"""

step_replace = """        # Move all actors
        for actor in self._actors:
            if self._scenario_actors is None:
                if actor.cls in VEHICLE_CLASSES:
                    has_alert = any(a.vehicle.track_id == actor.track_id for a in self._active_alerts)
                    
                    if has_alert and actor.compliance:
                        actor.reaction_timer += dt
                        if actor.reaction_timer >= actor.reaction_time:
                            actor.state = "yielding"
                    else:
                        actor.reaction_timer = 0.0
                        
                    vru_in_crossing = False
                    for other in self._actors:
                        if other.cls in VRU_CLASSES:
                            px = other.x + other.vx * 2.0
                            py = other.y + other.vy * 2.0
                            in_now = CROSSING_X1 <= other.x <= CROSSING_X2 and CROSSING_Y1 <= other.y <= CROSSING_Y2
                            in_2s = CROSSING_X1 <= px <= CROSSING_X2 and CROSSING_Y1 <= py <= CROSSING_Y2
                            if in_now or in_2s:
                                vru_in_crossing = True
                                break
                    
                    if vru_in_crossing and actor.compliance:
                        actor.state = "yielding"
                    elif not has_alert:
                        actor.state = "cruise"
                        
                    dist_to_car_ahead = float('inf')
                    for other in self._actors:
                        if other.track_id != actor.track_id and other.cls in VEHICLE_CLASSES:
                            if actor.vx > 0 and other.vx >= 0 and other.x > actor.x and abs(other.y - actor.y) < 40:
                                dist_to_car_ahead = min(dist_to_car_ahead, other.x - actor.x)
                            elif actor.vx < 0 and other.vx <= 0 and other.x < actor.x and abs(other.y - actor.y) < 40:
                                dist_to_car_ahead = min(dist_to_car_ahead, actor.x - other.x)
                    
                    gap_needed = 70 + abs(actor.vx) * 0.5
                    if dist_to_car_ahead < gap_needed:
                        actor.state = "yielding"
                        
                    braking_accel = 5.0 * self.ppm
                    accel = 2.0 * self.ppm
                    
                    if actor.state == "yielding":
                        stop_line_x = CROSSING_X1 - 40 if actor.vx > 0 else CROSSING_X2 + 40
                        dist_to_stop = (stop_line_x - actor.x) if actor.vx > 0 else (actor.x - stop_line_x)
                        
                        if dist_to_car_ahead < gap_needed:
                            req_decel = braking_accel
                        elif dist_to_stop > 0 and dist_to_stop < 200:
                            req_decel = (actor.vx**2) / (2 * dist_to_stop) if dist_to_stop > 5 else braking_accel
                            req_decel = min(req_decel, braking_accel)
                        elif dist_to_stop <= 0 and dist_to_stop > -40:
                            req_decel = braking_accel
                        else:
                            req_decel = 0.0
                            
                        if actor.vx > 0:
                            actor.vx = max(0.0, actor.vx - req_decel * dt)
                        else:
                            actor.vx = min(0.0, actor.vx + req_decel * dt)
                    else:
                        if actor.vx >= 0:
                            actor.vx = min(actor.target_speed, actor.vx + accel * dt)
                        else:
                            actor.vx = max(-actor.target_speed, actor.vx - accel * dt)
                            
                elif actor.cls in VRU_CLASSES:
                    if (actor.vy > 0 and ROAD_Y1 - 15 <= actor.y <= ROAD_Y1) or \\
                       (actor.vy < 0 and ROAD_Y2 <= actor.y <= ROAD_Y2 + 15):
                        car_close = False
                        for other in self._actors:
                            if other.cls in VEHICLE_CLASSES and abs(other.vx) > 1.0:
                                if abs(other.x - actor.x) < 300:
                                    if (other.vx > 0 and other.x < actor.x) or (other.vx < 0 and other.x > actor.x):
                                        car_close = True
                                        break
                        if car_close:
                            actor.vy = 0.0
                        else:
                            actor.vy = actor.target_speed if actor.y < ROAD_Y1 else -actor.target_speed

            actor.x += actor.vx * dt
            actor.y += actor.vy * dt
            if actor.x < -100 or actor.x > WIDTH + 100 or actor.y < -100 or actor.y > HEIGHT + 100:
                actor.alive = False"""
content = content.replace(step_target, step_replace)

# Update _spawn_continuous for new actor attributes
spawn_target1 = """            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls=cls,
                x=x, y=y, vx=vx, vy=0, spawn_t=self._t,
            ))"""
spawn_replace1 = """            compliance = self._rng.random() < self.driver_compliance
            reaction = self._rng.uniform(0.5, 1.0)
            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls=cls,
                x=x, y=y, vx=vx, vy=0, spawn_t=self._t,
                target_speed=abs(vx), reaction_time=reaction, compliance=compliance
            ))"""
content = content.replace(spawn_target1, spawn_replace1)

spawn_target2 = """            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="car",
                x=car_x, y=car_y, vx=car_vx, vy=0, spawn_t=self._t,
            ))
            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="person",
                x=ped_x, y=ped_y, vx=0, vy=ped_vy, spawn_t=self._t,
            ))"""
spawn_replace2 = """            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="car",
                x=car_x, y=car_y, vx=car_vx, vy=0, spawn_t=self._t,
                target_speed=abs(car_vx), reaction_time=0.8, compliance=False
            ))
            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="person",
                x=ped_x, y=ped_y, vx=0, vy=ped_vy, spawn_t=self._t,
                target_speed=abs(ped_vy)
            ))"""
content = content.replace(spawn_target2, spawn_replace2)

spawn_target3 = """            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="person",
                x=x, y=y, vx=0, vy=vy, spawn_t=self._t,
            ))"""
spawn_replace3 = """            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="person",
                x=x, y=y, vx=0, vy=vy, spawn_t=self._t,
                target_speed=abs(vy)
            ))"""
content = content.replace(spawn_target3, spawn_replace3)

spawn_target4 = """            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="bicycle",
                x=x, y=y, vx=0, vy=vy, spawn_t=self._t,
            ))"""
spawn_replace4 = """            self._actors.append(_Actor(
                track_id=self._alloc_id(), cls="bicycle",
                x=x, y=y, vx=0, vy=vy, spawn_t=self._t,
                target_speed=abs(vy)
            ))"""
content = content.replace(spawn_target4, spawn_replace4)

with open("app/vision/simulator.py", "w") as f:
    f.write(content)
