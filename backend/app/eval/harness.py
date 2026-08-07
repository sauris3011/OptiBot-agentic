"""Dual-arm evaluation harness (FR-3.1, FR-3.2, FR-3.6).

Structurally independent of the pipeline: this module imports graph/, and
graph/ never imports this. Measurement code must not entangle with the code
being measured -- if the pipeline could see the harness, a reviewer could
reasonably ask whether it behaves differently when observed.

Cache is bypassed on BOTH arms for every benchmark run. A warmed cache would let
the optimized arm replay the baseline's work and report a delta that is an
artifact of run order rather than of optimization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from app.eval import goldset
from app.eval.metrics import build_comparison
from app.graph.runner import run_ticket
from app.observability.logging import get_logger
from app.persistence.db import execute
from app.schemas.ticket import Ticket
from app.utils.ids import new_batch_id
from app.utils.timing import utc_now_iso

log = get_logger(__name__)

ARMS = ("baseline", "optimized")


@dataclass
class TicketOutcome:
    ticket_id: str
    run_ids: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class BatchResult:
    batch_id: str
    sample_size: int
    outcomes: list[TicketOutcome]
    comparison: dict


def load_seed_tickets(limit: int | None = None) -> list[Ticket]:
    raw = goldset.load_tickets()
    if limit:
        raw = raw[:limit]
    return [Ticket(**t) for t in raw]


def _open_batch(batch_id: str, sample_size: int) -> None:
    execute(
        "INSERT OR REPLACE INTO batches "
        "(batch_id, sample_size, cache_bypassed, status, started_at) VALUES (?,?,?,?,?)",
        (batch_id, sample_size, 1, "running", utc_now_iso()),
    )


def _close_batch(batch_id: str, status: str) -> None:
    execute(
        "UPDATE batches SET status = ?, completed_at = ? WHERE batch_id = ?",
        (status, utc_now_iso(), batch_id),
    )


def run_batch(
    tickets: Iterable[Ticket] | None = None,
    *,
    limit: int | None = None,
    on_progress: Callable[[str, str, int, int], None] | None = None,
) -> BatchResult:
    """Execute every ticket through both arms with the cache bypassed."""
    items = list(tickets) if tickets is not None else load_seed_tickets(limit)
    batch_id = new_batch_id()
    _open_batch(batch_id, len(items))
    log.info("batch_started", batch_id=batch_id, tickets=len(items))

    outcomes: list[TicketOutcome] = []
    total = len(items) * len(ARMS)
    done = 0

    for ticket in items:
        outcome = TicketOutcome(ticket_id=ticket.ticket_id)
        for arm in ARMS:
            try:
                result = run_ticket(
                    ticket,
                    arm,  # type: ignore[arg-type]
                    bypass_cache=True,
                    batch_id=batch_id,
                    # Pausing 50 tickets for human input would make unattended
                    # evaluation impossible, and resuming them would not change
                    # a single metric -- route() has already recorded the
                    # decision, which is what is being measured.
                    allow_interrupt=False,
                )
                outcome.run_ids[arm] = result.run_id
            except Exception as exc:  # noqa: BLE001 - recorded, batch continues
                # One failed ticket must not void the whole batch. The failure
                # is recorded and reported in the summary.
                outcome.errors[arm] = f"{type(exc).__name__}: {exc}"[:300]
                log.error("batch_ticket_failed", ticket=ticket.ticket_id, arm=arm,
                          error=str(exc)[:200])
            done += 1
            if on_progress:
                on_progress(ticket.ticket_id, arm, done, total)
        outcomes.append(outcome)

    failed = sum(1 for o in outcomes if o.errors)
    _close_batch(batch_id, "completed" if failed == 0 else "completed_with_errors")
    log.info("batch_complete", batch_id=batch_id, failed_tickets=failed)

    return BatchResult(
        batch_id=batch_id,
        sample_size=len(items),
        outcomes=outcomes,
        comparison=build_comparison(batch_id),
    )


def run_live_comparison(ticket: Ticket) -> dict:
    """One ticket through both arms, cache bypassed (FR-3.2).

    Proves the batch numbers were not fabricated: a judge watches the same delta
    appear live.
    """
    out: dict = {"ticket_id": ticket.ticket_id, "cache_bypassed": True, "arms": {}}
    for arm in ARMS:
        result = run_ticket(
            ticket, arm, bypass_cache=True, allow_interrupt=False  # type: ignore[arg-type]
        )
        state = result.state
        produced = state.get("draft")
        grounding = state.get("grounding")
        out["arms"][arm] = {
            "run_id": result.run_id,
            "decision": state.get("decision"),
            "decision_reason": state.get("decision_reason"),
            "claims": len(produced.claims) if produced else 0,
            "unsupported_claims": grounding.unsupported_claim_count if grounding else None,
            "citation_coverage": grounding.citation_coverage if grounding else None,
            "resolution": produced.render() if produced else "",
        }
    return out
