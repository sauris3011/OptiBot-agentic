"""RAG endpoints (Deliverable 4 SS2.4, FR-5.3)."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config.policy import get_policy
from app.rag import ingestion, rerank, store

router = APIRouter(prefix="/api/rag", tags=["rag"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    strategy: str = "structure_aware"
    top_k: int = Field(default=10, ge=1, le=50)
    category: str | None = None
    rerank_enabled: bool = False
    rerank_top_k: int = Field(default=3, ge=1, le=20)


class Hit(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    section: str
    category: str
    score: float
    token_count: int
    text: str


class SearchResponse(BaseModel):
    query: str
    strategy: str
    reranked: bool
    hits: list[Hit]


def _to_hit(h: store.SearchHit) -> Hit:
    return Hit(
        chunk_id=h.chunk_id,
        doc_id=h.doc_id,
        doc_title=h.doc_title,
        section=h.section,
        category=h.category,
        score=round(h.score, 4),
        token_count=h.token_count,
        text=h.text,
    )


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Debug retrieval without generating.

    Exists for the demo: it shows *why* the optimized arm retrieves better,
    rather than asking the audience to accept the precision number on faith.
    """
    hits = store.search(
        request.query,
        strategy=request.strategy,
        top_k=request.top_k,
        category=request.category,
    )
    if request.rerank_enabled:
        hits = rerank.rerank(request.query, hits, top_k=request.rerank_top_k)
    return SearchResponse(
        query=request.query,
        strategy=request.strategy,
        reranked=request.rerank_enabled,
        hits=[_to_hit(h) for h in hits],
    )


class CompareRequest(BaseModel):
    query: str = Field(min_length=1)
    category: str | None = None


@router.post("/compare")
def compare(request: CompareRequest) -> dict:
    """Run the same query through both arms' exact retrieval configurations.

    Each side uses its own Policy, so this is the real retrieval path, not an
    approximation of it.
    """
    out: dict = {"query": request.query, "arms": {}}
    for name in ("baseline", "optimized"):
        policy = get_policy(name)  # type: ignore[arg-type]
        hits = store.search(
            request.query,
            strategy=policy.chunking,
            top_k=policy.retrieval_top_k,
            category=request.category if policy.metadata_filter_enabled else None,
        )
        if policy.rerank_enabled and policy.rerank_top_k:
            hits = rerank.rerank(request.query, hits, top_k=policy.rerank_top_k)
        out["arms"][name] = {
            "strategy": policy.chunking,
            "top_k": policy.retrieval_top_k,
            "reranked": policy.rerank_enabled,
            "metadata_filter": policy.metadata_filter_enabled,
            "chunks_returned": len(hits),
            "context_tokens": sum(h.token_count for h in hits),
            "hits": [_to_hit(h).model_dump() for h in hits],
        }
    return out


@router.get("/stats")
def stats() -> dict:
    """Corpus statistics for the grounding panel (FR-5.3)."""
    return store.stats()


@router.post("/documents")
async def upload_document(file: UploadFile = File(...)) -> dict:
    """Upload and embed a document under both strategies."""
    if not file.filename or not file.filename.endswith((".md", ".txt")):
        raise HTTPException(400, "Only .md and .txt documents are supported")
    raw = (await file.read()).decode("utf-8", errors="replace")
    report = ingestion.ingest_single(file.filename, raw)
    return {
        "documents": report.documents,
        "chunks_by_strategy": report.chunks_by_strategy,
        "truncated_by_strategy": report.truncated_by_strategy,
        "corpus_version": report.corpus_version,
    }


@router.post("/reindex")
def reindex() -> dict:
    """Re-embed the seed corpus under every strategy."""
    report = ingestion.ingest_directory()
    return {
        "documents": report.documents,
        "chunks_by_strategy": report.chunks_by_strategy,
        "truncated_by_strategy": report.truncated_by_strategy,
        "corpus_version": report.corpus_version,
    }
