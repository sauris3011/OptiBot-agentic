"""Local sentence-transformer embeddings (PRD SS4.4).

In-process, zero gateway cost, zero TLS exposure. Re-embedding the corpus under
a different chunking strategy is therefore free, which is what makes the
strategy comparison practical to run live.

IMPORTANT: all-MiniLM-L6-v2 has a hard 256-token input limit. Anything longer is
silently TRUNCATED at embedding time -- no error, no warning, the tail simply
does not influence the vector. This module exposes that limit so chunking can
respect it and so truncation can be measured rather than discovered later.
"""

from __future__ import annotations

import logging as _logging
import os
import threading
from dataclasses import dataclass
from functools import lru_cache

from app.config.settings import get_settings
from app.observability.logging import get_logger

log = get_logger(__name__)

# sentence-transformers and huggingface_hub write tqdm bars and HTTP traces to
# stdout, which corrupts the structured JSON log stream NFR-3.3 requires be
# machine-parseable. Suppressed at import, before any model loads.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
for _noisy in ("httpx", "httpcore", "huggingface_hub", "sentence_transformers", "transformers"):
    _logging.getLogger(_noisy).setLevel(_logging.WARNING)

_model = None
_lock = threading.Lock()


@dataclass(frozen=True)
class EmbeddingModelInfo:
    name: str
    dimension: int
    max_tokens: int


@lru_cache(maxsize=1)
def get_model():
    """Load the model once per process. First call may download ~90MB."""
    global _model
    with _lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer

        name = get_settings().embedding_model
        log.info("embedding_model_loading", model=name)
        _model = SentenceTransformer(name)
        log.info(
            "embedding_model_loaded",
            model=name,
            dimension=_dimension_of(_model),
            max_seq_length=_model.max_seq_length,
        )
        return _model


def _dimension_of(model) -> int:
    """Embedding dimension, tolerant of the sentence-transformers rename."""
    getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    return int(getter())


@lru_cache(maxsize=1)
def model_info() -> EmbeddingModelInfo:
    model = get_model()
    return EmbeddingModelInfo(
        name=get_settings().embedding_model,
        dimension=_dimension_of(model),
        max_tokens=int(model.max_seq_length),
    )


def count_tokens(text: str) -> int:
    """Token count using the embedding model's OWN tokenizer.

    Using the real tokenizer rather than a word-count heuristic matters: chunk
    sizing decisions are only meaningful in the units the model actually
    truncates by.
    """
    return len(get_model().tokenizer.encode(text, add_special_tokens=True))


def is_truncated(text: str) -> bool:
    """True when this text will lose content at embedding time."""
    return count_tokens(text) > model_info().max_tokens


def embed_texts(texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
    """Embed a batch. Vectors are normalised, so cosine == dot product."""
    if not texts:
        return []
    vectors = get_model().encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
