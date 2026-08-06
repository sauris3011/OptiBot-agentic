"""Classification schema (node: classify)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Urgency = Literal["low", "medium", "high", "critical"]

#: Constrained label set. A closed vocabulary is what lets a lite model match a
#: reasoning model here -- and it is also what makes the category usable as a
#: LanceDB metadata filter, since free-text categories would never match.
CATEGORIES = (
    "Network & Connectivity",
    "Identity & Access",
    "Productivity Software",
    "Hardware",
    "Peripherals",
    "Software Management",
    "Account Lifecycle",
    "Security & Compliance",
    "Other",
)

Category = Literal[
    "Network & Connectivity",
    "Identity & Access",
    "Productivity Software",
    "Hardware",
    "Peripherals",
    "Software Management",
    "Account Lifecycle",
    "Security & Compliance",
    "Other",
]


class Classification(BaseModel):
    """Structured triage of an incoming ticket."""

    category: Category = Field(description="Closed-vocabulary ticket category")
    urgency: Urgency = Field(description="Assessed urgency")
    intent: str = Field(
        max_length=200, description="One-line statement of what the user needs"
    )
    confidence: float = Field(ge=0.0, le=1.0)
