import time
from fastapi import FastAPI

app = FastAPI(
    title="Inference Service",
    description="Inference-first IoT device state monitoring",
    version="1.0"
)

# Health check endpoint
@app.get("/health")
def health():
    return{
        "status": "ok",
        "ts": time.time(),
        "service": "inference"
    }

@app.on_event ("startup")
async def on_startup():
    pass
@app.on_event("shutdown")
async def on_shutdown():
    pass
    

