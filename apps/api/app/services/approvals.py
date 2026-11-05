"""Human approval decisions (§B6 human_approval, §B18 human approval rows).

- Row lock on the pending approval: the first decision wins, a concurrent second gets 409.
- SoD, role and amount limit are checked at decision time (never cached from assignment time).
- Bank-detail changes require a documented call-back checkbox.
- An approval yields a signed, single-use token bound to run_id + step + approver + amount.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.audit.chain import AuditEvent, append
from app.core.config import get_settings
from app.core.db import tenant_tx
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.domain.approval import Level
from app.domain.sod import Approver, InvoiceParties, check_sod
from app.tools.gateway import ToolContext, call_tool

FX = {"USD": Decimal("1"), "EUR": Decimal("1.08"), "INR": Decimal("0.012"), "GBP": Decimal("1.27")}

# Demo personas (§B16): one guest can walk the whole flow; SoD still applies between personas.
PERSONAS: dict[str, dict[str, Any]] = {
    "rahul": {"id": "persona:rahul", "name": "Rahul (AP clerk)", "roles": frozenset({"clerk"}), "limit_minor": None},
    "priya": {"id": "persona:priya", "name": "Priya (approver)", "roles": frozenset({"approver"}), "limit_minor": 1_000_000},
    "meera": {"id": "persona:meera", "name": "Meera (controller)", "roles": frozenset({"controller"}), "limit_minor": None},
}


@dataclass(frozen=True)
class Actor:
    user_id: str
    roles: frozenset[str]
    name: str
    limit_minor: int | None = None


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def sign_token(claims: dict[str, Any]) -> str:
    """Same format the ERP verifies: v1.<b64 json>.<b64 hmac-sha256>."""
    s = get_settings().approval_token_secret
    secret = s.get_secret_value() if s else ""
    if not secret:
        raise AppError("Approval signing is not configured", code="approval_unconfigured", status_code=503)
    body = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"v1.{body}.{sig}"


async def _parties(org_id: str, run_id: str, vendor_id: str | None) -> InvoiceParties:
    async with tenant_tx(org_id) as s:
        row = (await s.execute(text(
            "SELECT r.started_by, d.uploaded_by FROM ap.runs r JOIN ap.documents d ON d.id = r.document_id WHERE r.id = :r"),
            {"r": run_id})).mappings().one()
    bank_editor = creator = None
    if vendor_id:
        ctx = ToolContext(org_id=org_id, actor_id="system:approvals", roles=frozenset({"system"}), agent="invoice_to_pay", run_id=run_id)
        banks = await call_tool("get_vendor_bank_accounts", {"vendor_id": vendor_id}, ctx)
        bank_editor = (banks.get("current") or {}).get("changed_by")
        creator = (await call_tool("get_vendor", {"vendor_id": vendor_id}, ctx)).get("created_by")
    return InvoiceParties(preparer_id=row["started_by"], uploader_id=row["uploaded_by"],
                          vendor_bank_last_editor_id=bank_editor, vendor_created_by=None if creator is None else creator)


async def check_actor(org_id: str, run_id: str, actor: Actor) -> dict[str, Any]:
    """What the UI shows before acting: allowed or the list of SoD reasons (server enforces anyway)."""
    async with tenant_tx(org_id) as s:
        ap = (await s.execute(text(
            "SELECT step, required_role, packet, status FROM ap.approvals WHERE run_id=:r ORDER BY step DESC LIMIT 1"),
            {"r": run_id})).mappings().first()
    if not ap:
        raise NotFound("No approval for this run")
    pk = ap["packet"]
    base = int(Decimal(pk.get("total_minor") or 0) * FX.get(pk.get("currency") or "USD", Decimal(1)))
    parties = await _parties(org_id, run_id, pk.get("vendor_id"))
    v = check_sod(Approver(actor.user_id, actor.roles, actor.limit_minor), parties, Level(ap["required_role"]), base)
    return {"allowed": not v and ap["status"] == "pending", "status": ap["status"],
            "violations": [{"code": x.code, "message": x.message} for x in v], "required_role": ap["required_role"]}


async def decide(org_id: str, run_id: str, actor: Actor, *, decision: str, comment: str | None,
                 callback_verified: bool, packet_hash: str | None) -> dict[str, Any]:
    if decision not in ("approve", "reject", "request_info"):
        raise AppError("decision must be approve, reject or request_info", code="invalid_decision", status_code=422)
    async with tenant_tx(org_id, actor.user_id) as s:
        ap = (await s.execute(text(
            "SELECT id, step, required_role, packet_hash, packet, status FROM ap.approvals WHERE run_id=:r"
            " ORDER BY step DESC LIMIT 1 FOR UPDATE"), {"r": run_id})).mappings().first()
        if not ap:
            raise NotFound("No approval for this run")
        if ap["status"] != "pending":
            raise Conflict("This approval was already decided by someone else", code="already_decided")
        if packet_hash and packet_hash != ap["packet_hash"]:
            raise Conflict("The invoice facts changed since you opened it; reload and review again", code="packet_changed")
        pk = ap["packet"]
        base = int(Decimal(pk.get("total_minor") or 0) * FX.get(pk.get("currency") or "USD", Decimal(1)))
        parties = await _parties(org_id, run_id, pk.get("vendor_id"))
        viol = check_sod(Approver(actor.user_id, actor.roles, actor.limit_minor), parties, Level(ap["required_role"]), base)
        if decision != "approve":
            viol = [v for v in viol if v.code not in ("SOD_LIMIT",)]  # anyone eligible may reject/ask
        if viol:
            await append(s, org_id, AuditEvent(action="approval.denied", actor_type="human", actor_id=actor.user_id, run_id=run_id,
                                               decision="denied", details={"violations": [v.code for v in viol]}))
            raise Forbidden("Segregation of duties: " + "; ".join(v.message for v in viol), code="sod_violation",
                            details={"violations": [{"code": v.code, "message": v.message} for v in viol]})
        if decision == "approve" and "BANK_ACCOUNT_MISMATCH" in pk.get("flags", []) and not callback_verified:
            raise AppError("Bank details changed: confirm the documented call-back to the vendor first",
                           code="callback_required", status_code=422)
        if decision != "approve" or pk.get("flags"):
            if not comment or len(comment.strip()) < 3:
                raise AppError("A comment is required for this decision", code="comment_required", status_code=422)
        jti = uuid.uuid4().hex if decision == "approve" else None
        await s.execute(text(
            "UPDATE ap.approvals SET status='decided', decision=:d, comment=:c, callback_verified=:cb, decided_by=:u,"
            " decided_at=now(), token_jti=:j WHERE id=:id"),
            {"d": decision, "c": (comment or "")[:2000], "cb": callback_verified, "u": actor.user_id, "j": jti, "id": ap["id"]})
        await append(s, org_id, AuditEvent(action="approval.decided", actor_type="human", actor_id=actor.user_id, run_id=run_id,
                                           decision=decision, input={"packet_hash": ap["packet_hash"]},
                                           details={"step": ap["step"], "comment": (comment or "")[:500],
                                                    "callback_verified": callback_verified, "actor_name": actor.name},
                                           evidence_refs=[{"type": "approval_packet", "hash": ap["packet_hash"]}]))
    token = None
    if decision == "approve":
        token = sign_token({"run_id": run_id, "step": ap["step"], "approver_id": actor.user_id, "jti": jti,
                            "amount_minor": int(pk.get("total_minor") or 0), "exp": int(time.time()) + 3600})
    return {"decision": decision, "approver_id": actor.user_id, "comment": comment, "callback_verified": callback_verified,
            "step": ap["step"], "token": token}
