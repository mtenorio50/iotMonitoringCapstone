"""
Inference Service — FastAPI Entry Point
"""

import time
import logging
from fastapi import FastAPI
from app.mqtt_bridge import MQTTBridge

# Configure logging so you can see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Inference Service",
    description="Inference-first IoT device state monitoring",
    version="0.1.0",
)

# Global bridge instance — created on startup, stopped on shutdown
bridge: MQTTBridge = None


@app.get("/health")
def health():
    """Health check with current monitor status."""
    status = {
        "status": "ok",
        "ts": time.time(),
        "service": "inference",
    }

    if bridge:
        status["monitor"] = bridge.get_status()

    return status


@app.on_event("startup")
async def on_startup():
    """Start the MQTT bridge when the service boots."""
    global bridge
    try:
        bridge = MQTTBridge()
        bridge.start()
        logging.getLogger(__name__).info("MQTT bridge started")
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to start MQTT bridge: {e}")
        # Service still runs — /health works, MQTT can be retried


@app.on_event("shutdown")
async def on_shutdown():
    """Stop the MQTT bridge cleanly."""
    global bridge
    if bridge:
        bridge.stop()
        logging.getLogger(__name__).info("MQTT bridge stopped")
