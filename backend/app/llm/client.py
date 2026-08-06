r"""The single LLM chokepoint (Deliverable 5 SS1).

This is the ONLY module in the codebase that imports litellm. Verifiable with:

    grep -rn "import litellm" backend/app/ | grep -v "llm/client.py\|llm/tls.py\|llm/cost.py"

Everything that must apply to *every* LLM call -- TLS posture, retry policy,
budget enforcement, cache lookup, cost accounting, span emission, redaction --
applies here, once. There is no path by which a node can accidentally bypass
telemetry or caching, because nodes cannot reach litellm at all.

Call flow:
    1. resolve tier -> concrete model id
    2. cache lookup            (skipped when policy.cache_enabled is False)
    3. budget check
    4. litellm.completion      (wrapped in retry)
    5. structured validation   (+ one bounded repair retry)
    6. cost computation
    7. span emission -> SQLite (+ optional mirror)
    8. cache write
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

import litellm
from pydantic import BaseModel

from app.config.model_registry import ModelTier, get_registry
from app.config.policy import Policy
from app.config.settings import get_settings
from app.llm import cost as cost_module
from app.llm.retry import call_with_retry, get_budget
from app.llm.structured import ValidationResult, json_schema_instruction, validate_with_repair
from app.observability.logging import get_logger
from app.observability.redaction import prompt_hash
from app.observability.tracer import Span, counters, emit
from app.utils.timing import Stopwatch

T = TypeVar("T", bound=BaseModel)
log = get_logger(__name__)

# Deterministic by default so the comparison is reproducible to the limits of
# gateway non-determinism (Deliverable 6 SS8).
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 2048
REQUEST_TIMEOUT_SECONDS = 60.0


@dataclass
class LlmResult:
    """Validated response plus everything the span and metrics need."""

    value: BaseModel
    model: str
    tier: ModelTier
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cost_estimated: bool
    latency_ms: int
    cache_status: str
    retry_count: int
    schema_valid: bool
    repair_attempted: bool


def _raw_completion(model: str, prompt: str, *, temperature: float, max_tokens: int) -> tuple[str, int, int]:
    """One gateway round trip. Returns (text, tokens_in, tokens_out)."""
    settings = get_settings()
    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        api_base=settings.litellm_gateway_url,
        api_key=settings.litellm_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=REQUEST_TIMEOUT_SECONDS,
        response_format={"type": "json_object"},
    )
    usage = getattr(response, "usage", None)
    return (
        response.choices[0].message.content or "",
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def complete(
    *,
    node: str,
    prompt: str,
    schema: type[T],
    policy: Policy,
    run_id: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    corpus_version: str = "",
    prompt_version: str = "",
    chunk_ids: list[str] | None = None,
    parent_span_id: str | None = None,
) -> LlmResult:
    """Execute one structured LLM call end to end.

    `policy` is required, not optional: model tier, prompt variant, and cache
    posture are all policy-driven, which is what lets one graph serve both
    measurement arms without arm-name branching.
    """
    tier = policy.tier_for(node)
    model = get_registry().model_for(tier)
    full_prompt = f"{prompt}\n\n{json_schema_instruction(schema)}"
    watch = Stopwatch()
    counters.call_started()

    cache_status = "bypassed" if not policy.cache_enabled else "miss"
    tokens_in = tokens_out = 0
    retry_count = 0
    error_code: str | None = None

    try:
        # --- 2. Cache lookup ---------------------------------------------
        cached = None
        if policy.cache_enabled:
            from app.persistence import llm_cache

            cached = llm_cache.lookup(
                node=node,
                model=model,
                prompt=full_prompt,
                schema_name=schema.__name__,
                temperature=temperature,
                max_tokens=max_tokens,
                corpus_version=corpus_version,
                prompt_version=prompt_version,
            )

        if cached is not None:
            cache_status = cached.status
            value = schema.model_validate_json(cached.response_json)
            latency_ms = watch.stop()
            result = LlmResult(
                value=value,
                model=model,
                tier=tier,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                cost_estimated=False,
                latency_ms=latency_ms,
                cache_status=cache_status,
                retry_count=0,
                schema_valid=True,
                repair_attempted=False,
            )
            _emit(result, run_id, node, full_prompt, chunk_ids, parent_span_id, None)
            return result

        # --- 3+4. Budget check and gateway call --------------------------
        get_budget().check()

        outcome = call_with_retry(
            lambda: _raw_completion(
                model, full_prompt, temperature=temperature, max_tokens=max_tokens
            ),
            node=node,
        )
        raw, tokens_in, tokens_out = outcome.value  # type: ignore[misc]
        retry_count = outcome.retry_count
        get_budget().record(tokens_in + tokens_out)

        # --- 5. Structured validation with one bounded repair ------------
        def _repair(repair_prompt: str) -> str:
            nonlocal tokens_in, tokens_out
            inner = call_with_retry(
                lambda: _raw_completion(
                    model, repair_prompt, temperature=temperature, max_tokens=max_tokens
                ),
                node=f"{node}:repair",
            )
            text, r_in, r_out = inner.value  # type: ignore[misc]
            # Repair tokens are attributed to the originating call. The baseline
            # arm violates schemas more often, and that extra cost belongs in
            # its column rather than in an untracked footnote.
            tokens_in += r_in
            tokens_out += r_out
            get_budget().record(r_in + r_out)
            return text

        validated: ValidationResult = validate_with_repair(
            raw,
            schema,
            original_prompt=full_prompt,
            retry_fn=_repair,
            node=node,
        )

        # --- 6. Cost ------------------------------------------------------
        computed = cost_module.compute_cost(model, tokens_in, tokens_out)
        latency_ms = watch.stop()

        result = LlmResult(
            value=validated.value,
            model=model,
            tier=tier,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=computed.cost_usd,
            cost_estimated=computed.estimated,
            latency_ms=latency_ms,
            cache_status=cache_status,
            retry_count=retry_count,
            schema_valid=validated.schema_valid,
            repair_attempted=validated.repair_attempted,
        )

        # --- 7. Span ------------------------------------------------------
        _emit(result, run_id, node, full_prompt, chunk_ids, parent_span_id, None)

        # --- 8. Cache write ----------------------------------------------
        if policy.cache_enabled:
            from app.persistence import llm_cache

            llm_cache.store(
                node=node,
                model=model,
                prompt=full_prompt,
                schema_name=schema.__name__,
                temperature=temperature,
                max_tokens=max_tokens,
                corpus_version=corpus_version,
                prompt_version=prompt_version,
                response_json=validated.value.model_dump_json(),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=computed.cost_usd,
            )

        return result

    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
        error_code = type(exc).__name__
        failed = LlmResult(
            value=None,  # type: ignore[arg-type]
            model=model,
            tier=tier,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
            cost_estimated=False,
            latency_ms=watch.stop(),
            cache_status=cache_status,
            retry_count=retry_count,
            schema_valid=False,
            repair_attempted=False,
        )
        # A failed call is still measured. Partial spans are what make a failed
        # batch diagnosable rather than merely absent.
        _emit(failed, run_id, node, full_prompt, chunk_ids, parent_span_id, error_code)
        raise


def _emit(
    result: LlmResult,
    run_id: str,
    node: str,
    prompt: str,
    chunk_ids: list[str] | None,
    parent_span_id: str | None,
    error_code: str | None,
) -> None:
    emit(
        Span(
            run_id=run_id,
            node=node,
            kind="llm",
            latency_ms=result.latency_ms,
            parent_span_id=parent_span_id,
            tier=str(result.tier),
            resolved_model=result.model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            cost_estimated=result.cost_estimated,
            cache_status=result.cache_status,
            retry_count=result.retry_count,
            schema_valid=result.schema_valid,
            repair_attempted=result.repair_attempted,
            chunk_ids=chunk_ids,
            # Hash, never the prompt text (Deliverable 9 SS4).
            prompt_hash=prompt_hash(prompt),
            error_code=error_code,
        )
    )
