# Capstone Dev Log

## Context
Goal: Stand up a low-cost, always-on environment to host ThingsBoard CE (visuals + device ingestion) and a Python “inference brain” service, both on a Lightsail Ubuntu 24.04 instance, with ESP32 sending minimal telemetry.

Instance choice: 2GB RAM plan (with swap as safety buffer). Upgrade later only if proven necessary.

---

## 1 Jan 2026 — Initial Setup (Server + ThingsBoard + ESP32)

### 1) Server baseline and updates
- Logged into the Ubuntu 24.04 Lightsail instance.
- Ran system checks (`uptime`, `who -b`, `uname -r`) to confirm reboots and kernel version changes.
- Updated package indexes and checked pending upgrades (`apt update`, `apt list --upgradable`).
- Verified when a reboot is needed by checking `/var/run/reboot-required` (and saw “No reboot required” at one point).

### 2) Swap file added to reduce OOM risk on 2GB
Reason: ThingsBoard (Java) spikes RAM on startup and during DB initialization; swap reduces crash risk.
- Created `/swapfile` (2GB), set permissions, formatted, enabled swap, and persisted in `/etc/fstab`.
- Initial `swapon /swapfile` failed due to permissions; fixed by enabling via `sudo swapon /swapfile`.
- Verified with:
  - `swapon --show`
  - `free -h`
- Confirmed swap became active and visible.

### 3) Docker + Compose friction
- Installed Docker; confirmed Docker engine is running (`systemctl status docker`).
- Hit package error: `docker-compose-plugin` not found via apt initially.
- Later confirmed Docker Compose v2 is available: `docker compose version`.
- Also had legacy `docker-compose` v1.29.2 in the system (caused confusion and occasional errors). Decided to use **Compose v2** going forward.

### 4) ThingsBoard deployment via Docker Compose (first successful boot, then config changes)
- Brought up ThingsBoard + Postgres containers and validated containers/ports (`docker ps`).
- Confirmed ThingsBoard logs show startup sequence and DB bootstrap.
- Observed RAM usage high on 2GB plan during initialization; swap helped stabilize.

### 5) Networking and access (Lightsail firewall + nginx reverse proxy)
- Lightsail IPv4 firewall rules were reviewed/edited (SSH 22, HTTP 80, and 8080 initially).
- Installed and enabled nginx (`systemctl enable --now nginx`).
- Confirmed nginx default page working via `curl -I http://localhost`.
- Configured nginx to reverse proxy HTTP :80 → ThingsBoard :8080.
- Validated nginx config (`nginx -t`) and reloaded nginx.
- Confirmed browser access to ThingsBoard via public IP (port 80 via nginx, and also tested 8080).

---

## 22 Jan 2026 — OLED Integration + Runtime Fixes

### 1) Compose/runtime instability addressed
- Encountered compose errors when recreating containers (including `KeyError: 'ContainerConfig'`).
- Cleaned up stopped/exited containers and re-ran compose successfully.
- Re-verified that ThingsBoard becomes reachable and stabilizes after initial load.

### 2) ThingsBoard UI and rule chain confusion
- Logged into ThingsBoard and noticed expected menu items (like Rule Chains) weren’t visible in the UI at one stage.
- Realized parts of the environment were using different profiles/config contexts (effectively “looking at the wrong setup”).
- Attempted rule chain creation for “post telemetry → build inference event → REST API call → extract result”.
- Hit script/node error: event script used a transformer-style function signature and failed parsing (expected syntax didn’t match node type).

### 3) Python inference service (FastAPI) container added
Goal: Stand up a separate “inference brain” service that TB can call via REST.
- Created a minimal Dockerfile under `inference/` based on `python:3.12-slim`.
- Initial build failed due to Dockerfile content being corrupted (Dockerfile started with a `cat ...` line).
- Fixed Dockerfile; container started successfully.
- Verified inference service health endpoint works from server:
  - `curl http://localhost:8000/health` → returns JSON `{ ok: true, ts: ... }`
- Confirmed both containers are running:
  - ThingsBoard (ports 1883 MQTT, 8080 HTTP)
  - Inference service (port 8000)

### 4) ESP32 telemetry integration (PlatformIO)
- Started with ThingsBoard Arduino library but hit build error:
  - `no matching function for call to 'ThingsBoardSized<>::ThingsBoardSized(WiFiClient&)'`
- Decision: stop fighting the TB client library for now; use raw MQTT with `PubSubClient`.
- Implemented minimal MQTT publish to:
  - Topic: `v1/devices/me/telemetry`
  - Auth: username = device access token, password empty
- ESP32 successfully connected to MQTT broker at public IP:1883.
- Initially telemetry didn’t appear because the wrong ThingsBoard setup/profile/rule chain context was being used.
- Verified telemetry storage by checking DB tables:
  - `ts_kv_latest` empty
  - `ts_kv` count = 0 for that device ID
- After switching to the correct ThingsBoard context/profile, telemetry appeared in UI:
  - `hb = 1`
  - `rssi = -58`
  - `uptime_ms = 210045`

### 5) Meaning of telemetry keys (agreed direction)
- `rssi`: Wi-Fi signal strength (dBm) used as a comms-quality indicator (for inference about “silence vs degradation”).
- `uptime_ms`: millis since boot; used to detect resets/reboots (e.g., sudden drop implies restart).
- Decision: keep `rssi` as part of the minimal set.

---

## Decisions Locked
- Hosting approach: Lightsail Ubuntu 24.04 + Docker.
- Visuals: ThingsBoard CE.
- “Brain”: separate Python FastAPI service callable from TB via REST.
- Telemetry: minimal set includes heartbeat + uptime + RSSI.
- Cost control: stay on 2GB plan; use swap; only upgrade if evidence forces it.

---

## Known Issues / Risks
- ThingsBoard is RAM-hungry on startup; 2GB is tight without swap.
- Mixing `docker-compose` v1 and `docker compose` v2 caused errors/confusion; must standardize on v2.
- Rule chain editor/node types: scripts must match the exact node type (transformer vs event vs filter); otherwise syntax errors are misleading.
- Telemetry visibility depends on using the correct device profile/rule chain context; misconfiguration looks like “telemetry not arriving.”

---

## 21 Feb 2026 — Inference System Build-Out

### 6) State machine implementation (state_machine.py)
- Implemented `DeviceMonitor` — the proposed FSM with 5 states: OK, STALE, OFFLINE_FAULT, RECOVERED, SILENT.
- Key design features:
  - Graduated escalation: 2 absences → STALE, 4 absences → FAULT.
  - Hysteresis on recovery: requires 2 consecutive heartbeats to confirm recovery.
  - Suppression awareness: SILENT state during planned maintenance windows.
  - Relapse protection: absence during RECOVERED → back to FAULT.
  - Full audit trail: every transition logged with timestamp, event, and reason tag.
- Implemented `BaselineMonitor` — simple timeout counter as control experiment.
  - No suppression awareness, no RECOVERED state, no hysteresis.
  - Single heartbeat = immediate recovery (prone to flapping).
- Defined `MonitorConfig` with tunable parameters (heartbeat interval, tolerance, thresholds).

### 7) Digital twin scenario simulator (digital_twin.py)
- Built `DigitalTwin` class that generates 7 synthetic test scenarios, each with:
  - Controlled event streams (heartbeats, absences, suppression signals).
  - Ground truth state timelines for validation.
- Scenarios mapped to proposal Table 2:
  1. Normal sparse reporting — sanity check
  2. Suppression window — tests false alarm avoidance during planned silence
  3. Temporary dropout — tests connectivity loss detection and recovery
  4. Jitter/delayed delivery — tests transport delay tolerance
  5. Gradual degradation — tests slow failure detection
  6. Hard fault offline — tests sudden failure detection
  7. Flapping intermittent — tests hysteresis against fluke heartbeats
- All scenarios parameterised by heartbeat_interval for RQ3 parameter sweeps.
- Fixed random seed (42) for reproducible results.

### 8) Metrics engine (metrics.py)
- Implemented time-aligned comparison: samples inferred vs ground truth at 1-second intervals.
- Computes: accuracy, false positives, false negatives, fault detection latency, total transitions.
- Match rules: RECOVERED and STALE are acceptable during FAULT ground truth (monitor is escalating).

### 9) Experiment runner (run_experiments.py)
- Runs all 7 scenarios through both monitors and collects paired metrics.
- Outputs comparison table to console and `results/summary.csv`.
- Supports parameter sweep: varies heartbeat interval [15s, 30s, 60s, 120s] for RQ3.

### 10) Visualization (plots.py)
- Generates 4 types of publication-quality plots:
  1. **Accuracy comparison bar chart** (RQ1) — proposed vs baseline across all scenarios.
  2. **FP/FN grouped bar chart** (RQ1 + RQ2) — error breakdown per scenario.
  3. **State timeline plots** (RQ2) — ground truth vs proposed vs baseline for key scenarios.
  4. **Trade-off curves** (RQ3) — accuracy vs heartbeat interval sweep.
- Consistent color scheme across all plots (green=OK, orange=STALE, red=FAULT, blue=RECOVERED, purple=SILENT).
- Output: `results/plots/*.png`

### Key Experiment Results
| Scenario | Proposed | Baseline | Key Finding |
|----------|----------|----------|-------------|
| Normal sparse reporting | 100% | 100% | Both correct (sanity check) |
| Suppression window | 100% | 60% | Baseline generates 60 FPs during planned silence |
| Temporary dropout | 90% | 90% | Equal performance on dropout |
| Jitter/delayed delivery | 100% | 100% | Both handle jitter well |
| Gradual degradation | 71% | 71% | Both struggle with slow degradation |
| Hard fault offline | 90% | 90% | Equal on hard failure |
| Flapping intermittent | 90% | 70% | Baseline false-recovers on single fluke heartbeat |

---

## Decisions Locked (Updated — 21 Feb 2026)
- Hosting approach: Lightsail Ubuntu 24.04 + Docker.
- Visuals: ThingsBoard CE.
- "Brain": separate Python FastAPI service callable from TB via REST.
- Telemetry: minimal set includes heartbeat + uptime + RSSI.
- Cost control: stay on 2GB plan; use swap; only upgrade if evidence forces it.
- Validation: digital twin approach with 7 scenarios and time-aligned metrics.
- Comparison: proposed FSM vs baseline timeout monitor as control.

---

## Immediate Next Steps (as of 21 Feb 2026)
- Integrate the inference service with ThingsBoard rule chain (REST API call on telemetry arrival).
- Write inferred state + reason tag back to ThingsBoard as device attributes.
- Standardize telemetry keys: consider renaming `rssi` → `rssi_dbm`.

