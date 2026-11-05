"""Mock ERP service: REST (seeding, UI, demo helpers) + stateless Streamable HTTP MCP server.

Auth: each request carries `X-Org-Id` and `Authorization: Bearer <token>` where
token = HMAC-SHA256(ERP_SERVICE_TOKEN, org_id). One service token per org, derived from one
root secret so nothing per-org has to be stored.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from erp_mock import tools


def org_token(org_id: str) -> str:
    root = os.environ.get("ERP_SERVICE_TOKEN", "")
    return hmac.new(root.encode(), org_id.encode(), hashlib.sha256).hexdigest()


def _check(org_id: str | None, auth: str | None) -> str:
    if not org_id or not auth or not auth.startswith("Bearer "):
        raise HTTPException(401, "missing org or token")
    if not os.environ.get("ERP_SERVICE_TOKEN") or not hmac.compare_digest(auth[7:], org_token(org_id)):
        raise HTTPException(401, "invalid service token")
    return org_id


mcp = FastMCP(
    "aura-erp",
    instructions="Mock ERP for the AURA demo. Synthetic data only. Tools are tenant-scoped by the caller's org.",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    # Host-header checks are for local servers exposed to browsers; this sits behind auth.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _org(ctx: Context) -> str:
    req = ctx.request_context.request
    if req is None:
        raise PermissionError("no request")
    return _check(req.headers.get("x-org-id"), req.headers.get("authorization"))


async def _run(ctx: Context, name: str, **args: Any) -> dict[str, Any]:
    try:
        return await tools.call(name, _org(ctx), args)
    except tools.ErpError as e:
        return {"error": {"code": e.code, "message": e.message}}


@mcp.tool(description="Search vendors by tax ID (exact, normalised) or by fuzzy name/alias.")
async def search_vendors(ctx: Context, query: str | None = None, tax_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    return await _run(ctx, "search_vendors", query=query, tax_id=tax_id, limit=min(max(limit, 1), 20))


@mcp.tool(description="Get a vendor master record.")
async def get_vendor(ctx: Context, vendor_id: str) -> dict[str, Any]:
    return await _run(ctx, "get_vendor", vendor_id=vendor_id)


@mcp.tool(description="Vendor bank accounts: hashes and last 4 digits only, with change history.")
async def get_vendor_bank_accounts(ctx: Context, vendor_id: str) -> dict[str, Any]:
    return await _run(ctx, "get_vendor_bank_accounts", vendor_id=vendor_id)


@mcp.tool(description="Hash-compare invoice bank details with the vendor master.")
async def compare_bank_account(ctx: Context, vendor_id: str, routing: str, account_number: str) -> dict[str, Any]:
    return await _run(ctx, "compare_bank_account", vendor_id=vendor_id, routing=routing, account_number=account_number)


@mcp.tool(description="Get a purchase order with its lines and already-billed quantities.")
async def get_purchase_order(ctx: Context, po_number: str) -> dict[str, Any]:
    return await _run(ctx, "get_purchase_order", po_number=po_number)


@mcp.tool(description="Goods receipts for a PO, with received quantity per PO line.")
async def get_goods_receipts(ctx: Context, po_number: str) -> dict[str, Any]:
    return await _run(ctx, "get_goods_receipts", po_number=po_number)


@mcp.tool(description="Chart of accounts and cost centers.")
async def list_gl_accounts(ctx: Context) -> dict[str, Any]:
    return await _run(ctx, "list_gl_accounts")


@mcp.tool(description="Active contracts for a vendor.")
async def get_contract(ctx: Context, vendor_id: str) -> dict[str, Any]:
    return await _run(ctx, "get_contract", vendor_id=vendor_id)


@mcp.tool(description="Employees whose bank account hash equals the given hash (conflict check).")
async def get_employee_conflicts(ctx: Context, account_hash: str) -> dict[str, Any]:
    return await _run(ctx, "get_employee_conflicts", account_hash=account_hash)


@mcp.tool(description="Post an approved invoice to AP. Idempotent by idempotency_key.")
async def post_invoice(ctx: Context, idempotency_key: str, invoice_number: str, amount_minor: int, currency: str,
                       route: str, vendor_id: str | None = None, po_lines: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return await _run(ctx, "post_invoice", idempotency_key=idempotency_key, vendor_id=vendor_id, invoice_number=invoice_number,
                      amount_minor=amount_minor, currency=currency, route=route, po_lines=po_lines)


@mcp.tool(description="Schedule payment of a posted invoice. Non-auto routes require a signed single-use approval token.")
async def schedule_payment(ctx: Context, idempotency_key: str, erp_ref: str, amount_minor: int, currency: str,
                           due_date: str, route: str, approval_token: str | None = None) -> dict[str, Any]:
    return await _run(ctx, "schedule_payment", idempotency_key=idempotency_key, erp_ref=erp_ref, amount_minor=amount_minor,
                      currency=currency, due_date=due_date, route=route, approval_token=approval_token)


@mcp.tool(description="Open a vendor master change request (e.g. bank details) for the vendor team.")
async def create_vendor_change_request(ctx: Context, vendor_id: str, field: str, requested_by: str, note: str) -> dict[str, Any]:
    return await _run(ctx, "create_vendor_change_request", vendor_id=vendor_id, field=field, requested_by=requested_by, note=note)


@mcp.resource("erp://chart-of-accounts", description="Chart of accounts (demo org)")
async def chart_of_accounts() -> str:
    import json

    return json.dumps(await tools.list_gl_accounts("demo"))


@mcp.resource("erp://approval-matrix", description="Default approval matrix")
def approval_matrix() -> str:
    return (
        '{"auto_limit_minor":100000,"approver_limit_minor":1000000,"currency":"USD",'
        '"bank_change":"controller + call-back"}'
    )


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="AURA mock ERP (synthetic)", lifespan=lifespan, docs_url="/erp/docs", openapi_url="/erp/openapi.json")
app.mount("/erp/mcp", mcp.streamable_http_app())


@app.get("/erp/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "erp-mock"}


@app.post("/erp/tools/{name}")
async def call_tool(name: str, request: Request, x_org_id: str | None = Header(None),
                    authorization: str | None = Header(None)) -> JSONResponse:
    org = _check(x_org_id, authorization)
    args = await request.json() if (await request.body()) else {}
    try:
        return JSONResponse(await tools.call(name, org, args))
    except tools.ErpError as e:
        return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=400)


@app.post("/erp/admin/vendor-bank")
async def admin_vendor_bank(request: Request, x_org_id: str | None = Header(None),
                            authorization: str | None = Header(None)) -> dict[str, Any]:
    org = _check(x_org_id, authorization)
    b = await request.json()
    return await tools.update_vendor_bank(org, b["vendor_id"], b["routing"], b["account_number"], b["changed_by"])


@app.post("/erp/admin/goods-receipt")
async def admin_grn(request: Request, x_org_id: str | None = Header(None),
                    authorization: str | None = Header(None)) -> dict[str, Any]:
    org = _check(x_org_id, authorization)
    b = await request.json()
    return await tools.post_goods_receipt(org, b["po_number"], b["lines"])
