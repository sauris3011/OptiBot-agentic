"""ground_check node -- verify every claim against its cited chunk.

LLM, tier1 in BOTH arms. Deliberately not downgraded: this node detects
hallucinations, and downgrading it to save tokens would optimize away the thing
being optimized for.

One mechanism yields three outputs: the trust metric (unsupported_claim_count),
the governance control (nothing ungrounded reaches a user), and the escalation
gate (route() reads this).
"""

from __future__ import annotations

from app.graph.state import TicketState, context_chunks, format_claims, format_context
from app.llm import client
from app.llm.structured import SchemaValidationFailed
from app.observability.logging import get_logger
from app.prompts.loader import render
from app.schemas.ground_check import GroundingJudgement, GroundingReport

log = get_logger(__name__)

NODE = "ground_check"


def ground_check(state: TicketState) -> dict:
    policy = state["policy"]
    produced = state.get("draft")

    if produced is None:
        return {"grounding": GroundingReport()}

    total = len(produced.claims)
    uncited = produced.uncited_claim_count()

    # No claims to verify. Skip the call rather than spend tier1 tokens proving
    # an empty set is empty. fully_grounded is False for a zero-claim draft, so
    # this still routes to a human.
    if total == 0:
        log.info("ground_check_skipped", reason="no_claims")
        return {"grounding": GroundingReport(total_claims=0)}

    prompt = render(
        policy.prompt_variant,
        NODE,
        context=format_context(context_chunks(state)),
        claims=format_claims(produced),
    )

    try:
        result = client.complete(
            node=NODE,
            prompt=prompt,
            schema=GroundingJudgement,
            policy=policy,
            run_id=state["run_id"],
            corpus_version=state.get("corpus_version", ""),
            prompt_version=state.get("prompt_version", ""),
            chunk_ids=produced.cited_chunk_ids(),
        )
        judgement: GroundingJudgement = result.value
    except SchemaValidationFailed as exc:
        # Fail CLOSED. If grounding cannot be verified, every claim counts as
        # unsupported, which forces human review. Treating an unverifiable draft
        # as grounded would be the single most dangerous failure in the system.
        log.error("ground_check_fallback", error=str(exc)[:200])
        return {
            "grounding": GroundingReport(
                verdicts=[],
                unsupported_claim_count=total,
                total_claims=total,
                citation_coverage=0.0,
            ),
            "degraded": True,
            "errors": [*state.get("errors", []), f"{NODE}: schema validation exhausted"],
        }

    report = GroundingReport.derive(judgement, total_claims=total, uncited_claims=uncited)

    log.info(
        "grounding_checked",
        total_claims=report.total_claims,
        unsupported=report.unsupported_claim_count,
        coverage=report.citation_coverage,
        contradicts_source=report.contradicts_source,
        verdicts_returned=len(report.verdicts),
    )
    if report.contradicts_source:
        log.warning("draft_contradicts_source", run_id=state["run_id"])

    # A judge that returned fewer verdicts than cited claims did not do the job.
    # Failing closed already forces human review, but marking the run degraded
    # keeps these out of the clean hallucination statistics -- otherwise a
    # non-answer would be indistinguishable from a confident "all unsupported".
    if report.judgement_incomplete:
        log.error(
            "ground_check_incomplete",
            verdicts=len(report.verdicts),
            cited_claims=total - uncited,
        )
        return {
            "grounding": report,
            "degraded": True,
            "errors": [
                *state.get("errors", []),
                f"{NODE}: judge returned {len(report.verdicts)} verdicts "
                f"for {total - uncited} cited claims",
            ],
        }

    return {"grounding": report}
