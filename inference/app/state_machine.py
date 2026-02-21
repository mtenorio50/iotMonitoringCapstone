"""
Inference-First Device State Machine
=====================================
Core of the capstone project. Implements a Finite State Machine (FSM)
that infers device health from heartbeat arrivals and absence events.

KEY DESIGN PRINCIPLE: "Absence is evidence, not missing data."
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class DeviceState (Enum):
    OK = "OK"
    STALE = "STALE"
    OFFLINE_FAULT = "OFFLINE_FAULT"
    RECOVERED = "RECOVERED"
    SILENT = "SILENT"


class Event(Enum):
    HEARTBEAT = "HEARTBEAT"
    ABSENCE = "ABSENCE"
    SUPPRESS_ON = "SUPPRESS_ON"
    SUPPRESS_OFF = "SUPPRESS_OFF"


@dataclass
class Transition:
    timestamp: float
    from_state: DeviceState
    to_state: DeviceState
    event: Event
    reason: str


@dataclass
class MonitorConfig:
    heartbeat_interval_s: float = 30.0
    tolerance_s: float = 10.0
    stale_after_n_absences: int = 2
    fault_after_n_absences: int = 4
    recovery_heartbeats: int = 2


class DeviceMonitor:
    """
    Processes events and maintains inferred device state.

    USAGE:
        config = MonitorConfig(heartbeat_interval_s=30)
        monitor = DeviceMonitor("device-001", config)
        monitor.process_event(Event.HEARTBEAT, timestamp=0.0)
        monitor.process_event(Event.ABSENCE, timestamp=35.0)
        print(monitor.state)
        print(monitor.transitions)
    """

    def __init__(self, device_id: str, config: MonitorConfig):
        self.device_id = device_id
        self.config = config

        self.state = DeviceState.OK
        self.consecutive_absences = 0
        self.consecutive_heartbeats = 0

        self.suppressed = False
        self._state_before_suppression: Optional[DeviceState] = None

        self.transitions: list[Transition] = []
        self.last_event_ts: Optional[float] = None
        self.last_heartbeat_ts: Optional[float] = None

    def process_event(self, event: Event, timestamp: float) -> Optional[Transition]:
        """
        Feed an event into the state machine. Returns a Transition if
        state changed, or None if the state stayed the same.
        """
        self.last_event_ts = timestamp
        old_state = self.state

        # Suppression events override everything — they change HOW we
        # interpret silence, not what the device is doing
        if event == Event.SUPPRESS_ON:
            return self._handle_suppress_on(timestamp, old_state)

        if event == Event.SUPPRESS_OFF:
            return self._handle_suppress_off(timestamp, old_state)

        # During suppression, absorb events without escalation
        if self.suppressed:
            if event == Event.HEARTBEAT:
                self.last_heartbeat_ts = timestamp
            return None

        # Normal event processing
        if event == Event.HEARTBEAT:
            return self._handle_heartbeat(timestamp, old_state)

        if event == Event.ABSENCE:
            return self._handle_absence(timestamp, old_state)

        return None

    def _handle_heartbeat(self, ts: float, old_state: DeviceState) -> Optional[Transition]:
        """
        A heartbeat arrived. Meaning DEPENDS on current state:
        - In OK: just confirmation, reset absence counter
        - In STALE: recovery signal, go back to OK
        - In OFFLINE_FAULT: first sign of life → RECOVERED (not OK yet!)
        - In RECOVERED: building confidence, maybe promote to OK
        """
        self.last_heartbeat_ts = ts
        self.consecutive_absences = 0
        self.consecutive_heartbeats += 1

        if old_state == DeviceState.OK:
            return None

        if old_state == DeviceState.STALE:
            return self._transition(
                ts, old_state, DeviceState.OK, Event.HEARTBEAT,
                reason="heartbeat_received_during_stale"
            )

        if old_state == DeviceState.OFFLINE_FAULT:
            return self._transition(
                ts, old_state, DeviceState.RECOVERED, Event.HEARTBEAT,
                reason="first_heartbeat_after_fault"
            )

        if old_state == DeviceState.RECOVERED:
            if self.consecutive_heartbeats >= self.config.recovery_heartbeats:
                return self._transition(
                    ts, old_state, DeviceState.OK, Event.HEARTBEAT,
                    reason=f"{self.consecutive_heartbeats}_consecutive_heartbeats_stability_confirmed"
                )
            return None

        return None

    def _handle_absence(self, ts: float, old_state: DeviceState) -> Optional[Transition]:
        """
        Expected heartbeat didn't arrive. Graduated escalation:
        - 1 miss: maybe jitter, stay in current state
        - N misses: STALE
        - M misses: FAULT
        """
        self.consecutive_heartbeats = 0
        self.consecutive_absences += 1

        if old_state == DeviceState.OK:
            if self.consecutive_absences >= self.config.stale_after_n_absences:
                return self._transition(
                    ts, old_state, DeviceState.STALE, Event.ABSENCE,
                    reason=f"{self.consecutive_absences}_consecutive_absences_exceeded_stale_threshold"
                )
            return None

        if old_state == DeviceState.STALE:
            if self.consecutive_absences >= self.config.fault_after_n_absences:
                return self._transition(
                    ts, old_state, DeviceState.OFFLINE_FAULT, Event.ABSENCE,
                    reason=f"{self.consecutive_absences}_consecutive_absences_exceeded_fault_threshold"
                )
            return None

        if old_state == DeviceState.OFFLINE_FAULT:
            return None

        if old_state == DeviceState.RECOVERED:
            return self._transition(
                ts, old_state, DeviceState.OFFLINE_FAULT, Event.ABSENCE,
                reason="absence_during_recovery_relapse_to_fault"
            )

        return None

    def _handle_suppress_on(self, ts: float, old_state: DeviceState) -> Optional[Transition]:
        """Enter suppression window. Save current state to restore later."""
        if self.suppressed:
            return None

        self.suppressed = True
        self._state_before_suppression = old_state
        self.consecutive_absences = 0
        self.consecutive_heartbeats = 0

        return self._transition(
            ts, old_state, DeviceState.SILENT, Event.SUPPRESS_ON,
            reason="entering_suppression_window"
        )

    def _handle_suppress_off(self, ts: float, old_state: DeviceState) -> Optional[Transition]:
        """Leave suppression window. Restore previous state."""
        if not self.suppressed:
            return None

        self.suppressed = False
        restore_to = self._state_before_suppression or DeviceState.OK
        self._state_before_suppression = None

        return self._transition(
            ts, old_state, restore_to, Event.SUPPRESS_OFF,
            reason=f"leaving_suppression_window_restoring_{restore_to.value}"
        )

    def _transition(
        self, ts: float, from_state: DeviceState,
        to_state: DeviceState, event: Event, reason: str
    ) -> Transition:
        """
        Single point where ALL state changes happen.
        Guarantees every transition is logged — no silent state changes.
        """
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
        """
        What was the inferred state at a given time?
        Used by metrics engine for time-aligned accuracy calculations.
        """
        state = DeviceState.OK
        for t in self.transitions:
            if t.timestamp <= timestamp:
                state = t.to_state
            else:
                break
        return state

    def reset(self):
        """Reset monitor to initial state. Used between experiment runs."""
        self.state = DeviceState.OK
        self.consecutive_absences = 0
        self.consecutive_heartbeats = 0
        self.suppressed = False
        self._state_before_suppression = None
        self.transitions.clear()
        self.last_event_ts = None
        self.last_heartbeat_ts = None

    def __repr__(self):
        return (
            f"DeviceMonitor(device={self.device_id!r}, state={self.state.value}, "
            f"absences={self.consecutive_absences}, heartbeats={self.consecutive_heartbeats})"
        )
