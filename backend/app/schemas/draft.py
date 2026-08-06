"""Draft schema (node: draft).

The resolution is composed of CLAIMS, each carrying the chunk it came from,
rather than free prose with citations bolted on afterwards.

This is the load-bearing design choice for the whole trust story. If the model
writes a paragraph and then appends sources, there is no way to check which
sentence came from which chunk. Forcing claim-level structure at generation time
makes grounding mechanically verifiable: every claim either maps to a retrieved
chunk that supports it, or it does not.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Claim(BaseModel):
    """One factual assertion in the resolution, with its source."""

    text: str = Field(max_length=600, description="A single factual assertion")
    chunk_id: str | None = Field(
        default=None,
        description="Id of the retrieved chunk supporting this claim. "
        "Null when no retrieved chunk supports it -- do not invent an id.",
    )


class Draft(BaseModel):
    """Proposed resolution, assembled from individually-sourced claims."""

    summary: str = Field(max_length=300, description="One-line statement of the diagnosis")
    claims: list[Claim] = Field(
        default_factory=list, description="Factual assertions, each individually sourced"
    )
    next_steps: list[str] = Field(
        default_factory=list, max_length=8, description="Ordered actions for the user or agent"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    escalate_recommended: bool = Field(
        default=False,
        description="True when the KB does not cover this, or policy requires a human",
    )

    def render(self) -> str:
        """Human-readable resolution text for the review queue and audit view."""
        lines = [self.summary, ""]
        lines.extend(claim.text for claim in self.claims)
        if self.next_steps:
            lines.append("")
            lines.extend(f"{i}. {step}" for i, step in enumerate(self.next_steps, 1))
        return "\n".join(lines)

    def cited_chunk_ids(self) -> list[str]:
        seen: list[str] = []
        for claim in self.claims:
            if claim.chunk_id and claim.chunk_id not in seen:
                seen.append(claim.chunk_id)
        return seen

    def uncited_claim_count(self) -> int:
        """Claims with no chunk_id at all -- caught before ground_check runs."""
        return sum(1 for claim in self.claims if not claim.chunk_id)
