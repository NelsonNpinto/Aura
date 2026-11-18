"""Copilot tools (§B7), all executed through the gateway.

Everything here is read-only except `start_invoice_run`, which never acts without an explicit
confirmation from the user. SQL goes through named templates over RLS-protected, read-only
views, so a generated string can never widen the tenant scope.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.auth import Principal
from app.core.db import tenant_tx
from app.graph import service as graph_service
from app.rag.service import search_for_copilot
from app.tools.gateway import register_local

# ---------------------------------------------------------------- SQL templates (read-only)
# Each template is a fixed statement with bound parameters, run inside the caller's RLS
# transaction. There is no free-form SQL path.
SQL_TEMPLATES: dict[str, dict[str, Any]] = {
    "spend_by_vendor": {
        "description": "Total posted spend per vendor, newest period first.",
        "params": ["since"],
        "sql": (
            "SELECT vendor_id, vendor_name, currency, count(*) AS invoices,"
            " sum(total_minor) AS total_minor FROM ap.invoices"
            " WHERE status IN ('posted','auto') AND (CAST(:since AS date) IS NULL OR invoice_date >= :since)"
            " GROUP BY vendor_id, vendor_name, currency"
            " ORDER BY sum(total_minor) DESC LIMIT 50"
        ),
    },
    "invoices_by_status": {
        "description": "Invoice counts and totals by status.",
        "params": [],
        "sql": (
            "SELECT status, count(*) AS invoices, sum(total_minor) AS total_minor"
            " FROM ap.invoices GROUP BY status ORDER BY count(*) DESC LIMIT 20"
        ),
    },
    "open_exceptions": {
        "description": "Open exceptions with their type and reason.",
        "params": [],
        "sql": (
            "SELECT e.id, e.run_id, e.type, e.status, e.reason, e.created_at"
            " FROM ap.exceptions e WHERE e.status <> 'resolved'"
            " ORDER BY e.created_at DESC LIMIT 50"
        ),
    },
    "pending_approvals": {
        "description": "Approvals still awaiting a decision.",
        "params": [],
        "sql": (
            "SELECT a.run_id, a.step, a.required_role, a.status, a.created_at,"
            " i.invoice_number, i.vendor_name, i.total_minor, i.currency"
            " FROM ap.approvals a LEFT JOIN ap.invoices i ON i.run_id = a.run_id"
            " WHERE a.status = 'pending' ORDER BY a.created_at LIMIT 50"
        ),
    },
    "invoice_by_number": {
        "description": "Look up one invoice by its number.",
        "params": ["invoice_number"],
        "sql": (
            "SELECT id, run_id, invoice_number, vendor_id, vendor_name, total_minor, currency,"
            " invoice_date, status, route, risk_level FROM ap.invoices"
            " WHERE invoice_number = :invoice_number ORDER BY created_at DESC LIMIT 5"
        ),
    },
    "flags_by_code": {
        "description": "How often each flag was raised.",
        "params": [],
        "sql": (
            "SELECT code, severity, count(*) AS raised FROM ap.flags"
            " GROUP BY code, severity ORDER BY count(*) DESC LIMIT 30"
        ),
    },
}


def sql_catalog() -> list[dict[str, Any]]:
    return [
        {"name": k, "description": v["description"], "params": v["params"]}
        for k, v in SQL_TEMPLATES.items()
    ]


def _jsonable(rows: list[Any]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        row = {}
        for k, v in dict(r).items():
            row[k] = v.isoformat() if hasattr(v, "isoformat") else (str(v) if _is_uuid(v) else v)
        out.append(row)
    return out


def _is_uuid(v: Any) -> bool:
    return type(v).__name__ == "UUID"


# ---------------------------------------------------------------- executors
async def _search_policies(org_id: str, args: dict[str, Any]) -> dict[str, Any]:
    principal = Principal(args.get("_user_id") or "copilot", org_id, frozenset({"auditor"}))
    hits = await search_for_copilot(
        principal,
        args["query"],
        doc_types=args.get("doc_types"),
    )
    return {
        "passages": [
            {
                "chunk_id": h.chunk_id,
                "filename": h.filename,
                "heading": h.heading,
                "page": h.page,
                "doc_type": h.doc_type,
                "text": h.text[:1200],
            }
            for h in hits[:5]
        ]
    }


async def _graph_query(org_id: str, args: dict[str, Any]) -> dict[str, Any]:
    return await graph_service.explore_template(org_id, args["template"], args.get("params") or {})


async def _sql_query(org_id: str, args: dict[str, Any]) -> dict[str, Any]:
    tpl = SQL_TEMPLATES.get(args["template"])
    if tpl is None:
        return {
            "error": {
                "code": "unknown_template",
                "message": f"Unknown template. Known: {', '.join(SQL_TEMPLATES)}",
            }
        }
    given = args.get("params") or {}
    bound = {name: given.get(name) for name in tpl["params"]}
    async with tenant_tx(org_id) as s:
        rows = (await s.execute(text(tpl["sql"]), bound)).mappings().all()
    return {"template": args["template"], "rows": _jsonable(list(rows))}


async def _list_invoices(org_id: str, args: dict[str, Any]) -> dict[str, Any]:
    async with tenant_tx(org_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT id, run_id, invoice_number, vendor_id, vendor_name, total_minor,"
                        " currency, invoice_date, status, route, risk_level FROM ap.invoices"
                        " WHERE (CAST(:st AS text) IS NULL OR status = :st)"
                        " AND (CAST(:v AS text) IS NULL OR vendor_id = :v)"
                        " ORDER BY created_at DESC LIMIT :lim"
                    ),
                    {
                        "st": args.get("status"),
                        "v": args.get("vendor_id"),
                        "lim": min(int(args.get("limit") or 20), 50),
                    },
                )
            )
            .mappings()
            .all()
        )
    return {"invoices": _jsonable(list(rows))}


async def _get_invoice(org_id: str, args: dict[str, Any]) -> dict[str, Any]:
    async with tenant_tx(org_id) as s:
        inv = (
            (
                await s.execute(
                    text(
                        "SELECT * FROM ap.invoices WHERE id::text = :i OR invoice_number = :i"
                        " ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"i": args["invoice"]},
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
                        "SELECT code, severity, message, evidence FROM ap.flags WHERE run_id = :r"
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
                        "SELECT line_no, description, quantity, unit_price_minor, amount_minor,"
                        " gl_account, cost_center, match_outcome FROM ap.invoice_lines"
                        " WHERE invoice_id = :i ORDER BY line_no"
                    ),
                    {"i": inv["id"]},
                )
            )
            .mappings()
            .all()
        )
    return {
        "invoice": _jsonable([inv])[0],
        "flags": _jsonable(list(flags)),
        "lines": _jsonable(list(lines)),
    }


async def _explain_decision(org_id: str, args: dict[str, Any]) -> dict[str, Any]:
    from app.audit.chain import verify

    async with tenant_tx(org_id) as s:
        events = (
            (
                await s.execute(
                    text(
                        "SELECT seq, ts, actor_type, actor_id, action, decision, tool,"
                        " evidence_refs, details FROM audit.audit_events WHERE run_id = :r"
                        " ORDER BY seq LIMIT 200"
                    ),
                    {"r": args["run_id"]},
                )
            )
            .mappings()
            .all()
        )
        verification = await verify(s, org_id, run_id=args["run_id"])
    return {"events": _jsonable(list(events)), "chain": verification.public()}


async def _start_invoice_run(org_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """Write tool: never acts without an explicit confirmation (§B7 human-in-the-loop)."""
    if not args.get("confirm"):
        return {
            "status": "confirmation_required",
            "message": (
                "Starting a run costs demo budget and writes audit events. Ask the user to "
                "confirm, then call again with confirm=true."
            ),
            "document_id": args.get("document_id"),
        }
    return {
        "status": "start_in_app",
        "message": (
            "Confirmed. Start the run from the invoice inbox so it streams live and is charged "
            "to your demo budget."
        ),
        "document_id": args.get("document_id"),
    }


def register_copilot_tools() -> None:
    register_local("search_policies", _search_policies)
    register_local("graph_query", _graph_query)
    register_local("sql_query", _sql_query)
    register_local("list_invoices", _list_invoices)
    register_local("get_invoice", _get_invoice)
    register_local("explain_decision", _explain_decision)
    register_local("start_invoice_run", _start_invoice_run)
