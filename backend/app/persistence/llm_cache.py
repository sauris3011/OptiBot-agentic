"""LLM cache (Deliverable 8).

STATUS: no-op stub. The full exact + semantic implementation lands in
Milestone 6, deliberately after the headline comparison is locked.

Reason (Deliverable 8 SS1, roadmap M6): a half-built cache leaking into
benchmark runs would silently corrupt the baseline numbers -- and it would
corrupt them in the direction that flatters us, which is the hardest kind of
error to notice. Until the cache is complete and its bypass verified, every
lookup misses and nothing is stored.

The `llm_cache` table already exists (tables.py) so no migration is needed when
the real implementation arrives.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class CacheEntry:
    response_json: str
    status: str  # hit_exact | hit_semantic
    tokens_in: int
    tokens_out: int
    cost_usd: float


def cache_key(
    *,
    model: str,
    prompt: str,
    schema_name: str,
    temperature: float,
    max_tokens: int,
    corpus_version: str = "",
    prompt_version: str = "",
) -> str:
    """Exact-match key.

    Every component matters: omitting the model would serve a tier3 response to
    a tier1 request; omitting the schema would serve a classification where a
    draft was requested. Corpus and prompt versions are folded in so a re-index
    or template change invalidates affected entries automatically.
    """
    material = "\x1f".join(
        [
            model,
            prompt,
            schema_name,
            f"{temperature:.4f}",
            str(max_tokens),
            corpus_version,
            prompt_version,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def lookup(**_kwargs) -> CacheEntry | None:
    """Always a miss until Milestone 6."""
    return None


def store(**_kwargs) -> None:
    """No-op until Milestone 6."""
    return None


def stats() -> dict:
    """Hit/miss statistics for the settings modal (FR-5.2)."""
    from app.persistence.db import query_one

    row = query_one(
        """
        SELECT
          SUM(CASE WHEN cache_status IN ('hit_exact','hit_semantic') THEN 1 ELSE 0 END) AS hits,
          SUM(CASE WHEN cache_status = 'miss'     THEN 1 ELSE 0 END) AS misses,
          SUM(CASE WHEN cache_status = 'bypassed' THEN 1 ELSE 0 END) AS bypassed
        FROM spans WHERE kind = 'llm'
        """
    )
    hits = (row["hits"] if row else 0) or 0
    misses = (row["misses"] if row else 0) or 0
    bypassed = (row["bypassed"] if row else 0) or 0
    total = hits + misses
    return {
        "implemented": False,
        "hits": hits,
        "misses": misses,
        "bypassed": bypassed,
        "hit_rate": round(hits / total, 4) if total else 0.0,
    }
