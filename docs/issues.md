# Capstone Build Notes — Issues Encountered + What We Did

This document captures the main problems we hit while standing up ThingsBoard CE + Postgres + Python inference service on AWS Lightsail (Ubuntu 24.04), and the concrete fixes we applied.

---

## 1) Reboot + “How do I know it updated?”
Issue:
- After rebooting, SSH session disconnects and Lightsail tells you to close the window and reconnect.
- Confusion if updates actually applied.

What we did:
- Verified reboot actually happened using:
  - `who -b` (shows last boot time)
  - `uptime` (shows how long since boot)
- Verified kernel version after reboot:
  - `uname -r`

Outcome:
- Clear confirmation the instance rebooted and is running the expected kernel.

---

## 2) Swap file confusion (and permission error)
Issue:
- On 2GB RAM, ThingsBoard is tight. We added swap to avoid OOM crashes.
- `swapon: cannot open /swapfile: Permission denied`
- Later: `swapon failed: Device or resource busy`

What we did:
- Created and enabled swap properly:
  - `sudo fallocate -l 2G /swapfile`
  - `sudo chmod 600 /swapfile`
  - `sudo mkswap /swapfile`
  - `sudo swapon /swapfile`
- Persisted it across reboots:
  - Added `/swapfile none swap sw 0 0` to `/etc/fstab`
- Verified status:
  - `swapon --show`
  - `free -h`
- “resource busy” was simply because swap was already enabled.

Outcome:
- Swap is active (2GB) and provides a safety buffer during TB startup spikes.

---

## 3) Docker Compose package confusion
Issue:
- `Unable to locate package docker-compose-plugin`
- We ended up with both:
  - old `docker-compose` v1.29.x (python-based)
  - new `docker compose` v2.x (plugin)

What we did:
- Confirmed Docker Engine installed and running:
  - `docker --version`
  - `sudo systemctl status docker --no-pager`
- Confirmed Compose v2 exists:
  - `docker compose version`

Outcome:
- We decided to standardize on **Compose v2** (`docker compose ...`) going forward to avoid random v1 bugs.

---

## 4) ThingsBoard image/version mismatch + internal DB confusion
Issue A:
- `docker-compose pull` failed:
  - `manifest for thingsboard/tb:4.2.1.1 not found`
Meaning: tag doesn’t exist on Docker Hub under that name.

What we did:
- Switched to a valid tag (or used `latest`) based on what actually exists.

Issue B:
- Ran TB using `thingsboard/tb-postgres:latest` (which includes an internal Postgres bootstrap inside the TB container).
- At the same time we also defined a separate `postgres:16` service.
- This created confusion: “Which DB is TB actually using?”

What we did:
- Confirmed behavior via logs:
  - internal Postgres lines existed (pg_ctl, creating DB, etc.)
- If we want external Postgres, the right image is typically `thingsboard/tb` (not tb-postgres).
- For now we kept the setup stable instead of constantly switching architecture mid-flight.

Outcome:
- ThingsBoard runs. But we learned: **don’t mix tb-postgres image with an external Postgres service** unless you’re intentionally doing something advanced.

---

## 5) YAML file error (then suddenly “valid”)
Issue:
- `docker-compose down -v` failed:
  - `yaml.scanner.ScannerError: mapping values are not allowed here in docker-compose.yml`

What we did:
- Validated YAML properly:
  - `docker-compose config >/dev/null && echo "OK: YAML valid" || echo "ERROR"`
- We corrected formatting and revalidated until it returned:
  - `OK: YAML valid`

Outcome:
- Compose file syntax confirmed valid.

---

## 6) Nginx vs ThingsBoard routing confusion
Issue:
- Could not access ThingsBoard at public IP initially.
- `curl -I http://localhost:8080` returned inconsistent results:
  - `connection reset by peer`
  - `empty reply`
  - eventually `200 OK`

What we did:
- Checked container port binding:
  - `docker ps`
  - `docker-compose ps`
- Confirmed host is listening on 8080:
  - `sudo ss -lntp | grep ':8080'`
- Verified Lightsail firewall rules:
  - ensured TCP 8080 was open (initially restricted incorrectly in one screenshot)
- Installed and enabled nginx:
  - `sudo systemctl enable --now nginx`
  - verified `nginx -t` and `systemctl status nginx`
- Added nginx reverse proxy so public port 80 forwards to TB 8080.
- Verified via:
  - `curl -I http://localhost | head -n 15`

Outcome:
- ThingsBoard accessible via public IP reliably (port 80 through nginx, and 8080 directly when allowed).

---

## 7) ThingsBoard startup RAM spikes and UI “loading forever”
Issue:
- ThingsBoard UI sometimes stayed loading or sluggish.
- RAM usage showed warnings (80%+), especially during startup.

What we did:
- Monitored container usage:
  - `docker stats --no-stream thingsboard`
  - `free -h`
- Observed CPU spikes during boot then settling.
- Swap helped avoid crash during spikes.
- Accepted that initial bootstrap can be heavy; stability improves after warm-up.

Outcome:
- TB runs stably on 2GB + swap (tight but workable for a capstone).

---

## 8) “Rule chain not visible” / missing fields (Timeout, request body)
Issue:
- In the TB UI, you couldn’t find Rule Chains or certain REST node fields like timeout/request body.
- You were effectively looking at a TB context/version/profile where these options were not available or hidden.

What we did:
- Realized we were using the wrong configuration / different profile / different environment (mismatch).
- After switching to the correct context, telemetry and features became visible.

Outcome:
- The problem wasn’t your logic; it was “wrong place / wrong UI capability / wrong setup.”

---

## 9) TB script node error (Event script vs Transformer mismatch)
Issue:
- You pasted a transformer-style JS function:
  - `function Transform(msg, metadata, msgType) { ... }`
- Error shown:
  - `Expected : but found , metadata, ^`
Meaning: node expected a different scripting format (node type mismatch).

What we did:
- Recognized TB has different JS node types with different expected syntax:
  - Transform node expects `return { msg, metadata, msgType }` within correct wrapper
  - Other nodes may not accept a function wrapper at all
- Put rule-chain work on pause temporarily to reduce thrash and move forward with ESP32 ingestion first.

Outcome:
- We identified the cause: wrong script format for the selected node type.

---

## 10) “Telemetry not showing” (but ESP32 connected)
Issue:
- ESP32 serial showed:
  - WiFi OK
  - MQTT OK
- But TB UI showed no telemetry and DB queries returned 0 rows.

What we did:
- Confirmed TB logs show openConnections but not necessarily telemetry inserts.
- Root cause: you were using a different rule chain / different TB context.
- After switching to the correct chain/device context, telemetry appeared in UI.

Outcome:
- Telemetry pipeline is working; it was an operator/config mismatch.

---

## 11) PlatformIO + ThingsBoard Arduino library build failure
Issue:
- Error:
  - `no matching function for call to 'ThingsBoardSized<>::ThingsBoardSized(WiFiClient&)'`
This is a library API mismatch / version mismatch.

What we did:
- Stopped fighting the TB Arduino library for now.
- Switched to a simpler, reliable approach:
  - `WiFiClient` + `PubSubClient`
  - publish JSON telemetry to:
    - topic `v1/devices/me/telemetry`
    - username = device token

Outcome:
- ESP32 reliably publishes telemetry with minimal code and minimal moving parts.

---

## What We Have Now (Current State)
- Lightsail Ubuntu 24.04 instance running:
  - ThingsBoard CE container (MQTT + HTTP)
  - Python inference service container (FastAPI, `/health` working)
  - Nginx reverse proxy in front of TB
- ESP32 publishes telemetry (hb, rssi, uptime_ms) successfully and appears in TB UI.
- Monitoring tools in place:
  - `docker ps`, `docker logs`, `docker stats`
  - `free -h`, `swapon --show`
  - `nginx -t`, `systemctl status nginx`
- **Inference validation system complete**:
  - `state_machine.py` — proposed FSM monitor with 5 states, hysteresis, suppression, and audit trail
  - `baseline_monitor.py` — control monitor (simple timeout counter)
  - `digital_twin.py` — 7 synthetic test scenarios with ground truth timelines
  - `metrics.py` — time-aligned evaluation (accuracy, FP, FN, detection latency)
  - `run_experiments.py` — experiment runner outputting `results/summary.csv`
  - `plots.py` — publication-quality plots to `results/plots/`
- **Experiment results generated**: proposed monitor outperforms baseline in suppression (100% vs 60%) and flapping (90% vs 70%) scenarios

---

## Hard Lessons (So We Don’t Repeat)
- Don’t mix `docker-compose` v1 and `docker compose` v2 commands randomly.
- Don’t mix `thingsboard/tb-postgres` (internal DB) with an external Postgres service unless you fully understand it.
- If TB UI “doesn’t show features,” assume wrong version/profile/context before assuming you’re doing it wrong.
- For capstone speed: MQTT + PubSubClient beats library gymnastics.
- Fixed random seed matters — without seed=42 in the digital twin, experiments produce different results each run and results become unreproducible.
- Time-aligned sampling (1-second intervals) is essential for fair accuracy metrics — event-level comparison would distort results when event spacing is uneven.

