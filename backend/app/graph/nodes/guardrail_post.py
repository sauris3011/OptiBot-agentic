"""guardrail_post node -- screen generated output. LLM (tier1 -> tier3)."""

from __future__ import annotations

from app.graph.state import TicketState
from app.llm import client
from app.llm.structured import SchemaValidationFailed
from app.observability.logging import get_logger
from app.prompts.loader import render
from app.schemas.guardrail import GuardrailVerdict

log = get_logger(__name__)

NODE = "guardrail_post"

FALLBACK = GuardrailVerdict(
    allowed=False,
    risk="medium",
    issues=[],
    rationale="Output screening failed; blocked pending human review.",
)


def guardrail_post(state: TicketState) -> dict:
    policy = state["policy"]

    if not policy.guardrails_enabled:
        return {"guardrail_post": None}

    produced = state.get("draft")
    if produced is None or not produced.claims:
        return {"guardrail_post": None}

    prompt = render(policy.prompt_variant, NODE, resolution=produced.render())

    try:
        result = client.complete(
            node=NODE,
            prompt=prompt,
            schema=GuardrailVerdict,
            policy=policy,
            run_id=state["run_id"],
            corpus_version=state.get("corpus_version", ""),
            prompt_version=state.get("prompt_version", ""),
        )
        verdict = result.value
    except SchemaValidationFailed as exc:
        log.error("guardrail_post_fallback", error=str(exc)[:200])
        return {
            "guardrail_post": FALLBACK,
            "degraded": True,
            "errors": [*state.get("errors", []), f"{NODE}: schema validation exhausted"],
        }

    if verdict.blocked:
        log.warning("guardrail_post_blocked", risk=verdict.risk, issues=verdict.issues)
    return {"guardrail_post": verdict}
