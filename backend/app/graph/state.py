"""Typed graph state (Deliverable 6 SS2).

State is append-only per node. No node mutates a prior node's output, which is
what keeps the audit trail truthful and makes any run reconstructible from its
spans alone.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from app.config.policy import Policy
from app.rag.store import SearchHit
from app.schemas.classify import Classification
from app.schemas.draft import Draft
from app.schemas.ground_check import GroundingReport
from app.schemas.guardrail import GuardrailVerdict
from app.schemas.ticket import Ticket

Decision = Literal["auto_resolve", "human_review", "quarantine"]


class TicketState(TypedDict, total=False):
    """State carried through the graph."""

    # Identity
    run_id: str
    policy: Policy  # frozen; drives every node's behaviour
    corpus_version: str
    prompt_version: str

    # Input
    ticket: Ticket

    # Node outputs, each Pydantic-validated before entry
    classification: Classification | None
    guardrail_pre: GuardrailVerdict | None
    retrieved: list[SearchHit]
    reranked: list[SearchHit] | None
    draft: Draft | None
    grounding: GroundingReport | None
    guardrail_post: GuardrailVerdict | None

    # Routing
    decision: Decision | None
    decision_reason: str | None

    # Failure tracking. A node that falls back to a deterministic default sets
    # this, and route() forces human review regardless of other signals.
    degraded: bool
    errors: list[str]


def context_chunks(state: TicketState) -> list[SearchHit]:
    """The chunks the draft node actually sees.

    Reranked output when present, otherwise raw retrieval. Reading this through
    one accessor keeps every downstream consumer -- draft, ground_check, spans,
    the audit view -- looking at the same set.
    """
    reranked = state.get("reranked")
    return reranked if reranked else state.get("retrieved", [])


def format_context(hits: list[SearchHit]) -> str:
    """Render chunks for a prompt.

    chunk_id is stated explicitly per extract because the draft node is required
    to copy it verbatim into each claim's citation.
    """
    if not hits:
        return "(no knowledge base extracts were retrieved for this ticket)"
    blocks = []
    for hit in hits:
        header = f"[chunk_id: {hit.chunk_id}] {hit.doc_title}"
        if hit.section:
            header += f" > {hit.section}"
        blocks.append(f"{header}\n{hit.text}")
    return "\n\n---\n\n".join(blocks)


def format_claims(draft: Draft) -> str:
    """Render claims for the grounding judge, indexed for verdict matching."""
    if not draft.claims:
        return "(the draft made no claims)"
    return "\n".join(
        f"[{i}] (cites: {c.chunk_id or 'NONE'}) {c.text}" for i, c in enumerate(draft.claims)
    )
