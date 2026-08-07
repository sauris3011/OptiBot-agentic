"""Offline verification of the trust-critical deterministic logic.

No gateway, no tokens, no network. These cover the two pieces of the system that
decide whether an ungrounded resolution can reach a user:

  GroundingReport.derive()  the arithmetic behind unsupported_claim_count
  route()                   the escalation gate

Both are pure functions by design, precisely so they can be proven rather than
sampled. The LLM's judgement quality still needs live verification; this proves
that whatever the judge says is counted and acted on correctly.

Run: python backend/tests/test_trust_logic.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.policy import BASELINE, OPTIMIZED
from app.graph.nodes.route import _decide
from app.schemas.draft import Claim, Draft
from app.schemas.ground_check import ClaimVerdict, GroundingJudgement, GroundingReport
from app.schemas.guardrail import GuardrailVerdict
from app.schemas.ticket import Ticket

FAILURES: list[str] = []


def check(name: str, actual, expected) -> None:
    if actual == expected:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}\n         expected {expected!r}\n         got      {actual!r}")
        FAILURES.append(name)


def verdicts(*supported: bool) -> GroundingJudgement:
    return GroundingJudgement(
        verdicts=[
            ClaimVerdict(claim_index=i, supported=s, rationale="test")
            for i, s in enumerate(supported)
        ]
    )


# ---------------------------------------------------------------------------
# GroundingReport.derive -- the arithmetic must never be generous
# ---------------------------------------------------------------------------

def test_derive() -> None:
    print("\nGroundingReport.derive")

    r = GroundingReport.derive(verdicts(True, True, True), total_claims=3, uncited_claims=0)
    check("all supported -> 0 unsupported", r.unsupported_claim_count, 0)
    check("all supported -> coverage 1.0", r.citation_coverage, 1.0)
    check("all supported -> fully_grounded", r.fully_grounded, True)

    r = GroundingReport.derive(verdicts(True, False, True), total_claims=3, uncited_claims=0)
    check("one unsupported counted", r.unsupported_claim_count, 1)
    check("one unsupported -> not grounded", r.fully_grounded, False)

    # An uncited claim has no verdict. It must still count as unsupported,
    # otherwise a model could evade the check by omitting the citation.
    r = GroundingReport.derive(verdicts(True, True), total_claims=3, uncited_claims=1)
    check("uncited claim counts as unsupported", r.unsupported_claim_count, 1)
    check("uncited claim -> not grounded", r.fully_grounded, False)

    # A claim the judge silently skipped is not thereby supported.
    r = GroundingReport.derive(verdicts(True), total_claims=3, uncited_claims=0)
    check("skipped claims count as unsupported", r.unsupported_claim_count, 2)
    check("skipped claims flagged incomplete", r.judgement_incomplete, True)

    # The failure mode that produced a false 5/6 in the M2 gate.
    r = GroundingReport.derive(GroundingJudgement(), total_claims=4, uncited_claims=0)
    check("empty judgement -> all unsupported", r.unsupported_claim_count, 4)
    check("empty judgement -> incomplete", r.judgement_incomplete, True)
    check("empty judgement -> not grounded", r.fully_grounded, False)

    # An empty draft must not be 'grounded' by vacuity.
    r = GroundingReport.derive(GroundingJudgement(), total_claims=0, uncited_claims=0)
    check("zero claims -> not fully_grounded", r.fully_grounded, False)
    check("zero claims -> complete (nothing to judge)", r.judgement_incomplete, False)

    r = GroundingReport.derive(
        GroundingJudgement(
            verdicts=[
                ClaimVerdict(claim_index=0, supported=False, rationale="This contradicts KB-007.")
            ]
        ),
        total_claims=1,
        uncited_claims=0,
    )
    check("contradiction detected", r.contradicts_source, True)

    # Full-coverage judgement of all-uncited claims is complete, not incomplete.
    r = GroundingReport.derive(GroundingJudgement(), total_claims=2, uncited_claims=2)
    check("all-uncited -> complete", r.judgement_incomplete, False)
    check("all-uncited -> all unsupported", r.unsupported_claim_count, 2)


# ---------------------------------------------------------------------------
# route() -- nothing ungrounded may reach auto_resolve
# ---------------------------------------------------------------------------

TICKET = Ticket(ticket_id="T1", subject="s", body="b")


def state(**over) -> dict:
    base = {
        "run_id": "r1",
        "policy": OPTIMIZED,
        "ticket": TICKET,
        "degraded": False,
        "errors": [],
        "draft": Draft(
            summary="s",
            claims=[Claim(text="c", chunk_id="k1")],
            confidence=0.9,
            escalate_recommended=False,
        ),
        "grounding": GroundingReport(
            verdicts=[ClaimVerdict(claim_index=0, supported=True, rationale="ok")],
            unsupported_claim_count=0,
            total_claims=1,
            citation_coverage=1.0,
        ),
        "guardrail_pre": GuardrailVerdict(allowed=True, risk="none", rationale="ok"),
        "guardrail_post": GuardrailVerdict(allowed=True, risk="none", rationale="ok"),
    }
    base.update(over)
    return base


def test_route() -> None:
    print("\nroute() escalation gate")

    check("clean grounded run auto-resolves", _decide(state())[0], "auto_resolve")

    blocked = GuardrailVerdict(
        allowed=False, risk="high", issues=["social_engineering"], rationale="x"
    )
    check("input guardrail block -> quarantine", _decide(state(guardrail_pre=blocked))[0], "quarantine")
    check("output guardrail block -> quarantine", _decide(state(guardrail_post=blocked))[0], "quarantine")

    # Guardrails outrank everything: a blocked run must never reach a user even
    # when the draft is perfectly grounded and confident.
    check(
        "guardrail outranks perfect grounding",
        _decide(state(guardrail_pre=blocked))[0],
        "quarantine",
    )

    check(
        "unsupported claim -> human_review",
        _decide(
            state(
                grounding=GroundingReport(
                    unsupported_claim_count=1, total_claims=2, citation_coverage=0.5
                )
            )
        )[0],
        "human_review",
    )

    check(
        "zero-claim draft -> human_review",
        _decide(state(grounding=GroundingReport(total_claims=0)))[0],
        "human_review",
    )

    check("missing grounding -> human_review", _decide(state(grounding=None))[0], "human_review")
    check("missing draft -> human_review", _decide(state(draft=None))[0], "human_review")
    check(
        "degraded run -> human_review",
        _decide(state(degraded=True, errors=["x"]))[0],
        "human_review",
    )

    check(
        "model-recommended escalation honoured",
        _decide(
            state(
                draft=Draft(
                    summary="s",
                    claims=[Claim(text="c", chunk_id="k1")],
                    confidence=0.99,
                    escalate_recommended=True,
                )
            )
        )[0],
        "human_review",
    )

    check(
        "low confidence -> human_review",
        _decide(
            state(
                draft=Draft(
                    summary="s",
                    claims=[Claim(text="c", chunk_id="k1")],
                    confidence=0.10,
                    escalate_recommended=False,
                )
            )
        )[0],
        "human_review",
    )

    # The baseline's defining behaviour: everything goes to a human, which is
    # what the deflection-rate delta measures against.
    check(
        "baseline always escalates even when grounded",
        _decide(state(policy=BASELINE))[0],
        "human_review",
    )


def main() -> int:
    print("Offline trust-logic verification (no gateway required)")
    test_derive()
    test_route()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'All checks passed.'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
