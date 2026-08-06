"""Ticket input schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    """A service desk ticket as it enters the pipeline."""

    ticket_id: str
    subject: str
    body: str
    reported_by: str = ""
    channel: str = "portal"
    created_at: str = ""

    def as_query(self) -> str:
        """Retrieval query text. Subject and body carry different signal, so both."""
        return f"{self.subject}\n\n{self.body}"
