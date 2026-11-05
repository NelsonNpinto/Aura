"""Run lifecycle: start (inline SSE or background), resume after approval, durable checkpoints.

Checkpoints live in schema `lg` via LangGraph's AsyncPostgresSaver on the DIRECT (unpooled)
URL with search_path=lg, so LangGraph's own tables never land in `public` (which also holds the
legacy app's tables) and the pooler never sees a session-level search_path.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from langgraph.types import Command
from sqlalchemy import text

from app.agents.invoice_to_pay.events import TERMINAL, Emitter, last_seq
from app.agents.invoice_to_pay.graph import RUNTIME, Deps, build_graph
from app.core.config import get_settings
from app.core.db import tenant_tx
from app.core.logging import get_logger

log = get_logger("runner")
_setup_done = False
_setup_lock = asyncio.Lock()


def _conninfo() -> str:
    url = get_settings().migration_url.replace("postgresql+psycopg://", "postgresql://")
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options=-csearch_path%3Dlg"


@contextlib.asynccontextmanager
async def checkpointer() -> AsyncIterator[Any]:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row

    global _setup_done
    async with await AsyncConnection.connect(_conninfo(), autocommit=True, prepare_threshold=0, row_factory=dict_row) as conn:
        saver = AsyncPostgresSaver(conn)
        if not _setup_done:
            async with _setup_lock:
                if not _setup_done:
                    await conn.execute("CREATE SCHEMA IF NOT EXISTS lg")
                    await saver.setup()
                    _setup_done = True
        yield saver


async def _set_status(org_id: str, run_id: str, status: str) -> None:
    async with tenant_tx(org_id) as s:
        await s.execute(text("UPDATE ap.runs SET status=:s WHERE id=:r AND status NOT IN ('posted','rejected','exception','blocked','failed','cancelled')"),
                        {"s": status, "r": run_id})


async def execute(run_id: str, org_id: str, actor_id: str, *, document_id: str | None = None,
                  resume: dict[str, Any] | None = None, approval_token: str | None = None,
                  country: str | None = None, queue: asyncio.Queue[dict[str, Any]] | None = None,
                  fake: bool = False) -> dict[str, Any]:
    """Run (or resume) the graph to its next stop: completion or an approval interrupt."""
    emitter = Emitter(run_id, org_id, await last_seq(org_id, run_id))
    if queue is not None:
        emitter.queues.append(queue)
    RUNTIME[run_id] = Deps(run_id=run_id, org_id=org_id, actor_id=actor_id, emitter=emitter,
                           country=country, approval_token=approval_token, fake=fake)
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 40}
    try:
        async with checkpointer() as saver:
            graph = build_graph().compile(checkpointer=saver)
            if resume is None:
                await _set_status(org_id, run_id, "running")
                await emitter.emit("run.started", None, document_id=document_id)
                inp: Any = {"run_id": run_id, "org_id": org_id, "document_id": document_id, "started_by": actor_id,
                            "flags": [], "errors": [], "timings": {}, "costs": {"tokens": 0, "est_usd_micros": 0}}
            else:
                await _set_status(org_id, run_id, "running")
                await emitter.emit("run.resumed", "human_approval", decision=resume.get("decision"), approver_id=resume.get("approver_id"))
                inp = Command(resume=resume)
            final: dict[str, Any] = {}
            async for chunk in graph.astream(inp, config, stream_mode="values"):
                final = chunk
            snap = await graph.aget_state(config)
            if snap.next and "human_approval" in snap.next:
                return {"status": "awaiting_approval", "route": final.get("route")}
            await emitter.emit("run.completed", None, route=final.get("route"), outcome=final.get("status"))
            return {"status": final.get("status"), "route": final.get("route")}
    except Exception as exc:
        log.error("run.failed", run_id=run_id, error=type(exc).__name__, detail=str(exc)[:300])
        async with tenant_tx(org_id) as s:
            await s.execute(text("UPDATE ap.runs SET status='failed', error=:e, finished_at=now() WHERE id=:r"),
                            {"e": f"{type(exc).__name__}: {str(exc)[:500]}", "r": run_id})
        await emitter.emit("run.failed", None, error=type(exc).__name__)
        return {"status": "failed", "route": None}
    finally:
        RUNTIME.pop(run_id, None)


async def stream(run_id: str, org_id: str, actor_id: str, **kw: Any) -> AsyncIterator[dict[str, Any]]:
    """Run inline and yield events as they happen (single-invoice SSE path)."""
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    task = asyncio.create_task(execute(run_id, org_id, actor_id, queue=q, **kw))
    while True:
        get = asyncio.create_task(q.get())
        done, _ = await asyncio.wait({get, task}, return_when=asyncio.FIRST_COMPLETED)
        if get in done:
            ev = get.result()
            yield ev
            if ev["type"] in TERMINAL or ev["type"] == "interrupt":
                if ev["type"] == "interrupt":
                    await task
                    while not q.empty():
                        yield q.get_nowait()
                    return
                await task
                return
        else:
            get.cancel()
            while not q.empty():
                yield q.get_nowait()
            return
