from contextlib import asynccontextmanager
import os
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator

from database import Base, engine, AsyncSessionLocal, get_db
from tracing import setup_tracing

from shared.orchestrator import (
    ChaosConfig as OrchestratorChaosConfig,
    OrchestratorConfig,
    build_router,
    configure,
    get_orchestrator_chaos,
    set_orchestrator_chaos,
    start_leader_loop,
    stop_leader_loop,
)


class HealthResponse(BaseModel):
    status: str
    service: str


class ChaosConfig(BaseModel):
    FAILURE_RATE: Optional[float] = None
    LATENCY_MS: Optional[int] = None
    TIMEOUT_RATE: Optional[float] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    configure(
        OrchestratorConfig(
            service_name="order-service",
            priority=int(os.getenv("ORCHESTRATOR_PRIORITY", "100")),
            get_db=get_db,
            session_factory=AsyncSessionLocal,
        )
    )
    app.include_router(build_router())
    await start_leader_loop()
    yield
    await stop_leader_loop()


app = FastAPI(title="order-service", lifespan=lifespan)
setup_tracing(app, "order-service")
Instrumentator().instrument(app).expose(app)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="order-service")


# Backward-compatible chaos config: this service's chaos IS the shared
# orchestrator's chaos (order-service is the classic orchestrator), so /chaos/config
# keeps working exactly as before after the Phase 4 module extraction.
@app.get("/chaos/config")
def get_chaos_config():
    return get_orchestrator_chaos()


@app.post("/chaos/config")
def update_chaos_config(config: ChaosConfig):
    return set_orchestrator_chaos(
        OrchestratorChaosConfig(**config.model_dump(exclude_none=True))
    )