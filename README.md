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
- A small inference service applies deterministic rules:
  - OK, SILENT (suppression), STALE, OFFLINE/FAULT
- Each state transition produces a reason tag for auditability.

4) ThingsBoard used for transport + visualization  
- ThingsBoard handles device connectivity (MQTT) and dashboards.
- Python is the “brain” that produces inferred state timelines and reasons.

---

## Architecture (high level)

ESP32 (MQTT telemetry)
→ ThingsBoard (ingestion + rule chain)
→ REST API call to Python inference service
→ ThingsBoard stores inferred results (telemetry/attributes) for dashboards

---

## Repo structure (suggested)

.
├── scs-stack/
│   ├── docker-compose.yml
│   ├── nginx/
│   │   └── thingsboard.conf
│   └── inference/
│       ├── Dockerfile
│       └── app/
│           └── main.py
├── esp32/
│   ├── platformio.ini
│   └── src/
│       └── main.cpp
└── docs/
    └── build-notes.md

Notes:
- `docs/build-notes.md` = the “issues + fixes” log (your engineering trail).
- `inference/app/main.py` should expose at least:
  - `GET /health`
  - `POST /infer` (or similar)

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
cd scs-stack
