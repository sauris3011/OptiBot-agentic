"""route node -- the escalation gate. No LLM, deliberately.

An LLM deciding whether to escalate would be unauditable and non-reproducible.
The gate is code a reviewer can read in ten seconds and a compliance officer can
be shown directly.

Order matters: guardrails first (a blocked run never reaches a user at all),
then grounding, then policy, then confidence.
"""

from __future__ import annotations

from app.graph.state import TicketState
from app.observability.logging import get_logger
from app.observability.tracer import Span, emit
from app.utils.timing import Stopwatch

log = get_logger(__name__)

NODE = "route"


def _decide(state: TicketState) -> tuple[str, str]:
    policy = state["policy"]

    pre = state.get("guardrail_pre")
    if pre is not None and pre.blocked:
        return "quarantine", f"input guardrail blocked: {pre.summary()}"

    post = state.get("guardrail_post")
    if post is not None and post.blocked:
        return "quarantine", f"output guardrail blocked: {post.summary()}"

    if state.get("degraded"):
        return "human_review", "run degraded: " + "; ".join(state.get("errors", []))[:200]

    produced = state.get("draft")
    if produced is None:
        return "human_review", "no draft produced"

    grounding = state.get("grounding")
    if grounding is None or not grounding.fully_grounded:
        count = grounding.unsupported_claim_count if grounding else len(produced.claims)
        if grounding and grounding.total_claims == 0:
            return "human_review", "draft made no verifiable claims"
        return "human_review", f"unsupported claims: {count}"

    if produced.escalate_recommended:
        return "human_review", "model recommended escalation"

    # Baseline sends everything to a human. That is the naive default the
    # optimized arm improves on, and the deflection-rate delta is the business
    # metric it produces.
    if policy.escalation == "always_human":
        return "human_review", "policy: always_human"

    if produced.confidence < policy.confidence_threshold:
        return (
            "human_review",
            f"confidence {produced.confidence:.2f} below threshold {policy.confidence_threshold:.2f}",
        )

    return "auto_resolve", "fully grounded and above confidence threshold"


def route(state: TicketState) -> dict:
    watch = Stopwatch()
    decision, reason = _decide(state)

    emit(
        Span(
            run_id=state["run_id"],
            node=NODE,
            kind="deterministic",
            latency_ms=watch.stop(),
        )
    )
    log.info("routed", decision=decision, reason=reason)
    return {"decision": decision, "decision_reason": reason}


def route_edge(state: TicketState) -> str:
    """Conditional edge function. Reads the decision route() already recorded."""
    return state.get("decision") or "human_review"
