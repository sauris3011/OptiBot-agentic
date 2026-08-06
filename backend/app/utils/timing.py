"""Timing helpers."""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Iterator


def utc_now_iso() -> str:
    """Timestamp format used consistently across every table and log line."""
    return datetime.now(UTC).isoformat()


class Stopwatch:
    """Monotonic elapsed-time measurement.

    Monotonic rather than wall clock: a clock adjustment mid-run must not
    corrupt a latency metric that ends up on the comparison dashboard.
    """

    __slots__ = ("_start", "_elapsed_ms")

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._elapsed_ms: int | None = None

    def stop(self) -> int:
        if self._elapsed_ms is None:
            self._elapsed_ms = int((time.perf_counter() - self._start) * 1000)
        return self._elapsed_ms

    @property
    def elapsed_ms(self) -> int:
        if self._elapsed_ms is not None:
            return self._elapsed_ms
        return int((time.perf_counter() - self._start) * 1000)


@contextmanager
def timed() -> Iterator[Stopwatch]:
    watch = Stopwatch()
    try:
        yield watch
    finally:
        watch.stop()
