"""classify node -- category, urgency, intent. LLM (tier1 -> tier3)."""

from __future__ import annotations

from app.graph.state import TicketState
from app.llm import client
from app.llm.structured import SchemaValidationFailed
from app.observability.logging import get_logger
from app.prompts.loader import render
from app.schemas.classify import Classification

log = get_logger(__name__)

NODE = "classify"

#: Deterministic fallback when validation is exhausted (FR-1.4). Chosen to be
#: safe rather than convenient: "Other" disables the metadata filter and
#: zero confidence forces human review downstream.
FALLBACK = Classification(
    category="Other", urgency="medium", intent="Classification unavailable", confidence=0.0
)


def classify(state: TicketState) -> dict:
    ticket = state["ticket"]
    policy = state["policy"]

    prompt = render(policy.prompt_variant, NODE, subject=ticket.subject, body=ticket.body)

    try:
        result = client.complete(
            node=NODE,
            prompt=prompt,
            schema=Classification,
            policy=policy,
            run_id=state["run_id"],
            corpus_version=state.get("corpus_version", ""),
            prompt_version=state.get("prompt_version", ""),
        )
    except SchemaValidationFailed as exc:
        log.error("classify_fallback", error=str(exc)[:200])
        return {
            "classification": FALLBACK,
            "degraded": True,
            "errors": [*state.get("errors", []), f"{NODE}: schema validation exhausted"],
        }

    classification = result.value
    log.info(
        "classified",
        category=classification.category,
        urgency=classification.urgency,
        confidence=classification.confidence,
    )
    return {"classification": classification}
