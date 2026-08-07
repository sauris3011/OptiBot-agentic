"""Human review queue and decisions (Deliverable 4 SS2.2, FR-5.5, FR-2.6)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.graph.runner import resume_run
from app.persistence import reviews, runs, spans

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/queue")
def queue() -> list[dict]:
    """Pending escalations with the evidence a reviewer needs (FR-5.5)."""
    out = []
    for run in runs.pending_review():
        run_spans = spans.for_run(run["run_id"])
        chunk_ids: list[str] = []
        for span in run_spans:
            for chunk_id in span.get("chunk_ids") or []:
                if chunk_id not in chunk_ids:
                    chunk_ids.append(chunk_id)
        out.append(
            {
                "run_id": run["run_id"],
                "ticket_id": run["ticket_id"],
                "policy": run["policy"],
                "escalation_reason": run["decision_reason"],
                "unsupported_claims": run["unsupported_claims"],
                "citation_coverage": run["citation_coverage"],
                "evidence_chunk_ids": chunk_ids,
                "started_at": run["started_at"],
            }
        )
    return out


class DecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reviewer: str = Field(min_length=1)
    reason: str | None = None


@router.post("/{run_id}/decision")
def decide(run_id: str, request: DecisionRequest) -> dict:
    """Record a decision and resume the paused graph (FR-1.8).

    The decision is written BEFORE resuming, so a crash during resume leaves the
    audit trail complete rather than losing the reviewer's action.
    """
    run = runs.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"No run {run_id}")
    if run["status"] != "awaiting_review":
        raise HTTPException(
            409, f"Run {run_id} is {run['status']}, not awaiting review"
        )

    review_id = reviews.record(
        run_id=run_id,
        reviewer=request.reviewer,
        decision=request.decision,
        reason=request.reason,
        escalation_cause=run["decision_reason"] or "unspecified",
    )

    result = resume_run(run_id, approved=request.decision == "approve")
    return {
        "review_id": review_id,
        "run_id": run_id,
        "decision": request.decision,
        "status": "completed" if request.decision == "approve" else "rejected",
        "resumed": not result.interrupted,
    }


@router.get("/history")
def history(limit: int = 100) -> list[dict]:
    return reviews.history(limit)


@router.get("/stats")
def stats() -> dict:
    return reviews.stats()
