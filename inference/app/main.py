"""
Inference Service — FastAPI Entry Point
=========================================
Endpoints:
  GET  /health  — service health + current monitor state
  POST /infer   — called by ThingsBoard rule chain on each heartbeat
"""

import time
import logging
from fastapi import FastAPI, Request

from app.heartbeat_handler import HeartbeatHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Inference Service",
    description="Inference-first IoT device state monitoring",
    version="0.2.0",
)

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
