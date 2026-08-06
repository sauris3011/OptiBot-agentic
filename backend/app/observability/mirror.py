"""Optional SaaS telemetry mirror (NFR-3.2, Deliverable 9 SS5).

Off by default. SQLite holds the authoritative record; this is a convenience
view, never a dependency.

The failure mode this guards against is specific: behind an intercepting proxy
an outbound SaaS call can *hang* rather than fail fast. If telemetry sat on the
critical path, every LLM call would inherit that hang and the demo would stall
for reasons unrelated to the system being demonstrated.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import TYPE_CHECKING

from app.config.settings import get_settings
from app.observability.logging import get_logger
from app.observability.redaction import redact

if TYPE_CHECKING:
    from app.observability.tracer import Span

log = get_logger(__name__)

MIRROR_TIMEOUT_SECONDS = 2.0

_executor: ThreadPoolExecutor | None = None
_client = None
_lock = threading.Lock()

#: Surfaced in the settings modal. Degraded silently is still degraded, so a
#: failing mirror stays visible even though it is non-fatal.
failure_count = 0


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mirror")
        return _executor


def _get_client():
    """Lazily construct the provider client; None disables mirroring."""
    global _client
    if _client is not None:
        return _client

    settings = get_settings()
    try:
        if settings.telemetry_mirror_provider == "langfuse":
            from langfuse import Langfuse

            _client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
                timeout=MIRROR_TIMEOUT_SECONDS,
            )
        else:
            import agentops

            agentops.init(api_key=settings.langfuse_secret_key, auto_start_session=False)
            _client = agentops
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetry_mirror_unavailable", error=str(exc)[:200])
        _client = None
    return _client


def _send(span: "Span") -> None:
    global failure_count
    client = _get_client()
    if client is None:
        return
    try:
        payload = redact(asdict(span))
        if get_settings().telemetry_mirror_provider == "langfuse":
            client.generation(
                name=span.node,
                model=span.resolved_model,
                trace_id=span.run_id,
                metadata=payload,
            )
        else:
            client.record(payload)
    except Exception as exc:  # noqa: BLE001
        failure_count += 1
        log.debug("telemetry_mirror_failed", error=str(exc)[:200])


def forward(span: "Span") -> None:
    """Queue a span for mirroring. Returns immediately."""
    _get_executor().submit(_send, span)


def flush() -> None:
    """Drain in-flight mirror work at shutdown (FR-7.5)."""
    global _executor
    with _lock:
        if _executor is None:
            return
        _executor.shutdown(wait=True, cancel_futures=False)
        _executor = None
    try:
        client = _client
        if client is not None and hasattr(client, "flush"):
            client.flush()
    except Exception:  # noqa: BLE001
        pass


def stats() -> dict:
    return {
        "enabled": get_settings().telemetry_mirror_enabled,
        "provider": get_settings().telemetry_mirror_provider,
        "failure_count": failure_count,
    }
