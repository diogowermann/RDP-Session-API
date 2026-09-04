from fastapi import FastAPI

from app.api.agent import router as agent_router
from app.api.alerts import router as alerts_router
from app.api.health import router as health_router
from app.api.servers import router as servers_router
from app.api.v2 import router as v2_router

app = FastAPI(
    title="Remote Session API",
    version="0.5.0",
    description="Receives and queries normalized remote-session telemetry while preserving the legacy RDP v1 contract.",
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(servers_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")
app.include_router(v2_router, prefix="/api/v2")
