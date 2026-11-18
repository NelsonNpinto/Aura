"""AURA MCP server (§B9) — stateless Streamable HTTP, mounted at /mcp.

The same services run with the caller's identity and permissions: every tool resolves a
Principal from the request's API key, and read tools go through the same org-scoped queries the
web app uses. The one write tool, `approve_invoice`, requires the approver's own identity, the
server-side segregation-of-duties check, and explicit confirmation:

  * hosts that support elicitation are asked to confirm before anything is decided;
  * hosts without elicitation get a link to confirm in the AURA web app (§B18) — the tool never
    approves on its own.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import text

from app.core.auth import Principal, verify_api_key
from app.core.config import get_settings
from app.core.db import tenant_tx
from app.core.errors import AppError, Unauthorized
from app.core.logging import get_logger

log = get_logger("mcp_server")

mcp = FastMCP(
    "aura",
    instructions=(
        "AURA — auditable finance operations. Read invoices, explain decisions with their audit "
        "lineage, and ask the finance copilot. Data is synthetic. Approvals require the "
        "approver's own API key and explicit confirmation."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    # Host-header checks protect local servers exposed to browsers; this sits behind API keys.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _principal(ctx: Context[Any, Any]) -> Principal:
    req = ctx.request_context.request
    if req is None:
        raise Unauthorized("No request context")
    key = req.headers.get("x-api-key") or ""
    auth = req.headers.get("authorization", "")
    if not key and auth.lower().startswith("bearer "):
        key = auth[7:].strip()
    if not key:
        raise Unauthorized("An AURA API key is required (x-api-key)")
    return await verify_api_key(key)


def _err(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, AppError):
        return {"error": {"code": exc.code, "message": exc.message}}
    log.error("mcp.tool_failed", error=type(exc).__name__)
    return {"error": {"code": "internal_error", "message": type(exc).__name__}}


@mcp.tool(description="List invoices for the caller's workspace, newest first.")
async def list_invoices(
    ctx: Context[Any, Any], status: str | None = None, vendor_id: str | None = None, limit: int = 20
) -> dict[str, Any]:
    try:
        p = await _principal(ctx)
        async with tenant_tx(p.org_id, p.user_id) as s:
            rows = (
                (
                    await s.execute(
                        text(
                            "SELECT i.id, i.invoice_number, i.vendor_id, i.vendor_name,"
                            " i.total_minor, i.currency, i.invoice_date, i.status, i.route,"
                            " i.risk_level, i.run_id FROM ap.invoices i"
                            " WHERE (CAST(:st AS text) IS NULL OR i.status = :st)"
                            "   AND (CAST(:v AS text) IS NULL OR i.vendor_id = :v)"
                            " ORDER BY i.created_at DESC LIMIT :lim"
                        ),
                        {"st": status, "v": vendor_id, "lim": max(1, min(limit, 100))},
                    )
                )
                .mappings()
                .all()
            )
        return {
            "invoices": [
                {k: str(v) if k in ("id", "run_id") else v for k, v in r.items()} for r in rows
            ]
        }
    except Exception as exc:
        return _err(exc)


@mcp.tool(description="One invoice with its flags, match outcome and approval state.")
async def get_invoice(ctx: Context[Any, Any], invoice_id: str) -> dict[str, Any]:
    try:
        p = await _principal(ctx)
        async with tenant_tx(p.org_id, p.user_id) as s:
            inv = (
                (
                    await s.execute(
                        text("SELECT * FROM ap.invoices WHERE id = :i"), {"i": invoice_id}
                    )
                )
                .mappings()
                .first()
            )
            if inv is None:
                return {"error": {"code": "not_found", "message": "invoice not found"}}
            flags = (
                (
                    await s.execute(
                        text(
                            "SELECT code, severity, message FROM ap.flags WHERE run_id = :r"
                            " ORDER BY severity DESC"
                        ),
                        {"r": inv["run_id"]},
                    )
                )
                .mappings()
                .all()
            )
            lines = (
                (
                    await s.execute(
                        text(
                            "SELECT line_no, description, quantity, unit_price_minor,"
                            " amount_minor, gl_account, cost_center, match_outcome"
                            " FROM ap.invoice_lines WHERE invoice_id = :i ORDER BY line_no"
                        ),
                        {"i": invoice_id},
                    )
                )
                .mappings()
                .all()
            )
        return {
            "invoice": {
                k: str(v) if k in ("id", "run_id", "document_id") else v for k, v in inv.items()
            },
            "flags": [dict(f) for f in flags],
            "lines": [dict(ln) for ln in lines],
        }
    except Exception as exc:
        return _err(exc)


@mcp.tool(
    description="Why a run decided what it did: audit lineage, flags, evidence and chain status."
)
async def explain_decision(ctx: Context[Any, Any], run_id: str) -> dict[str, Any]:
    try:
        p = await _principal(ctx)
        from app.audit.chain import verify

        async with tenant_tx(p.org_id, p.user_id) as s:
            events = (
                (
                    await s.execute(
                        text(
                            "SELECT seq, ts, actor_type, actor_id, action, decision, tool,"
                            " evidence_refs, details FROM audit.audit_events"
                            " WHERE run_id = :r ORDER BY seq"
                        ),
                        {"r": run_id},
                    )
                )
                .mappings()
                .all()
            )
            verification = await verify(s, p.org_id, run_id=run_id)
        return {
            "run_id": run_id,
            "events": [{**dict(e), "ts": e["ts"].isoformat()} for e in events],
            "chain": verification.public(),
        }
    except Exception as exc:
        return _err(exc)


@mcp.tool(description="Ask the finance copilot a question. Answers cite their evidence.")
async def ask_copilot(ctx: Context[Any, Any], question: str) -> dict[str, Any]:
    try:
        p = await _principal(ctx)
        from app.agents.copilot.agent import run_copilot
        from app.llm.router import CallContext

        result = await run_copilot(
            p, question, CallContext(org_id=p.org_id, user_id=p.user_id, internal_job=True)
        )
        return {
            "answer": result["answer"],
            "citations": result.get("sources", []),
            "citation_valid": result.get("citation_valid"),
        }
    except Exception as exc:
        return _err(exc)


@mcp.tool(
    description=(
        "Approve or reject an invoice awaiting approval, as the API key's own user. Confirmation "
        "is always required: the host is asked to confirm, or a link to confirm in AURA is "
        "returned. Segregation of duties is enforced server-side."
    )
)
async def approve_invoice(
    ctx: Context[Any, Any], run_id: str, decision: str, comment: str, confirm: bool = False
) -> dict[str, Any]:
    try:
        p = await _principal(ctx)
        if decision not in ("approve", "reject"):
            return {"error": {"code": "bad_request", "message": "decision must be approve|reject"}}
        if len(comment.strip()) < 3:
            return {"error": {"code": "bad_request", "message": "a comment is required"}}
        web = get_settings().web_origin.rstrip("/")
        link = f"{web}/app/approvals?run={run_id}"
        if not confirm:
            confirmed = await _elicit_confirmation(ctx, run_id, decision)
            if confirmed is None:
                return {
                    "status": "confirmation_required",
                    "message": (
                        "This host cannot ask for confirmation. Open the approval in AURA and "
                        "confirm there; nothing has been decided."
                    ),
                    "confirm_url": link,
                }
            if not confirmed:
                return {"status": "cancelled", "message": "Not approved. Nothing was decided."}

        from app.services.approvals import resume_with_decision

        outcome = await resume_with_decision(
            p, run_id=run_id, decision=decision, comment=comment, source="mcp"
        )
        return {"status": "recorded", "run_id": run_id, "decision": decision, **outcome}
    except Exception as exc:
        return _err(exc)


async def _elicit_confirmation(ctx: Context[Any, Any], run_id: str, decision: str) -> bool | None:
    """Ask the host to confirm. None means the host has no elicitation support."""
    elicit = getattr(ctx, "elicit", None)
    if elicit is None:
        return None
    try:
        from pydantic import BaseModel

        class Confirm(BaseModel):
            confirmed: bool

        result = await elicit(
            message=f"Confirm you want to {decision} run {run_id} in AURA.", schema=Confirm
        )
    except Exception:
        return None
    action = getattr(result, "action", None)
    if action != "accept":
        return False
    data = getattr(result, "data", None)
    return bool(getattr(data, "confirmed", False))


@mcp.prompt(description="Month-end accounts-payable summary for the caller's workspace.")
def month_end_summary(month: str) -> str:
    return (
        f"Summarise AURA accounts payable for {month}. Use list_invoices to gather the month's "
        "invoices, group them by status and route, call out every HIGH-severity flag, and use "
        "explain_decision for anything that was auto-posted above the auto-approve limit. "
        "Cite invoice numbers and run ids for every claim; say so plainly if the data does not "
        "support a statement."
    )


@mcp.resource("aura://approval-matrix", description="Approval matrix in force for the demo org")
def approval_matrix() -> str:
    from app.domain.approval import ApprovalMatrix

    m = ApprovalMatrix()
    return json.dumps(
        {
            "auto_limit_minor": m.auto_limit_minor,
            "approver_limit_minor": m.approver_limit_minor,
            "currency": m.currency,
            "bank_change": "controller + documented call-back verification",
        }
    )
