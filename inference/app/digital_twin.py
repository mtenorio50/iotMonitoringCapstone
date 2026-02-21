"""
Digital Twin — Scenario Simulator
===================================
Generates synthetic heartbeat streams under controlled conditions,
paired with ground-truth state timelines for validation.

Each scenario models a specific monitoring challenge from proposal Table 2.
Scenarios are parameterised to support the sweeps needed for RQ3.

RUN: python -m app.digital_twin (to preview scenarios)
"""

import random
from dataclasses import dataclass, field
from typing import Optional
from app.state_machine import DeviceState, Event


@dataclass
class SimEvent:
    """A single event in the synthetic stream."""
    timestamp: float
    event: Event


@dataclass
class GroundTruthSegment:
    """
    A time period where the TRUE device state is known.

    Example: GroundTruthSegment(0, 60, DeviceState.OK) means
    'from t=0 to t=60, the device was truly OK.'

    WHY segments (not per-second)?
    Because ground truth changes at specific moments (fault injection,
    recovery), not continuously. Segments are more natural and efficient.
    """
    start: float
    end: float
    state: DeviceState


@dataclass
class Scenario:
    """
    A complete test scenario with events and ground truth.

    This is what the experiment runner consumes:
      - Feed 'events' to both monitors
      - Compare their inferred timelines against 'ground_truth'
    """
    name: str
    description: str
    events: list[SimEvent]
    ground_truth: list[GroundTruthSegment]
    duration: float
    parameters: dict = field(default_factory=dict)

    def get_true_state_at(self, timestamp: float) -> DeviceState:
        """Look up the true state at a given time."""
        for seg in self.ground_truth:
            if seg.start <= timestamp < seg.end:
                return seg.state
        # After last segment, return last known state
        if self.ground_truth:
            return self.ground_truth[-1].state
        return DeviceState.OK


class DigitalTwin:
    """
    Generates scenarios with synthetic events and ground truth.

    Each method creates one scenario from proposal Table 2.
    All scenarios are parameterised by heartbeat_interval so RQ3
    parameter sweeps just call the same methods with different values.
    """

    def __init__(self, heartbeat_interval: float = 30.0, seed: Optional[int] = 42):
        self.hb = heartbeat_interval
        # Fixed seed makes experiments REPRODUCIBLE — same seed = same results
        # WHY reproducibility matters: if your supervisor says "show me that
        # result again", you can. Random without seed = different every time.
        self.rng = random.Random(seed)

    # ── Scenario 1: Standard sparse reporting (Table 2 Row 1) ──────

    def scenario_normal(self, duration: float = 300.0) -> Scenario:
        """
        Device sends heartbeats on time for the entire duration.
        Ground truth: OK throughout.
        PURPOSE: Sanity check — both monitors should report OK with zero errors.
        """
        events = []
        t = 0.0
        while t < duration:
            events.append(SimEvent(timestamp=t, event=Event.HEARTBEAT))
            t += self.hb

        ground_truth = [GroundTruthSegment(0, duration, DeviceState.OK)]

        return Scenario(
            name="normal_sparse_reporting",
            description="Regular heartbeats, no faults or disruptions",
            events=events,
            ground_truth=ground_truth,
            duration=duration,
            parameters={"heartbeat_interval": self.hb},
        )

    # ── Scenario 2: Suppression window (Table 2 Row 2) ─────────────

    def scenario_suppression(
        self, suppress_start: float = 90.0, suppress_end: float = 210.0,
        duration: float = 300.0,
    ) -> Scenario:
        """
        Device enters a maintenance window — silence is EXPECTED.
        Ground truth: OK → SILENT → OK
        PURPOSE: Tests RQ2 — can the proposed monitor avoid false alarms
        during planned silence? Baseline should fail here.
        """
        events = []
        t = 0.0
        while t < duration:
            if t < suppress_start or t >= suppress_end:
                # Normal heartbeat outside suppression
                events.append(SimEvent(timestamp=t, event=Event.HEARTBEAT))
            elif t == suppress_start or (len(events) > 0 and events[-1].timestamp < suppress_start):
                # Send SUPPRESS_ON at the start of the window
                events.append(SimEvent(timestamp=suppress_start,
                              event=Event.SUPPRESS_ON))
            t += self.hb

        # Ensure SUPPRESS_ON and SUPPRESS_OFF are in the stream
        suppress_on_exists = any(e.event == Event.SUPPRESS_ON for e in events)
        if not suppress_on_exists:
            events.append(SimEvent(timestamp=suppress_start,
                          event=Event.SUPPRESS_ON))

        events.append(SimEvent(timestamp=suppress_end,
                      event=Event.SUPPRESS_OFF))

        # During suppression, generate ABSENCE events (heartbeats aren't sent)
        t = suppress_start + self.hb
        while t < suppress_end:
            events.append(SimEvent(timestamp=t, event=Event.ABSENCE))
            t += self.hb

        # Sort by timestamp — events must be in chronological order
        events.sort(key=lambda e: e.timestamp)

        ground_truth = [
            GroundTruthSegment(0, suppress_start, DeviceState.OK),
            GroundTruthSegment(suppress_start, suppress_end,
                               DeviceState.SILENT),
            GroundTruthSegment(suppress_end, duration, DeviceState.OK),
        ]

        return Scenario(
            name="suppression_window",
            description=f"Planned silence from t={suppress_start}s to t={suppress_end}s",
            events=events,
            ground_truth=ground_truth,
            duration=duration,
            parameters={
                "heartbeat_interval": self.hb,
                "suppress_start": suppress_start,
                "suppress_end": suppress_end,
            },
        )

    # ── Scenario 3: Temporary dropout + recovery (Table 2 Row 3) ───

    def scenario_dropout(
        self, dropout_start: float = 90.0, dropout_end: float = 180.0,
        duration: float = 300.0,
    ) -> Scenario:
        """
        Device loses connectivity temporarily, then recovers.
        Ground truth: OK → STALE → OK
        PURPOSE: Tests whether monitors correctly detect and recover from dropout.
        """
        events = []
        t = 0.0
        while t < duration:
            if t < dropout_start or t >= dropout_end:
                events.append(SimEvent(timestamp=t, event=Event.HEARTBEAT))
            else:
                events.append(SimEvent(timestamp=t, event=Event.ABSENCE))
            t += self.hb

        ground_truth = [
            GroundTruthSegment(0, dropout_start, DeviceState.OK),
            GroundTruthSegment(dropout_start, dropout_end, DeviceState.STALE),
            GroundTruthSegment(dropout_end, duration, DeviceState.OK),
        ]

        return Scenario(
            name="temporary_dropout",
            description=f"Connectivity lost from t={dropout_start}s to t={dropout_end}s",
            events=events,
            ground_truth=ground_truth,
            duration=duration,
            parameters={
                "heartbeat_interval": self.hb,
                "dropout_start": dropout_start,
                "dropout_end": dropout_end,
            },
        )

    # ── Scenario 4: Jitter / delayed delivery (Table 2 Row 4) ──────

    def scenario_jitter(
        self, jitter_range: float = 15.0, duration: float = 300.0,
    ) -> Scenario:
        """
        Heartbeats arrive but with random delay. Some may be late enough
        to trigger an ABSENCE before arriving.
        Ground truth: OK throughout (device is healthy, just delayed).
        PURPOSE: Tests RQ2 — can monitors avoid false STALE/FAULT from jitter?
        """
        events = []
        t = 0.0
        while t < duration:
            # Add random delay to each heartbeat
            jitter = self.rng.uniform(-jitter_range, jitter_range)
            actual_arrival = max(0, t + jitter)

            # If heartbeat arrives after the next expected window,
            # an ABSENCE would have been generated first
            expected_deadline = t + self.hb + (self.hb * 0.5)
            if actual_arrival > t + self.hb:
                # Absence detected before late heartbeat arrives
                events.append(
                    SimEvent(timestamp=t + self.hb, event=Event.ABSENCE))

            events.append(
                SimEvent(timestamp=actual_arrival, event=Event.HEARTBEAT))
            t += self.hb

        events.sort(key=lambda e: e.timestamp)

        # Ground truth: device is OK the entire time (jitter is a transport issue)
        ground_truth = [GroundTruthSegment(0, duration, DeviceState.OK)]

        return Scenario(
            name="jitter_delayed_delivery",
            description=f"Heartbeats delayed ±{jitter_range}s randomly",
            events=events,
            ground_truth=ground_truth,
            duration=duration,
            parameters={
                "heartbeat_interval": self.hb,
                "jitter_range": jitter_range,
            },
        )

    # ── Scenario 5: Gradual degradation (Table 2 Row 5) ────────────

    def scenario_degradation(
        self, degrade_start: float = 90.0, duration: float = 300.0,
    ) -> Scenario:
        """
        Device starts dropping more and more heartbeats over time.
        Ground truth: OK → STALE → OFFLINE_FAULT
        PURPOSE: Tests whether monitors detect slow degradation, not just sudden failure.
        """
        events = []
        t = 0.0
        # drop_probability increases linearly from 0 to 1 after degrade_start
        degrade_duration = duration - degrade_start

        while t < duration:
            if t < degrade_start:
                events.append(SimEvent(timestamp=t, event=Event.HEARTBEAT))
            else:
                # Probability of dropping increases over time
                elapsed = t - degrade_start
                drop_prob = min(elapsed / degrade_duration, 0.95)

                if self.rng.random() < drop_prob:
                    events.append(SimEvent(timestamp=t, event=Event.ABSENCE))
                else:
                    events.append(SimEvent(timestamp=t, event=Event.HEARTBEAT))
            t += self.hb

        # Ground truth: transition from OK to STALE to FAULT
        # STALE begins when drops become frequent (roughly 1/3 through degradation)
        stale_start = degrade_start + (degrade_duration * 0.3)
        fault_start = degrade_start + (degrade_duration * 0.7)

        ground_truth = [
            GroundTruthSegment(0, degrade_start, DeviceState.OK),
            GroundTruthSegment(degrade_start, stale_start, DeviceState.OK),
            GroundTruthSegment(stale_start, fault_start, DeviceState.STALE),
            GroundTruthSegment(fault_start, duration,
                               DeviceState.OFFLINE_FAULT),
        ]

        return Scenario(
            name="gradual_degradation",
            description=f"Increasing drop rate from t={degrade_start}s onward",
            events=events,
            ground_truth=ground_truth,
            duration=duration,
            parameters={
                "heartbeat_interval": self.hb,
                "degrade_start": degrade_start,
            },
        )

    # ── Scenario 6: Hard fault / offline (Table 2 Row 6) ───────────

    def scenario_hard_fault(
        self, fault_start: float = 120.0, duration: float = 300.0,
    ) -> Scenario:
        """
        Device stops completely and never recovers.
        Ground truth: OK → OFFLINE_FAULT
        PURPOSE: Both monitors should detect this. The question is HOW FAST.
        """
        events = []
        t = 0.0
        while t < duration:
            if t < fault_start:
                events.append(SimEvent(timestamp=t, event=Event.HEARTBEAT))
            else:
                events.append(SimEvent(timestamp=t, event=Event.ABSENCE))
            t += self.hb

        ground_truth = [
            GroundTruthSegment(0, fault_start, DeviceState.OK),
            GroundTruthSegment(fault_start, duration,
                               DeviceState.OFFLINE_FAULT),
        ]

        return Scenario(
            name="hard_fault_offline",
            description=f"Device fails at t={fault_start}s, never recovers",
            events=events,
            ground_truth=ground_truth,
            duration=duration,
            parameters={
                "heartbeat_interval": self.hb,
                "fault_start": fault_start,
            },
        )

    # ── Scenario 7: Flapping / intermittent heartbeat (NEW) ────────

    def scenario_flapping(
        self, fault_start: float = 60.0, flap_at: float = 210.0,
        duration: float = 300.0,
    ) -> Scenario:
        """
        Device fails, sends ONE heartbeat mid-outage (network retry or
        buffer flush), then stays down. Baseline will false-recover.
        Ground truth: OK → OFFLINE_FAULT (the single heartbeat is a fluke)
        PURPOSE: Tests hysteresis — proposed should NOT report OK on one heartbeat.
        """
        events = []
        t = 0.0
        while t < duration:
            if t < fault_start:
                events.append(SimEvent(timestamp=t, event=Event.HEARTBEAT))
            elif abs(t - flap_at) < 1.0:
                # One heartbeat sneaks through mid-outage
                events.append(SimEvent(timestamp=t, event=Event.HEARTBEAT))
            else:
                events.append(SimEvent(timestamp=t, event=Event.ABSENCE))
            t += self.hb

        ground_truth = [
            GroundTruthSegment(0, fault_start, DeviceState.OK),
            GroundTruthSegment(fault_start, duration,
                               DeviceState.OFFLINE_FAULT),
        ]

        return Scenario(
            name="flapping_intermittent",
            description=f"Fault at t={fault_start}s, one fluke heartbeat at t={flap_at}s",
            events=events,
            ground_truth=ground_truth,
            duration=duration,
            parameters={
                "heartbeat_interval": self.hb,
                "fault_start": fault_start,
                "flap_at": flap_at,
            },
        )

    # ── Convenience ──────────────────────────────────────────────────

    def all_scenarios(self) -> list[Scenario]:
        """Generate all 6 standard scenarios. Used by the experiment runner."""
        return [
            self.scenario_normal(),
            self.scenario_suppression(),
            self.scenario_dropout(),
            self.scenario_jitter(),
            self.scenario_degradation(),
            self.scenario_hard_fault(),
            self.scenario_flapping()
        ]


# ── Preview runner ───────────────────────────────────────────────────
# Run this file directly to see what the twin generates:
#   python -m app.digital_twin

if __name__ == "__main__":
    twin = DigitalTwin(heartbeat_interval=30.0, seed=42)

    for scenario in twin.all_scenarios():
        print(f"\n{'='*60}")
        print(f"Scenario: {scenario.name}")
        print(f"Description: {scenario.description}")
        print(f"Duration: {scenario.duration}s")
        print(f"Events: {len(scenario.events)}")
        print(f"Ground truth segments: {len(scenario.ground_truth)}")
        print(f"Parameters: {scenario.parameters}")
        print(f"First 5 events:")
        for e in scenario.events[:5]:
            print(f"  t={e.timestamp:6.1f}s  {e.event.value}")
        print(f"Ground truth:")
        for seg in scenario.ground_truth:
            print(f"  {seg.start:6.1f}s - {seg.end:6.1f}s  {seg.state.value}")
