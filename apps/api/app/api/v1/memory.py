"""Agent memory API (§B8.3).

Shows users exactly what the agent "knows" about a vendor or about them, where each fact came
from, and lets them delete it. Writes are policy-checked in `app.memory.store`: a human
confirmation, or three consistent observations — never document text.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.audit.chain import AuditEvent, append
from app.core.auth import CurrentPrincipal, Principal, require_roles
from app.core.db import tenant_tx
from app.core.errors import AppError, NotFound
from app.memory import store

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryCreate(BaseModel):
    kind: Literal["vendor", "user"]
    subject_id: str = Field(min_length=1, max_length=64)
    fact: str = Field(min_length=3, max_length=store.MAX_FACT_CHARS)
    confirmed: bool = True
    ttl_days: int = Field(default=store.DEFAULT_TTL_DAYS, ge=1, le=720)


@router.get("")
async def list_memories(
    p: CurrentPrincipal,
    kind: Literal["vendor", "user"] | None = Query(default=None),
    subject_id: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        items = await store.list_memories(s, p.org_id, kind=kind, subject_id=subject_id)
    return {"memories": [m.public() for m in items], "ttl_days": store.DEFAULT_TTL_DAYS}


@router.post("")
async def create_memory(body: MemoryCreate, p: CurrentPrincipal) -> dict[str, Any]:
    """Record a human-confirmed fact. Confirmed writes are audited."""
    if body.kind == "user" and body.subject_id != p.user_id and not p.has_any("admin"):
        raise AppError("Only an admin can write memories about another user")
    try:
        async with tenant_tx(p.org_id, p.user_id) as s:
            item = await store.remember(
                s,
                p.org_id,
                kind=body.kind,
                subject_id=body.subject_id,
                fact=body.fact,
                created_by=p.user_id,
                confirmed=body.confirmed,
                ttl_days=body.ttl_days,
            )
            await append(
                s,
                p.org_id,
                AuditEvent(
                    action="memory.write",
                    actor_type="human",
                    actor_id=p.user_id,
                    target_type="memory",
                    target_id=item.id,
                    decision=item.status,
                    input={"kind": body.kind, "subject_id": body.subject_id},
                    output={"fact": item.fact, "confidence": item.confidence},
                ),
            )
    except store.MemoryRejected as exc:
        raise AppError(str(exc)) from exc
    return item.public()


@router.delete("/{memory_id}")
async def delete_memory(memory_id: UUID, p: CurrentPrincipal) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        deleted = await store.forget(s, p.org_id, memory_id)
        if not deleted:
            raise NotFound("memory not found")
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="memory.delete",
                actor_type="human",
                actor_id=p.user_id,
                target_type="memory",
                target_id=str(memory_id),
                decision="deleted",
            ),
        )
    return {"deleted": True, "id": str(memory_id)}


@router.delete("/subject/{kind}/{subject_id}")
async def delete_subject(
    kind: Literal["vendor", "user"],
    subject_id: str,
    p: Principal = require_roles("admin", "controller"),
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        count = await store.forget_subject(s, p.org_id, kind, subject_id)
    return {"deleted": count, "kind": kind, "subject_id": subject_id}


@router.post("/decay")
async def run_decay(p: Principal = require_roles("admin")) -> dict[str, int]:
    """TTL and decay sweep for this org (also run nightly)."""
    async with tenant_tx(p.org_id, p.user_id) as s:
        return await store.decay(s, p.org_id)
