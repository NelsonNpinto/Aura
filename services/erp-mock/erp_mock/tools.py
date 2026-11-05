"""ERP tool implementations (§B9). Shared by the REST API, the MCP server and (in tests/local
dev) the AURA gateway's in-process executor. Every function is tenant-scoped by org_id.

Writes are idempotent by key: replaying post_invoice/schedule_payment returns the original
record instead of creating a second one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class ErpError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _db_url() -> str:
    url = os.environ.get("ERP_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    for p in ("postgresql://", "postgres://"):
        if url.startswith(p):
            url = "postgresql+psycopg://" + url[len(p):]
    return url


@lru_cache
def engine() -> AsyncEngine:
    from sqlalchemy.pool import NullPool

    return create_async_engine(
        _db_url(), poolclass=NullPool, connect_args={"prepare_threshold": None, "connect_timeout": 10}
    )


def _rows(res: Any) -> list[dict[str, Any]]:
    out = []
    for r in res.mappings().all():
        d = {}
        for k, v in r.items():
            if isinstance(v, Decimal):
                v = str(v.normalize()) if v == v.to_integral() else str(v)
            elif isinstance(v, date):
                v = v.isoformat()
            d[k] = v
        out.append(d)
    return out


def _bank_hash(routing: str, account: str) -> str:
    return hashlib.sha256(f"{routing.strip()}:{account.strip()}".encode()).hexdigest()


# ------------------------------------------------------------------ approval tokens
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_approval_token(secret: str, claims: dict[str, Any]) -> str:
    body = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"v1.{body}.{sig}"


def verify_approval_token(secret: str, token: str) -> dict[str, Any]:
    try:
        ver, body, sig = token.split(".")
    except ValueError as exc:
        raise ErpError("approval_token_invalid", "Malformed approval token") from exc
    good = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if ver != "v1" or not hmac.compare_digest(good, sig):
        raise ErpError("approval_token_invalid", "Approval token signature is invalid")
    claims = json.loads(_unb64(body))
    if int(claims.get("exp", 0)) < time.time():
        raise ErpError("approval_token_expired", "Approval token has expired")
    return claims


# ------------------------------------------------------------------ read tools
async def search_vendors(org_id: str, query: str | None = None, tax_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    async with engine().connect() as c:
        if tax_id:
            norm = "".join(ch for ch in tax_id.upper() if ch.isalnum())
            res = await c.execute(
                text("SELECT id, name, aliases, tax_id, currency, status FROM erp.vendors WHERE org_id=:o"
                     " AND regexp_replace(upper(tax_id), '[^A-Z0-9]', '', 'g') = :t"),
                {"o": org_id, "t": norm},
            )
            rows = _rows(res)
            if rows:
                return {"match": "tax_id", "vendors": rows}
        if not query:
            return {"match": "none", "vendors": []}
        res = await c.execute(
            text(
                "SELECT id, name, aliases, tax_id, currency, status,"
                " greatest(similarity(lower(name), lower(:q)),"
                "   coalesce((SELECT max(similarity(lower(a), lower(:q))) FROM jsonb_array_elements_text(aliases) a), 0)) AS score"
                " FROM erp.vendors WHERE org_id=:o ORDER BY score DESC LIMIT :n"
            ),
            {"o": org_id, "q": query, "n": limit},
        )
        rows = [r for r in _rows(res) if float(r["score"]) >= 0.3]
        for r in rows:
            r["score"] = round(float(r["score"]), 3)
        return {"match": "name" if rows else "none", "vendors": rows}


async def get_vendor(org_id: str, vendor_id: str) -> dict[str, Any]:
    async with engine().connect() as c:
        rows = _rows(await c.execute(
            text("SELECT id, name, aliases, tax_id, category, currency, country, address, payment_terms_days,"
                 " cost_center, created_by, contract_id, status FROM erp.vendors WHERE org_id=:o AND id=:v"),
            {"o": org_id, "v": vendor_id}))
    if not rows:
        raise ErpError("not_found", f"Vendor {vendor_id} not found")
    return rows[0]


async def get_vendor_bank_accounts(org_id: str, vendor_id: str) -> dict[str, Any]:
    async with engine().connect() as c:
        rows = _rows(await c.execute(
            text("SELECT account_hash, last4, effective_from, effective_to, changed_by"
                 " FROM erp.vendor_bank_accounts WHERE org_id=:o AND vendor_id=:v ORDER BY effective_from DESC"),
            {"o": org_id, "v": vendor_id}))
    current = next((r for r in rows if r["effective_to"] is None), None)
    return {"vendor_id": vendor_id, "current": current, "history": rows}


async def compare_bank_account(org_id: str, vendor_id: str, routing: str, account_number: str) -> dict[str, Any]:
    """Hash-compare invoice bank details with the vendor master; the raw number never leaves."""
    accts = await get_vendor_bank_accounts(org_id, vendor_id)
    cur = accts["current"]
    h = _bank_hash(routing, account_number)
    return {
        "vendor_id": vendor_id,
        "matches_current": bool(cur and cur["account_hash"] == h),
        "matches_previous": any(r["account_hash"] == h for r in accts["history"] if r is not cur),
        "invoice_last4": account_number.strip()[-4:],
        "master_last4": cur["last4"] if cur else None,
        "last_changed_by": cur["changed_by"] if cur else None,
    }


async def get_purchase_order(org_id: str, po_number: str) -> dict[str, Any]:
    async with engine().connect() as c:
        head = _rows(await c.execute(
            text("SELECT po_number, vendor_id, currency, order_date, requester_id, status FROM erp.purchase_orders"
                 " WHERE org_id=:o AND upper(po_number)=upper(:p)"), {"o": org_id, "p": po_number.strip()}))
        if not head:
            raise ErpError("not_found", f"Purchase order {po_number} not found")
        lines = _rows(await c.execute(
            text("SELECT line_no, description, quantity, uom, unit_price_minor, gl_account, cost_center, is_service,"
                 " billed_qty FROM erp.po_lines WHERE org_id=:o AND po_number=:p ORDER BY line_no"),
            {"o": org_id, "p": head[0]["po_number"]}))
    return {**head[0], "lines": lines}


async def get_goods_receipts(org_id: str, po_number: str) -> dict[str, Any]:
    async with engine().connect() as c:
        rows = _rows(await c.execute(
            text("SELECT g.grn_number, g.received_date, l.po_line, l.quantity FROM erp.goods_receipts g"
                 " JOIN erp.grn_lines l ON l.org_id=g.org_id AND l.grn_number=g.grn_number"
                 " WHERE g.org_id=:o AND upper(g.po_number)=upper(:p) ORDER BY g.received_date, l.po_line"),
            {"o": org_id, "p": po_number.strip()}))
    received: dict[int, Decimal] = {}
    for r in rows:
        received[r["po_line"]] = received.get(r["po_line"], Decimal(0)) + Decimal(r["quantity"])
    return {"po_number": po_number, "receipts": rows,
            "received_by_line": {str(k): str(v) for k, v in sorted(received.items())}}


async def list_gl_accounts(org_id: str) -> dict[str, Any]:
    async with engine().connect() as c:
        gl = _rows(await c.execute(text("SELECT code, name, guidance FROM erp.gl_accounts WHERE org_id=:o ORDER BY code"), {"o": org_id}))
        cc = _rows(await c.execute(text("SELECT code, name FROM erp.cost_centers WHERE org_id=:o ORDER BY code"), {"o": org_id}))
    return {"gl_accounts": gl, "cost_centers": cc}


async def get_contract(org_id: str, vendor_id: str) -> dict[str, Any]:
    async with engine().connect() as c:
        rows = _rows(await c.execute(
            text("SELECT id, vendor_id, description, monthly_cap_minor, currency, start_date, end_date"
                 " FROM erp.contracts WHERE org_id=:o AND vendor_id=:v"), {"o": org_id, "v": vendor_id}))
    return {"vendor_id": vendor_id, "contracts": rows}


async def get_employee_conflicts(org_id: str, account_hash: str) -> dict[str, Any]:
    async with engine().connect() as c:
        rows = _rows(await c.execute(
            text("SELECT id, name FROM erp.employees WHERE org_id=:o AND bank_hash=:h"), {"o": org_id, "h": account_hash}))
    return {"employees": rows}


# ------------------------------------------------------------------ write tools
async def post_invoice(org_id: str, idempotency_key: str, vendor_id: str | None, invoice_number: str,
                       amount_minor: int, currency: str, route: str, po_lines: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    async with engine().begin() as c:
        prior = _rows(await c.execute(
            text("SELECT erp_ref, posted_at FROM erp.posted_invoices WHERE org_id=:o AND idempotency_key=:k"),
            {"o": org_id, "k": idempotency_key}))
        if prior:
            return {"erp_ref": prior[0]["erp_ref"], "replayed": True}
        ref = f"AP-{uuid.uuid4().hex[:10].upper()}"
        await c.execute(text(
            "INSERT INTO erp.posted_invoices (org_id, erp_ref, idempotency_key, vendor_id, invoice_number, amount_minor, currency, route)"
            " VALUES (:o,:r,:k,:v,:n,:a,:c,:route)"),
            {"o": org_id, "r": ref, "k": idempotency_key, "v": vendor_id, "n": invoice_number,
             "a": amount_minor, "c": currency, "route": route})
        for pl in po_lines or []:
            await c.execute(text(
                "UPDATE erp.po_lines SET billed_qty = billed_qty + :q WHERE org_id=:o AND po_number=:p AND line_no=:l"),
                {"q": Decimal(str(pl["quantity"])), "o": org_id, "p": pl["po_number"], "l": int(pl["line_no"])})
    return {"erp_ref": ref, "replayed": False}


async def schedule_payment(org_id: str, idempotency_key: str, erp_ref: str, amount_minor: int, currency: str,
                           due_date: str, route: str, approval_token: str | None = None) -> dict[str, Any]:
    if amount_minor <= 0:
        raise ErpError("invalid_amount", "Credit notes and zero amounts are never scheduled for payment")
    jti = None
    if route != "auto":
        if not approval_token:
            raise ErpError("approval_required", "Non-auto routes need a signed approval token")
        claims = verify_approval_token(os.environ.get("APPROVAL_TOKEN_SECRET", ""), approval_token)
        if int(claims.get("amount_minor", -1)) != amount_minor:
            raise ErpError("approval_token_mismatch", "Approval token does not cover this amount")
        jti = str(claims["jti"])
    async with engine().begin() as c:
        prior = _rows(await c.execute(
            text("SELECT payment_ref FROM erp.payments WHERE org_id=:o AND idempotency_key=:k"),
            {"o": org_id, "k": idempotency_key}))
        if prior:
            return {"payment_ref": prior[0]["payment_ref"], "replayed": True}
        if jti:
            used = (await c.execute(text("SELECT 1 FROM erp.payments WHERE approval_jti=:j"), {"j": jti})).first()
            if used:
                raise ErpError("approval_token_used", "Approval token was already used")
        ref = f"PAY-{uuid.uuid4().hex[:10].upper()}"
        await c.execute(text(
            "INSERT INTO erp.payments (org_id, payment_ref, erp_ref, idempotency_key, amount_minor, currency, due_date, approval_jti)"
            " VALUES (:o,:r,:e,:k,:a,:c,:d,:j)"),
            {"o": org_id, "r": ref, "e": erp_ref, "k": idempotency_key, "a": amount_minor, "c": currency,
             "d": date.fromisoformat(due_date), "j": jti})
    return {"payment_ref": ref, "replayed": False, "due_date": due_date}


async def create_vendor_change_request(org_id: str, vendor_id: str, field: str, requested_by: str, note: str) -> dict[str, Any]:
    async with engine().begin() as c:
        rid = (await c.execute(text(
            "INSERT INTO erp.vendor_change_requests (org_id, vendor_id, field, requested_by, note) VALUES (:o,:v,:f,:r,:n) RETURNING id"),
            {"o": org_id, "v": vendor_id, "f": field, "r": requested_by, "n": note[:1000]})).scalar_one()
    return {"request_id": rid, "status": "open"}


async def update_vendor_bank(org_id: str, vendor_id: str, routing: str, account_number: str, changed_by: str) -> dict[str, Any]:
    """Demo/admin helper (REST only): rotate the vendor's current bank account."""
    today = date.today()
    async with engine().begin() as c:
        await c.execute(text(
            "UPDATE erp.vendor_bank_accounts SET effective_to=:d WHERE org_id=:o AND vendor_id=:v AND effective_to IS NULL"),
            {"d": today - timedelta(days=0), "o": org_id, "v": vendor_id})
        await c.execute(text(
            "INSERT INTO erp.vendor_bank_accounts (org_id, vendor_id, account_hash, last4, effective_from, changed_by)"
            " VALUES (:o,:v,:h,:l,:d,:by) ON CONFLICT (org_id, vendor_id, effective_from) DO UPDATE"
            " SET account_hash=EXCLUDED.account_hash, last4=EXCLUDED.last4, changed_by=EXCLUDED.changed_by, effective_to=NULL"),
            {"o": org_id, "v": vendor_id, "h": _bank_hash(routing, account_number), "l": account_number.strip()[-4:],
             "d": today, "by": changed_by})
    return {"vendor_id": vendor_id, "last4": account_number.strip()[-4:], "changed_by": changed_by}


async def post_goods_receipt(org_id: str, po_number: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
    grn = f"GRN-{uuid.uuid4().hex[:6].upper()}"
    async with engine().begin() as c:
        await c.execute(text("INSERT INTO erp.goods_receipts (org_id, grn_number, po_number, received_date) VALUES (:o,:g,:p,:d)"),
                        {"o": org_id, "g": grn, "p": po_number, "d": date.today()})
        for ln in lines:
            await c.execute(text("INSERT INTO erp.grn_lines (org_id, grn_number, po_line, quantity) VALUES (:o,:g,:l,:q)"),
                            {"o": org_id, "g": grn, "l": int(ln["po_line"]), "q": Decimal(str(ln["quantity"]))})
    return {"grn_number": grn}


TOOLS = {
    "search_vendors": search_vendors,
    "get_vendor": get_vendor,
    "get_vendor_bank_accounts": get_vendor_bank_accounts,
    "compare_bank_account": compare_bank_account,
    "get_purchase_order": get_purchase_order,
    "get_goods_receipts": get_goods_receipts,
    "list_gl_accounts": list_gl_accounts,
    "get_contract": get_contract,
    "get_employee_conflicts": get_employee_conflicts,
    "post_invoice": post_invoice,
    "schedule_payment": schedule_payment,
    "create_vendor_change_request": create_vendor_change_request,
}


async def call(name: str, org_id: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = TOOLS.get(name)
    if fn is None:
        raise ErpError("unknown_tool", f"Unknown ERP tool {name}")
    return await fn(org_id, **args)  # type: ignore[operator]
