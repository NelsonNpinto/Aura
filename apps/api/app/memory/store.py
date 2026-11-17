"""Long-term agent memory (§B8.3).

Namespaces are (org_id, kind, subject_id) with kind in {vendor, user}. Memories are written
only from human-confirmed corrections or from three or more consistent observations — never
from document text, which is untrusted (anti-poisoning, §B11 memory poisoning).

Every memory carries its source, who created it, a confidence and a TTL. Retrieval records
`last_used_at`; unused memories decay and expire. Users can see and delete everything the agent
"knows" about them or a vendor.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.tables import memories
from app.rag.embeddings import get_embedder

log = get_logger("memory")

Kind = Literal["vendor", "user"]

DEFAULT_TTL_DAYS = 180
OBSERVATIONS_FOR_ACTIVE = 3  # §B8.3: 3+ consistent observations, or one human confirmation
CONFIRMED_CONFIDENCE = 95
OBSERVED_CONFIDENCE = 60
MAX_FACT_CHARS = 400
# A memory unused for this long decays: its confidence drops and it stops being retrieved.
DECAY_DAYS = 60
DECAY_STEP = 15


class MemoryRejected(ValueError):
    """The write policy refused this memory."""


@dataclass(frozen=True)
class Memory:
    id: str
    kind: str
    subject_id: str
    fact: str
    status: str
    observations: int
    confidence: int
    created_by: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    source_event_id: str | None

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _rowcount(result: Any) -> int:
    """Rows affected by a DML statement. `Result` only types `rowcount` on `CursorResult`."""
    return int(getattr(result, "rowcount", 0) or 0)


def normalize_fact(fact: str) -> str:
    """Fold a fact to a comparison key so repeated observations collapse onto one row."""
    folded = unicodedata.normalize("NFKC", fact).casefold().strip()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def _row(r: Any) -> Memory:
    return Memory(
        id=str(r["id"]),
        kind=r["kind"],
        subject_id=r["subject_id"],
        fact=r["fact"],
        status=r["status"],
        observations=int(r["observations"]),
        confidence=int(r["confidence"]),
        created_by=r["created_by"],
        created_at=r["created_at"].isoformat(),
        last_used_at=r["last_used_at"].isoformat() if r["last_used_at"] else None,
        expires_at=r["expires_at"].isoformat() if r["expires_at"] else None,
        source_event_id=str(r["source_event_id"]) if r["source_event_id"] else None,
    )


async def remember(
    session: AsyncSession,
    org_id: str,
    *,
    kind: Kind,
    subject_id: str,
    fact: str,
    created_by: str,
    confirmed: bool,
    source_event_id: UUID | str | None = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> Memory:
    """Record an observation or a human-confirmed fact.

    `confirmed=True` (a human correction or override) activates the memory immediately.
    Unconfirmed observations stay `pending` until the same fact has been seen
    OBSERVATIONS_FOR_ACTIVE times. Raises MemoryRejected for facts that policy forbids.
    """
    fact = " ".join(fact.split())
    if not fact or len(fact) > MAX_FACT_CHARS:
        raise MemoryRejected(f"Fact must be 1-{MAX_FACT_CHARS} characters")
    if kind not in ("vendor", "user"):
        raise MemoryRejected("kind must be 'vendor' or 'user'")
    if not subject_id:
        raise MemoryRejected("subject_id required")
    norm = normalize_fact(fact)
    if not norm:
        raise MemoryRejected("Fact has no comparable content")
    embedding = (await get_embedder().embed([fact]))[0]
    expires = datetime.now(UTC) + timedelta(days=ttl_days)
    stmt = (
        pg_insert(memories)
        .values(
            org_id=org_id,
            kind=kind,
            subject_id=subject_id,
            fact=fact,
            fact_norm=norm,
            status="active" if confirmed else "pending",
            observations=1,
            confidence=CONFIRMED_CONFIDENCE if confirmed else OBSERVED_CONFIDENCE,
            source_event_id=str(source_event_id) if source_event_id else None,
            created_by=created_by,
            embedding=embedding,
            expires_at=expires,
        )
        .on_conflict_do_update(
            index_elements=["org_id", "kind", "subject_id", "fact_norm"],
            set_={
                "observations": memories.c.observations + 1,
                "fact": fact,
                "expires_at": expires,
                "status": text(
                    "CASE WHEN EXCLUDED.status = 'active' OR ai.memories.observations + 1 >= "
                    f"{OBSERVATIONS_FOR_ACTIVE} THEN 'active' ELSE 'pending' END"
                ),
                "confidence": text(
                    "GREATEST(ai.memories.confidence, EXCLUDED.confidence)",
                ),
            },
        )
        .returning(memories)
    )
    row = (await session.execute(stmt)).mappings().one()
    log.info(
        "memory.write",
        org_id=org_id,
        kind=kind,
        subject_id=subject_id,
        status=row["status"],
        confirmed=confirmed,
    )
    return _row(row)


async def recall(
    session: AsyncSession,
    org_id: str,
    *,
    kind: Kind,
    subject_id: str,
    query: str | None = None,
    limit: int = 5,
) -> list[Memory]:
    """Top-k active, unexpired memories for a namespace. Marks them used."""
    base = select(memories).where(
        memories.c.org_id == org_id,
        memories.c.kind == kind,
        memories.c.subject_id == subject_id,
        memories.c.status == "active",
        memories.c.confidence > 0,
        (memories.c.expires_at.is_(None)) | (memories.c.expires_at > datetime.now(UTC)),
    )
    if query:
        vec = (await get_embedder().embed([query], query=True))[0]
        stmt = base.order_by(memories.c.embedding.cosine_distance(vec)).limit(limit)
    else:
        stmt = base.order_by(memories.c.confidence.desc(), memories.c.created_at.desc()).limit(
            limit
        )
    rows = (await session.execute(stmt)).mappings().all()
    if rows:
        await session.execute(
            update(memories)
            .where(memories.c.id.in_([r["id"] for r in rows]))
            .values(last_used_at=datetime.now(UTC))
        )
    return [_row(r) for r in rows]


async def list_memories(
    session: AsyncSession, org_id: str, *, kind: Kind | None = None, subject_id: str | None = None
) -> list[Memory]:
    stmt = select(memories).where(memories.c.org_id == org_id)
    if kind:
        stmt = stmt.where(memories.c.kind == kind)
    if subject_id:
        stmt = stmt.where(memories.c.subject_id == subject_id)
    rows = (
        (await session.execute(stmt.order_by(memories.c.created_at.desc()).limit(200)))
        .mappings()
        .all()
    )
    return [_row(r) for r in rows]


async def forget(session: AsyncSession, org_id: str, memory_id: UUID | str) -> bool:
    """Hard delete one memory (user request, or vendor deletion)."""
    res = await session.execute(
        delete(memories).where(memories.c.org_id == org_id, memories.c.id == str(memory_id))
    )
    return _rowcount(res) > 0


async def forget_subject(session: AsyncSession, org_id: str, kind: Kind, subject_id: str) -> int:
    res = await session.execute(
        delete(memories).where(
            memories.c.org_id == org_id,
            memories.c.kind == kind,
            memories.c.subject_id == subject_id,
        )
    )
    return _rowcount(res)


async def decay(session: AsyncSession, org_id: str | None = None) -> dict[str, int]:
    """TTL + decay sweep (nightly). Expired rows are deleted; unused rows lose confidence."""
    now = datetime.now(UTC)
    where_org = (memories.c.org_id == org_id) if org_id else text("true")
    expired = await session.execute(
        delete(memories).where(
            where_org, memories.c.expires_at.is_not(None), memories.c.expires_at <= now
        )
    )
    stale_before = now - timedelta(days=DECAY_DAYS)
    decayed = await session.execute(
        update(memories)
        .where(
            where_org,
            memories.c.status == "active",
            ((memories.c.last_used_at.is_(None)) & (memories.c.created_at <= stale_before))
            | (memories.c.last_used_at <= stale_before),
        )
        .values(confidence=memories.c.confidence - DECAY_STEP)
    )
    retired = await session.execute(
        update(memories)
        .where(where_org, memories.c.confidence <= 0, memories.c.status != "retired")
        .values(status="retired")
    )
    return {
        "expired": _rowcount(expired),
        "decayed": _rowcount(decayed),
        "retired": _rowcount(retired),
    }
