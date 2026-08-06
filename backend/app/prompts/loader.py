"""Prompt template loading and versioning.

Templates live as files, not string literals, so prompt compression is a
diffable lever rather than a code change -- and so prompt_version can be a hash
of what actually ran.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=64)
def load_template(variant: str, node: str) -> str:
    path = PROMPT_DIR / variant / f"{node}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"No prompt template for node {node!r} in variant {variant!r} (looked in {path})"
        )
    return path.read_text(encoding="utf-8").strip()


def render(variant: str, node: str, **fields: object) -> str:
    """Load and fill a template.

    Uses str.format, so literal braces in a template must be doubled. JSON
    Schema blocks are appended by llm/structured.py rather than embedded here,
    which keeps templates free of brace escaping.
    """
    return load_template(variant, node).format(**fields)


@lru_cache(maxsize=4)
def prompt_version(variant: str) -> str:
    """Hash of every template in a variant.

    Recorded per run and folded into cache keys, so editing a prompt invalidates
    affected cache entries and no comparison can silently mix prompt versions.
    """
    directory = PROMPT_DIR / variant
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.txt")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return f"{variant}-{digest.hexdigest()[:10]}"
