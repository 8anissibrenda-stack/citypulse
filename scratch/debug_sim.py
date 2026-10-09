import sys
import os

sys.path.append(os.getcwd())
from app.vision.simulator import JunctionSimulator

sim = JunctionSimulator(fps=15, pixels_per_meter=25, seed=42)

for frame in range(60 * 15):
    _, objects = sim.step(1.0/15.0)
    for o in objects:
        if o.category == 'vehicle' and hasattr(o, 'vx') and (o.vx**2 + getattr(o, 'vy', 0)**2)**0.5 < 1.0:
            print(f"Frame {frame}: Vehicle {o.track_id} yielded at {o.cx}, {o.cy}. VRU in crossing?")
            vrus_in_crossing = False
            for v in objects:
                if v.category == 'vru' and 560 <= v.cx <= 700 and 230 <= v.cy <= 590:
                    vrus_in_crossing = True
                    print(f"  VRU {v.track_id} at {v.cx}, {v.cy}, vy={v.vy}")
            print(f"  VRU in crossing: {vrus_in_crossing}")
            
            # Check cars ahead
            for v in objects:
                if v.category == 'vehicle' and v.track_id != o.track_id:
                    print(f"  Other car {v.track_id} at {v.cx}, {v.cy}, vx={v.vx}")

            # Let's run a few more frames and watch this vehicle
            yield_id = o.track_id
            for f2 in range(frame+1, frame + 60*15):
                _, objs2 = sim.step(1.0/15.0)
                v_obj = next((x for x in objs2 if x.track_id == yield_id), None)
                if not v_obj:
                    print(f"Vehicle {yield_id} disappeared")
                    sys.exit(0)
                if (v_obj.vx**2 + getattr(v_obj, 'vy', 0)**2)**0.5 > 2.0:
                    print(f"Vehicle {yield_id} accelerated at frame {f2}, speed={v_obj.vx}")
                    sys.exit(0)
                if f2 % 30 == 0:
                    print(f"Frame {f2}: Vehicle {yield_id} speed={v_obj.vx}. VRUs in crossing:")
                    for v in objs2:
                        if v.category == 'vru' and 560 <= v.cx <= 700 and 230 <= v.cy <= 590:
                            print(f"  VRU {v.track_id} at {v.cx}, {v.cy}, vy={v.vy}")
            print("Did not accelerate!")
            sys.exit(1)
