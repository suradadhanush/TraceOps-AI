"""
Execution Audit System v3 — FastAPI Application
"""
import time
import uuid

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import events, metrics, proxy, reports, tasks
from app.api.scheduler import router as scheduler_router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.logger import configure_logging, get_logger
from app.services.config_store import apply_db_config_to_singleton

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Configure JSON logging
    configure_logging(settings.LOG_LEVEL)

    # 2. Create DB tables
    async with engine.begin() as conn:
        from app.models.models import Task, Event, Score, Report, AIProxyLog  # noqa: F401
        from app.services.webhook_durability import WebhookEvent               # noqa: F401
        from app.services.config_store import ConfigStore                       # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

    # 3. Load persisted config from DB (replaces ephemeral file)
    applied = await apply_db_config_to_singleton()
    log.info("startup complete",
             extra={"eas_config_from_db": applied, "eas_env": settings.APP_ENV})

    yield

    await engine.dispose()
    log.info("shutdown complete")


app = FastAPI(
    title="Execution Audit System",
    description="Production-grade developer execution tracker. AI + Git + Deploy → scored daily audit.",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.monotonic()
    log.info("request.start", extra={
        "eas_request_id": request_id,
        "eas_method": request.method,
        "eas_path": request.url.path,
    })
    try:
        response: Response = await call_next(request)
        elapsed = int((time.monotonic() - start) * 1000)
        log.info("request.end", extra={
            "eas_request_id": request_id,
            "eas_status": response.status_code,
            "eas_latency_ms": elapsed,
        })
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        log.error("request.error", extra={
            "eas_request_id": request_id,
            "eas_error": str(exc)[:200],
            "eas_latency_ms": elapsed,
        })
        raise


# Routers
app.include_router(tasks.router)
app.include_router(events.router)
app.include_router(reports.router)
app.include_router(proxy.router)
app.include_router(metrics.router)
app.include_router(scheduler_router)


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "service": "eas", "version": "3.0.0"}


@app.get("/health/deep", tags=["System"])
async def health_deep():
    """Full deep health: DB + Redis + Celery worker. Used by UptimeRobot."""
    from app.api.scheduler import check_db_alive, check_redis_alive, check_worker_alive
    db_s     = await check_db_alive()
    redis_s  = await check_redis_alive()
    worker_s = await check_worker_alive()
    overall  = db_s["alive"] and redis_s["alive"]
    return {
        "status": "ok" if overall else "degraded",
        "components": {"database": db_s, "redis": redis_s, "celery_worker": worker_s},
    }


@app.get("/", tags=["System"])
async def root():
    return {"service": "Execution Audit System v3", "docs": "/docs", "health": "/health"}
