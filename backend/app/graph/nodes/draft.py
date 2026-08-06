"""draft node -- compose a resolution from retrieved context. LLM (tier1 -> tier2)."""

from __future__ import annotations

from app.graph.state import TicketState, context_chunks, format_context
from app.llm import client
from app.llm.structured import SchemaValidationFailed
from app.observability.logging import get_logger
from app.prompts.loader import render
from app.schemas.draft import Draft

log = get_logger(__name__)

NODE = "draft"

#: Empty draft with escalation recommended. An empty draft is never treated as
#: grounded (see GroundingReport.fully_grounded), so this routes to a human.
FALLBACK = Draft(
    summary="Unable to produce a resolution.",
    claims=[],
    next_steps=[],
    confidence=0.0,
    escalate_recommended=True,
)


def draft(state: TicketState) -> dict:
    policy = state["policy"]
    ticket = state["ticket"]
    classification = state.get("classification")
    hits = context_chunks(state)

    prompt = render(
        policy.prompt_variant,
        NODE,
        context=format_context(hits),
        subject=ticket.subject,
        body=ticket.body,
        category=classification.category if classification else "Unknown",
        urgency=classification.urgency if classification else "medium",
    )

    try:
        result = client.complete(
            node=NODE,
            prompt=prompt,
            schema=Draft,
            policy=policy,
            run_id=state["run_id"],
            corpus_version=state.get("corpus_version", ""),
            prompt_version=state.get("prompt_version", ""),
            chunk_ids=[h.chunk_id for h in hits],
        )
    except SchemaValidationFailed as exc:
        log.error("draft_fallback", error=str(exc)[:200])
        return {
            "draft": FALLBACK,
            "degraded": True,
            "errors": [*state.get("errors", []), f"{NODE}: schema validation exhausted"],
        }

    produced: Draft = result.value

    # Citations pointing at chunks that were never retrieved are hallucinated
    # ids. Null them here so ground_check judges a claim as uncited rather than
    # trying to verify it against a chunk that does not exist.
    valid_ids = {h.chunk_id for h in hits}
    invented = 0
    for claim in produced.claims:
        if claim.chunk_id and claim.chunk_id not in valid_ids:
            invented += 1
            claim.chunk_id = None

    if invented:
        log.warning("draft_invented_chunk_ids", count=invented)

    log.info(
        "drafted",
        claims=len(produced.claims),
        uncited=produced.uncited_claim_count(),
        invented_ids=invented,
        confidence=produced.confidence,
        escalate_recommended=produced.escalate_recommended,
    )
    return {"draft": produced}
