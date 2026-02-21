"""
Baseline Timeout Monitor
=========================
Simple missed-heartbeat counter used as the CONTROL in experiments.

Deliberately simple — no hysteresis, no suppression awareness, no RECOVERED state.
This represents what most real-world timeout monitors do today.

Used to answer RQ1: "How does inference-first compare to timeout-based monitoring?"
"""

from typing import Optional
from app.state_machine import DeviceState, Event, Transition, MonitorConfig


class BaselineMonitor:
    """
    Counts missed heartbeats. That's it.

    Key differences from DeviceMonitor:
      - No RECOVERED state (heartbeat after FAULT → straight to OK)
      - No SILENT state (suppression events ignored entirely)
      - No hysteresis (no consecutive-heartbeat requirement)
      - No relapse protection
    """

    def __init__(self, device_id: str, config: MonitorConfig):
        self.device_id = device_id
        self.config = config

        self.state = DeviceState.OK
        self.consecutive_absences = 0

        self.transitions: list[Transition] = []
        self.last_event_ts: Optional[float] = None
        self.last_heartbeat_ts: Optional[float] = None

    def process_event(self, event: Event, timestamp: float) -> Optional[Transition]:
        """Same interface as DeviceMonitor — so both can process the same event stream."""
        self.last_event_ts = timestamp
        old_state = self.state

        # Suppression events are IGNORED — baseline has no awareness of them
        if event in (Event.SUPPRESS_ON, Event.SUPPRESS_OFF):
            return None

        if event == Event.HEARTBEAT:
            return self._handle_heartbeat(timestamp, old_state)

        if event == Event.ABSENCE:
            return self._handle_absence(timestamp, old_state)

        return None

    def _handle_heartbeat(self, ts: float, old_state: DeviceState) -> Optional[Transition]:
        """Any heartbeat → OK immediately. No questions asked."""
        self.last_heartbeat_ts = ts
        self.consecutive_absences = 0

        if old_state == DeviceState.OK:
            return None

        # FAULT → OK in one step. This is where flapping happens.
        return self._transition(
            ts, old_state, DeviceState.OK, Event.HEARTBEAT,
            reason="heartbeat_received"
        )

    def _handle_absence(self, ts: float, old_state: DeviceState) -> Optional[Transition]:
        """Count misses, escalate at thresholds. Same thresholds as proposed monitor."""
        self.consecutive_absences += 1

        if old_state == DeviceState.OK:
            if self.consecutive_absences >= self.config.stale_after_n_absences:
                return self._transition(
                    ts, old_state, DeviceState.STALE, Event.ABSENCE,
                    reason=f"{self.consecutive_absences}_misses_stale_threshold"
                )
            return None

        if old_state == DeviceState.STALE:
            if self.consecutive_absences >= self.config.fault_after_n_absences:
                return self._transition(
                    ts, old_state, DeviceState.OFFLINE_FAULT, Event.ABSENCE,
                    reason=f"{self.consecutive_absences}_misses_fault_threshold"
                )
            return None

        # Already FAULT — nothing to escalate to
        return None

    def _transition(
        self, ts: float, from_state: DeviceState,
        to_state: DeviceState, event: Event, reason: str
    ) -> Transition:
        self.state = to_state
        t = Transition(
            timestamp=ts,
            from_state=from_state,
            to_state=to_state,
            event=event,
            reason=reason,
        )
        self.transitions.append(t)
        return t

    def get_state_at(self, timestamp: float) -> DeviceState:
        state = DeviceState.OK
        for t in self.transitions:
            if t.timestamp <= timestamp:
                state = t.to_state
            else:
                break
        return state

    def reset(self):
        self.state = DeviceState.OK
        self.consecutive_absences = 0
        self.transitions.clear()
        self.last_event_ts = None
        self.last_heartbeat_ts = None

    def __repr__(self):
        return (
            f"BaselineMonitor(device={self.device_id!r}, state={self.state.value}, "
            f"absences={self.consecutive_absences})"
        )
