"""Terminal nodes: auto_resolve, human_review, quarantine. No LLM.

human_review is where the graph genuinely pauses. builder.py compiles with
interrupt_before=["human_review"], so execution stops at a SQLite checkpoint and
resumes only when a decision is recorded (FR-1.8).
"""

from __future__ import annotations

from app.graph.state import TicketState
from app.observability.logging import get_logger

log = get_logger(__name__)


def auto_resolve(state: TicketState) -> dict:
    produced = state.get("draft")
    log.info(
        "auto_resolved",
        claims=len(produced.claims) if produced else 0,
        coverage=state["grounding"].citation_coverage if state.get("grounding") else 0.0,
    )
    return {}


def human_review(state: TicketState) -> dict:
    """Executed only AFTER a reviewer decision resumes the graph.

    The interrupt fires before this node, so reaching its body means the pause
    is over.
    """
    log.info("human_review_resumed", reason=state.get("decision_reason"))
    return {}


def quarantine(state: TicketState) -> dict:
    log.warning("quarantined", reason=state.get("decision_reason"))
    return {}
