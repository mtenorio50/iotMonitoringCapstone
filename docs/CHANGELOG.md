# Project Changelog

Record of development activity for the Smart City Streets capstone project.

---

## 2026-01-01 — Project Kickoff & ThingsBoard Integration

**Commit:** `4e2c4d4` — *Initial commit with TB integration*

- Created PlatformIO project for ESP32 microcontroller
- Wrote initial `main.cpp` with MQTT telemetry publishing to ThingsBoard
- Configured `.gitignore`, VS Code settings, and PlatformIO build config
- Added project documentation:
  - `README.md` — project overview
  - `docs/steps.md` — setup and development steps
  - `docs/issues.md` — known issues and troubleshooting notes

**Files:** 12 files, 720 lines added

---

## 2026-01-22 — OLED Display & LDR Sensor Integration

**Commit:** `afedb7c` — *integrate with oled*

- Added OLED display module (`oled.h` / `oled.cpp`) for on-device status readout
- Added LDR (Light Dependent Resistor) sensor module (`ldr.h` / `ldr.cpp`) for ambient light sensing
- Significantly expanded `main.cpp` (197 new lines) to integrate both peripherals
- Updated PlatformIO dependencies for display and sensor libraries

**Files:** 6 files, 309 insertions, 23 deletions

---

## 2026-02-21 — Monorepo Restructure

**Commit:** `dbb7c49` — *restructure to monorepo*

- Reorganized project into a monorepo layout:
  - `esp32/` — all ESP32 firmware (PlatformIO project moved here)
  - `inference/` — Python inference service (placeholder)
  - `nginx/` — reverse proxy config
  - `docker-compose.yml` — container orchestration (placeholder)
  - `docs/` — shared documentation
- Expanded ESP32 `main.cpp` with 114 new lines of functionality
- Added VS Code C/C++ IntelliSense, launch, and settings configs under `esp32/.vscode/`
- Created placeholder files for `env.example`, `architecture.md`, and `docker-compose.yml`

**Files:** 18 files, 666 insertions, 13 deletions

---

## 2026-02-21 — Inference Service: Initial Scaffolding

**Commit:** `e214a4a` — *initial inference files*

- Created Python package structure for the inference service:
  - `inference/app/__init__.py`
  - `inference/results/plots/__init__.py`
  - `inference/results/scenarios/__init__.py`
  - `inference/tests/__init__.py`

**Files:** 4 files, 4 insertions

---

## 2026-02-21 — Inference Service: State Machine & Baseline Monitor

**Commit:** `0ba82b4` — *added inference*

- Implemented `state_machine.py` — FSM-based device monitor with graduated escalation (OK → STALE → FAULT), hysteresis recovery, suppression awareness, and audit logging (257 lines)
- Implemented `baseline_monitor.py` — simple timeout-based monitor for comparison (127 lines)
- Created `main.py` — FastAPI entry point with `/health` endpoint
- Added `requirements.txt` with project dependencies
- Wrote `test_state_machine.py` — 200 lines of unit tests for the state machine
- Updated `.gitignore` for Python artifacts

**Files:** 7 files, 630 insertions

---

## 2026-02-21 — Inference Service: Digital Twin, Metrics & Experiments

**Commit:** `b11021f` — *added inference functions*

- Implemented `digital_twin.py` — scenario simulator generating 7 synthetic test scenarios with ground truth labels (428 lines)
- Implemented `metrics.py` — time-aligned evaluation engine computing accuracy, false positives, false negatives, and detection latency (156 lines)
- Implemented `run_experiments.py` — automated experiment runner across all scenarios, exports results to CSV (133 lines)
- Generated `results/summary.csv` with experiment results (15 rows)
- Minor fix in `state_machine.py`

**Files:** 5 files, 733 insertions

---

## 2026-02-21 — Inference Service: Visualization & Plots

**Commit:** `c812500` — *added plots*

- Implemented `plots.py` — generates publication-quality comparison charts (320 lines)
- Generated 6 plot images in `results/plots/`:
  - `accuracy_comparison.png` — proposed vs baseline accuracy
  - `fp_fn_comparison.png` — false positive/negative breakdown
  - `timeline_flapping_intermittent.png` — scenario 7 timeline
  - `timeline_hard_fault_offline.png` — scenario 6 timeline
  - `timeline_suppression_window.png` — scenario 2 timeline
  - `timeline_temporary_dropout.png` — scenario 3 timeline
  - `tradeoff_curves.png` — parameter sweep trade-off analysis

**Files:** 8 files, 320 insertions

---

## 2026-02-21 — Merge Inference Branch & Documentation Update

**Commits:** `8442fe1`, `02903b2`, `f741fc5`

- Merged `inference` branch into `main`
- Minor fix to `plots.py` (3 lines)
- Major documentation update:
  - Rewrote `README.md` with full project overview (+85 lines)
  - Created `docs/architecture.md` — system architecture, state machine design, digital twin scenarios, evaluation methodology (110 lines)
  - Updated `docs/issues.md` and `docs/steps.md` with latest information

**Files:** 5 files, 296 insertions, 29 deletions

---

## 2026-02-22 — Docker Compose & MQTT Bridge (Live Integration)

**Commit:** `debc40e` — *docker setup*

- Created `docker-compose.yml` defining full service stack:
  - Mosquitto MQTT broker
  - Python inference service
  - (ThingsBoard + Postgres on AWS)
- Implemented `mqtt_bridge.py` — live MQTT integration layer (241 lines):
  - Subscribes to `devices/+/telemetry` on Mosquitto
  - Runs absence watchdog timer for heartbeat monitoring
  - Publishes inferred device state to Mosquitto (retained) and ThingsBoard HTTP API
  - Thread-safe state machine access
  - Configurable via environment variables
- Created `inference/Dockerfile` for containerized deployment
- Added `mosquitto/config/mosquitto.conf` for broker configuration
- Expanded `inference/app/main.py` with MQTT bridge startup logic
- Updated `README.md` with Docker instructions
- Added ESP32 `.gitignore` for build artifacts

**Files:** 11 files, 412 insertions, 45 deletions

---

## 2026-02-25 — Infrastructure Simplification

**Commit:** `da36334` — *change infrastructure*

- Replaced MQTT bridge (`mqtt_bridge.py`) with REST-based `HeartbeatHandler` (`heartbeat_handler.py`)
- Removed Mosquitto broker from docker-compose — ThingsBoard's built-in MQTT broker handles all device telemetry
- New integration flow: TB rule chain → REST POST `/infer` → HeartbeatHandler → pushes state back to TB HTTP API
- Added offline duration tracking: `offline_since` on FAULT, `offline_duration_ms` on recovery
- Simplified docker-compose to two services: ThingsBoard (`tb-postgres`) and inference

**Files:** Infrastructure refactor

---

## 2026-03-03 — Documentation & Code Updates

**Commit:** `56a3a6f` — *update*

- Updated documentation and code to reflect architecture changes
- Cleaned up references to removed Mosquitto/MQTT bridge components

---

## 2026-03-09 — Experiment API Endpoints

**Commit:** `f3b3817` — *included experiments*

- Added `experiment_api.py` — REST endpoints for ThingsBoard HTML widgets:
  - `GET /experiments/scenarios` — list all 7 test scenarios
  - `GET /experiments/summary` — run all scenarios, return comparison metrics
  - `GET /experiments/timeline` — run one scenario, return tick-by-tick states
  - `GET /experiments/sweep` — RQ3 parameter sweep (15s, 30s, 60s, 120s)
  - `GET /experiments/telemetry-cost` — telemetry volume analysis
- Updated `main.py` to include experiment router and CORS middleware
- ESP32 telemetry keys finalized: `uptime_ms`, `rssi_dbm` (hb and LDR fields commented out)

---

## Summary Timeline

| Date | Milestone |
|------|-----------|
| 2026-01-01 | Project started — ESP32 + ThingsBoard MQTT telemetry |
| 2026-01-22 | Added OLED display and LDR light sensor to ESP32 |
| 2026-02-21 | Restructured to monorepo (esp32 / inference / nginx) |
| 2026-02-21 | Built full inference pipeline: state machine, digital twin, metrics, experiments, plots |
| 2026-02-21 | Merged inference branch, updated all documentation |
| 2026-02-22 | Docker Compose setup, initial MQTT bridge |
| 2026-02-25 | Simplified to REST-based integration — removed Mosquitto, replaced MQTT bridge with HeartbeatHandler |
| 2026-03-03 | Documentation and code cleanup |
| 2026-03-09 | Added experiment API endpoints for dashboard widgets |
