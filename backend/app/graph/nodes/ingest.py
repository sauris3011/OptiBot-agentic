"""ingest node -- normalise input and open the run. No LLM."""

from __future__ import annotations

from app.graph.state import TicketState
from app.observability.logging import bind_run_context, get_logger

log = get_logger(__name__)


def ingest(state: TicketState) -> dict:
    ticket = state["ticket"]
    policy = state["policy"]

    bind_run_context(
        run_id=state["run_id"],
        policy=policy.name,
        ticket_id=ticket.ticket_id,
    )
    log.info("run_started", subject=ticket.subject[:80], cache_enabled=policy.cache_enabled)

    return {
        "retrieved": [],
        "errors": [],
        "degraded": False,
    }
