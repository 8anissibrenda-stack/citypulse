"""Test signal controller."""

import pytest
from app.signals.controller import SignalController, Phase, Colour


@pytest.fixture
def controller():
    ctrl = SignalController()
    phases = [
        Phase(1, "NS Green", "NS", 20),
        Phase(2, "EW Green", "EW", 20)
    ]
    ctrl.add_signal(1, phases, yellow_s=3, all_red_s=2, min_green_s=5, max_preempt_hold=30)
    return ctrl


def test_normal_cycle(controller):
    """Test standard GREEN -> YELLOW -> RED transition."""
    # Starts NS Green
    assert controller.get_colour(1, "NS") == Colour.GREEN
    assert controller.get_colour(1, "EW") == Colour.RED
    
    controller.simulate_until(20.1)
    assert controller.get_colour(1, "NS") == Colour.YELLOW
    
    controller.simulate_until(23.2)
    assert controller.get_colour(1, "NS") == Colour.RED
    assert controller.get_colour(1, "EW") == Colour.RED # All red
    
    controller.simulate_until(25.3)
    assert controller.get_colour(1, "NS") == Colour.RED
    assert controller.get_colour(1, "EW") == Colour.GREEN


def test_never_both_green(controller):
    """Ensure NS and EW are never both green."""
    # Step through 100 seconds checking every 0.1s
    for _ in range(1000):
        controller.tick(0.1)
        c_ns = controller.get_colour(1, "NS")
        c_ew = controller.get_colour(1, "EW")
        assert not (c_ns == Colour.GREEN and c_ew == Colour.GREEN)


def test_preemption_hold_green(controller):
    """Pre-emption on already green approach extends it."""
    controller.simulate_until(15.0) # NS is green
    req = controller.request_priority(1, "NS", eta_s=10.0)
    
    assert req.outcome == "granted"
    
    # Advance past normal green end (20s)
    controller.simulate_until(25.0)
    
    # Should still be green because it's held
    assert controller.get_colour(1, "NS") == Colour.GREEN


def test_preemption_switch(controller):
    """Pre-emption forces a safe switch to the other approach."""
    controller.simulate_until(5.0) # NS is green
    
    # Request EW green. Requires 3s yellow + 2s red = 5s
    req = controller.request_priority(1, "EW", eta_s=10.0)
    assert req.outcome == "granted"
    
    # At 5.1s, NS should be yellow
    controller.tick(0.1)
    assert controller.get_colour(1, "NS") == Colour.YELLOW
    
    # After 3s yellow + 2s red (total +5.0)
    controller.simulate_until(10.1)
    assert controller.get_colour(1, "NS") == Colour.RED
    assert controller.get_colour(1, "EW") == Colour.GREEN


def test_preemption_late(controller):
    """Pre-emption is late if ETA is too short."""
    controller.simulate_until(5.0) # NS is green
    
    # Request EW green. Requires 5s, but ETA is 2s
    req = controller.request_priority(1, "EW", eta_s=2.0)
    assert req.outcome == "late"
    
    # It still initiates the switch safely
    controller.tick(0.1)
    assert controller.get_colour(1, "NS") == Colour.YELLOW
