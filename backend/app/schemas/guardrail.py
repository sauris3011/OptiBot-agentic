"""Guardrail schemas (nodes: guardrail_pre, guardrail_post)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["none", "low", "medium", "high"]

IssueType = Literal[
    "prompt_injection",
    "social_engineering",
    "pii_exposure",
    "credential_request",
    "policy_violation",
    "unsafe_content",
    "none",
]


class GuardrailVerdict(BaseModel):
    """Screening decision for input or output content."""

    allowed: bool = Field(description="False blocks the pipeline and quarantines the run")
    risk: RiskLevel
    issues: list[IssueType] = Field(
        default_factory=list, description="Issue types detected; empty when clean"
    )
    rationale: str = Field(max_length=400)

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def summary(self) -> str:
        """Compact form for the span's guardrail_verdict column."""
        if self.allowed:
            return f"allow:{self.risk}"
        return f"block:{self.risk}:{','.join(self.issues) or 'unspecified'}"
