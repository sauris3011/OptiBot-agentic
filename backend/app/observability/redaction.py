"""Secret and PII redaction (FR-2.5, Deliverable 9 SS4).

Applied as a single processor shared by logs, spans, and the optional SaaS
mirror. One implementation for all three channels on purpose: a redaction rule
applied in two of three places is a leak.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# Field names whose values are replaced wholesale, regardless of content.
SENSITIVE_KEYS = frozenset(
    {
        "api_key", "apikey", "authorization", "auth", "token", "secret",
        "password", "litellm_api_key", "langfuse_secret_key", "token_hash",
        "bearer", "credential", "credentials",
    }
)

# Prompt and response bodies are never logged in full (Deliverable 9 SS4).
BODY_KEYS = frozenset({"prompt", "messages", "completion", "response_text", "content"})

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "[REDACTED:key]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b", re.I), "Bearer [REDACTED:token]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"), "[REDACTED:key]"),
)

_EMAIL = re.compile(r"\b([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")
_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d{1,3})\b")

MAX_PREVIEW_CHARS = 200


def _mask_email(match: re.Match[str]) -> str:
    """Hash the local part, keep the domain.

    A deliberate middle path: full redaction destroys the ability to notice that
    every failure came from one tenant; full retention is a compliance problem.
    """
    digest = hashlib.sha256(match.group(1).encode()).hexdigest()[:8]
    return f"[EMAIL:{digest}@{match.group(2)}]"


def redact_text(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    value = _EMAIL.sub(_mask_email, value)
    value = _IPV4.sub(r"\1.xxx", value)
    return value


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively redact a log/span payload."""
    if _depth > 8:  # guard against pathological nesting
        return "[REDACTED:depth]"

    if isinstance(value, str):
        return redact_text(value)

    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in SENSITIVE_KEYS:
                result[key] = "[REDACTED:secret]"
            elif lowered in BODY_KEYS:
                result[key] = _preview(item)
            else:
                result[key] = redact(item, _depth + 1)
        return result

    if isinstance(value, (list, tuple)):
        return [redact(item, _depth + 1) for item in value]

    return value


def _preview(value: Any) -> str:
    """Truncated, redacted preview of a body field."""
    text = redact_text(str(value))
    if len(text) <= MAX_PREVIEW_CHARS:
        return text
    return f"{text[:MAX_PREVIEW_CHARS]}... [truncated {len(text) - MAX_PREVIEW_CHARS} chars]"


def prompt_hash(prompt: str) -> str:
    """Stable hash used in place of prompt text.

    This removes the largest PII surface entirely rather than trying to scrub it,
    while still supporting reproducibility verification and cache correlation --
    everything the prompt text was needed for.
    """
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def structlog_processor(_logger, _method, event_dict: dict) -> dict:
    """structlog processor entry point."""
    return redact(event_dict)
