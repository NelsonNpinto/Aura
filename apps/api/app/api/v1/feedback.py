"""Feedback inbox (§B13): in-app corrections, an authenticated webhook, and triage into datasets.

The webhook is idempotent by `event_id`: replaying the same payload returns the original event,
a different payload for the same id is a 409. Requests are signed with HMAC over
`timestamp.body` and accepted inside a 5-minute window, so a captured request cannot be replayed
later (§B18).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.audit.chain import AuditEvent, append
from app.core.auth import CurrentPrincipal, Principal, require_roles
from app.core.config import get_settings
from app.core.db import tenant_tx
from app.core.errors import AppError, Conflict, NotFound, Unauthorized
from app.core.logging import get_logger
from app.memory import store as memory_store

log = get_logger("feedback")
router = APIRouter(prefix="/feedback", tags=["feedback"])

SIGNATURE_TOLERANCE_S = 300


class FeedbackIn(BaseModel):
    """An in-app correction or override made by a human."""

    kind: Literal["field_correction", "gl_override", "decision_override"]
    run_id: UUID | None = None
    subject: str = Field(default="", max_length=120)
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    comment: str = Field(default="", max_length=1000)
    remember_for_vendor: str | None = Field(default=None, max_length=40)


class Triage(BaseModel):
    dataset: str = Field(min_length=1, max_length=60)
    case_id: str = Field(default="", max_length=80)
    accept: bool = True


def verify_signature(body: bytes, signature: str | None, timestamp: str | None) -> None:
    secret = get_settings().webhook_secret
    if not secret:
        raise Unauthorized("Webhook secret is not configured", code="webhook_not_configured")
    if not signature or not timestamp:
        raise Unauthorized("Missing signature headers")
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise Unauthorized("Bad timestamp") from exc
    if abs(time.time() - sent_at) > SIGNATURE_TOLERANCE_S:
        raise Unauthorized("Signature expired", code="signature_expired")
    expected = hmac.new(
        secret.get_secret_value().encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.strip().removeprefix("sha256=")):
        raise Unauthorized("Bad signature")


@router.post("/webhooks/ai-failure")
async def ai_failure(
    request: Request,
    x_aura_signature: str | None = Header(default=None),
    x_aura_timestamp: str | None = Header(default=None),
    x_aura_org: str | None = Header(default=None),
) -> dict[str, Any]:
    """Accept an external AI-failure report. Idempotent by event_id (§B13)."""
    body = await request.body()
    verify_signature(body, x_aura_signature, x_aura_timestamp)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AppError("Body must be JSON", code="invalid_json") from exc
    event_id = str(payload.get("event_id") or "").strip()
    if not event_id or len(event_id) > 120:
        raise AppError("event_id is required", code="missing_event_id")
    org_id = x_aura_org or str(payload.get("org_id") or "demo")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    async with tenant_tx(org_id, "webhook") as s:
        existing = (
            (
                await s.execute(
                    text(
                        "SELECT id, payload_hash, status FROM ai.feedback_events"
                        " WHERE event_id = :e"
                    ),
                    {"e": event_id},
                )
            )
            .mappings()
            .first()
        )
        if existing:
            if existing["payload_hash"] != digest:
                raise Conflict(
                    "event_id was already used with a different payload",
                    code="event_id_conflict",
                )
            return {"id": str(existing["id"]), "status": existing["status"], "duplicate": True}
        new_id = (
            await s.execute(
                text(
                    "INSERT INTO ai.feedback_events (org_id, event_id, source, payload,"
                    " payload_hash) VALUES (:o, :e, :src, CAST(:p AS jsonb), :h) RETURNING id"
                ),
                {
                    "o": org_id,
                    "e": event_id,
                    "src": str(payload.get("source") or "webhook")[:60],
                    "p": json.dumps(payload),
                    "h": digest,
                },
            )
        ).scalar_one()
    log.info("feedback.webhook", org_id=org_id, event_id=event_id)
    return {"id": str(new_id), "status": "new", "duplicate": False}


@router.post("")
async def submit(body: FeedbackIn, p: CurrentPrincipal) -> dict[str, Any]:
    """Record an in-app human correction, and optionally remember it for the vendor (§B8.3)."""
    async with tenant_tx(p.org_id, p.user_id) as s:
        fid = (
            await s.execute(
                text(
                    "INSERT INTO ap.feedback (org_id, run_id, kind, field, before, after,"
                    " comment, created_by)"
                    " VALUES (:o, :r, :k, :sub, CAST(:b AS jsonb), CAST(:a AS jsonb), :c, :u)"
                    " RETURNING id"
                ),
                {
                    "o": p.org_id,
                    "r": str(body.run_id) if body.run_id else None,
                    "k": body.kind,
                    "sub": body.subject,
                    "b": json.dumps(body.before),
                    "a": json.dumps(body.after),
                    "c": body.comment,
                    "u": p.user_id,
                },
            )
        ).scalar_one()
        memory_id = None
        if body.remember_for_vendor and body.comment:
            try:
                mem = await memory_store.remember(
                    s,
                    p.org_id,
                    kind="vendor",
                    subject_id=body.remember_for_vendor,
                    fact=body.comment,
                    created_by=p.user_id,
                    confirmed=True,  # a human correction is a confirmation
                )
                memory_id = mem.id
            except memory_store.MemoryRejected as exc:
                log.info("feedback.memory_rejected", reason=str(exc))
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="feedback.submitted",
                actor_type="human",
                actor_id=p.user_id,
                run_id=str(body.run_id) if body.run_id else None,
                target_type="feedback",
                target_id=str(fid),
                decision=body.kind,
                input=body.before,
                output=body.after,
            ),
        )
    return {"id": str(fid), "memory_id": memory_id}


@router.get("/inbox")
async def inbox(
    p: Principal = require_roles("admin", "controller", "auditor"),
    status: str = "new",
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        events = (
            (
                await s.execute(
                    text(
                        "SELECT id, event_id, source, payload, status, dataset, case_id,"
                        " created_at FROM ai.feedback_events WHERE status = :st"
                        " ORDER BY created_at DESC LIMIT 200"
                    ),
                    {"st": status},
                )
            )
            .mappings()
            .all()
        )
        corrections = (
            (
                await s.execute(
                    text(
                        "SELECT id, run_id, kind, field, before, after, comment,"
                        " created_by, created_at FROM ap.feedback"
                        " ORDER BY created_at DESC LIMIT 100"
                    )
                )
            )
            .mappings()
            .all()
        )
    return {
        "events": [
            {**dict(e), "id": str(e["id"]), "created_at": e["created_at"].isoformat()}
            for e in events
        ],
        "corrections": [
            {
                **dict(c),
                "id": str(c["id"]),
                "run_id": str(c["run_id"]) if c["run_id"] else None,
                "created_at": c["created_at"].isoformat(),
            }
            for c in corrections
        ],
    }


@router.post("/inbox/{event_id}/triage")
async def triage(
    event_id: UUID,
    body: Triage,
    p: Principal = require_roles("admin", "controller"),
) -> dict[str, Any]:
    """Accept a reported failure into a regression dataset. Idempotent."""
    status = "accepted" if body.accept else "rejected"
    case_id = body.case_id or f"fb-{str(event_id)[:8]}"
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = (
            (
                await s.execute(
                    text(
                        "UPDATE ai.feedback_events SET status = :st, dataset = :ds, case_id = :ci,"
                        " triaged_by = :u, triaged_at = now()"
                        " WHERE id = :i AND status = 'new' RETURNING id, status, dataset, case_id"
                    ),
                    {
                        "st": status,
                        "ds": body.dataset if body.accept else None,
                        "ci": case_id if body.accept else None,
                        "u": p.user_id,
                        "i": str(event_id),
                    },
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            current = (
                (
                    await s.execute(
                        text(
                            "SELECT id, status, dataset, case_id FROM ai.feedback_events"
                            " WHERE id = :i"
                        ),
                        {"i": str(event_id)},
                    )
                )
                .mappings()
                .first()
            )
            if current is None:
                raise NotFound("feedback event not found")
            return {**dict(current), "id": str(current["id"]), "already_triaged": True}
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="feedback.triaged",
                actor_type="human",
                actor_id=p.user_id,
                target_type="feedback_event",
                target_id=str(event_id),
                decision=status,
                output={"dataset": body.dataset, "case_id": case_id},
            ),
        )
    return {**dict(row), "id": str(row["id"]), "already_triaged": False}
