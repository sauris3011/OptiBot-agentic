"""guardrail_pre node -- screen input before generation. LLM (tier1 -> tier3).

Disabled in the baseline arm (policy.guardrails_enabled), which is the point:
the naive workflow has no input screening at all, so a social-engineering
attempt reaches the draft node unchallenged.
"""

from __future__ import annotations

from app.graph.state import TicketState
from app.llm import client
from app.llm.structured import SchemaValidationFailed
from app.observability.logging import get_logger
from app.prompts.loader import render
from app.schemas.guardrail import GuardrailVerdict

log = get_logger(__name__)

NODE = "guardrail_pre"

#: Fail CLOSED. When the screening model cannot be trusted to have run, the safe
#: default is to block and escalate, not to wave the content through.
FALLBACK = GuardrailVerdict(
    allowed=False,
    risk="medium",
    issues=[],
    rationale="Guardrail evaluation failed; blocked pending human review.",
)


def guardrail_pre(state: TicketState) -> dict:
    policy = state["policy"]

    if not policy.guardrails_enabled:
        return {"guardrail_pre": None}

    ticket = state["ticket"]
    prompt = render(policy.prompt_variant, NODE, subject=ticket.subject, body=ticket.body)

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
        log.error("guardrail_pre_fallback", error=str(exc)[:200])
        return {
            "guardrail_pre": FALLBACK,
            "degraded": True,
            "errors": [*state.get("errors", []), f"{NODE}: schema validation exhausted"],
        }

    if verdict.blocked:
        log.warning("guardrail_pre_blocked", risk=verdict.risk, issues=verdict.issues)
    return {"guardrail_pre": verdict}
