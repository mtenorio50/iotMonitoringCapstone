"""
Inference Service — FastAPI Entry Point
=========================================
Endpoints:
  GET  /health  — service health + current monitor state
  POST /infer   — called by ThingsBoard rule chain on each heartbeat
  GET  /experiments/scenarios — list available test scenarios
  GET  /experiments/summary   — run all scenarios, return comparison metrics
  GET  /experiments/timeline  — run one scenario, return tick-by-tick states
"""

import time
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.heartbeat_handler import HeartbeatHandler
from app.experiment_api import router as experiment_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Inference Service",
    description="Inference-first IoT device state monitoring",
    version="0.3.0",
)

# Allow TB dashboard HTML widgets to call our API
# WHY CORS? TB HTML widgets run in the browser. The browser blocks
# requests to a different origin (port 8000) unless CORS is enabled.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register experiment endpoints
app.include_router(experiment_router)

# Global handler instance
handler: HeartbeatHandler = None


@app.get("/health")
def health():
    """Health check with current monitor status."""
    status = {
        "status": "ok",
        "ts": time.time(),
        "service": "inference",
    }

    if handler:
        status["monitor"] = handler.get_status()

    return status


@app.post("/infer")
async def infer(request: Request):
    """
    Receives heartbeat telemetry forwarded by ThingsBoard rule chain.

    ThingsBoard sends the raw telemetry payload as the POST body:
      {"uptime_ms": 12345, "rssi_dbm": -58, "ldr_raw": 1024, "ldr_v": 1.234}

    We process it through the state machine and return the current state.
    The handler also pushes inferred state back to TB via HTTP.
    """
    if not handler:
        return {"error": "handler not initialized"}, 503

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    logger.info(f"/infer called with: {payload}")

    result = handler.receive_heartbeat(payload)

    return result


@app.on_event("startup")
async def on_startup():
    """Start the heartbeat handler when the service boots."""
    global handler
    try:
        handler = HeartbeatHandler()
        handler.start()
        logger.info("HeartbeatHandler started")
    except Exception as e:
        logger.error(f"Failed to start HeartbeatHandler: {e}")


@app.on_event("shutdown")
async def on_shutdown():
    """Stop the heartbeat handler cleanly."""
    global handler
    if handler:
        handler.stop()
        logger.info("HeartbeatHandler stopped")