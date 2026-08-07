"""Ticket submission, run inspection, and the audit trail (Deliverable 4 SS2.1)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.policy import PolicyName
from app.eval import goldset
from app.graph.runner import run_ticket
from app.persistence import reviews, runs, spans
from app.schemas.ticket import Ticket

router = APIRouter(prefix="/api", tags=["tickets"])


class SubmitRequest(BaseModel):
    ticket: Ticket
    policy: PolicyName = "optimized"
    bypass_cache: bool = False


class SubmitResponse(BaseModel):
    run_id: str
    decision: str | None
    decision_reason: str | None
    awaiting_review: bool
    resolution: str
    claims: int
    unsupported_claims: int | None
    citation_coverage: float | None


@router.post("/tickets", response_model=SubmitResponse)
def submit(request: SubmitRequest) -> SubmitResponse:
    result = run_ticket(
        request.ticket, request.policy, bypass_cache=request.bypass_cache
    )
    state = result.state
    produced = state.get("draft")
    grounding = state.get("grounding")

    return SubmitResponse(
        run_id=result.run_id,
        decision=state.get("decision"),
        decision_reason=state.get("decision_reason"),
        awaiting_review=result.interrupted,
        resolution=produced.render() if produced else "",
        claims=len(produced.claims) if produced else 0,
        unsupported_claims=grounding.unsupported_claim_count if grounding else None,
        citation_coverage=grounding.citation_coverage if grounding else None,
    )


@router.get("/tickets/inbox")
def inbox() -> list[dict]:
    """Open tickets. Served from the seed set until WireMock lands in M8."""
    return goldset.load_tickets()


@router.get("/runs")
def list_runs(batch_id: str | None = None, limit: int = 100) -> list[dict]:
    return runs.list_runs(batch_id=batch_id, limit=limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = runs.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"No run {run_id}")
    return run


@router.get("/runs/{run_id}/audit")
def audit(run_id: str) -> dict:
    """Complete governance record for one run (FR-2.4, FR-5.6).

    Answers the three questions a compliance reviewer actually asks: what did it
    say, what evidence did it have, and who approved it.
    """
    run = runs.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"No run {run_id}")
    return {
        "run": run,
        "spans": spans.for_run(run_id),
        "node_breakdown": spans.node_breakdown(run_id),
        "review": reviews.for_run(run_id),
    }
