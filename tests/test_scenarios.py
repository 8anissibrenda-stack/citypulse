"""Test all seeded scenarios."""

import pytest
from app import db
from app.routers.scenarios import run_road_safety_scenario, run_ambulance_scenario

def test_all_scenarios():
    """Run all seeded scenarios and verify they pass."""
    # Setup DB connection if needed
    db.get_conn()
    
    scenarios = db.query_all("SELECT * FROM test_scenarios ORDER BY id")
    assert len(scenarios) > 0, "No scenarios found in seed data"
    
    for scenario in scenarios:
        if scenario["scenario_type"] == "road_safety":
            result = run_road_safety_scenario(scenario)
        elif scenario["scenario_type"] == "ambulance":
            result = run_ambulance_scenario(scenario)
        else:
            continue
            
        assert result["passed"], f"Scenario {scenario['code']} failed: {result['notes']}"
