"""Chunking strategies -- the baseline/optimized retrieval lever (PRD SS4.2).

Two strategies, both stored simultaneously in the same LanceDB table so the two
arms query identical code differing only by a filter predicate.

  fixed_512        naive: 512-token windows, no overlap, no structure, no metadata
  structure_aware  heading-scoped sections, metadata attached, sized to the
                   embedding model's real token limit

A note on fairness, because this is the comparison a reviewer should challenge:
512 tokens is not a strawman chosen to fail. It is the single most common
default in RAG tutorials and framework examples, and all-MiniLM-L6-v2 is the
most common default embedding model. The pairing is the archetypal naive setup.
What makes it bad is that the model truncates at 256 tokens, so roughly half of
every 512-token chunk never reaches the vector at all -- silently, with no error.
We measure that truncation rate and report it rather than leaving it implicit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.embeddings import count_tokens, model_info
from app.utils.ids import new_chunk_id

FIXED_CHUNK_TOKENS = 512  # the ubiquitous default
STRUCTURE_TARGET_TOKENS = 220  # inside the model's 256 limit, with headroom
STRUCTURE_MIN_TOKENS = 40  # below this, merge into a sibling
FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


@dataclass
class Chunk:
    chunk_id: str
    text: str
    doc_id: str
    doc_title: str
    section: str
    chunk_index: int
    category: str
    product: str
    strategy: str
    token_count: int
    truncated: bool = False


@dataclass
class ParsedDocument:
    doc_id: str
    title: str
    category: str
    product: str
    body: str
    meta: dict[str, str] = field(default_factory=dict)


def parse_document(raw: str, fallback_doc_id: str) -> ParsedDocument:
    """Split YAML-ish frontmatter from the markdown body."""
    meta: dict[str, str] = {}
    body = raw
    match = FRONTMATTER.match(raw)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
        body = raw[match.end():]

    return ParsedDocument(
        doc_id=meta.get("doc_id", fallback_doc_id),
        title=meta.get("title", fallback_doc_id),
        category=meta.get("category", ""),
        product=meta.get("product", ""),
        body=body.strip(),
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Baseline: fixed_512
# ---------------------------------------------------------------------------

def chunk_fixed(doc: ParsedDocument) -> list[Chunk]:
    """512-token windows over flat text. No overlap, no structure, no metadata.

    Faithful to the naive pattern: headings are stripped to plain text and the
    document is cut on token boundaries, so chunks routinely begin mid-sentence
    and span two unrelated procedures.
    """
    words = doc.body.split()
    if not words:
        return []

    # Approximate words-per-window from the document's own token density rather
    # than a fixed constant, so the window really is ~512 tokens for this text.
    sample = " ".join(words[:400])
    density = count_tokens(sample) / max(1, len(sample.split()))
    words_per_window = max(1, int(FIXED_CHUNK_TOKENS / max(density, 0.1)))

    limit = model_info().max_tokens
    chunks: list[Chunk] = []
    for index, start in enumerate(range(0, len(words), words_per_window)):
        text = " ".join(words[start : start + words_per_window]).strip()
        if not text:
            continue
        tokens = count_tokens(text)
        chunks.append(
            Chunk(
                chunk_id=new_chunk_id(doc.doc_id, "fixed_512", index),
                text=text,
                doc_id=doc.doc_id,
                doc_title=doc.title,
                # Deliberately empty. The naive strategy discards structure, so
                # the optimized arm's metadata filter has nothing to filter on
                # here. That advantage is a consequence of better ingestion,
                # not a handicap imposed on the baseline.
                section="",
                chunk_index=index,
                category="",
                product="",
                strategy="fixed_512",
                token_count=tokens,
                truncated=tokens > limit,
            )
        )
    return chunks


# ---------------------------------------------------------------------------
# Optimized: structure_aware
# ---------------------------------------------------------------------------

def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split markdown into (heading_path, text) pairs."""
    matches = list(HEADING.finditer(body))
    if not matches:
        return [("", body.strip())]

    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []

    preamble = body[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[match.end() : end].strip()

        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
        path = " > ".join(h for _, h in stack)

        if text:
            sections.append((path, text))
    return sections


def _split_oversized(path: str, text: str) -> list[tuple[str, str]]:
    """Break a long section at paragraph boundaries, never mid-sentence."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts: list[tuple[str, str]] = []
    buffer: list[str] = []

    for paragraph in paragraphs:
        candidate = "\n\n".join(buffer + [paragraph])
        if buffer and count_tokens(f"{path}\n\n{candidate}") > STRUCTURE_TARGET_TOKENS:
            parts.append((path, "\n\n".join(buffer)))
            buffer = [paragraph]
        else:
            buffer.append(paragraph)

    if buffer:
        parts.append((path, "\n\n".join(buffer)))
    return parts


def chunk_structure_aware(doc: ParsedDocument) -> list[Chunk]:
    """One chunk per leaf section, heading path prepended, metadata attached."""
    limit = model_info().max_tokens
    raw_sections = _split_sections(doc.body)

    # Merge undersized sections forward so a two-line section does not become a
    # chunk whose embedding is dominated by its heading.
    merged: list[tuple[str, str]] = []
    for path, text in raw_sections:
        if merged and count_tokens(text) < STRUCTURE_MIN_TOKENS:
            prev_path, prev_text = merged[-1]
            merged[-1] = (prev_path, f"{prev_text}\n\n{text}")
        else:
            merged.append((path, text))

    sized: list[tuple[str, str]] = []
    for path, text in merged:
        if count_tokens(f"{path}\n\n{text}") > STRUCTURE_TARGET_TOKENS:
            sized.extend(_split_oversized(path, text))
        else:
            sized.append((path, text))

    chunks: list[Chunk] = []
    for index, (path, text) in enumerate(sized):
        # The heading path is embedded with the body. A chunk about clearing
        # cached credentials is far more retrievable when its own text says it
        # belongs to "VPN Connection Failures > MFA token rejected after a
        # password change" than when that context lives only in a metadata
        # column the vector never sees.
        contextual = f"{doc.title} > {path}\n\n{text}" if path else f"{doc.title}\n\n{text}"
        tokens = count_tokens(contextual)
        chunks.append(
            Chunk(
                chunk_id=new_chunk_id(doc.doc_id, "structure_aware", index),
                text=contextual,
                doc_id=doc.doc_id,
                doc_title=doc.title,
                section=path,
                chunk_index=index,
                category=doc.category,
                product=doc.product,
                strategy="structure_aware",
                token_count=tokens,
                truncated=tokens > limit,
            )
        )
    return chunks


STRATEGIES = {
    "fixed_512": chunk_fixed,
    "structure_aware": chunk_structure_aware,
}


def chunk_document(doc: ParsedDocument, strategy: str) -> list[Chunk]:
    try:
        return STRATEGIES[strategy](doc)
    except KeyError:
        raise ValueError(
            f"Unknown chunking strategy {strategy!r}. Known: {', '.join(STRATEGIES)}"
        ) from None
