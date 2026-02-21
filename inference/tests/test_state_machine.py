"""
State Machine Tests
Each test maps to a scenario from the research proposal Table 2.
RUN: python -m pytest tests/ -v
"""

import pytest
from app.state_machine import DeviceMonitor, DeviceState, Event, MonitorConfig


@pytest.fixture
def config():
    return MonitorConfig(
        heartbeat_interval_s=30.0,
        stale_after_n_absences=2,
        fault_after_n_absences=4,
        recovery_heartbeats=2,
    )


@pytest.fixture
def monitor(config):
    return DeviceMonitor("test-device", config)


# === Scenario 1: Normal operation (Table 2 Row 1) ===

class TestNormalOperation:

    def test_initial_state_is_ok(self, monitor):
        assert monitor.state == DeviceState.OK

    def test_heartbeat_keeps_ok(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.HEARTBEAT, timestamp=30)
        monitor.process_event(Event.HEARTBEAT, timestamp=60)
        assert monitor.state == DeviceState.OK
        assert len(monitor.transitions) == 0

    def test_single_absence_stays_ok(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.ABSENCE, timestamp=35)
        assert monitor.state == DeviceState.OK
        assert monitor.consecutive_absences == 1


# === Scenario 2: Graduated escalation (Table 2 Rows 3 & 6) ===

class TestGraduatedEscalation:

    def test_two_absences_triggers_stale(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.ABSENCE, timestamp=35)
        monitor.process_event(Event.ABSENCE, timestamp=65)
        assert monitor.state == DeviceState.STALE
        assert monitor.transitions[0].reason == "2_consecutive_absences_exceeded_stale_threshold"

    def test_four_absences_triggers_fault(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        for i in range(1, 5):
            monitor.process_event(Event.ABSENCE, timestamp=i * 35)
        assert monitor.state == DeviceState.OFFLINE_FAULT
        assert len(monitor.transitions) == 2

    def test_fault_stays_at_fault(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        for i in range(1, 5):
            monitor.process_event(Event.ABSENCE, timestamp=i * 35)
        transitions_before = len(monitor.transitions)
        monitor.process_event(Event.ABSENCE, timestamp=200)
        monitor.process_event(Event.ABSENCE, timestamp=235)
        assert monitor.state == DeviceState.OFFLINE_FAULT
        assert len(monitor.transitions) == transitions_before


# === Scenario 3: Recovery with hysteresis (Table 2 Row 3) ===

class TestRecoveryHysteresis:

    def test_stale_recovers_to_ok_on_heartbeat(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.ABSENCE, timestamp=35)
        monitor.process_event(Event.ABSENCE, timestamp=65)
        monitor.process_event(Event.HEARTBEAT, timestamp=95)
        assert monitor.state == DeviceState.OK

    def test_fault_requires_multiple_heartbeats_to_ok(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        for i in range(1, 5):
            monitor.process_event(Event.ABSENCE, timestamp=i * 35)
        monitor.process_event(Event.HEARTBEAT, timestamp=200)
        assert monitor.state == DeviceState.RECOVERED
        monitor.process_event(Event.HEARTBEAT, timestamp=230)
        assert monitor.state == DeviceState.OK

    def test_absence_during_recovery_relapses_to_fault(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        for i in range(1, 5):
            monitor.process_event(Event.ABSENCE, timestamp=i * 35)
        monitor.process_event(Event.HEARTBEAT, timestamp=200)
        monitor.process_event(Event.ABSENCE, timestamp=235)
        assert monitor.state == DeviceState.OFFLINE_FAULT
        assert "relapse" in monitor.transitions[-1].reason

# === Scenario 4: Suppression window (Table 2 Row 2) ===

class TestSuppression:

    def test_suppress_on_transitions_to_silent(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.SUPPRESS_ON, timestamp=10)
        assert monitor.state == DeviceState.SILENT

    def test_absences_during_suppression_do_not_escalate(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.SUPPRESS_ON, timestamp=10)
        monitor.process_event(Event.ABSENCE, timestamp=45)
        monitor.process_event(Event.ABSENCE, timestamp=75)
        monitor.process_event(Event.ABSENCE, timestamp=105)
        monitor.process_event(Event.ABSENCE, timestamp=135)
        assert monitor.state == DeviceState.SILENT

    def test_suppress_off_restores_previous_state(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.SUPPRESS_ON, timestamp=10)
        monitor.process_event(Event.SUPPRESS_OFF, timestamp=120)
        assert monitor.state == DeviceState.OK

    def test_suppress_from_stale_restores_stale(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.ABSENCE, timestamp=35)
        monitor.process_event(Event.ABSENCE, timestamp=65)
        monitor.process_event(Event.SUPPRESS_ON, timestamp=70)
        monitor.process_event(Event.SUPPRESS_OFF, timestamp=200)
        assert monitor.state == DeviceState.STALE


# === Scenario 5: Jitter (Table 2 Row 4) ===

class TestJitter:

    def test_alternating_absence_heartbeat_stays_ok(self, monitor):
        for i in range(10):
            ts = i * 35
            if i % 2 == 0:
                monitor.process_event(Event.HEARTBEAT, timestamp=ts)
            else:
                monitor.process_event(Event.ABSENCE, timestamp=ts)
        assert monitor.state == DeviceState.OK

    def test_two_absences_then_heartbeat_no_fault(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.ABSENCE, timestamp=35)
        monitor.process_event(Event.ABSENCE, timestamp=65)
        monitor.process_event(Event.HEARTBEAT, timestamp=95)
        assert monitor.state == DeviceState.OK
        states = [t.to_state for t in monitor.transitions]
        assert DeviceState.OFFLINE_FAULT not in states


# === Edge cases ===

class TestEdgeCases:

    def test_double_suppress_on_is_idempotent(self, monitor):
        monitor.process_event(Event.SUPPRESS_ON, timestamp=0)
        monitor.process_event(Event.SUPPRESS_ON, timestamp=10)
        assert len(monitor.transitions) == 1

    def test_suppress_off_without_on_is_safe(self, monitor):
        monitor.process_event(Event.SUPPRESS_OFF, timestamp=0)
        assert monitor.state == DeviceState.OK
        assert len(monitor.transitions) == 0

    def test_every_transition_has_reason(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        for i in range(1, 5):
            monitor.process_event(Event.ABSENCE, timestamp=i * 35)
        monitor.process_event(Event.HEARTBEAT, timestamp=200)
        monitor.process_event(Event.HEARTBEAT, timestamp=230)
        for t in monitor.transitions:
            assert t.reason and len(t.reason) > 0

    def test_get_state_at_various_times(self, monitor):
        monitor.process_event(Event.HEARTBEAT, timestamp=0)
        monitor.process_event(Event.ABSENCE, timestamp=35)
        monitor.process_event(Event.ABSENCE, timestamp=65)
        monitor.process_event(Event.HEARTBEAT, timestamp=95)
        assert monitor.get_state_at(50) == DeviceState.OK
        assert monitor.get_state_at(65) == DeviceState.STALE
        assert monitor.get_state_at(80) == DeviceState.STALE
        assert monitor.get_state_at(95) == DeviceState.OK

    def test_reset_clears_everything(self, monitor):
        monitor.process_event(Event.ABSENCE, timestamp=35)
        monitor.process_event(Event.ABSENCE, timestamp=65)
        monitor.reset()
        assert monitor.state == DeviceState.OK
        assert monitor.consecutive_absences == 0
        assert len(monitor.transitions) == 0