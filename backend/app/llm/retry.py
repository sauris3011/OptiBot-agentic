"""Retry policy and token budget enforcement (FR-7.4, Deliverable 5 SS4).

Retries are counted, not hidden: retry_count lands on every span and is reported
as a reliability metric. The baseline arm's higher schema-violation rate produces
more repair retries, and that cost belongs in the comparison.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from app.config.settings import get_settings
from app.observability.logging import get_logger

T = TypeVar("T")
log = get_logger(__name__)

MAX_BACKOFF_SECONDS = 30.0

#: Transient. Retrying may help.
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})

#: Terminal. A malformed request or a bad key does not improve with repetition,
#: and retrying one burns quota while hiding the real error from the operator.
NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404, 422})


class TokenBudgetExceeded(RuntimeError):
    """Process-lifetime token cap reached."""


class GatewayError(RuntimeError):
    """Gateway call failed after exhausting retries."""

    def __init__(self, message: str, *, status: int | None = None, attempts: int = 0):
        super().__init__(message)
        self.status = status
        self.attempts = attempts


@dataclass
class RetryOutcome:
    value: object
    attempts: int
    retry_count: int


class TokenBudget:
    """Hard ceiling on tokens for the process lifetime.

    A retry storm during an unattended batch evaluation is exactly how a
    hackathon quota disappears. The cap makes that failure loud and bounded
    instead of silent and total.
    """

    def __init__(self, cap: int | None) -> None:
        self._cap = cap
        self._used = 0
        self._lock = threading.Lock()

    def check(self) -> None:
        if self._cap is None:
            return
        with self._lock:
            if self._used >= self._cap:
                raise TokenBudgetExceeded(
                    f"Token budget of {self._cap:,} exhausted ({self._used:,} used). "
                    "Raise TOKEN_BUDGET_CAP in .env or restart the process."
                )

    def record(self, tokens: int) -> None:
        with self._lock:
            self._used += tokens

    @property
    def used(self) -> int:
        return self._used

    @property
    def cap(self) -> int | None:
        return self._cap

    @property
    def remaining(self) -> int | None:
        return None if self._cap is None else max(0, self._cap - self._used)


_budget: TokenBudget | None = None


def get_budget() -> TokenBudget:
    global _budget
    if _budget is None:
        _budget = TokenBudget(get_settings().token_budget_cap)
    return _budget


def _status_of(exc: Exception) -> int | None:
    for attr in ("status_code", "http_status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _retry_after(exc: Exception) -> float | None:
    """Honour the gateway's own backoff instruction when it supplies one."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _backoff(attempt: int, base: float) -> float:
    """Exponential backoff with full jitter.

    Jitter matters because batch evaluation issues many concurrent calls;
    unjittered backoff would resynchronise them into a thundering herd against
    the gateway that just rate-limited us.
    """
    ceiling = min(base * (2**attempt), MAX_BACKOFF_SECONDS)
    return random.uniform(0, ceiling)


def call_with_retry(fn: Callable[[], T], *, node: str = "unknown") -> RetryOutcome:
    """Invoke `fn`, retrying transient gateway failures."""
    settings = get_settings()
    get_budget().check()

    last: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            return RetryOutcome(fn(), attempts=attempt + 1, retry_count=attempt)
        except TokenBudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            last = exc
            status = _status_of(exc)

            if status in NON_RETRYABLE_STATUS:
                raise GatewayError(
                    f"Gateway rejected the request (HTTP {status}): {exc}",
                    status=status,
                    attempts=attempt + 1,
                ) from exc

            if attempt >= settings.llm_max_retries:
                break

            if status is not None and status not in RETRYABLE_STATUS:
                raise GatewayError(
                    f"Gateway returned HTTP {status}: {exc}",
                    status=status,
                    attempts=attempt + 1,
                ) from exc

            delay = _retry_after(exc) or _backoff(attempt, settings.llm_backoff_base_seconds)
            log.warning(
                "llm_retry",
                node=node,
                attempt=attempt + 1,
                status=status,
                delay_seconds=round(delay, 2),
                error=str(exc)[:200],
            )
            time.sleep(delay)

    raise GatewayError(
        f"Gateway call failed after {settings.llm_max_retries + 1} attempts: {last}",
        status=_status_of(last) if last else None,
        attempts=settings.llm_max_retries + 1,
    ) from last
