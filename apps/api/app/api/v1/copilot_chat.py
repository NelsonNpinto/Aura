"""Finance copilot chat (§B7): threads, SSE streaming, cited answers.

Threads persist per user. Long threads are summarised before they are carried into a new turn,
so the context stays inside the free-tier token budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.agents.copilot.agent import run_copilot
from app.api.deps import call_context
from app.core.auth import CurrentPrincipal
from app.core.db import tenant_tx
from app.core.errors import NotFound
from app.core.limits import charge_run
from app.core.logging import get_logger
from app.guardrails.pii import redact
from app.llm.router import get_router

router = APIRouter(prefix="/copilot", tags=["copilot"])
log = get_logger("copilot.chat")

SUMMARY_INTERVAL = 12
HISTORY_MESSAGES = 6
CHAT_TIMEOUT_SECONDS = 55


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=1000)
    thread_id: UUID | None = None


async def _load_thread(session: Any, user_id: str, thread_id: UUID | None) -> dict[str, Any]:
    if thread_id is None:
        return {"id": None, "summary": "", "messages": []}
    row = (
        (
            await session.execute(
                text("SELECT id, summary FROM ai.copilot_threads WHERE id = :t AND user_id = :u"),
                {"t": str(thread_id), "u": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFound("thread not found")
    messages = (
        (
            await session.execute(
                text(
                    "SELECT role, content FROM ai.copilot_messages WHERE thread_id = :t"
                    " ORDER BY created_at DESC, role ASC, id DESC LIMIT :n"
                ),
                {"t": str(thread_id), "n": HISTORY_MESSAGES},
            )
        )
        .mappings()
        .all()
    )
    return {
        "id": str(row["id"]),
        "summary": row["summary"],
        "messages": [dict(m) for m in reversed(messages)],
    }


@router.get("/threads")
async def list_threads(p: CurrentPrincipal) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT id, title, created_at, last_message_at FROM ai.copilot_threads"
                        " WHERE user_id = :u ORDER BY COALESCE(last_message_at, created_at) DESC"
                        " LIMIT 50"
                    ),
                    {"u": p.user_id},
                )
            )
            .mappings()
            .all()
        )
    return {
        "threads": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "created_at": r["created_at"].isoformat(),
                "last_message_at": r["last_message_at"].isoformat()
                if r["last_message_at"]
                else None,
            }
            for r in rows
        ]
    }


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: UUID, p: CurrentPrincipal) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        head = (
            (
                await s.execute(
                    text(
                        "SELECT id, title, summary FROM ai.copilot_threads"
                        " WHERE id = :t AND user_id = :u"
                    ),
                    {"t": str(thread_id), "u": p.user_id},
                )
            )
            .mappings()
            .first()
        )
        if head is None:
            raise NotFound("thread not found")
        msgs = (
            (
                await s.execute(
                    text(
                        "SELECT id, role, content, citations, tool_events, llm, created_at"
                        " FROM ai.copilot_messages WHERE thread_id = :t"
                        " ORDER BY created_at, role DESC, id"
                    ),
                    {"t": str(thread_id)},
                )
            )
            .mappings()
            .all()
        )
    return {
        "id": str(head["id"]),
        "title": head["title"],
        "summary": head["summary"],
        "messages": [{**dict(m), "created_at": m["created_at"].isoformat()} for m in msgs],
    }


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: UUID, p: CurrentPrincipal) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        res = await s.execute(
            text("DELETE FROM ai.copilot_threads WHERE id = :t AND user_id = :u"),
            {"t": str(thread_id), "u": p.user_id},
        )
    if not int(getattr(res, "rowcount", 0) or 0):
        raise NotFound("thread not found")
    return {"deleted": True, "id": str(thread_id)}


@router.post("/chat")
async def chat(
    body: ChatRequest, request: Request, p: CurrentPrincipal, background: BackgroundTasks
) -> StreamingResponse:
    """Stream the copilot's tool events and final cited answer over SSE."""
    ctx = call_context(request, p)
    async with tenant_tx(p.org_id, p.user_id) as s:
        thread = await _load_thread(s, p.user_id, body.thread_id)
    await charge_run(p)

    async def gen() -> AsyncIterator[bytes]:
        seq = 0

        def sse(event: dict[str, Any]) -> bytes:
            nonlocal seq
            seq += 1
            kind = event.get("type", "message")
            return f"id: {seq}\nevent: {kind}\ndata: {json.dumps(event, default=str)}\n\n".encode()

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def work() -> dict[str, Any]:
            try:
                async with asyncio.timeout(CHAT_TIMEOUT_SECONDS):
                    return await run_copilot(
                        p,
                        body.question,
                        ctx,
                        thread_summary=thread["summary"],
                        history=thread["messages"],
                        emit=emit,
                    )
            finally:
                await queue.put(None)

        yield sse({"type": "chat.started", "thread_id": thread["id"]})
        task = asyncio.create_task(work())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                if event is None:
                    break
                yield sse(event)
            result = await task
            thread_id, count = await _persist(p, thread, body.question, result)
        except Exception as exc:
            log.warning("copilot.chat_failed", error=type(exc).__name__)
            message = (
                "Copilot reached its time limit. Try a more specific question."
                if isinstance(exc, TimeoutError)
                else "Copilot could not complete this answer. Try again."
            )
            yield sse({"type": "chat.failed", "error": message})
        else:
            if count % SUMMARY_INTERVAL == 0:
                background.add_task(_summarise, p, thread_id)
            yield sse({"type": "chat.completed", "thread_id": thread_id, **result})
        finally:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
        background=background,
    )


async def _persist(
    p: CurrentPrincipal, thread: dict[str, Any], question: str, result: dict[str, Any]
) -> tuple[str, int]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        thread_id = thread["id"]
        if thread_id is None:
            thread_id = str(
                (
                    await s.execute(
                        text(
                            "INSERT INTO ai.copilot_threads (org_id, user_id, title)"
                            " VALUES (:o, :u, :t) RETURNING id"
                        ),
                        {"o": p.org_id, "u": p.user_id, "t": redact(question)[:80]},
                    )
                ).scalar_one()
            )
        for role, content, extra in (
            ("user", redact(question), {}),
            (
                "assistant",
                result["answer"],
                {
                    "citations": result.get("sources", []),
                    "tool_events": result.get("tool_events", []),
                    "llm": {
                        **(result.get("llm") or {}),
                        "citation_valid": result["citation_valid"],
                    },
                },
            ),
        ):
            await s.execute(
                text(
                    "INSERT INTO ai.copilot_messages"
                    " (org_id, thread_id, role, content, citations, tool_events, llm)"
                    " VALUES (:o, :t, :r, :c, :cit, :te, :llm)"
                ),
                {
                    "o": p.org_id,
                    "t": thread_id,
                    "r": role,
                    "c": content,
                    "cit": json.dumps(extra.get("citations", [])),
                    "te": json.dumps(extra.get("tool_events", [])),
                    "llm": json.dumps(extra.get("llm", {})),
                },
            )
        await s.execute(
            text("UPDATE ai.copilot_threads SET last_message_at = now() WHERE id = :t"),
            {"t": thread_id},
        )
        count = (
            await s.execute(
                text("SELECT count(*) FROM ai.copilot_messages WHERE thread_id = :t"),
                {"t": thread_id},
            )
        ).scalar_one()
    return str(thread_id), int(count)


async def _summarise(p: CurrentPrincipal, thread_id: str) -> None:
    """Compact a long thread so later turns stay inside the context budget."""
    from app.llm.router import CallContext

    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT role, content FROM ai.copilot_messages WHERE thread_id = :t"
                        " ORDER BY created_at DESC, role ASC, id DESC OFFSET :recent LIMIT 24"
                    ),
                    {"t": thread_id, "recent": HISTORY_MESSAGES},
                )
            )
            .mappings()
            .all()
        )
    transcript = "\n".join(f"{r['role']}: {r['content'][:600]}" for r in reversed(rows))
    try:
        async with asyncio.timeout(12):
            res = await get_router().run(
                "copilot_summary",
                {"transcript": transcript},
                CallContext(org_id=p.org_id, user_id=p.user_id),
            )
    except Exception:
        return
    async with tenant_tx(p.org_id, p.user_id) as s:
        await s.execute(
            text("UPDATE ai.copilot_threads SET summary = :sm WHERE id = :t"),
            {"sm": res.text[:2000], "t": thread_id},
        )
