"""
TraceOps AI — FastAPI Application
"""
import time
import uuid

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import os

from app.api import events, metrics, proxy, reports, tasks
from app.api.scheduler import router as scheduler_router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.logger import configure_logging, get_logger
from app.services.config_store import apply_db_config_to_singleton

log = get_logger("main")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.LOG_LEVEL)

    async with engine.begin() as conn:
        from app.models.models import Task, Event, Score, Report, AIProxyLog  # noqa
        from app.services.webhook_durability import WebhookEvent               # noqa
        from app.services.config_store import ConfigStore                       # noqa
        await conn.run_sync(Base.metadata.create_all)

    applied = await apply_db_config_to_singleton()
    log.info("startup complete", extra={
        "traceops_config_from_db": applied,
        "traceops_env": settings.APP_ENV,
    })
    yield
    await engine.dispose()
    log.info("shutdown complete")


app = FastAPI(
    title="TraceOps AI",
    description="AI-powered execution audit. Git + AI proxy + Deploy → daily scored report.",
    version="1.0.0",
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
        "traceops_request_id": request_id,
        "traceops_method": request.method,
        "traceops_path": request.url.path,
    })
    try:
        response: Response = await call_next(request)
        elapsed = int((time.monotonic() - start) * 1000)
        log.info("request.end", extra={
            "traceops_request_id": request_id,
            "traceops_status": response.status_code,
            "traceops_latency_ms": elapsed,
        })
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        log.error("request.error", extra={
            "traceops_request_id": request_id,
            "traceops_error": str(exc)[:200],
            "traceops_latency_ms": elapsed,
        })
        raise


# ── API Routers ───────────────────────────────────────────────────────────────
app.include_router(tasks.router)
app.include_router(events.router)
app.include_router(reports.router)
app.include_router(proxy.router)
app.include_router(metrics.router)
app.include_router(scheduler_router)


# ── Static files ──────────────────────────────────────────────────────────────
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── System endpoints ──────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "service": "traceops", "version": "1.0.0"}


@app.get("/health/deep", tags=["System"])
async def health_deep():
    from app.api.scheduler import check_db_alive, check_redis_alive, check_worker_alive
    db_s     = await check_db_alive()
    redis_s  = await check_redis_alive()
    worker_s = await check_worker_alive()
    overall  = db_s["alive"] and redis_s["alive"]
    return {
        "status": "ok" if overall else "degraded",
        "components": {"database": db_s, "redis": redis_s, "celery_worker": worker_s},
    }


# ── Frontend routes ───────────────────────────────────────────────────────────
@app.get("/app/{page:path}", include_in_schema=False)
async def app_shell(page: str):
    shell = os.path.join(STATIC_DIR, "app.html")
    if os.path.exists(shell):
        return FileResponse(shell)
    return HTMLResponse("<h1>TraceOps AI</h1><p><a href='/docs'>API Docs</a></p>")


@app.get("/", include_in_schema=False)
async def landing():
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"service": "TraceOps AI", "docs": "/docs", "health": "/health", "app": "/app/dashboard"}
