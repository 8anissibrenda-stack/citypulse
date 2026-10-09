"""Traffic-signal state machine with emergency pre-emption.

Each signal cycles through its phases:
    GREEN (duration_s) → YELLOW (yellow_s) → ALL_RED (all_red_s) → next phase

The controller supports a time-scale factor so ambulance runs can be
accelerated (e.g. 10x), and a deterministic ``simulate_until(t)`` for tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class Colour(str, Enum):
    """Traffic light colour."""
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass
class Phase:
    """One phase of a signal cycle."""
    phase_order: int
    phase_name: str
    green_approach: str  # 'NS' or 'EW'
    duration_s: float


@dataclass
class PreemptionRequest:
    """A record of a pre-emption request and its outcome."""
    signal_id: int
    approach: str
    eta_s: float
    requested_at: float  # sim time
    outcome: str = "pending"  # 'granted', 'late', 'denied', 'already_green'


@dataclass
class _SignalState:
    """Internal runtime state for one signal."""
    signal_id: int
    phases: list[Phase]
    yellow_s: float
    all_red_s: float
    min_green_s: float
    max_preempt_hold: float
    initial_offset_s: float

    # Runtime
    current_phase_idx: int = 0
    phase_elapsed: float = 0.0
    sub_state: str = "green"  # 'green', 'yellow', 'all_red'
    sub_elapsed: float = 0.0

    # Pre-emption
    preempt_active: bool = False
    preempt_approach: str = ""
    preempt_hold_elapsed: float = 0.0
    preempt_pending: PreemptionRequest | None = None

    # For the cycle
    total_cycle_s: float = 0.0

    def __post_init__(self) -> None:
        self.total_cycle_s = sum(
            p.duration_s + self.yellow_s + self.all_red_s for p in self.phases
        )

    @property
    def current_phase(self) -> Phase:
        """Return the current phase."""
        return self.phases[self.current_phase_idx]

    def colour_for(self, approach: str) -> Colour:
        """Return the displayed colour for the given approach (NS or EW)."""
        if self.sub_state == "green" and self.current_phase.green_approach == approach:
            return Colour.GREEN
        if self.sub_state == "yellow" and self.current_phase.green_approach == approach:
            return Colour.YELLOW
        return Colour.RED

    def ns_colour(self) -> Colour:
        return self.colour_for("NS")

    def ew_colour(self) -> Colour:
        return self.colour_for("EW")


class SignalController:
    """Manages all traffic signals with deterministic timing.

    Usage::

        ctrl = SignalController()
        ctrl.add_signal(signal_id, phases, ...)
        ctrl.tick(dt)  # advance by dt seconds
        state = ctrl.get_state(signal_id)
    """

    def __init__(self, on_update: Callable[[int, dict], None] | None = None) -> None:
        """
        Args:
            on_update: Optional callback ``(signal_id, state_dict)`` called on
                       every state change (for WebSocket broadcast).
        """
        self._signals: dict[int, _SignalState] = {}
        self._time: float = 0.0
        self._on_update = on_update
        self._preemption_log: list[PreemptionRequest] = []

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def add_signal(
        self,
        signal_id: int,
        phases: list[Phase],
        yellow_s: float = 3.0,
        all_red_s: float = 2.0,
        min_green_s: float = 8.0,
        max_preempt_hold: float = 30.0,
        initial_offset_s: float = 0.0,
    ) -> None:
        """Register a signal with its phases and timing parameters."""
        state = _SignalState(
            signal_id=signal_id,
            phases=phases,
            yellow_s=yellow_s,
            all_red_s=all_red_s,
            min_green_s=min_green_s,
            max_preempt_hold=max_preempt_hold,
            initial_offset_s=initial_offset_s,
        )
        self._signals[signal_id] = state
        # Apply initial offset
        if initial_offset_s > 0:
            self._advance_signal(state, initial_offset_s, suppress_callback=True)

    # ------------------------------------------------------------------
    # Ticking
    # ------------------------------------------------------------------

    def tick(self, dt: float) -> None:
        """Advance all signals by ``dt`` seconds."""
        self._time += dt
        for state in self._signals.values():
            self._advance_signal(state, dt)

    def simulate_until(self, t: float) -> None:
        """Advance deterministically to time ``t`` in 0.1s steps."""
        step = 0.1
        while self._time < t - 1e-9:
            dt = min(step, t - self._time)
            self.tick(dt)

    def reset(self) -> None:
        """Reset all signals to t=0."""
        for state in self._signals.values():
            state.current_phase_idx = 0
            state.phase_elapsed = 0.0
            state.sub_state = "green"
            state.sub_elapsed = 0.0
            state.preempt_active = False
            state.preempt_approach = ""
            state.preempt_hold_elapsed = 0.0
            state.preempt_pending = None
            # Re-apply initial offset
            if state.initial_offset_s > 0:
                self._advance_signal(state, state.initial_offset_s, suppress_callback=True)
        self._time = 0.0
        self._preemption_log.clear()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_state(self, signal_id: int) -> dict:
        """Return the current state of a signal as a dict."""
        state = self._signals[signal_id]
        return {
            "signal_id": signal_id,
            "phase_name": state.current_phase.phase_name,
            "green_approach": state.current_phase.green_approach,
            "sub_state": state.sub_state,
            "ns_colour": state.ns_colour().value,
            "ew_colour": state.ew_colour().value,
            "preempt_active": state.preempt_active,
            "preempt_approach": state.preempt_approach,
            "time": round(self._time, 1),
        }

    def get_all_states(self) -> list[dict]:
        """Return state dicts for all signals."""
        return [self.get_state(sid) for sid in sorted(self._signals)]

    def get_colour(self, signal_id: int, approach: str) -> Colour:
        """Return the current colour for a signal's approach."""
        return self._signals[signal_id].colour_for(approach)

    @property
    def time(self) -> float:
        """Current simulation time."""
        return self._time

    # ------------------------------------------------------------------
    # Pre-emption
    # ------------------------------------------------------------------

    def request_priority(self, signal_id: int, approach: str, eta_s: float) -> PreemptionRequest:
        """Request emergency pre-emption for a signal.

        Args:
            signal_id: The signal to pre-empt.
            approach: The approach that needs green ('NS' or 'EW').
            eta_s: Estimated time of arrival in seconds.

        Returns:
            A PreemptionRequest with the outcome.
        """
        state = self._signals.get(signal_id)
        if state is None:
            req = PreemptionRequest(signal_id, approach, eta_s, self._time, outcome="denied")
            self._preemption_log.append(req)
            return req

        req = PreemptionRequest(signal_id, approach, eta_s, self._time)

        # If already pre-empted for this approach, extend hold
        if state.preempt_active and state.preempt_approach == approach:
            req.outcome = "already_green"
            self._preemption_log.append(req)
            return req

        current_colour = state.colour_for(approach)

        if current_colour == Colour.GREEN:
            # Already green — just hold it
            state.preempt_active = True
            state.preempt_approach = approach
            state.preempt_hold_elapsed = 0.0
            req.outcome = "granted"
            logger.info("Signal %d: approach %s already GREEN, holding", signal_id, approach)
        else:
            # Need to transition — calculate time to switch
            time_to_switch = self._time_to_switch(state, approach)

            if time_to_switch <= eta_s:
                # Can switch in time — schedule the transition
                state.preempt_pending = req
                state.preempt_approach = approach
                req.outcome = "granted"
                logger.info(
                    "Signal %d: pre-emption granted for %s, switch in %.1fs, ETA %.1fs",
                    signal_id, approach, time_to_switch, eta_s,
                )
            else:
                req.outcome = "late"
                logger.warning(
                    "Signal %d: pre-emption LATE for %s, need %.1fs but ETA %.1fs",
                    signal_id, approach, time_to_switch, eta_s,
                )
                # Still try — grant it and it'll be a bit late
                state.preempt_pending = req
                state.preempt_approach = approach

        self._preemption_log.append(req)
        if self._on_update:
            self._on_update(signal_id, self.get_state(signal_id))
        return req

    def release_priority(self, signal_id: int) -> None:
        """Release emergency pre-emption and resume normal cycling."""
        state = self._signals.get(signal_id)
        if state is None:
            return
        state.preempt_active = False
        state.preempt_approach = ""
        state.preempt_hold_elapsed = 0.0
        state.preempt_pending = None
        logger.info("Signal %d: pre-emption released, resuming normal cycle", signal_id)
        if self._on_update:
            self._on_update(signal_id, self.get_state(signal_id))

    def _time_to_switch(self, state: _SignalState, target_approach: str) -> float:
        """Estimate time to switch to the target approach's green."""
        time_needed = 0.0

        # If we're in GREEN for the current phase, we need to wait for min_green_s
        if state.sub_state == "green":
            remaining_green = max(0, state.min_green_s - state.sub_elapsed)
            time_needed += remaining_green
            time_needed += state.yellow_s + state.all_red_s
        elif state.sub_state == "yellow":
            remaining_yellow = max(0, state.yellow_s - state.sub_elapsed)
            time_needed += remaining_yellow + state.all_red_s
        elif state.sub_state == "all_red":
            remaining_ar = max(0, state.all_red_s - state.sub_elapsed)
            time_needed += remaining_ar

        # If the next phase isn't the target, add more cycle time
        next_idx = (state.current_phase_idx + 1) % len(state.phases)
        if state.phases[next_idx].green_approach != target_approach:
            # Need to go through the next phase too
            time_needed += state.phases[next_idx].duration_s + state.yellow_s + state.all_red_s

        return time_needed

    # ------------------------------------------------------------------
    # Internal advance
    # ------------------------------------------------------------------

    def _advance_signal(self, state: _SignalState, dt: float, suppress_callback: bool = False) -> None:
        """Advance a single signal's state machine by dt seconds."""
        remaining = dt

        while remaining > 1e-9:
            prev_ns = state.ns_colour()
            prev_ew = state.ew_colour()

            if state.preempt_active:
                # Holding green for pre-emption
                state.preempt_hold_elapsed += remaining
                state.sub_elapsed += remaining
                if state.preempt_hold_elapsed >= state.max_preempt_hold:
                    # Max hold expired — release
                    self.release_priority(state.signal_id)
                remaining = 0
            elif state.sub_state == "green":
                green_duration = state.current_phase.duration_s

                # Check if pre-emption pending: if target approach is the next phase,
                # cut current green short (but respect min_green_s)
                if state.preempt_pending and state.current_phase.green_approach != state.preempt_approach:
                    green_duration = max(state.min_green_s, state.sub_elapsed)

                time_left = green_duration - state.sub_elapsed
                if remaining < time_left:
                    state.sub_elapsed += remaining
                    remaining = 0
                else:
                    remaining -= time_left
                    state.sub_elapsed = 0
                    state.sub_state = "yellow"
            elif state.sub_state == "yellow":
                time_left = state.yellow_s - state.sub_elapsed
                if remaining < time_left:
                    state.sub_elapsed += remaining
                    remaining = 0
                else:
                    remaining -= time_left
                    state.sub_elapsed = 0
                    state.sub_state = "all_red"
            elif state.sub_state == "all_red":
                time_left = state.all_red_s - state.sub_elapsed
                if remaining < time_left:
                    state.sub_elapsed += remaining
                    remaining = 0
                else:
                    remaining -= time_left
                    state.sub_elapsed = 0
                    # Move to next phase
                    state.current_phase_idx = (state.current_phase_idx + 1) % len(state.phases)
                    state.sub_state = "green"
                    state.phase_elapsed = 0

                    # Check if this is the pre-empted approach
                    if (
                        state.preempt_pending
                        and state.current_phase.green_approach == state.preempt_approach
                    ):
                        state.preempt_active = True
                        state.preempt_hold_elapsed = 0.0
                        state.preempt_pending = None
                        logger.info(
                            "Signal %d: pre-emption active — %s is now GREEN",
                            state.signal_id, state.preempt_approach,
                        )

            # Broadcast state change if colours changed
            new_ns = state.ns_colour()
            new_ew = state.ew_colour()
            if not suppress_callback and (new_ns != prev_ns or new_ew != prev_ew):
                if self._on_update:
                    self._on_update(state.signal_id, self.get_state(state.signal_id))
