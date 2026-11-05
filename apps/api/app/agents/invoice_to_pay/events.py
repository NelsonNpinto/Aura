"""Run events (§B6 SSE): persisted to ap.run_events for replay/reconnect and pushed to live
subscribers. Every event carries run_id, seq, ts, node and a payload."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.core.db import tenant_tx

TERMINAL = {"run.completed", "run.failed"}


class Emitter:
    def __init__(self, run_id: str, org_id: str, start_seq: int = 0) -> None:
        self.run_id, self.org_id, self.seq = run_id, org_id, start_seq
        self.queues: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = asyncio.Lock()

    async def emit(self, type_: str, node: str | None = None, **payload: Any) -> dict[str, Any]:
        async with self._lock:
            self.seq += 1
            ev = {"run_id": self.run_id, "seq": self.seq, "ts": datetime.now(UTC).isoformat(),
                  "type": type_, "node": node, "payload": payload}
            async with tenant_tx(self.org_id) as s:
                await s.execute(
                    text("INSERT INTO ap.run_events (org_id, run_id, seq, type, node, ts, payload)"
                         " VALUES (:o, :r, :s, :t, :n, :ts, CAST(:p AS jsonb))"),
                    {"o": self.org_id, "r": self.run_id, "s": self.seq, "t": type_, "n": node,
                     "ts": datetime.fromisoformat(ev["ts"]), "p": json.dumps(payload, default=str)},
                )
        for q in self.queues:
            q.put_nowait(ev)
        return ev


async def last_seq(org_id: str, run_id: str) -> int:
    async with tenant_tx(org_id) as s:
        return int((await s.execute(
            text("SELECT coalesce(max(seq), 0) FROM ap.run_events WHERE run_id = :r"), {"r": run_id}
        )).scalar_one())


async def events_after(org_id: str, run_id: str, after: int) -> list[dict[str, Any]]:
    async with tenant_tx(org_id) as s:
        rows = (await s.execute(
            text("SELECT seq, type, node, ts, payload FROM ap.run_events WHERE run_id = :r AND seq > :a ORDER BY seq"),
            {"r": run_id, "a": after},
        )).mappings().all()
    return [{"run_id": run_id, "seq": r["seq"], "ts": r["ts"].isoformat(), "type": r["type"],
             "node": r["node"], "payload": r["payload"]} for r in rows]
