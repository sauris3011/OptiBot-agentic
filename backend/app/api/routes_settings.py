"""Health and settings endpoints (Deliverable 4 SS2.5).

/api/health is the Milestone 0 exit criterion: it proves the model tiers
resolved and reports the active TLS posture.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config.model_registry import ModelTierUnresolved, get_registry
from app.config.settings import get_settings
from app.llm.tls import get_posture
from app.observability import mirror
from app.persistence import llm_cache
from app.persistence.db import query_one

router = APIRouter(prefix="/api", tags=["system"])


class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"
    models: dict[str, str]
    models_degraded: bool
    model_source: str
    tls: dict
    database: str
    token_budget: dict


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness plus resolved model tiers and TLS posture."""
    from app.llm.retry import get_budget

    try:
        registry = get_registry()
        models, degraded, source = registry.as_dict(), registry.is_degraded(), registry.source
        status = "degraded" if degraded else "ok"
    except ModelTierUnresolved as exc:
        models, degraded, source, status = {}, True, str(exc), "model_tiers_unresolved"

    try:
        row = query_one("SELECT version FROM schema_meta ORDER BY version DESC LIMIT 1")
        database = f"ok (schema v{row['version']})" if row else "ok (no schema row)"
    except Exception as exc:  # noqa: BLE001
        database, status = f"error: {exc}", "degraded"

    budget = get_budget()
    return HealthResponse(
        status=status,
        models=models,
        models_degraded=degraded,
        model_source=source,
        tls=get_posture().to_dict(),
        database=database,
        token_budget={"cap": budget.cap, "used": budget.used, "remaining": budget.remaining},
    )


class SettingsResponse(BaseModel):
    gateway_url: str
    api_key_masked: str
    backend_port: int
    frontend_port: int
    wiremock_port: int
    ssl_verify: bool
    tls: dict
    embedding_model: str
    telemetry_mirror: dict
    cache: dict


def _mask(secret: str) -> str:
    """Never return a key in full (NFR-2.1)."""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * 8}{secret[-4:]}"


@router.get("/settings", response_model=SettingsResponse)
def read_settings() -> SettingsResponse:
    settings = get_settings()
    return SettingsResponse(
        gateway_url=settings.litellm_gateway_url,
        api_key_masked=_mask(settings.litellm_api_key),
        backend_port=settings.backend_port,
        frontend_port=settings.frontend_port,
        wiremock_port=settings.wiremock_port,
        # Drives the persistent UI warning banner (FR-5.8).
        ssl_verify=get_posture().verifying,
        tls=get_posture().to_dict(),
        embedding_model=settings.embedding_model,
        telemetry_mirror=mirror.stats(),
        cache=llm_cache.stats(),
    )


@router.get("/telemetry/cache")
def cache_stats() -> dict:
    """Live cache hit/miss ratios for the settings modal (FR-5.2)."""
    return llm_cache.stats()
