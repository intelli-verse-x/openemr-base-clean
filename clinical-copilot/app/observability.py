"""Structured logging, correlation IDs, Prometheus metrics, and Langfuse tracing.

Every log line, tool call, and LLM interaction carries the request's correlation_id
so a full trace can be reconstructed from logs alone (engineering requirement).
PHI is NOT written to logs — only ids, counts, timings (AUDIT compliance §5).
"""
from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any

from prometheus_client import Counter, Histogram
from pythonjsonlogger import jsonlogger

from .config import get_settings

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def new_correlation_id() -> str:
    cid = f"req-{uuid.uuid4().hex[:12]}"
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    return _correlation_id.get()


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(correlation_id)s %(message)s"
        )
    )
    handler.addFilter(_CorrelationFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


log = logging.getLogger("copilot")

# --- Prometheus metrics (feed the dashboard: requests, errors, latency, tools) ---
REQUESTS = Counter("copilot_requests_total", "Chat requests", ["outcome"])
TOOL_CALLS = Counter("copilot_tool_calls_total", "Tool calls", ["tool", "outcome"])
LLM_TOKENS = Counter("copilot_llm_tokens_total", "LLM tokens", ["kind"])
VERIFICATION = Counter("copilot_verification_total", "Verification outcomes", ["result"])
RETRIES = Counter("copilot_retries_total", "Retries", ["stage"])
LATENCY = Histogram(
    "copilot_request_latency_seconds",
    "End-to-end chat latency",
    buckets=(0.5, 1, 2, 3, 5, 8, 13, 21, 34),
)
TOOL_LATENCY = Histogram(
    "copilot_tool_latency_seconds", "Per-tool latency", ["tool"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8),
)


class _NoopSpan:
    def update(self, **_: Any) -> None: ...
    def end(self, **_: Any) -> None: ...
    def generation(self, **_: Any) -> "_NoopSpan":
        return self


class Tracer:
    """Thin Langfuse wrapper that degrades to no-op when not configured."""

    def __init__(self) -> None:
        self._client = None
        s = get_settings()
        if s.langfuse_enabled:
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=s.langfuse_public_key,
                    secret_key=s.langfuse_secret_key,
                    host=s.langfuse_host,
                )
            except Exception as exc:  # pragma: no cover
                log.warning("langfuse init failed: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def trace(self, name: str, **kw: Any):
        if not self._client:
            return _NoopSpan()
        try:
            if get_settings().langfuse_public_traces:
                kw.setdefault("public", True)
            return self._client.trace(name=name, id=get_correlation_id(), **kw)
        except Exception:  # pragma: no cover
            return _NoopSpan()

    def flush(self) -> None:
        if self._client:
            try:
                self._client.flush()
            except Exception:  # pragma: no cover
                pass


_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


class step_timer:
    """Context manager that records a labeled duration into a histogram."""

    def __init__(self, histogram: Histogram, *labels: str) -> None:
        self._h = histogram.labels(*labels) if labels else histogram
        self._start = 0.0
        self.elapsed = 0.0

    def __enter__(self) -> "step_timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed = time.perf_counter() - self._start
        self._h.observe(self.elapsed)
