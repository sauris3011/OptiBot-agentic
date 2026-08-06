"""Structured JSON logging (NFR-3.3, Deliverable 9 SS3).

structlog with bound context, so run_id / policy / node appear on every line
within a run without being threaded through call signatures.

JSON is the default so logs are machine-parseable without a second code path;
LOG_FORMAT=console switches to human-readable output for local development.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config.settings import get_settings
from app.observability.redaction import structlog_processor

_configured = False


def configure_logging() -> None:
    """Install the logging pipeline. Idempotent; called once from lifespan."""
    global _configured
    if _configured:
        return

    settings = get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Redaction runs last, immediately before rendering, so it sees the
        # fully-merged event including anything bound by contextvars.
        structlog_processor,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Uvicorn's access log duplicates information already captured in spans and
    # adds noise to a JSON stream that is meant to be read by machines.
    logging.getLogger("uvicorn.access").disabled = True

    _configured = True


def get_logger(name: str = "optibot") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_run_context(*, run_id: str, policy: str, **extra: Any) -> None:
    """Bind run-scoped context for the current execution context.

    Everything logged downstream carries run_id and policy automatically, which
    is what makes a single identifier correlate spans, logs, API responses, and
    the audit trail (Deliverable 9 SS2).
    """
    structlog.contextvars.bind_contextvars(run_id=run_id, policy=policy, **extra)


def clear_run_context() -> None:
    structlog.contextvars.clear_contextvars()
