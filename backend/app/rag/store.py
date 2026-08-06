"""LanceDB vector store (Deliverable 7 SS1).

The ONLY module that imports lancedb. Single-writer discipline lives here, which
is what makes the clean-shutdown guarantee (FR-7.5) enforceable -- an abrupt
termination mid-write is the realistic corruption path.

Both chunking strategies occupy the same table, distinguished by the `strategy`
column. That is deliberate: the two arms query identical code differing only in
a filter predicate, so neither can benefit from a fresher index.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import lancedb
import pyarrow as pa

from app.config.settings import get_settings
from app.observability.logging import get_logger
from app.rag.chunking import Chunk
from app.rag.embeddings import embed_query, embed_texts, model_info

log = get_logger(__name__)

TABLE_NAME = "kb_chunks"

_db = None
_write_lock = threading.RLock()


@dataclass
class SearchHit:
    chunk_id: str
    text: str
    doc_id: str
    doc_title: str
    section: str
    category: str
    product: str
    strategy: str
    score: float
    token_count: int


def _schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("chunk_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), model_info().dimension)),
            pa.field("text", pa.string()),
            pa.field("doc_id", pa.string()),
            pa.field("doc_title", pa.string()),
            pa.field("section", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("category", pa.string()),
            pa.field("product", pa.string()),
            pa.field("strategy", pa.string()),
            pa.field("corpus_version", pa.string()),
            pa.field("token_count", pa.int32()),
            pa.field("truncated", pa.bool_()),
        ]
    )


def get_db():
    global _db
    with _write_lock:
        if _db is None:
            path = get_settings().lancedb_path
            path.mkdir(parents=True, exist_ok=True)
            _db = lancedb.connect(str(path))
        return _db


def get_table():
    db = get_db()
    if TABLE_NAME not in db.table_names():
        return db.create_table(TABLE_NAME, schema=_schema())
    return db.open_table(TABLE_NAME)


def upsert_chunks(chunks: list[Chunk], corpus_version: str) -> int:
    """Embed and write chunks, replacing any existing rows for the same strategy.

    Held under the write lock so retrieval never races ingestion.
    """
    if not chunks:
        return 0

    with _write_lock:
        table = get_table()
        vectors = embed_texts([c.text for c in chunks])
        rows = [
            {
                "chunk_id": c.chunk_id,
                "vector": vector,
                "text": c.text,
                "doc_id": c.doc_id,
                "doc_title": c.doc_title,
                "section": c.section,
                "chunk_index": c.chunk_index,
                "category": c.category,
                "product": c.product,
                "strategy": c.strategy,
                "corpus_version": corpus_version,
                "token_count": c.token_count,
                "truncated": c.truncated,
            }
            for c, vector in zip(chunks, vectors, strict=True)
        ]

        strategies = {c.strategy for c in chunks}
        doc_ids = {c.doc_id for c in chunks}
        for strategy in strategies:
            docs = "', '".join(sorted(doc_ids))
            table.delete(f"strategy = '{strategy}' AND doc_id IN ('{docs}')")

        table.add(rows)
        log.info("chunks_upserted", count=len(rows), strategies=sorted(strategies))
        return len(rows)


def search(
    query: str,
    *,
    strategy: str,
    top_k: int = 10,
    category: str | None = None,
) -> list[SearchHit]:
    """Semantic search within one strategy's chunks.

    `category` is the optimized arm's metadata filter. It is unavailable to the
    baseline not by rule but by consequence: fixed_512 chunks carry no category,
    because the naive strategy discards the structure it would come from.
    """
    table = get_table()
    if table.count_rows() == 0:
        return []

    predicate = f"strategy = '{strategy}'"
    if category:
        predicate += f" AND category = '{category}'"

    results = (
        table.search(embed_query(query))
        .where(predicate)
        .limit(top_k)
        .to_list()
    )

    hits = []
    for row in results:
        # LanceDB returns L2 distance on normalised vectors; convert to a
        # similarity in [0, 1] so scores read the same way everywhere.
        distance = float(row.get("_distance", 0.0))
        hits.append(
            SearchHit(
                chunk_id=row["chunk_id"],
                text=row["text"],
                doc_id=row["doc_id"],
                doc_title=row["doc_title"],
                section=row["section"],
                category=row["category"],
                product=row["product"],
                strategy=row["strategy"],
                score=max(0.0, 1.0 - distance / 2.0),
                token_count=row["token_count"],
            )
        )
    return hits


def stats() -> dict:
    """Corpus statistics for the RAG grounding panel (FR-5.3)."""
    table = get_table()
    total = table.count_rows()
    info = model_info()
    if total == 0:
        return {
            "total_chunks": 0,
            "by_strategy": {},
            "embedding_model": info.name,
            "dimension": info.dimension,
            "max_tokens": info.max_tokens,
        }

    rows = table.to_arrow().to_pylist()
    by_strategy: dict[str, dict] = {}
    for row in rows:
        entry = by_strategy.setdefault(
            row["strategy"],
            {"chunks": 0, "docs": set(), "tokens": 0, "truncated": 0, "corpus_version": ""},
        )
        entry["chunks"] += 1
        entry["docs"].add(row["doc_id"])
        entry["tokens"] += row["token_count"]
        entry["truncated"] += 1 if row["truncated"] else 0
        entry["corpus_version"] = row["corpus_version"]

    return {
        "total_chunks": total,
        "embedding_model": info.name,
        "dimension": info.dimension,
        "max_tokens": info.max_tokens,
        "by_strategy": {
            name: {
                "chunks": e["chunks"],
                "documents": len(e["docs"]),
                "avg_tokens": round(e["tokens"] / e["chunks"], 1),
                "truncated_chunks": e["truncated"],
                # Share of chunks losing content silently at embedding time.
                "truncation_rate": round(e["truncated"] / e["chunks"], 4),
                "corpus_version": e["corpus_version"],
            }
            for name, e in by_strategy.items()
        },
    }


def close() -> None:
    """Release the writer at shutdown (FR-7.5)."""
    global _db
    with _write_lock:
        _db = None
