"""Tracing (0.7): ai.traces is authoritative; Langfuse Cloud export is optional and sampled.

Everything that leaves the process passes the PII redactor first, and Langfuse also gets
the redactor as its `mask` function (defence in depth).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import insert

from app.core.config import get_settings
from app.core.context import trace_id_var
from app.core.db import tenant_tx
from app.core.logging import get_logger
from app.guardrails.pii import redact_any
from app.models.tables import traces

log = get_logger("tracing")
_MAX_FIELD = 8000


def _bounded(value: Any) -> Any:
    red = redact_any(value)
    raw = json.dumps(red, default=str)
    return red if len(raw) <= _MAX_FIELD else {"truncated": raw[:_MAX_FIELD]}


@lru_cache
def _langfuse() -> Any | None:
    s = get_settings()
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key.get_secret_value(),
        host=s.langfuse_host,
        environment=s.app_env,
        release=s.git_sha,
        sample_rate=s.langfuse_sample_rate,
        mask=lambda *, data, **_: redact_any(data),
    )


@dataclass
class Span:
    org_id: str
    name: str
    kind: str
    trace_id: str
    parent_id: str | None
    input: Any = None
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _t0: float = field(default_factory=time.perf_counter)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    def set_output(self, output: Any, **meta: Any) -> None:
        self.output = output
        self.metadata.update(meta)


class Tracer:
    def __init__(self, *, persist: bool = True) -> None:
        self.persist = persist
        self.memory: list[dict[str, Any]] = []

    @asynccontextmanager
    async def span(
        self, org_id: str, name: str, *, kind: str = "span", input: Any = None, **meta: Any
    ) -> AsyncIterator[Span]:
        parent = trace_id_var.get()
        trace_id = parent or uuid.uuid4().hex
        token = trace_id_var.set(trace_id)
        sp = Span(org_id, name, kind, trace_id, parent, input=input, metadata=dict(meta))
        try:
            yield sp
        except Exception as exc:
            sp.status = "error"
            sp.metadata["error_type"] = type(exc).__name__
            raise
        finally:
            trace_id_var.reset(token)
            await self._finish(sp)

    async def _finish(self, sp: Span) -> None:
        duration_ms = int((time.perf_counter() - sp._t0) * 1000)
        row = {
            "org_id": sp.org_id,
            "trace_id": sp.trace_id,
            "parent_id": sp.parent_id,
            "name": sp.name,
            "kind": sp.kind,
            "input": _bounded(sp.input),
            "output": _bounded(sp.output),
            "metadata": _bounded(sp.metadata),
            "status": sp.status,
            "started_at": sp.started_at,
            "duration_ms": duration_ms,
            "exported": False,
        }
        lf = _langfuse()
        if lf is not None:  # Langfuse applies sample_rate itself
            try:
                obs = lf.start_observation(
                    trace_context={"trace_id": sp.trace_id},
                    name=sp.name,
                    as_type="generation" if sp.kind == "llm" else "span",
                    input=row["input"],
                    output=row["output"],
                    metadata=row["metadata"],
                    level="ERROR" if sp.status == "error" else None,
                )
                obs.end()
                await asyncio.to_thread(lf.flush)
                row["exported"] = True
            except Exception as exc:
                log.warning("langfuse_export_failed", error_type=type(exc).__name__)
        if not self.persist:
            self.memory.append(row)
            return
        try:
            async with tenant_tx(sp.org_id) as s:
                await s.execute(insert(traces).values(**row))
        except Exception as exc:
            log.warning("trace_write_failed", error_type=type(exc).__name__)


_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
