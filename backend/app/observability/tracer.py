"""Span emission (NFR-3.1, Deliverable 9 SS2).

Spans are written synchronously to SQLite before the LLM call returns. Not
batched, not async, not fire-and-forget.

Reason: a crash mid-batch must leave every completed run measurable. Async
batching risks losing the tail of a run, and the tail is where failures cluster
-- exactly the data worth keeping. At ~1ms per write against ~500ms per LLM
call, the cost is invisible.

SQLite is authoritative. The optional SaaS mirror is best-effort and never on
the critical path.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field

from app.observability.logging import get_logger
from app.persistence.db import execute
from app.utils.ids import new_span_id
from app.utils.timing import utc_now_iso

log = get_logger(__name__)


@dataclass
class Span:
    """One LLM call or instrumented node execution."""

    run_id: str
    node: str
    kind: str  # llm | retrieval | rerank | deterministic
    latency_ms: int
    span_id: str = field(default_factory=new_span_id)
    parent_span_id: str | None = None
    tier: str | None = None
    resolved_model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    cost_estimated: bool = False
    cache_status: str | None = None  # hit_exact | hit_semantic | miss | bypassed
    retry_count: int = 0
    schema_valid: bool | None = None
    repair_attempted: bool = False
    guardrail_verdict: str | None = None
    chunk_ids: list[str] | None = None
    prompt_hash: str | None = None
    error_code: str | None = None


_INSERT = """
INSERT INTO spans (
  span_id, run_id, parent_span_id, node, kind, tier, resolved_model,
  tokens_in, tokens_out, cost_usd, cost_estimated, latency_ms, cache_status,
  retry_count, schema_valid, repair_attempted, guardrail_verdict, chunk_ids,
  prompt_hash, error_code, created_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


class LiveCounters:
    """Process-lifetime counters backing the header monitor (FR-5.1).

    Held in memory for cheap reads; reconciled against SQLite on reconnect so a
    page refresh does not zero them.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.cost_estimated = False
        self.cache_hits = 0
        self.cache_misses = 0

    def call_started(self) -> None:
        with self._lock:
            self.active_calls += 1

    def call_finished(self, span: Span) -> None:
        with self._lock:
            self.active_calls = max(0, self.active_calls - 1)
            self.tokens_in += span.tokens_in or 0
            self.tokens_out += span.tokens_out or 0
            self.cost_usd += span.cost_usd or 0.0
            self.cost_estimated = self.cost_estimated or span.cost_estimated
            if span.cache_status in ("hit_exact", "hit_semantic"):
                self.cache_hits += 1
            elif span.cache_status == "miss":
                self.cache_misses += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "active_calls": self.active_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "cost_usd": round(self.cost_usd, 6),
                "cost_estimated": self.cost_estimated,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
            }


counters = LiveCounters()


def emit(span: Span) -> None:
    """Persist a span and update live counters."""
    try:
        execute(
            _INSERT,
            (
                span.span_id,
                span.run_id,
                span.parent_span_id,
                span.node,
                span.kind,
                span.tier,
                span.resolved_model,
                span.tokens_in,
                span.tokens_out,
                span.cost_usd,
                int(span.cost_estimated),
                span.latency_ms,
                span.cache_status,
                span.retry_count,
                None if span.schema_valid is None else int(span.schema_valid),
                int(span.repair_attempted),
                span.guardrail_verdict,
                json.dumps(span.chunk_ids) if span.chunk_ids else None,
                span.prompt_hash,
                span.error_code,
                utc_now_iso(),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        # A failed span write must not fail the run it was measuring. It is
        # logged loudly because a missing span means a gap in the audit trail.
        log.error("span_write_failed", span_id=span.span_id, error=str(exc))

    counters.call_finished(span)
    log.info("span", **{k: v for k, v in asdict(span).items() if v is not None})

    _mirror(span)


def _mirror(span: Span) -> None:
    """Best-effort forward to the optional SaaS mirror (NFR-3.2)."""
    from app.config.settings import get_settings

    if not get_settings().telemetry_mirror_enabled:
        return
    try:
        from app.observability import mirror

        mirror.forward(span)
    except Exception:  # noqa: BLE001
        # Behind an intercepting proxy an outbound SaaS call can hang or fail.
        # SQLite already holds the authoritative record, so this is non-fatal
        # by design.
        pass


def flush() -> None:
    """Shutdown hook (FR-7.5).

    Spans are written synchronously, so nothing is buffered here. The mirror may
    have in-flight work worth draining.
    """
    from app.config.settings import get_settings

    if not get_settings().telemetry_mirror_enabled:
        return
    try:
        from app.observability import mirror

        mirror.flush()
    except Exception:  # noqa: BLE001
        pass
