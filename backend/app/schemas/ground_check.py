"""Grounding verification schemas (node: ground_check).

Two schemas, deliberately separate:

  GroundingJudgement  what the LLM returns -- per-claim verdicts ONLY
  GroundingReport     what the node produces -- verdicts plus DERIVED counts

The split matters. `unsupported_claim_count` gates escalation and is a headline
trust metric, so it must not be something a model reports about its own output.
Models miscount, and a model that judged three claims unsupported but reported a
count of one would silently release an ungrounded resolution.

The model makes judgements. Python does the arithmetic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClaimVerdict(BaseModel):
    """Whether one claim is genuinely supported by the chunk it cites."""

    claim_index: int = Field(ge=0, description="Index into the draft's claims list")
    supported: bool = Field(
        description="True only if the cited chunk actually states or directly implies this claim"
    )
    rationale: str = Field(max_length=300)


class GroundingJudgement(BaseModel):
    """LLM output: verdicts only, no counts."""

    verdicts: list[ClaimVerdict] = Field(default_factory=list)


class GroundingReport(BaseModel):
    """Node output: verdicts plus counts derived in code."""

    verdicts: list[ClaimVerdict] = Field(default_factory=list)
    unsupported_claim_count: int = 0
    total_claims: int = 0
    citation_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    contradicts_source: bool = False

    #: True when the judge returned fewer verdicts than there were cited claims.
    #: An empty `verdicts` list is schema-VALID but is not a judgement -- it is a
    #: non-answer. Counting those claims as unsupported is the right safety
    #: behaviour, but reporting it as a confident grounding result would be a
    #: lie, and would silently corrupt the hallucination metric with runs where
    #: the judge never actually ran.
    judgement_incomplete: bool = False

    @classmethod
    def derive(
        cls,
        judgement: GroundingJudgement,
        *,
        total_claims: int,
        uncited_claims: int,
    ) -> "GroundingReport":
        """Compute counts from verdicts. Never trust a model-reported total.

        An uncited claim is unsupported by definition and is counted even though
        no verdict exists for it -- otherwise a model could evade the check
        simply by omitting the citation.
        """
        judged_unsupported = sum(1 for v in judgement.verdicts if not v.supported)

        # A claim the judge silently skipped is not thereby supported. Count any
        # gap between claims and verdicts as unsupported.
        unjudged = max(0, total_claims - len(judgement.verdicts) - uncited_claims)

        unsupported = judged_unsupported + uncited_claims + unjudged
        supported = max(0, total_claims - unsupported)

        cited_claims = max(0, total_claims - uncited_claims)
        return cls(
            verdicts=judgement.verdicts,
            unsupported_claim_count=unsupported,
            total_claims=total_claims,
            citation_coverage=round(supported / total_claims, 4) if total_claims else 0.0,
            contradicts_source=any(
                not v.supported and "contradict" in v.rationale.lower()
                for v in judgement.verdicts
            ),
            judgement_incomplete=len(judgement.verdicts) < cited_claims,
        )

    @property
    def fully_grounded(self) -> bool:
        """Gates auto-resolve. An empty draft is not 'grounded' by vacuity."""
        return self.unsupported_claim_count == 0 and self.total_claims > 0
