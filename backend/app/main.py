"""FastAPI application assembly and lifespan.

Assembly only -- no business logic. Startup resolves the two environment risks
that can invalidate everything downstream (TLS posture and model tiers) before
serving a single request. Shutdown flushes telemetry and closes the embedded
stores cleanly (FR-7.5).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_rag, routes_settings
from app.config.model_registry import ModelTierUnresolved, get_registry
from app.config.settings import get_settings
from app.llm.tls import configure_tls
from app.observability.logging import configure_logging, get_logger
from app.observability.tracer import flush as flush_spans
from app.persistence.db import close_db, init_db
from app.rag import store as rag_store

log = get_logger("optibot.main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    settings = get_settings()

    log.info("startup_begin", backend_port=settings.backend_port, data_dir=str(settings.data_dir))

    # 1. TLS before anything makes an outbound call.
    posture = configure_tls()
    log.info("tls_configured", mode=posture.mode, verifying=posture.verifying)
    if not posture.verifying:
        log.warning("tls_verification_disabled", detail=posture.warning)

    # 2. Embedded stores.
    init_db()
    settings.lancedb_path.mkdir(parents=True, exist_ok=True)
    log.info("storage_ready", sqlite=str(settings.sqlite_path))

    # 3. Model tiers. A failure here is reported but not fatal -- the process
    #    stays up so /api/health can explain what went wrong, which is more
    #    useful than a container that exits before anyone can ask it.
    try:
        registry = get_registry()
        log.info("models_resolved", source=registry.source, **registry.as_dict())
        if registry.is_degraded():
            log.warning("model_tiers_degraded", detail="one or more tiers fell back")
    except ModelTierUnresolved as exc:
        log.error("model_tiers_unresolved", error=str(exc))

    log.info("startup_complete")
    yield

    log.info("shutdown_begin")
    flush_spans()
    # LanceDB writer released before SQLite closes; an abrupt termination
    # mid-write is the realistic corruption path (FR-7.5).
    rag_store.close()
    close_db()
    log.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="OptiBot",
        description="IT service desk triage that measures its own improvement",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Loopback-only frontend; nothing is exposed beyond this machine.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://127.0.0.1:{settings.frontend_port}",
            f"http://localhost:{settings.frontend_port}",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_settings.router)
    app.include_router(routes_rag.router)
    return app


app = create_app()
