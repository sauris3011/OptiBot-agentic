"""Evaluation endpoints (Deliverable 4 SS2.3)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.eval import goldset, harness
from app.eval.metrics import build_comparison
from app.graph.runner import run_ticket
from app.persistence.db import query
from app.rag import rerank, store
from app.schemas.ticket import Ticket

router = APIRouter(prefix="/api/eval", tags=["eval"])


class BatchRequest(BaseModel):
    limit: int | None = None


@router.post("/batch")
def run_batch(request: BatchRequest) -> dict:
    """Run the seeded set through both arms, cache bypassed (FR-3.1)."""
    result = harness.run_batch(limit=request.limit)
    return {
        "batch_id": result.batch_id,
        "sample_size": result.sample_size,
        "failed": [
            {"ticket_id": o.ticket_id, "errors": o.errors} for o in result.outcomes if o.errors
        ],
        "comparison": result.comparison,
    }


@router.get("/comparison")
def comparison(batch_id: str | None = None) -> dict:
    """The headline endpoint (FR-5.4). Reads pre-computed rows; no LLM calls."""
    return build_comparison(batch_id)


@router.get("/batches")
def batches() -> list[dict]:
    return [dict(r) for r in query("SELECT * FROM batches ORDER BY started_at DESC LIMIT 50")]


class LiveRequest(BaseModel):
    ticket: Ticket | None = None
    ticket_id: str | None = None


@router.post("/live")
def live(request: LiveRequest) -> dict:
    """One ticket through both arms live, cache bypassed (FR-3.2)."""
    ticket = request.ticket
    if ticket is None:
        if not request.ticket_id:
            raise HTTPException(400, "Provide either `ticket` or `ticket_id`")
        match = next(
            (t for t in goldset.load_tickets() if t["ticket_id"] == request.ticket_id), None
        )
        if match is None:
            raise HTTPException(404, f"No seed ticket {request.ticket_id}")
        ticket = Ticket(**match)
    return harness.run_live_comparison(ticket)


@router.get("/goldset")
def goldset_scores(top_k: int = 10) -> dict:
    """Retrieval precision@k and citation coverage per arm (FR-3.4).

    Retrieval-only, so this costs no tokens and works with the gateway down.
    """
    from app.config.policy import get_policy

    judgements = goldset.load_judgements()
    out: dict = {"tickets": len(judgements), "arms": {}}

    for name in ("baseline", "optimized"):
        policy = get_policy(name)  # type: ignore[arg-type]
        scores, context_tokens = [], []
        for ticket in goldset.load_tickets():
            judgement = judgements.get(ticket["ticket_id"])
            if judgement is None:
                continue
            query_text = goldset.query_text(ticket)
            hits = store.search(
                query_text, strategy=policy.chunking, top_k=policy.retrieval_top_k
            )
            if policy.rerank_enabled and policy.rerank_top_k:
                hits = rerank.rerank(query_text, hits, top_k=policy.rerank_top_k)
            scores.append(goldset.score_retrieval(hits, judgement))
            context_tokens.append(sum(h.token_count for h in hits))

        aggregate = goldset.aggregate(scores)
        aggregate["context_tokens_per_query"] = (
            round(sum(context_tokens) / len(context_tokens), 1) if context_tokens else 0.0
        )
        aggregate["strategy"] = policy.chunking
        out["arms"][name] = aggregate

    return out
