"""Document ingestion: file -> parsed -> chunks -> vectors (FR-5.3).

Ingests every document under BOTH strategies in one pass. Storing both
simultaneously is what allows the strategy comparison to run instantly and
prevents either arm from querying a fresher index than the other.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.observability.logging import get_logger
from app.persistence.db import execute
from app.rag import store
from app.rag.chunking import STRATEGIES, Chunk, chunk_document, parse_document
from app.utils.timing import utc_now_iso

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS_DIR = REPO_ROOT / "seed" / "kb_articles"


@dataclass
class IngestionReport:
    documents: int
    chunks_by_strategy: dict[str, int]
    truncated_by_strategy: dict[str, int]
    corpus_version: str


def corpus_version(docs: list[tuple[str, str]]) -> str:
    """Hash of (document contents + strategy set + embedding model).

    Recorded on every run and folded into cache keys, so a re-index invalidates
    affected entries automatically and no comparison can silently mix corpora.
    """
    from app.rag.embeddings import model_info

    digest = hashlib.sha256()
    for name, content in sorted(docs):
        digest.update(name.encode())
        digest.update(content.encode())
    digest.update("|".join(sorted(STRATEGIES)).encode())
    digest.update(model_info().name.encode())
    return digest.hexdigest()[:12]


def ingest_documents(documents: list[tuple[str, str]]) -> IngestionReport:
    """Ingest (filename, raw_markdown) pairs under every strategy."""
    version = corpus_version(documents)
    chunks_by_strategy: dict[str, int] = {}
    truncated_by_strategy: dict[str, int] = {}
    doc_count = 0

    for filename, raw in documents:
        parsed = parse_document(raw, fallback_doc_id=Path(filename).stem)
        doc_count += 1

        per_doc: dict[str, int] = {}
        for strategy in STRATEGIES:
            chunks: list[Chunk] = chunk_document(parsed, strategy)
            store.upsert_chunks(chunks, version)
            chunks_by_strategy[strategy] = chunks_by_strategy.get(strategy, 0) + len(chunks)
            truncated = sum(1 for c in chunks if c.truncated)
            truncated_by_strategy[strategy] = truncated_by_strategy.get(strategy, 0) + truncated
            per_doc[strategy] = len(chunks)

        execute(
            "INSERT OR REPLACE INTO documents "
            "(doc_id, title, source, category, chunk_counts, uploaded_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                parsed.doc_id,
                parsed.title,
                filename,
                parsed.category,
                str(per_doc).replace("'", '"'),
                utc_now_iso(),
            ),
        )

    log.info(
        "ingestion_complete",
        documents=doc_count,
        corpus_version=version,
        **{f"chunks_{k}": v for k, v in chunks_by_strategy.items()},
    )
    return IngestionReport(doc_count, chunks_by_strategy, truncated_by_strategy, version)


def ingest_directory(directory: Path | None = None) -> IngestionReport:
    directory = directory or DEFAULT_CORPUS_DIR
    files = sorted(directory.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No markdown documents found in {directory}")
    return ingest_documents([(f.name, f.read_text(encoding="utf-8")) for f in files])


def ingest_single(filename: str, raw: str) -> IngestionReport:
    """Ingest one uploaded document (FR-5.3 dynamic upload)."""
    return ingest_documents([(filename, raw)])
