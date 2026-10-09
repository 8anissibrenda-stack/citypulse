"""Run all seeded test scenarios and print metrics."""

import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path so we can import app
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from app import db
from app.routers.scenarios import run_road_safety_scenario, run_ambulance_scenario

logging.basicConfig(level=logging.ERROR) # suppress verbose output

def main():
    print("=" * 60)
    print(" CityPulse Validation Scenarios")
    print("=" * 60)
    
    scenarios = db.query_all("SELECT * FROM test_scenarios ORDER BY id")
    if not scenarios:
        print("No scenarios found in database.")
        return
        
    results = []
    
    for scenario in scenarios:
        print(f"Running {scenario['code']}: {scenario['name']}...")
        if scenario["scenario_type"] == "road_safety":
            result = run_road_safety_scenario(scenario)
        elif scenario["scenario_type"] == "ambulance":
            result = run_ambulance_scenario(scenario)
        else:
            continue
            
        result["scenario"] = scenario
        results.append(result)
        
        status = "PASS" if result["passed"] else "FAIL"
        print(f"  -> {status} ({result['notes']})")
    
    print("\n" + "=" * 60)
    print(" Validation Metrics")
    print("=" * 60)
    
    rs_results = [r for r in results if r["scenario"]["scenario_type"] == "road_safety"]
    amb_results = [r for r in results if r["scenario"]["scenario_type"] == "ambulance"]
    
    # Road Safety Metrics
    if rs_results:
        detection_acc = sum(1 for r in rs_results if r["detected"]) / len(rs_results) * 100
        
        # Warning accuracy: % of high-risk (expect alert/critical) that actually alerted
        high_risk = [r for r in rs_results if r["scenario"]["expected_outcome"] in ("alert", "critical_alert")]
        warning_acc = sum(1 for r in high_risk if r["alerted"]) / len(high_risk) * 100 if high_risk else 100
        
        false_alerts = sum(1 for r in rs_results if r["false_alert"])
        
        avg_resp = sum(r["response_ms"] for r in rs_results) / len(rs_results)
        
        print("Road Safety Flow:")
        print(f"  Detection Accuracy:     {detection_acc:.1f}%")
        print(f"  Warning Accuracy:       {warning_acc:.1f}%")
        print(f"  False Alerts:           {false_alerts}")
        print(f"  Mean Response Time:     {avg_resp:.1f} ms")
        
    # Ambulance Metrics
    if amb_results:
        # Extract time saved from notes (hacky but works for this script)
        # notes: Baseline: 168.2s/3 stops, Priority: 124.0s/0 stops
        total_base = 0
        total_prio = 0
        for r in amb_results:
            notes = r["notes"]
            try:
                parts = notes.split(", ")
                b_str = parts[0].split(" ")[1].replace("s", "").split("/")[0]
                p_str = parts[1].split(" ")[1].replace("s", "").split("/")[0]
                total_base += float(b_str)
                total_prio += float(p_str)
            except:
                pass
                
        improvement = ((total_base - total_prio) / total_base * 100) if total_base > 0 else 0
        
        print("\nAmbulance Flow:")
        print(f"  Journey Time Improv.:   {improvement:.1f}%")
        
    print("=" * 60)

if __name__ == "__main__":
    main()
