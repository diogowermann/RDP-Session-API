from fastapi import FastAPI

from app.api.agent import router as agent_router
from app.api.health import router as health_router

app = FastAPI(
    title="RDP Session API",
    version="0.1.0",
    description="Receives RDP session events and state snapshots from authenticated Windows agents.",
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
