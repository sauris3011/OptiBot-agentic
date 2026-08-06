"""Reranking -- optimized arm only (PRD SS4.2).

Bi-encoder retrieval embeds query and document independently, so it scores
topical similarity but cannot judge whether a passage actually answers the
question. Reranking re-scores the shortlist with the query and passage seen
together, which is what lets top-k drop from 10 to 3 without losing the answer.

That drop is a substantial share of the token saving in the draft node: three
focused chunks instead of ten diffuse ones, on every ticket.

Deterministic and LLM-free, so it costs no tokens and adds no variance to the
comparison.
"""

from __future__ import annotations

import re
import threading
from functools import lru_cache

from app.observability.logging import get_logger
from app.rag.store import SearchHit

log = get_logger(__name__)

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_encoder = None
_lock = threading.Lock()
_STOPWORDS = frozenset(
    "a an and are as at be but by for from had has have i if in into is it its me my "
    "no not of on or our so that the their then there these they this to was we were what "
    "when where which who will with you your".split()
)


def _load_cross_encoder():
    """Load the cross-encoder, or None if unavailable.

    Returning None rather than raising is deliberate: the lexical fallback below
    is a genuine reranking signal, so a missing optional model degrades the
    optimized arm slightly instead of breaking the demo.
    """
    global _encoder
    with _lock:
        if _encoder is not None:
            return _encoder if _encoder is not False else None
        try:
            from sentence_transformers import CrossEncoder

            _encoder = CrossEncoder(CROSS_ENCODER_MODEL)
            log.info("cross_encoder_loaded", model=CROSS_ENCODER_MODEL)
        except Exception as exc:  # noqa: BLE001
            log.warning("cross_encoder_unavailable", error=str(exc)[:200])
            _encoder = False
            return None
        return _encoder


@lru_cache(maxsize=512)
def _terms(text: str) -> frozenset[str]:
    return frozenset(
        w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS and len(w) > 2
    )


def _lexical_score(query: str, hit: SearchHit) -> float:
    """Overlap-based fallback signal.

    Weights the heading path above the body: a section titled for the user's
    problem is strong evidence, and it is exactly the signal the fixed_512
    chunks lack.
    """
    q = _terms(query)
    if not q:
        return 0.0
    body = len(q & _terms(hit.text)) / len(q)
    heading = len(q & _terms(f"{hit.doc_title} {hit.section}")) / len(q)
    return 0.6 * body + 0.4 * heading


def rerank(query: str, hits: list[SearchHit], *, top_k: int) -> list[SearchHit]:
    """Re-score and narrow the shortlist.

    NOTE: reranked scores are cross-encoder LOGITS, not the [0, 1] similarity
    that `store.search` returns. They are unbounded and frequently negative, and
    only the ordering is meaningful. The UI must label reranked scores as
    relevance rank rather than rendering them on the same scale as raw
    similarity.
    """
    if not hits:
        return []
    if len(hits) <= 1:
        return hits[:top_k]

    encoder = _load_cross_encoder()
    if encoder is not None:
        scores = encoder.predict(
            [(query, hit.text) for hit in hits], show_progress_bar=False
        )
        ranked = sorted(zip(hits, scores, strict=True), key=lambda p: float(p[1]), reverse=True)
    else:
        ranked = sorted(
            ((hit, _lexical_score(query, hit)) for hit in hits),
            key=lambda p: p[1],
            reverse=True,
        )

    out: list[SearchHit] = []
    for hit, score in ranked[:top_k]:
        hit.score = float(score)
        out.append(hit)
    return out
