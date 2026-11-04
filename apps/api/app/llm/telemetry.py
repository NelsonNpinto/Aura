"""One ai.llm_calls row per attempt (§B10 telemetry)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from sqlalchemy import insert

from app.core.db import tenant_tx
from app.core.logging import get_logger
from app.models.tables import llm_calls

log = get_logger("llm.telemetry")


@dataclass
class LlmCallRecord:
    org_id: str
    task: str
    provider: str
    model: str
    status: str  # ok | error | skipped
    attempt: int = 1
    trace_id: str | None = None
    request_id: str | None = None
    run_id: str | None = None
    prompt_name: str | None = None
    prompt_version: int | None = None
    variant: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    est_cost_microusd: int = 0
    latency_ms: int = 0
    cache_hit: bool = False
    fallback_reason: str | None = None
    error_type: str | None = None


class TelemetrySink(Protocol):
    async def write(self, records: list[LlmCallRecord]) -> None: ...


class MemorySink:
    def __init__(self) -> None:
        self.records: list[LlmCallRecord] = []

    async def write(self, records: list[LlmCallRecord]) -> None:
        self.records.extend(records)


class DbSink:
    """Writes all attempts of one task call in a single tenant transaction."""

    async def write(self, records: list[LlmCallRecord]) -> None:
        if not records:
            return
        try:
            async with tenant_tx(records[0].org_id) as s:
                await s.execute(insert(llm_calls), [asdict(r) for r in records])
        except Exception as exc:  # telemetry must never break the request
            log.warning("llm_telemetry_write_failed", error_type=type(exc).__name__)
