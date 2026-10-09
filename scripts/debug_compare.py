import sys
import requests

def run():
    r = requests.post("http://127.0.0.1:8000/api/ambulance/compare")
    if r.status_code != 200:
        print(f"Error: {r.status_code} {r.text}")
        return
    data = r.json()
    b_ticks = data["baseline"]["ticks"]
    p_ticks = data["priority"]["ticks"]
    
    print("t | BASE y / S1 S2 S3 / blocked | PRIO y / S1 S2 S3 / ring")
    print("-" * 65)
    for i in range(0, max(len(b_ticks), len(p_ticks)), 10):
        b = b_ticks[i] if i < len(b_ticks) else b_ticks[-1]
        p = p_ticks[i] if i < len(p_ticks) else p_ticks[-1]
        
        b_sigs = f"{b['signals'][0][0].upper()}{b['signals'][1][0].upper()}{b['signals'][2][0].upper()}"
        p_sigs = f"{p['signals'][0][0].upper()}{p['signals'][1][0].upper()}{p['signals'][2][0].upper()}"
        
        p_ring = "".join(["1" if x else "0" for x in p["priority_active"]])
        
        print(f"{b['t']:4.1f} | "
              f"{b['y_px']:5.1f} / {b_sigs} / {str(b['blocked'])[0]:1}       | "
              f"{p['y_px']:5.1f} / {p_sigs} / {p_ring}")

if __name__ == "__main__":
    run()
