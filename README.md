# Inference-First IoT Monitoring (Capstone) — ThingsBoard + Python + ESP32 (Low-Telemetry)

This repo is a capstone proof-of-concept for “reasoning under telemetry insufficiency”: when devices send minimal telemetry and silence is ambiguous (suppression vs delay vs comms loss vs failure), the system should still infer defensible device states using timing windows, transition constraints, and explicit “absence events”.

The stack is intentionally lightweight and cheap to run (AWS Lightsail + Docker).

---

## What this project demonstrates

1) Minimal device telemetry  
- ESP32 publishes a heartbeat (`hb`) every fixed interval plus small context signals (e.g., RSSI, uptime) to help disambiguate comms quality and device resets.

2) Arrival + absence as first-class events  
- Telemetry arrival is an event.
- Missing telemetry is turned into an explicit “absence event” (time-window based), instead of being treated as a vague dashboard symptom.

3) Explicit inference as a state machine (Python service)
- A proposed FSM monitor applies deterministic rules with graduated escalation:
  - OK → STALE → OFFLINE_FAULT → RECOVERED → OK
  - SILENT state for planned suppression windows
- Hysteresis: requires multiple consecutive heartbeats to confirm recovery (prevents flapping).
- Each state transition produces a reason tag for auditability.

4) Baseline comparison (control experiment)
- A simple timeout-based monitor serves as the control.
- No suppression awareness, no RECOVERED state, no hysteresis.
- Used to answer RQ1: “How does inference-first compare to timeout-based monitoring?”

5) Digital twin validation
- 7 synthetic scenarios simulate real-world conditions (normal, suppression, dropout, jitter, degradation, hard fault, flapping).
- Time-aligned metrics (accuracy, FP, FN, detection latency) compare both monitors against ground truth.
- Parameter sweeps vary heartbeat interval to explore telemetry-rate trade-offs (RQ3).
- Publication-quality plots generated for the report.

6) ThingsBoard used for visualization + storage
- Mosquitto handles MQTT transport (device telemetry + inferred state pub/sub).
- Python MQTT bridge is the “brain” that subscribes to heartbeats, runs the state machine, and pushes inferred state to both Mosquitto and ThingsBoard HTTP API.
- ThingsBoard provides dashboards and telemetry storage.

---

## Architecture (high level)

ESP32 (MQTT telemetry: hb, rssi_dbm, uptime_ms)
→ Mosquitto MQTT broker
→ MQTT Bridge (Python) subscribes, runs state machine, detects absence
→ Publishes inferred state to Mosquitto (retained) + ThingsBoard HTTP API
→ ThingsBoard dashboards display inferred state, reason tags, and forwarded telemetry

---

## Repo structure

```
.
├── docker-compose.yml              # ThingsBoard + Postgres + inference containers
├── nginx/
│   └── thingsboard.conf            # Reverse proxy config (port 80 → TB 8080)
├── inference/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                 # FastAPI service (GET /health)
│   │   ├── state_machine.py        # Proposed FSM monitor (OK → STALE → FAULT → RECOVERED → SILENT)
│   │   ├── baseline_monitor.py     # Control monitor (simple timeout, no hysteresis/suppression)
│   │   ├── mqtt_bridge.py          # Live MQTT integration — subscribes to Mosquitto, runs state machine
│   │   ├── digital_twin.py         # Scenario simulator — 7 synthetic test scenarios with ground truth
│   │   ├── metrics.py              # Evaluation engine — accuracy, FP, FN, detection latency
│   │   ├── run_experiments.py      # Experiment runner — runs all scenarios, outputs CSV
│   │   └── plots.py                # Visualization — generates publication-quality PNG plots
│   ├── tests/
│   │   └── test_state_machine.py   # Unit tests for the state machine
│   └── results/
│       ├── summary.csv             # Experiment results (7 scenarios × 2 monitors)
│       ├── plots/                  # Generated plot PNGs (accuracy, FP/FN, timelines, trade-offs)
│       └── scenarios/              # Scenario output data
├── esp32/
│   ├── platformio.ini
│   └── src/
│       ├── main.cpp                # MQTT heartbeat publisher (PubSubClient)
│       ├── oled.cpp                # OLED display integration
│       └── ldr.cpp                 # Light-dependent resistor sensor
├── docs/
│   ├── steps.md                    # Dev log (dated, setup + deployment trail)
│   ├── issues.md                   # Issues encountered + fixes applied
│   └── architecture.md             # System architecture notes
└── claude.md                       # AI assistant context file
```

---

## Prerequisites

Local:
- Git
- PlatformIO (VS Code extension)

Server (Ubuntu 24.04):
- Docker + Docker Compose v2
- Nginx (optional but recommended if you want port 80)

---

## Deployment (AWS Lightsail)

This project was tested on:
- Ubuntu 24.04 LTS
- 2GB RAM instance + 2GB swap (tight but workable for capstone)

### 1) Install Docker + Compose v2 (server)

Check:
- `docker --version`
- `docker compose version`

(If you already have both v1 `docker-compose` and v2 `docker compose`, prefer v2.)

### 2) Clone repo
```bash
git clone <your-repo-url>
cd capstoneProject
```

---

## Running the Inference Experiments

The inference subsystem runs entirely offline — no server or ESP32 needed.

### Install dependencies
```bash
cd inference
pip install -r requirements.txt   # FastAPI, matplotlib, numpy
```

### Run all experiments and print comparison table
```bash
python -m app.run_experiments
```
Outputs `results/summary.csv` with accuracy, FP, FN, and detection latency for all 7 scenarios.

### Generate plots for the report
```bash
python -m app.plots
```
Outputs PNG plots to `results/plots/`:
- `accuracy_comparison.png` — Proposed vs baseline accuracy per scenario (RQ1)
- `fp_fn_comparison.png` — False positives & negatives breakdown (RQ1 + RQ2)
- `timeline_*.png` — State timelines showing ground truth vs inferred states (RQ2)
- `tradeoff_curves.png` — Accuracy vs heartbeat interval sweep (RQ3)

### Preview digital twin scenarios
```bash
python -m app.digital_twin
```

---

## Research Questions Addressed

| RQ | Question | Evidence |
|----|----------|----------|
| RQ1 | How does inference-first compare to timeout-based monitoring? | Accuracy comparison + FP/FN counts across 7 scenarios |
| RQ2 | Can the proposed monitor reduce false alarms during planned silence? | Suppression window scenario (100% vs 60% accuracy) + state timelines |
| RQ3 | What is the trade-off between reducing telemetry and inference quality? | Parameter sweep plots across heartbeat intervals 15s–120s |

---

## Key Experiment Results (summary.csv)

| Scenario | Proposed Accuracy | Baseline Accuracy | Key Difference |
|----------|------------------|-------------------|----------------|
| Normal sparse reporting | 100% | 100% | Both correct (sanity check) |
| Suppression window | 100% | 60% | Baseline has 60 FPs during planned silence |
| Temporary dropout | 90% | 90% | Both handle dropout equally |
| Jitter/delayed delivery | 100% | 100% | Both handle jitter well |
| Gradual degradation | 71% | 71% | Both struggle with slow degradation |
| Hard fault offline | 90% | 90% | Both detect hard failure equally |
| Flapping intermittent | 90% | 70% | Baseline false-recovers on single fluke heartbeat |
