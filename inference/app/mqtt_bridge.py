"""
MQTT Bridge — Live Integration
================================
Connects the inference state machine to Mosquitto MQTT broker.

Subscribes to device heartbeats, detects absence via watchdog timer,
and publishes inferred state to both Mosquitto and ThingsBoard.
"""

import json
import time
import threading
import logging
import os
import paho.mqtt.client as mqtt
from app.state_machine import DeviceMonitor, DeviceState, Event, MonitorConfig

logger = logging.getLogger(__name__)

# Topic structure:
#   devices/{device_id}/telemetry   — ESP32 publishes here
#   devices/{device_id}/state       — inference publishes inferred state here
TELEMETRY_TOPIC = "devices/+/telemetry"
STATE_TOPIC_TEMPLATE = "devices/{device_id}/state"


class MQTTBridge:
    """
    Bridges MQTT heartbeats to the inference state machine.

    FLOW:
      ESP32 → Mosquitto (devices/esp32/telemetry)
      Inference subscribes → processes → publishes state
      Inference → Mosquitto (devices/esp32/state)
      Inference → ThingsBoard HTTP API (for dashboards)
    """

    def __init__(
        self,
        monitor_config: MonitorConfig = None,
        broker_host: str = None,
        broker_port: int = None,
        device_id: str = "esp32",
    ):
        self.broker_host = broker_host or os.getenv(
            "MQTT_BROKER_HOST", "localhost")
        self.broker_port = broker_port or int(
            os.getenv("MQTT_BROKER_PORT", "1883"))
        self.device_id = device_id

        # ThingsBoard HTTP API for pushing results to dashboards
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

        # Threading
        self._lock = threading.Lock()
        self._watchdog_timer: threading.Timer = None
        self._running = False

        # MQTT client
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"inference-{device_id}",
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        self.last_payload: dict = {}

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info(
                f"MQTT connected to {self.broker_host}:{self.broker_port}")
            # Subscribe to ALL device telemetry
            # '+' is MQTT wildcard — matches any device ID
            client.subscribe(TELEMETRY_TOPIC)
            logger.info(f"Subscribed to {TELEMETRY_TOPIC}")
            self._reset_watchdog()
        else:
            logger.error(f"MQTT connection failed, rc={rc}")

    def _on_message(self, client, userdata, msg):
        """Heartbeat received — device is alive."""
        try:
            payload = json.loads(msg.payload.decode())
            logger.info(f"Heartbeat received on {msg.topic}: {payload}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
            logger.warning(f"Could not decode payload: {msg.payload}")

        self.last_payload = payload
        ts = time.time()

        with self._lock:
            transition = self.monitor.process_event(Event.HEARTBEAT, ts)

        if transition:
            logger.info(
                f"STATE CHANGE: {transition.from_state.value} → "
                f"{transition.to_state.value} | reason: {transition.reason}"
            )
            self._publish_state()

        self._reset_watchdog()

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        logger.warning(f"MQTT disconnected, rc={rc}")

    # ── Absence Watchdog ─────────────────────────────────────────

    def _reset_watchdog(self):
        if self._watchdog_timer:
            self._watchdog_timer.cancel()

        if self._running:
            self._watchdog_timer = threading.Timer(
                self.absence_window, self._on_absence_timeout
            )
            self._watchdog_timer.daemon = True
            self._watchdog_timer.start()

    def _on_absence_timeout(self):
        ts = time.time()
        logger.warning(
            f"ABSENCE detected — no heartbeat for {self.absence_window}s")

        with self._lock:
            transition = self.monitor.process_event(Event.ABSENCE, ts)

        if transition:
            logger.info(
                f"STATE CHANGE: {transition.from_state.value} → "
                f"{transition.to_state.value} | reason: {transition.reason}"
            )
            self._publish_state()

        self._reset_watchdog()

    # ── Publish State ────────────────────────────────────────────

    def _publish_state(self):
        """Publish inferred state to Mosquitto and ThingsBoard."""
        state_data = {
            "inferred_state": self.monitor.state.value,
            "consecutive_absences": self.monitor.consecutive_absences,
            "consecutive_heartbeats": self.monitor.consecutive_heartbeats,
        }

        if self.monitor.transitions:
            last = self.monitor.transitions[-1]
            state_data["last_reason"] = last.reason

        payload = json.dumps(state_data)

        # Publish to Mosquitto (for any subscriber)
        state_topic = STATE_TOPIC_TEMPLATE.format(device_id=self.device_id)
        try:
            self.client.publish(state_topic, payload, retain=True)
            logger.info(f"Published state to {state_topic}: {state_data}")
        except Exception as e:
            logger.error(f"Failed to publish state to Mosquitto: {e}")

        # Publish to ThingsBoard via HTTP API (for dashboards)
        self._push_to_thingsboard(state_data)

    def _push_to_thingsboard(self, data: dict):
        """
        Send inferred state to ThingsBoard via HTTP API.

        WHY HTTP and not MQTT? Because TB's MQTT is device-specific.
        The HTTP telemetry API is simpler for server-to-server communication.
        """
        if not self.tb_device_token:
            return  # No token configured, skip TB push

        import urllib.request

        url = f"{self.tb_http_url}/api/v1/{self.tb_device_token}/telemetry"
        payload = json.dumps(data).encode("utf-8")

        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            logger.debug(f"Pushed state to ThingsBoard: {data}")
        except Exception as e:
            logger.warning(f"Failed to push to ThingsBoard: {e}")

    # ── Lifecycle ────────────────────────────────────────────────

    def start(self):
        logger.info(
            f"Starting MQTT bridge: {self.broker_host}:{self.broker_port} "
            f"(absence window: {self.absence_window}s)"
        )

        self._running = True
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.client.loop_start()

    def stop(self):
        logger.info("Stopping MQTT bridge")
        self._running = False

        if self._watchdog_timer:
            self._watchdog_timer.cancel()

        self.client.loop_stop()
        self.client.disconnect()

    def get_status(self) -> dict:
        with self._lock:
            return {
                "device_id": self.device_id,
                "state": self.monitor.state.value,
                "consecutive_absences": self.monitor.consecutive_absences,
                "consecutive_heartbeats": self.monitor.consecutive_heartbeats,
                "last_event_ts": self.monitor.last_event_ts,
                "transitions_count": len(self.monitor.transitions),
                "last_payload": self.last_payload,
            }
