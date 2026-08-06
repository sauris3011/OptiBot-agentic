"""Identifier generation.

Short, prefixed, sortable-by-creation IDs. Readability matters here: run_id is
the correlation key a human reads across the dashboard, the audit view, and the
log stream, so it needs to be quotable out loud during a demo.
"""

from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford-ish: no i, l, o, u


def _b32(value: int, width: int) -> str:
    out = []
    for _ in range(width):
        value, rem = divmod(value, 32)
        out.append(_ALPHABET[rem])
    return "".join(reversed(out))


def _new_id(prefix: str) -> str:
    """Time-prefixed so lexical order matches creation order."""
    stamp = _b32(int(time.time() * 1000), 8)
    rand = _b32(secrets.randbits(20), 4)
    return f"{prefix}_{stamp}{rand}"


def new_run_id() -> str:
    return _new_id("run")


def new_span_id() -> str:
    return _new_id("spn")


def new_batch_id() -> str:
    return _new_id("bat")


def new_review_id() -> str:
    return _new_id("rev")


def new_chunk_id(doc_id: str, strategy: str, index: int) -> str:
    """Deterministic chunk id.

    Deterministic on purpose: re-ingesting the same document under the same
    strategy must produce the same chunk ids, otherwise stored citations and
    gold-set labels would break on every re-index.
    """
    return f"{doc_id}:{strategy}:{index:04d}"
