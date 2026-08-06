"""Strict JSON enforcement (FR-1.3, FR-1.4, Deliverable 5 SS5).

Every LLM boundary returns JSON validated against a Pydantic model before it
enters graph state.

On failure: exactly one bounded repair retry, then a deterministic fallback.
One attempt, not a loop -- unbounded repair is a cost sink that turns a bad
prompt into an expensive bad prompt.

Every outcome is counted. schema_violation_rate is a headline before/after
metric (PRD SS8.2): the baseline's verbose unpinned prompts produce measurably
more malformed JSON than the optimized arm's schema-constrained ones. It is one
of the cleanest quality deltas available because it is objectively countable --
no judge model, no interpretation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from app.observability.logging import get_logger

T = TypeVar("T", bound=BaseModel)
log = get_logger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class SchemaValidationFailed(RuntimeError):
    """Repair retry exhausted; caller must apply a deterministic fallback."""

    def __init__(self, message: str, *, raw: str, errors: str):
        super().__init__(message)
        self.raw = raw
        self.errors = errors


@dataclass
class ValidationResult:
    value: BaseModel
    schema_valid: bool
    repair_attempted: bool


def extract_json(text: str) -> str:
    """Pull a JSON object out of a model response.

    Models wrap JSON in prose or code fences even when told not to. Stripping
    that here rather than counting it as a violation keeps the
    schema_violation_rate metric measuring what it claims to measure --
    genuinely malformed structure, not cosmetic packaging.
    """
    text = text.strip()
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def validate(raw: str, schema: type[T]) -> T:
    """Parse and validate, raising ValidationError on failure."""
    return schema.model_validate(json.loads(extract_json(raw)))


def _repair_prompt(original: str, raw: str, errors: str, schema: type[BaseModel]) -> str:
    return (
        f"{original}\n\n"
        "--- CORRECTION REQUIRED ---\n"
        "Your previous response did not satisfy the required schema.\n\n"
        f"Your response was:\n{raw}\n\n"
        f"Validation errors:\n{errors}\n\n"
        f"Required JSON Schema:\n{json.dumps(schema.model_json_schema(), indent=2)}\n\n"
        "Return ONLY corrected JSON. No prose, no code fences."
    )


def validate_with_repair(
    raw: str,
    schema: type[T],
    *,
    original_prompt: str,
    retry_fn: Callable[[str], str],
    node: str = "unknown",
) -> ValidationResult:
    """Validate, attempting exactly one repair round trip on failure.

    `retry_fn` re-issues a completion with the repair prompt.
    """
    try:
        return ValidationResult(validate(raw, schema), schema_valid=True, repair_attempted=False)
    except (ValidationError, json.JSONDecodeError) as first_error:
        errors = str(first_error)[:1000]
        log.warning("schema_violation", node=node, schema=schema.__name__, error=errors[:300])

        repaired_raw = retry_fn(_repair_prompt(original_prompt, raw, errors, schema))
        try:
            value = validate(repaired_raw, schema)
        except (ValidationError, json.JSONDecodeError) as second_error:
            log.error(
                "schema_repair_failed",
                node=node,
                schema=schema.__name__,
                error=str(second_error)[:300],
            )
            raise SchemaValidationFailed(
                f"{schema.__name__} validation failed after one repair attempt",
                raw=repaired_raw,
                errors=str(second_error)[:1000],
            ) from second_error

        log.info("schema_repair_succeeded", node=node, schema=schema.__name__)
        # schema_valid stays False: the first attempt violated the schema, and
        # that is what the metric counts. Marking a repaired response as valid
        # would hide the exact cost difference the comparison exists to show.
        return ValidationResult(value, schema_valid=False, repair_attempted=True)


def json_schema_instruction(schema: type[BaseModel]) -> str:
    """Schema block appended to every structured prompt."""
    return (
        "Respond with a single JSON object conforming exactly to this JSON Schema. "
        "No prose, no markdown, no code fences.\n\n"
        f"{json.dumps(schema.model_json_schema(), indent=2)}"
    )
