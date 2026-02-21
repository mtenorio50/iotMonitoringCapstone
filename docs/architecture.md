# System Architecture

## High-Level Flow

```
ESP32 (MQTT telemetry: hb, rssi, uptime_ms)
  → ThingsBoard CE (MQTT ingestion + rule chain)
    → REST API call to Python inference service
      → ThingsBoard stores inferred state + reason for dashboards
```

## Component Overview

### 1. ESP32 Device Layer
- Publishes minimal telemetry via MQTT (`PubSubClient`) to `v1/devices/me/telemetry`
- Telemetry keys: `hb` (heartbeat), `rssi` (Wi-Fi signal strength), `uptime_ms` (millis since boot)
- Auth: device access token as MQTT username

### 2. ThingsBoard CE (Transport + Visualization)
- Runs as Docker container on AWS Lightsail (Ubuntu 24.04, 2GB RAM + 2GB swap)
- Handles MQTT broker (port 1883) and HTTP API (port 8080)
- Nginx reverse proxy forwards port 80 → 8080
- Rule chain triggers REST call to inference service on telemetry arrival

### 3. Python Inference Service (FastAPI)
- Runs as separate Docker container (port 8000)
- **API endpoints**: `GET /health`
- **Core modules**:

| Module | Purpose |
|--------|---------|
| `state_machine.py` | Proposed FSM monitor — graduated escalation with hysteresis |
| `baseline_monitor.py` | Control monitor — simple timeout counter, no suppression/recovery |
| `digital_twin.py` | Scenario simulator — 7 synthetic scenarios with ground truth |
| `metrics.py` | Evaluation engine — time-aligned accuracy, FP, FN, detection latency |
| `run_experiments.py` | Experiment runner — runs all scenarios, exports CSV |
| `plots.py` | Visualization — generates publication-quality PNG plots |

## State Machine Design

### Proposed Monitor (DeviceMonitor)

States: `OK`, `STALE`, `OFFLINE_FAULT`, `RECOVERED`, `SILENT`

```
         HEARTBEAT           HEARTBEAT (×N)
  OK ←──────────── STALE ←──────────── OFFLINE_FAULT
  │                  ↑                      │
  │   ABSENCE (×2)  │     ABSENCE (×4)      │  HEARTBEAT
  └─────────────────┘                       ↓
                                        RECOVERED
                                            │
                                   HEARTBEAT (×recovery_n)
                                            ↓
                                           OK

  SUPPRESS_ON → SILENT → SUPPRESS_OFF → (restore previous state)
```

Key design features:
- **Graduated escalation**: OK → STALE (2 absences) → FAULT (4 absences)
- **Hysteresis on recovery**: Requires `recovery_heartbeats` (default 2) consecutive heartbeats to confirm recovery
- **Suppression awareness**: SILENT state during planned maintenance windows — no false alarms
- **Relapse protection**: Absence during RECOVERED → back to FAULT immediately
- **Audit trail**: Every transition logged with timestamp, event, and reason tag

### Baseline Monitor (BaselineMonitor)

States: `OK`, `STALE`, `OFFLINE_FAULT` (no RECOVERED, no SILENT)

Key differences:
- No suppression awareness (SUPPRESS events ignored)
- No RECOVERED state (heartbeat after FAULT → straight to OK)
- No hysteresis (single heartbeat = recovery)
- No relapse protection

### Configuration (MonitorConfig)

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `heartbeat_interval_s` | 30.0 | Expected interval between heartbeats |
| `tolerance_s` | 10.0 | Grace period before declaring absence |
| `stale_after_n_absences` | 2 | Consecutive absences to trigger STALE |
| `fault_after_n_absences` | 4 | Consecutive absences to trigger FAULT |
| `recovery_heartbeats` | 2 | Consecutive heartbeats needed to confirm recovery |

## Digital Twin Scenarios

| # | Scenario | Ground Truth | Purpose |
|---|----------|-------------|---------|
| 1 | Normal sparse reporting | OK throughout | Sanity check — both should score 100% |
| 2 | Suppression window | OK → SILENT → OK | RQ2: Can proposed avoid false alarms during planned silence? |
| 3 | Temporary dropout | OK → STALE → OK | Tests detection and recovery from connectivity loss |
| 4 | Jitter/delayed delivery | OK throughout | RQ2: Can monitors handle transport delay without false alarms? |
| 5 | Gradual degradation | OK → STALE → FAULT | Tests slow degradation detection (increasing drop probability) |
| 6 | Hard fault offline | OK → FAULT | Both should detect; tests detection speed |
| 7 | Flapping intermittent | OK → FAULT | Tests hysteresis — single fluke heartbeat mid-outage |

## Evaluation Methodology

- **Time-aligned comparison**: Sample inferred state and ground truth at 1-second intervals
- **Metrics**: Accuracy (proportion of matched samples), false positives, false negatives, fault detection latency, total transitions
- **Match rules**: RECOVERED and STALE are treated as acceptable during FAULT ground truth (monitor is escalating)
- **Parameter sweep (RQ3)**: Vary heartbeat interval [15s, 30s, 60s, 120s] and re-run all scenarios

## Infrastructure

- **Hosting**: AWS Lightsail, Ubuntu 24.04, 2GB RAM + 2GB swap
- **Containers**: Docker Compose v2 (ThingsBoard + Postgres + inference service)
- **Reverse proxy**: Nginx (port 80 → ThingsBoard 8080)
