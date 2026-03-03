"""
Heartbeat Handler — REST-Based Integration
=============================================
Replaces the MQTT bridge. Instead of subscribing to Mosquitto,
ThingsBoard's rule chain calls our /infer endpoint on every heartbeat.

This handler:
  1. Receives heartbeat notifications from TB rule chain (REST POST)
  2. Feeds them into the state machine
  3. Runs a watchdog timer to detect absence (no heartbeat within window)
  4. Pushes inferred state back to ThingsBoard via HTTP API
  5. Tracks offline duration: records offline_since on FAULT,
     computes offline_duration_ms on recovery — zero writes in between

WHY REST INSTEAD OF MQTT?
  - TB stores raw telemetry automatically (uptime_ms, rssi_dbm)
  - We only need to know "a heartbeat arrived" to run inference
  - The rule chain is TB's native way to trigger external services
  - No second MQTT broker needed — simpler architecture
"""

import json
import time
import threading
import logging
import os
import urllib.request

from app.state_machine import DeviceMonitor, DeviceState, Event, MonitorConfig

logger = logging.getLogger(__name__)


class HeartbeatHandler:
    """
    Processes heartbeat events from ThingsBoard rule chain
    and manages absence detection via watchdog timer.

    FLOW:
      ESP32 → TB MQTT (stores raw telemetry automatically)
           → TB Rule Chain → POST /infer → this handler
           → processes heartbeat/absence via state machine
           → pushes inferred state back to TB via HTTP API
    """

    def __init__(
        self,
        monitor_config: MonitorConfig = None,
        device_id: str = "esp32",
    ):
        self.device_id = device_id

        # ThingsBoard HTTP API for pushing results
        self.tb_http_url = os.getenv("TB_HTTP_URL", "http://localhost:8080")
        self.tb_device_token = os.getenv("TB_DEVICE_TOKEN", "")

        if monitor_config is None:
            monitor_config = MonitorConfig(
                heartbeat_interval_s=float(
                    os.getenv("HEARTBEAT_INTERVAL_S", "30")),
                stale_after_n_absences=int(os.getenv("STALE_AFTER_N", "2")),
                fault_after_n_absences=int(os.getenv("FAULT_AFTER_N", "4")),
                recovery_heartbeats=int(os.getenv("RECOVERY_HEARTBEATS", "2")),
            )

        self.config = monitor_config
        self.monitor = DeviceMonitor(device_id, monitor_config)

        self.absence_window = (
            monitor_config.heartbeat_interval_s + monitor_config.tolerance_s
        )

        # Threading for watchdog timer
        self._lock = threading.Lock()
        self._watchdog_timer: threading.Timer = None
        self._running = False

        # Track last payload for status endpoint
        self.last_payload: dict = {}
        self.last_heartbeat_ts: float = None

        # ── Offline Duration Tracking ──
        # offline_since: Unix timestamp when OFFLINE_FAULT began (None if online)
        # offline_events: history of completed offline periods for /health
        self.offline_since: float = None
        self.offline_events: list = []

    # ── Heartbeat Processing (called by /infer endpoint) ─────

    def receive_heartbeat(self, payload: dict) -> dict:
        """
        Called when TB rule chain forwards a telemetry message.

        Args:
            payload: The telemetry JSON from ESP32
                     e.g. {"uptime_ms": 12345, "rssi_dbm": -58, ...}

        Returns:
            Current state dict (for the /infer response)
        """
        self.last_payload = payload
        self.last_heartbeat_ts = time.time()
        ts = time.time()

        logger.info(f"Heartbeat received: {payload}")

        with self._lock:
            transition = self.monitor.process_event(Event.HEARTBEAT, ts)

        if transition:
            logger.info(
                f"STATE CHANGE: {transition.from_state.value} → "
                f"{transition.to_state.value} | reason: {transition.reason}"
            )

            # Handle offline duration tracking on state change
            self._handle_offline_tracking(transition, ts)

            # Only push to TB when the state actually changes
            self._push_state_to_tb()

        # Reset the watchdog — we got a heartbeat, clock starts over
        self._reset_watchdog()

        return self._current_state_dict()

    # ── Absence Watchdog ─────────────────────────────────────

    def _reset_watchdog(self):
        """
        Reset the absence timer. Called after every heartbeat.

        If no heartbeat arrives within absence_window seconds,
        _on_absence_timeout fires and feeds an ABSENCE event.
        """
        if self._watchdog_timer:
            self._watchdog_timer.cancel()

        if self._running:
            self._watchdog_timer = threading.Timer(
                self.absence_window, self._on_absence_timeout
            )
            self._watchdog_timer.daemon = True
            self._watchdog_timer.start()

    def _on_absence_timeout(self):
        """Watchdog fired — no heartbeat received within the expected window."""
        ts = time.time()
        logger.warning(
            f"ABSENCE detected — no heartbeat for {self.absence_window}s"
        )

        with self._lock:
            transition = self.monitor.process_event(Event.ABSENCE, ts)

        if transition:
            logger.info(
                f"STATE CHANGE: {transition.from_state.value} → "
                f"{transition.to_state.value} | reason: {transition.reason}"
            )

            # Handle offline duration tracking on state change
            self._handle_offline_tracking(transition, ts)

            # Only push when state transitions
            self._push_state_to_tb()

        # Restart watchdog — if still absent, it fires again
        self._reset_watchdog()

    # ── Offline Duration Tracking ────────────────────────────

    def _handle_offline_tracking(self, transition, ts: float):
        """
        Track offline start and end times based on state transitions.
        All timestamps and durations use epoch MILLISECONDS to align
        with ThingsBoard's native timestamp format.

        WHEN OFFLINE_FAULT BEGINS:
          - Record offline_since as epoch ms (one write to TB)
          - Dashboard computes live timer: Date.now() - offline_since

        WHEN DEVICE RECOVERS TO OK:
          - Compute offline_duration_ms
          - Push to TB (one write)
          - Reset offline_since to 0
        """
        # Device just entered OFFLINE_FAULT — record the start time
        if (
            transition.to_state == DeviceState.OFFLINE_FAULT
            and self.offline_since is None
        ):
            self.offline_since = int(ts * 1000)  # epoch ms
            logger.info(f"Offline period started at {self.offline_since} (epoch ms)")

        # Device recovered back to OK — compute and store the duration
        if (
            transition.to_state == DeviceState.OK
            and self.offline_since is not None
        ):
            recovered_at_ms = int(ts * 1000)
            duration_ms = recovered_at_ms - self.offline_since

            event = {
                "offline_since": self.offline_since,
                "recovered_at": recovered_at_ms,
                "offline_duration_ms": duration_ms,
                "recovery_reason": transition.reason,
            }
            self.offline_events.append(event)

            logger.info(
                f"Offline period ended. Duration: {duration_ms}ms "
                f"({self._format_duration(duration_ms / 1000)})"
            )

            # Push the completed offline event to TB as telemetry
            self._push_offline_event_to_tb(event)

            # Clear locally and in TB
            # Setting to 0 is an explicit "not offline" signal
            # JS falsy check: 0 is falsy, so widget shows "ONLINE"
            self.offline_since = None

    def _format_duration(self, seconds: float) -> str:
        """Human-readable duration string for logging."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            m = int(seconds // 60)
            s = int(seconds % 60)
            return f"{m}m {s}s"
        else:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}h {m}m"

    def _push_offline_event_to_tb(self, event: dict):
        """
        Push a completed offline event to ThingsBoard.

        Sends offline_duration_ms as telemetry so it appears in time-series.
        The dashboard can show a table/chart of offline events with durations.
        """
        if not self.tb_device_token:
            return

        data = {
            "offline_duration_ms": event["offline_duration_ms"],
            "offline_since": 0,
        }

        url = f"{self.tb_http_url}/api/v1/{self.tb_device_token}/telemetry"
        payload = json.dumps(data).encode("utf-8")

        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            logger.info(
                f"Pushed offline event to TB: {event['offline_duration_ms']}ms"
            )
        except Exception as e:
            logger.warning(f"Failed to push offline event to TB: {e}")

    # ── Push State to ThingsBoard ────────────────────────────

    def _current_state_dict(self) -> dict:
        """Build the current state as a dictionary."""
        state_data = {
            "inferred_state": self.monitor.state.value,
            "consecutive_absences": self.monitor.consecutive_absences,
            "consecutive_heartbeats": self.monitor.consecutive_heartbeats,
        }

        if self.monitor.transitions:
            last = self.monitor.transitions[-1]
            state_data["last_reason"] = last.reason

        return state_data

    def _push_state_to_tb(self):
        """
        Send inferred state to ThingsBoard via HTTP telemetry API.

        WHY telemetry (not attributes)?
          - Telemetry has time-series storage → chart state over time
          - Important for capstone: showing state transitions on a timeline

        NOTE: TB rule chain filter checks for 'uptime_ms' in the message.
          Inference results don't contain 'uptime_ms', so they won't loop.
        """
        if not self.tb_device_token:
            logger.warning("No TB_DEVICE_TOKEN configured — skipping TB push")
            return

        data = self._current_state_dict()

        # Include offline_since when device is currently offline
        # WHY: The dashboard reads this value to compute a live countdown
        # Formula in widget: current_time - offline_since = live duration
        # This is written ONCE when FAULT begins, not repeatedly
        if self.offline_since is not None:
            data["offline_since"] = self.offline_since

        url = f"{self.tb_http_url}/api/v1/{self.tb_device_token}/telemetry"
        payload = json.dumps(data).encode("utf-8")

        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            logger.debug(f"Pushed state to ThingsBoard: {data}")
        except Exception as e:
            logger.warning(f"Failed to push to ThingsBoard: {e}")

    # ── Lifecycle ────────────────────────────────────────────

    def start(self):
        """Start the watchdog timer. Called on FastAPI startup."""
        logger.info(
            f"HeartbeatHandler started "
            f"(absence window: {self.absence_window}s)"
        )
        self._running = True
        self._reset_watchdog()

    def stop(self):
        """Stop the watchdog timer. Called on FastAPI shutdown."""
        logger.info("HeartbeatHandler stopping")
        self._running = False
        if self._watchdog_timer:
            self._watchdog_timer.cancel()

    def get_status(self) -> dict:
        """Status snapshot for /health endpoint."""
        with self._lock:
            return {
                "device_id": self.device_id,
                "state": self.monitor.state.value,
                "consecutive_absences": self.monitor.consecutive_absences,
                "consecutive_heartbeats": self.monitor.consecutive_heartbeats,
                "last_event_ts": self.monitor.last_event_ts,
                "last_heartbeat_ts": self.last_heartbeat_ts,
                "transitions_count": len(self.monitor.transitions),
                "last_payload": self.last_payload,
                "offline_since": self.offline_since,
                "offline_events": self.offline_events,
            }