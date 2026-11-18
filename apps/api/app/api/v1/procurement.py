"""Procurement assignment: scoped documents, mandatory reviews and payment confirmation."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, ColumnElement, func, or_, select, text

from app.api.deps import call_context
from app.audit.chain import AuditEvent, append
from app.core.auth import CurrentPrincipal, Principal
from app.core.config import get_settings
from app.core.db import system_tx, tenant_tx
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.limits import charge_run
from app.domain.procurement import PURCHASING_DEMO_ORG, EvidenceDocument, Line, compare, transition
from app.guardrails.pii import redact
from app.llm.providers import provider_configured
from app.llm.router import RouterError, get_router
from app.models.tables import procurement_cases, procurement_members
from app.services.blob import get_blob_store
from app.services.payment_email import delivery_blocker, dispatch, payment_message
from app.services.pdf import PdfText, extract_text, render_pages_png
from app.services.runs import create_document, sniff

router = APIRouter(prefix="/procurement", tags=["procurement"])
EXTRACTION_TIMEOUT_SECONDS = 35

# Fingerprints of the four synthetic PDFs supplied with the local purchasing demo.
_DEMO_DOCUMENTS = {
    "cb1a816dfe8bfdd821d81b26855a50671af69d14cbb1bb0696986051d87a886e": (
        "po",
        "PO-DEMO-1001",
        2,
        5000000,
    ),
    "f3c9d345723f154a6b605a3fdc76472fa3beb396b8d52032775404cae89d36dd": (
        "invoice",
        "INV-DEMO-1001",
        2,
        5000000,
    ),
    "412fb89f777b8c0c764e00829ae248df4df0f6529e66312edb439fea8a5d44d6": (
        "receipt",
        "GRN-DEMO-1001-A",
        1,
        0,
    ),
    "b9940d896bde945aa2699e33093cfacd564e8da6531886f81b53e80622c4b98c": (
        "receipt",
        "GRN-DEMO-1001-B",
        2,
        0,
    ),
}


@router.post("/cases/{case_id}/extract/{kind}")
async def extract_document(
    case_id: uuid.UUID,
    kind: Literal["po", "invoice", "receipt"],
    request: Request,
    p: CurrentPrincipal,
    file: UploadFile = File(),
    synthetic_confirmed: bool = Form(False),
    use_ai: bool = Form(True),
) -> dict[str, Any]:
    roles, vendor = await actor(p)
    required = {
        "invoice": {"vendor", "clerk", "admin"},
        "po": {"purchasing", "clerk", "admin"},
        "receipt": {"purchasing", "receiving", "clerk", "admin"},
    }[kind]
    if not roles & required or ("vendor" in roles and not vendor):
        raise Forbidden("This document belongs to another workflow role")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, vendor)
        if row["state"]["payment"]:
            raise Conflict("Paid cases cannot accept more documents")
    # Leave room for multipart headers within Vercel's 4.5 MB request limit.
    max_bytes = 4_000_000 if get_settings().is_deployed else 10_000_000
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise AppError(
            f"Document exceeds {max_bytes // 1_000_000} MB",
            code="document_too_large",
            status_code=413,
        )
    if not synthetic_confirmed:
        raise Conflict("Confirm that this upload contains only synthetic demo data")
    mime = sniff(data)
    pdf = await asyncio.to_thread(extract_text, data, 20) if mime == "application/pdf" else None
    if pdf and pdf.hidden:
        raise Conflict("Document needs manual review: hidden text detected")
    fixture = (
        _DEMO_DOCUMENTS.get(hashlib.sha256(data).hexdigest())
        if get_settings().app_env == "local"
        else None
    )
    if fixture and (fixture[0] != kind or row["po_number"] != "PO-DEMO-1001"):
        raise Conflict("Use this demo PDF in its matching document section on PO-DEMO-1001.")
    task = "extract_procurement" if pdf and pdf.has_text_layer else "extract_procurement_vision"
    if (
        use_ai
        and not fixture
        and not any(provider_configured(model) for model in get_router().config.tasks[task].chain)
    ):
        raise AppError(
            "Document extraction needs a configured AI provider. Enter the details manually.",
            code="extraction_provider_unavailable",
            status_code=503,
        )
    draft: dict[str, Any] | None = None
    llm = None
    if use_ai and not fixture:
        await charge_run(p)
        try:
            async with asyncio.timeout(EXTRACTION_TIMEOUT_SECONDS):
                draft, llm = await _extract_draft(kind, request, p, data, pdf, row["po_number"])
        except (RouterError, TimeoutError) as exc:
            raise AppError(
                "AI extraction could not finish. Try again or enter the document details manually.",
                code="extraction_unavailable",
                status_code=503,
            ) from exc
    source = await create_document(
        p.org_id, p.user_id, file.filename or "document.pdf", data, synthetic=True, guest=p.is_guest
    )
    async with tenant_tx(p.org_id, p.user_id) as s:
        current = await case_row(s, p, case_id, vendor, lock=True)
        if current["state"].get("payment"):
            raise Conflict("Paid cases cannot accept more documents")
        await s.execute(
            text(
                "INSERT INTO ap.procurement_uploads (org_id,case_id,kind,user_id,document_id)"
                " VALUES (:o,:c,:k,:u,:d) ON CONFLICT DO NOTHING"
            ),
            {"o": p.org_id, "c": case_id, "k": kind, "u": p.user_id, "d": source["document_id"]},
        )
    if not use_ai:
        return {
            "draft": None,
            "source_document_id": source["document_id"],
            "requires_human_confirmation": True,
            "extraction_mode": "manual",
            "llm": None,
        }
    if fixture:
        _, number, quantity, price = fixture
        fixture_draft = EvidenceDocument(
            number=number,
            po_number="PO-DEMO-1001",
            currency="INR",
            lines=[
                Line(
                    sku="LAPTOP-01",
                    description="14-inch business laptop",
                    quantity=quantity,
                    unit_price_minor=price,
                )
            ],
            total_minor=quantity * price,
            source_document_id=source["document_id"],
        )
        return {
            "draft": fixture_draft.model_dump(mode="json"),
            "source_document_id": source["document_id"],
            "requires_human_confirmation": True,
            "extraction_mode": "demo_fixture",
            "llm": None,
        }
    assert draft is not None
    draft["source_document_id"] = source["document_id"]
    return {
        "draft": draft,
        "source_document_id": source["document_id"],
        "requires_human_confirmation": True,
        "llm": llm,
    }


async def _extract_draft(
    kind: str, request: Request, p: Principal, data: bytes, pdf: PdfText | None, po_number: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    marker = "AURA_CASE_PO_REFERENCE"
    masked_po = False
    if pdf and pdf.has_text_layer:
        document = pdf.visible_text[:18000]
        # Keep a long numeric PO reference from looking like a phone number to the PII scrubber.
        # Send a placeholder only when the known reference actually occurs in this source.
        if marker not in document and redact(po_number) != po_number:
            document, count = re.subn(
                rf"(?<![\w-]){re.escape(po_number)}(?![\w-])", marker, document
            )
            masked_po = count > 0
        result = await get_router().run(
            "extract_procurement",
            {"kind": kind, "document": redact(document)},
            call_context(request, p),
        )
    else:
        images = await asyncio.to_thread(render_pages_png, data, 3, 1.5) if pdf else [data]
        parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": "Read the synthetic document images; every field will be reviewed by a person.",
            }
        ]
        for image in images:
            mime = "image/png" if image.startswith(b"\x89PNG") else "image/jpeg"
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"},
                }
            )
        result = await get_router().run(
            "extract_procurement_vision",
            {"kind": kind, "document": "Synthetic page images follow."},
            call_context(request, p),
            extra_messages=[{"role": "user", "content": parts}],
        )
    draft = result.parsed.model_dump(mode="json") if result.parsed else json.loads(result.text)
    if masked_po:
        for field in ("number", "po_number"):
            if draft.get(field) == marker:
                draft[field] = po_number
    return draft, result.public()


@router.get("/cases/{case_id}/documents/{kind}/file")
async def file_for_case(
    case_id: uuid.UUID, kind: Literal["po", "invoice", "receipt"], p: CurrentPrincipal
) -> Response:
    roles, vendor = await actor(p)
    if "vendor" in roles and not vendor:
        raise Forbidden("Vendor identity required")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, vendor)
        did = row["state"]["documents"].get(kind, {}).get("source_document_id")
        doc = (
            await s.execute(
                text("SELECT blob_key,mime FROM ap.documents WHERE id::text=:d"), {"d": did}
            )
        ).first()
    if not doc:
        raise NotFound("No source file attached")
    return Response(
        await get_blob_store().get(doc.blob_key),
        media_type=doc.mime,
        headers={"Cache-Control": "private, no-store"},
    )


async def actor(p: Principal) -> tuple[frozenset[str], str | None]:
    if p.procurement_scope is not None:
        return p.procurement_scope
    # Re-read membership on every operation: revocation does not wait for JWT expiry.
    async with tenant_tx(p.org_id, p.user_id) as s:
        member = (
            await s.execute(
                text("SELECT role,vendor_id FROM ap.procurement_members WHERE user_id=:u"),
                {"u": p.user_id},
            )
        ).first()
    if member:
        return frozenset({member.role}), member.vendor_id
    if p.kind == "jwt":
        async with system_tx() as s:
            row = (
                await s.execute(
                    text('SELECT role FROM auth.member WHERE "userId"=:u AND "organizationId"=:o'),
                    {"u": p.user_id, "o": p.org_id},
                )
            ).first()
        if not row:
            raise Forbidden("Workspace membership required")
        return frozenset(row.role.split(",")), None
    if "vendor" in p.roles:
        raise Forbidden("Vendor access must be assigned by purchasing")
    return p.roles, None


def vendor_matches(column: Column[str], vendor: str, org_id: str) -> ColumnElement[bool]:
    # Demo vendor IDs were typed manually. Existing workspace assignments can distinguish case.
    if org_id == PURCHASING_DEMO_ORG:
        return func.lower(func.btrim(column)) == func.lower(func.btrim(vendor))
    return column == vendor


def visible_to_vendor(p: Principal, vendor: str) -> ColumnElement[bool]:
    columns = procurement_cases.c
    matches = vendor_matches(columns.vendor_id, vendor, p.org_id)
    if p.org_id == PURCHASING_DEMO_ORG:
        return or_(matches, columns.state["demo_vendor_user_id"].astext == p.user_id)
    return matches


async def case_row(
    s: Any, p: Principal, case_id: uuid.UUID, vendor: str | None, lock: bool = False
) -> Any:
    columns = procurement_cases.c
    query = select(procurement_cases).where(columns.id == case_id, columns.org_id == p.org_id)
    if vendor is not None:
        query = query.where(visible_to_vendor(p, vendor))
    if lock:
        query = query.with_for_update()
    row = (await s.execute(query)).mappings().first()
    if not row:
        raise NotFound("Procurement case not found")
    return row


async def save(
    s: Any, p: Principal, case_id: uuid.UUID, state: dict[str, Any], action: str
) -> None:
    await s.execute(
        text("UPDATE ap.procurement_cases SET state=CAST(:state AS jsonb) WHERE id=:id"),
        {"id": case_id, "state": json.dumps(state)},
    )
    await append(
        s,
        p.org_id,
        AuditEvent(
            action=action,
            actor_type="human",
            actor_id=p.user_id,
            target_type="procurement_case",
            target_id=str(case_id),
            output=state,
        ),
    )


class MemberRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Literal["vendor", "purchasing", "receiving", "approver", "finance", "auditor"]
    vendor_id: str | None = Field(default=None, min_length=1, max_length=80)


@router.post("/members")
async def member(body: MemberRequest, p: CurrentPrincipal) -> dict[str, str]:
    roles, _ = await actor(p)
    if "admin" not in roles or p.is_guest:
        raise Forbidden("Only the workspace administrator can assign access")
    if body.role == "vendor" and not body.vendor_id:
        raise Conflict("A vendor identifier is required")
    async with system_tx() as s:
        user = (
            await s.execute(
                text('SELECT id FROM auth."user" WHERE lower(email)=lower(:e)'), {"e": body.email}
            )
        ).first()
        if not user:
            raise NotFound("Ask this person to create an AURA account first")
        if user.id == p.user_id:
            raise Forbidden("Assign other accounts; do not replace your administrator role")
        await s.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"),
            {"k": f"membership:{p.org_id}:{user.id}"},
        )
        await s.execute(
            text(
                'INSERT INTO auth.member (id,"organizationId","userId",role,"createdAt") SELECT :id,:o,:u,:r,now() WHERE NOT EXISTS (SELECT 1 FROM auth.member WHERE "organizationId"=:o AND "userId"=:u)'
            ),
            {"id": str(uuid.uuid4()), "o": p.org_id, "u": user.id, "r": body.role},
        )
        await s.execute(
            text('UPDATE auth.member SET role=:r WHERE "organizationId"=:o AND "userId"=:u'),
            {"r": body.role, "o": p.org_id, "u": user.id},
        )
        await s.execute(
            text(
                "UPDATE core.api_keys SET revoked_at=now() WHERE org_id=:o AND user_id=:u AND revoked_at IS NULL"
            ),
            {"o": p.org_id, "u": user.id},
        )
        await s.execute(
            text(
                "INSERT INTO ap.procurement_members (org_id,user_id,role,vendor_id) VALUES (:o,:u,:r,:v) ON CONFLICT (org_id,user_id) DO UPDATE SET role=excluded.role,vendor_id=excluded.vendor_id"
            ),
            {
                "o": p.org_id,
                "u": user.id,
                "r": body.role,
                "v": body.vendor_id if body.role == "vendor" else None,
            },
        )
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="procurement.access_assigned",
                actor_type="human",
                actor_id=p.user_id,
                target_id=user.id,
                details={"role": body.role, "vendor_id": body.vendor_id},
            ),
        )
    return {"status": "assigned"}


class CreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    vendor_id: str = Field(min_length=1, max_length=80)
    po_number: str = Field(min_length=1, max_length=80)


@router.post("/cases", status_code=201)
async def create(body: CreateRequest, p: CurrentPrincipal) -> dict[str, str]:
    roles, _ = await actor(p)
    if not roles & {"purchasing", "clerk", "admin"}:
        raise Forbidden("Purchasing access required")
    cid = uuid.uuid4()
    state: dict[str, Any] = {
        "status": "collecting_documents",
        "revision": 0,
        "documents": {},
        "evidence": {},
        "approvals": [],
        "payment": None,
        "created_by": p.user_id,
    }
    if p.org_id == PURCHASING_DEMO_ORG:
        state["demo_vendor_user_id"] = f"{p.org_id}-vendor"
    async with tenant_tx(p.org_id, p.user_id) as s:
        inserted = (
            await s.execute(
                text(
                    "INSERT INTO ap.procurement_cases (id,org_id,vendor_id,po_number,state)"
                    " VALUES (:id,:o,:v,:n,CAST(:st AS jsonb))"
                    " ON CONFLICT (org_id,po_number) DO NOTHING RETURNING id"
                ),
                {
                    "id": cid,
                    "o": p.org_id,
                    "v": body.vendor_id,
                    "n": body.po_number,
                    "st": json.dumps(state),
                },
            )
        ).scalar_one_or_none()
        if inserted is None:
            raise Conflict("This PO already has a case")
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="procurement.created",
                actor_type="human",
                actor_id=p.user_id,
                target_id=str(cid),
            ),
        )
    return {"id": str(cid)}


class UpdateCaseRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    po_number: str | None = Field(default=None, min_length=1, max_length=80)
    vendor_id: str | None = Field(default=None, min_length=1, max_length=80)


@router.put("/cases/{case_id}")
async def update_case(
    case_id: uuid.UUID, body: UpdateCaseRequest, p: CurrentPrincipal
) -> dict[str, str]:
    """Correct a case's PO number or vendor before any document is confirmed against it.

    Confirmed documents carry the PO number they were checked against, so the identity of the
    case is fixed from the first confirmation onwards.
    """
    roles, _ = await actor(p)
    if not roles & {"purchasing", "clerk", "admin"}:
        raise Forbidden("Purchasing access required")
    if body.po_number is None and body.vendor_id is None:
        raise AppError("Nothing to change", code="invalid_request", status_code=422)
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, None, True)
        if row["state"].get("documents"):
            raise Conflict(
                "The PO number and vendor are fixed once a document is confirmed",
                code="case_locked",
            )
        po_number = body.po_number or row["po_number"]
        vendor_id = body.vendor_id or row["vendor_id"]
        columns = procurement_cases.c
        if po_number != row["po_number"]:
            taken = (
                await s.execute(
                    select(columns.id).where(
                        columns.org_id == p.org_id,
                        columns.po_number == po_number,
                        columns.id != case_id,
                    )
                )
            ).first()
            if taken:
                raise Conflict("This PO already has a case")
        await s.execute(
            text("UPDATE ap.procurement_cases SET po_number=:n, vendor_id=:v WHERE id=:id"),
            {"id": case_id, "n": po_number, "v": vendor_id},
        )
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="procurement.case_updated",
                actor_type="human",
                actor_id=p.user_id,
                target_type="procurement_case",
                target_id=str(case_id),
                details={
                    "po_number": po_number,
                    "vendor_id": vendor_id,
                    "previous": {"po_number": row["po_number"], "vendor_id": row["vendor_id"]},
                },
            ),
        )
    return {"id": str(case_id), "po_number": po_number, "vendor_id": vendor_id}


@router.get("/cases")
async def cases(
    p: CurrentPrincipal,
    view: Literal["full", "summary"] = "full",
    include_default: bool = False,
) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if "vendor" in roles and not vendor:
        raise Forbidden("No vendor identity assigned")
    columns = procurement_cases.c
    query = (
        select(
            columns.id,
            columns.po_number,
            columns.vendor_id,
            columns.state["status"].astext.label("status"),
        )
        if view == "summary"
        else select(procurement_cases)
    )
    query = query.where(columns.org_id == p.org_id)
    if vendor is not None:
        query = query.where(visible_to_vendor(p, vendor))
    query = query.order_by(columns.created_at.desc(), columns.id.desc()).limit(100)
    default_case = None
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (await s.execute(query)).mappings().all()
        if include_default and view == "summary" and rows:
            try:
                default_case = dict(await case_row(s, p, rows[0]["id"], vendor))
            except NotFound:
                # The case could have been deleted since the list SELECT.
                rows = rows[1:]
    visible_cases = [dict(row) for row in rows]
    if view == "full":
        await decorate_cases(visible_cases)
    if default_case is not None:
        await decorate_cases([default_case])
        default_case["can_delete"] = can_delete_case(p, roles, default_case["state"])
    result: dict[str, Any] = {"roles": sorted(roles), "vendor_id": vendor, "cases": visible_cases}
    if include_default:
        result["default_case"] = default_case
    return result


@router.get("/cases/{case_id}")
async def get_case(case_id: uuid.UUID, p: CurrentPrincipal) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if "vendor" in roles and not vendor:
        raise Forbidden("No vendor identity assigned")
    async with tenant_tx(p.org_id, p.user_id) as s:
        case = dict(await case_row(s, p, case_id, vendor))
    await decorate_cases([case])
    case["can_delete"] = can_delete_case(p, roles, case["state"])
    return case


def can_delete_case(p: Principal, roles: frozenset[str], state: dict[str, Any]) -> bool:
    return (
        not state.get("payment")
        and state.get("status") != "paid"
        and (
            "admin" in roles
            or (bool(roles & {"purchasing", "clerk"}) and state.get("created_by") == p.user_id)
        )
    )


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(
    case_id: uuid.UUID, p: CurrentPrincipal, revision: int = Query(ge=0)
) -> Response:
    roles, _ = await actor(p)
    if not roles & {"purchasing", "clerk", "admin"}:
        raise Forbidden("Only the case creator or a workspace administrator can delete cases")
    async with tenant_tx(p.org_id, p.user_id) as s:
        case = await case_row(s, p, case_id, None, lock=True)
        state = case["state"]
        if state.get("payment") or state.get("status") == "paid":
            raise Conflict("Paid cases are part of payment history and cannot be deleted")
        if not can_delete_case(p, roles, state):
            raise Forbidden(
                "Only the case creator or a workspace administrator can delete this case"
            )
        if state["revision"] != revision:
            raise Conflict(
                "The evidence changed. Review the case before deleting.", code="revision_changed"
            )
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="procurement.deleted",
                actor_type="human",
                actor_id=p.user_id,
                target_type="procurement_case",
                target_id=str(case_id),
                details={"po_number": case["po_number"], "vendor_id": case["vendor_id"]},
                output=state,
            ),
        )
        await s.execute(
            procurement_cases.delete().where(
                procurement_cases.c.id == case_id, procurement_cases.c.org_id == p.org_id
            )
        )
    return Response(status_code=204)


async def decorate_cases(visible_cases: list[dict[str, Any]]) -> None:
    for case in visible_cases:
        case["email_send_blocker"] = delivery_blocker(case["org_id"])
        state = case["state"]
        notification = state.get("notification")
        if (
            notification
            and notification["status"] in {"preview", "pending", "failed"}
            and state.get("payment")
        ):
            subject, body = payment_message(
                {
                    "invoice_number": state["documents"]["invoice"]["number"],
                    "po_number": case["po_number"],
                    "payment": state["payment"],
                }
            )
            notification.update(subject=subject, body=body)
    history = [
        entry
        for case in visible_cases
        for entry in [*case["state"].get("approvals", []), case["state"].get("payment")]
        if entry and entry.get("actor")
    ]
    if history:
        # Resolve names only for history on cases already filtered by tenant and vendor.
        async with system_tx() as s:
            users = await s.execute(
                text('SELECT id, name FROM auth."user" WHERE id = ANY(:ids)'),
                {"ids": sorted({entry["actor"] for entry in history})},
            )
            names = {user.id: user.name.strip() for user in users if user.name}
        for entry in history:
            entry["actor_name"] = names.get(entry["actor"]) or None


@router.put("/cases/{case_id}/documents/{kind}")
async def document(
    case_id: uuid.UUID,
    kind: Literal["po", "invoice", "receipt"],
    body: EvidenceDocument,
    p: CurrentPrincipal,
    revision: int | None = Query(default=None, ge=0),
) -> dict[str, Any]:
    roles, vendor = await actor(p)
    allowed = {
        "po": {"purchasing", "clerk", "admin"},
        "invoice": {"vendor", "clerk", "admin"},
        "receipt": {"receiving", "purchasing", "clerk", "admin"},
    }
    if not roles & allowed[kind] or ("vendor" in roles and not vendor):
        raise Forbidden("This role cannot supply this document")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, vendor, True)
        state: dict[str, Any] = row["state"]
        if state["payment"]:
            raise Conflict("Paid cases cannot be edited")
        if revision is not None and state["revision"] != revision:
            raise Conflict(
                "Documents changed. Review the latest evidence before saving.",
                code="revision_changed",
            )
        if body.po_number != row["po_number"]:
            raise Conflict("Document PO number differs from this case")
        if kind == "invoice":
            if body.total_minor <= 0:
                raise Conflict("The invoice total must be greater than zero")
            # Serialize duplicate invoice checks across different POs for the same vendor.
            vendor_id = row["vendor_id"]
            vendor_key = vendor_id.strip().lower() if p.org_id == PURCHASING_DEMO_ORG else vendor_id
            key = f"{p.org_id}:{vendor_key}:{body.number.upper()}"
            await s.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"), {"k": key}
            )
            columns = procurement_cases.c
            duplicate = (
                await s.execute(
                    select(columns.id)
                    .where(
                        columns.org_id == p.org_id,
                        vendor_matches(columns.vendor_id, vendor_id, p.org_id),
                        columns.id != case_id,
                        func.upper(
                            func.btrim(columns.state["documents"]["invoice"]["number"].astext)
                        )
                        == body.number.upper(),
                    )
                    .limit(1),
                )
            ).first()
            if duplicate:
                raise Conflict(
                    "This vendor invoice number is already attached to another PO",
                    code="duplicate_invoice",
                )
        if body.source_document_id:
            old_source = state["documents"].get(kind, {}).get("source_document_id")
            source_allowed = (
                await s.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM ap.documents d"
                        " WHERE d.id::text=:d AND ("
                        " d.id::text=:old"
                        " OR EXISTS (SELECT 1 FROM ap.procurement_uploads s"
                        " WHERE s.case_id=:c AND s.kind=:k AND s.user_id=:u AND s.document_id=d.id)))"
                    ),
                    {
                        "d": body.source_document_id,
                        "u": p.user_id,
                        "old": old_source,
                        "c": case_id,
                        "k": kind,
                    },
                )
            ).scalar_one()
            if not source_allowed:
                raise Forbidden("Upload the source file in this document section before confirming")
        state["documents"][kind] = body.model_dump(mode="json")
        state["evidence"][kind] = {"actor": p.user_id, "at": datetime.now(UTC).isoformat()}
        state["revision"] += 1
        state["approvals"] = []
        state.pop("correction", None)
        result = compare(state["documents"])
        state["comparison"] = result
        state["status"] = (
            "awaiting_l1"
            if result["matched"]
            else "collecting_documents"
            if result["missing"]
            else "needs_correction"
        )
        await save(s, p, case_id, state, "procurement.document_confirmed")
    return state


class ReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    revision: int = Field(strict=True, ge=1)
    action: Literal["l1", "finance", "reject"]
    comment: str = Field(min_length=1, max_length=2000)


@router.post("/cases/{case_id}/review")
async def review(case_id: uuid.UUID, body: ReviewRequest, p: CurrentPrincipal) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if vendor or "vendor" in roles:
        raise Forbidden("Vendors cannot approve")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, None, True)
        state: dict[str, Any] = row["state"]
        if state["revision"] != body.revision:
            raise Conflict("Documents changed; refresh the evidence", code="revision_changed")
        state = transition(state, body.action, p.user_id, roles, body.comment)
        await save(s, p, case_id, state, "procurement." + body.action)
    return state


class PaidRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    revision: int = Field(strict=True, ge=1)
    reference: str = Field(min_length=1, max_length=100)
    date: date
    amount_minor: int = Field(strict=True, gt=0, le=100000000000)


@router.post("/cases/{case_id}/paid")
async def paid(case_id: uuid.UUID, body: PaidRequest, p: CurrentPrincipal) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if vendor or not roles & {"finance", "controller"}:
        raise Forbidden("Finance access required")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, None, True)
        state: dict[str, Any] = row["state"]
        payment = {
            "reference": body.reference,
            "date": body.date.isoformat(),
            "amount_minor": body.amount_minor,
            "revision": body.revision,
        }
        if state["payment"]:
            if all(state["payment"].get(k) == v for k, v in payment.items()):
                return state
            raise Conflict("Payment already recorded with different details")
        if state["status"] != "approved_for_payment" or state["revision"] != body.revision:
            raise Conflict("Both current approvals are required")
        if (
            body.date > date.today()
            or body.amount_minor != state["documents"]["invoice"]["total_minor"]
        ):
            raise Conflict("Payment date or amount is invalid")
        members = procurement_members.c
        recipient_scope = vendor_matches(members.vendor_id, row["vendor_id"], p.org_id)
        if p.org_id == PURCHASING_DEMO_ORG and (demo_vendor := state.get("demo_vendor_user_id")):
            recipient_scope = or_(recipient_scope, members.user_id == demo_vendor)
        recipients = (
            await s.execute(
                select(members.user_id).where(
                    members.org_id == p.org_id,
                    members.role == "vendor",
                    recipient_scope,
                )
            )
        ).all()
        if not recipients:
            raise Conflict("Assign the vendor login before recording payment")
        payment.update(
            {
                "actor": p.user_id,
                "recorded_at": datetime.now(UTC).isoformat(),
                "simulated": True,
                "currency": state["documents"]["invoice"]["currency"],
            }
        )
        state["payment"] = payment
        state["status"] = "paid"
        blocker = delivery_blocker(p.org_id)
        state["notification"] = {
            "status": "preview" if blocker else "pending",
            "event_id": f"procurement-paid:{case_id}",
        }
        if blocker:
            state["notification"]["notice"] = blocker
        await s.execute(
            text(
                "INSERT INTO ops.outbox (org_id,topic,payload) VALUES (:o,'procurement.payment_email',CAST(:p AS jsonb))"
            ),
            {
                "o": p.org_id,
                "p": json.dumps(
                    {
                        "case_id": str(case_id),
                        "vendor_id": row["vendor_id"],
                        "recipients": [r.user_id for r in recipients],
                        "invoice_number": state["documents"]["invoice"]["number"],
                        "po_number": row["po_number"],
                        "payment": payment,
                    }
                ),
            },
        )
        await save(s, p, case_id, state, "procurement.paid")
    return state


@router.post("/cases/{case_id}/notification/retry", include_in_schema=False)
@router.post("/cases/{case_id}/notification/send")
async def send_notification(case_id: uuid.UUID, p: CurrentPrincipal) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if vendor or not roles & {"finance", "controller", "admin"}:
        raise Forbidden("Finance access required")
    async with tenant_tx(p.org_id, p.user_id) as s:
        case = await case_row(s, p, case_id, None)
        if not case["state"].get("payment"):
            raise Conflict("Record the simulated payment before sending email")
    if blocker := delivery_blocker(p.org_id):
        raise Conflict(blocker, code="gmail_unavailable")
    return await dispatch(p.org_id, case_id)
