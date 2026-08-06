"""Retrieval scoring against the hand-labelled gold set (FR-3.4).

Labels are at DOCUMENT + SECTION level, never chunk id. Chunk ids differ between
strategies, so a chunk-id gold set would make it arithmetically impossible for
one strategy to score against labels derived from the other. Document-level
judgements are strategy-neutral, which is what makes precision@k a fair
comparison rather than a rigged one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.rag.store import SearchHit

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDSET_PATH = REPO_ROOT / "seed" / "goldset.json"
TICKETS_PATH = REPO_ROOT / "seed" / "tickets.json"


@dataclass(frozen=True)
class Judgement:
    ticket_id: str
    relevant_doc_ids: frozenset[str]
    primary_doc_id: str
    answer_section: str
    notes: str = ""


@dataclass
class RetrievalScore:
    ticket_id: str
    precision_at_k: float
    recall_at_k: float
    primary_hit: bool
    primary_rank: int | None
    section_hit: bool
    reciprocal_rank: float


def load_judgements() -> dict[str, Judgement]:
    data = json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))
    return {
        j["ticket_id"]: Judgement(
            ticket_id=j["ticket_id"],
            relevant_doc_ids=frozenset(j["relevant_doc_ids"]),
            primary_doc_id=j["primary_doc_id"],
            answer_section=j["answer_section"],
            notes=j.get("notes", ""),
        )
        for j in data["judgements"]
    }


def load_tickets() -> list[dict]:
    return json.loads(TICKETS_PATH.read_text(encoding="utf-8"))


def query_text(ticket: dict) -> str:
    return f"{ticket['subject']}\n\n{ticket['body']}"


def score_retrieval(hits: list[SearchHit], judgement: Judgement) -> RetrievalScore:
    """Score one ticket's retrieved set."""
    if not hits:
        return RetrievalScore(judgement.ticket_id, 0.0, 0.0, False, None, False, 0.0)

    retrieved_docs = [h.doc_id for h in hits]
    relevant_positions = [i for i, d in enumerate(retrieved_docs) if d in judgement.relevant_doc_ids]

    precision = len(relevant_positions) / len(hits)

    # Recall over documents, not chunks: several chunks from one relevant
    # document should not count as having found several relevant documents.
    found_docs = {d for d in retrieved_docs if d in judgement.relevant_doc_ids}
    recall = len(found_docs) / len(judgement.relevant_doc_ids)

    primary_rank = next(
        (i + 1 for i, d in enumerate(retrieved_docs) if d == judgement.primary_doc_id), None
    )

    # Section hit is the stricter test: did we retrieve the passage that
    # actually answers the ticket, not merely the right document? fixed_512
    # chunks carry no section metadata, so this is matched against chunk text as
    # a fallback -- the inability to report it cleanly IS part of the finding.
    needle = judgement.answer_section.lower()
    section_hit = any(
        (h.section and needle in h.section.lower()) or needle in h.text.lower() for h in hits
    )

    return RetrievalScore(
        ticket_id=judgement.ticket_id,
        precision_at_k=round(precision, 4),
        recall_at_k=round(recall, 4),
        primary_hit=primary_rank is not None,
        primary_rank=primary_rank,
        section_hit=section_hit,
        reciprocal_rank=round(1.0 / primary_rank, 4) if primary_rank else 0.0,
    )


def aggregate(scores: list[RetrievalScore]) -> dict:
    """Corpus-level retrieval metrics."""
    if not scores:
        return {}
    n = len(scores)
    return {
        "tickets": n,
        "precision_at_k": round(sum(s.precision_at_k for s in scores) / n, 4),
        "recall_at_k": round(sum(s.recall_at_k for s in scores) / n, 4),
        "primary_hit_rate": round(sum(1 for s in scores if s.primary_hit) / n, 4),
        "section_hit_rate": round(sum(1 for s in scores if s.section_hit) / n, 4),
        "mrr": round(sum(s.reciprocal_rank for s in scores) / n, 4),
    }
