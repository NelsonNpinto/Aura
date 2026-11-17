"""Mock legacy vendor portal (Phase 5.2).

Deliberately API-free: invoices can only be reached by signing in and clicking through the UI,
which is what makes the browser agent worth having. Everything is synthetic and in memory.

Routes:
  GET  /portal/            sign-in form
  POST /portal/login       sets a session cookie
  GET  /portal/invoices    list (requires the cookie)
  GET  /portal/invoices/{id}  detail page with a download link
  GET  /portal/download/{id}  the PDF bytes
"""

from __future__ import annotations

import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

PORTAL_USER = os.environ.get("PORTAL_USER", "acme")
PORTAL_PASSWORD = os.environ.get("PORTAL_PASSWORD", "portal-demo-only")
SESSION_COOKIE = "portal_session"
_SESSIONS: set[str] = set()


@dataclass(frozen=True)
class PortalInvoice:
    id: str
    number: str
    issued: date
    total: str
    currency: str
    po_number: str


INVOICES = [
    PortalInvoice("1", "INV-7001", date(2026, 10, 2), "1,240.00", "USD", "PO-1001"),
    PortalInvoice("2", "INV-7002", date(2026, 10, 14), "860.50", "USD", "PO-1002"),
    PortalInvoice("3", "INV-7003", date(2026, 10, 29), "4,310.75", "USD", "PO-1003"),
    PortalInvoice("4", "INV-7004", date(2026, 11, 5), "275.00", "USD", "PO-1004"),
]

app = FastAPI(
    title="Northwind vendor portal (mock)",
    docs_url=None,
    openapi_url=None,
)

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
 body{{font:16px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#111}}
 header{{background:#17324d;color:#fff;padding:12px 20px;font-weight:600}}
 main{{max-width:820px;margin:24px auto;padding:0 16px}}
 table{{width:100%;border-collapse:collapse;background:#fff}}
 th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid #e3e6ea}}
 a{{color:#17324d}} label{{display:block;margin:12px 0 4px}}
 input{{padding:8px;width:240px}} button{{padding:8px 16px;margin-top:14px;cursor:pointer}}
 .note{{color:#5a6472;font-size:14px;margin-top:20px}}
</style></head><body>
<header>Northwind Supplies — vendor portal (mock, synthetic data)</header>
<main>{body}</main></body></html>"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(PAGE.format(title=title, body=body))


def _authed(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE, "")
    return bool(token) and token in _SESSIONS


@app.get("/portal/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    if _authed(request):
        return RedirectResponse("/portal/invoices", status_code=303)  # type: ignore[return-value]
    return _page(
        "Sign in",
        """
        <h1>Sign in</h1>
        <form method="post" action="/portal/login">
          <label for="username">Username</label>
          <input id="username" name="username" autocomplete="username">
          <label for="password">Password</label>
          <input id="password" name="password" type="password" autocomplete="current-password">
          <button type="submit">Sign in</button>
        </form>
        <p class="note">Synthetic demo portal. No real accounts, documents or payments.</p>
        """,
    )


@app.post("/portal/login")
async def login(username: str = Form(""), password: str = Form("")) -> Response:
    ok = hmac.compare_digest(username, PORTAL_USER) and hmac.compare_digest(
        password, PORTAL_PASSWORD
    )
    if not ok:
        return _page("Sign in", "<h1>Sign in failed</h1><p><a href='/portal/'>Try again</a></p>")
    token = secrets.token_urlsafe(24)
    _SESSIONS.add(token)
    response = RedirectResponse("/portal/invoices", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return response


@app.get("/portal/invoices", response_class=HTMLResponse)
async def invoices(request: Request) -> HTMLResponse:
    if not _authed(request):
        return RedirectResponse("/portal/", status_code=303)  # type: ignore[return-value]
    rows = "".join(
        f"<tr><td><a href='/portal/invoices/{i.id}' data-testid='invoice-link'>{i.number}</a></td>"
        f"<td>{i.issued.isoformat()}</td><td>{i.po_number}</td>"
        f"<td>{i.currency} {i.total}</td></tr>"
        for i in INVOICES
    )
    return _page(
        "Invoices",
        f"""
        <h1>Your invoices</h1>
        <table><thead><tr><th>Invoice</th><th>Date</th><th>PO</th><th>Total</th></tr></thead>
        <tbody>{rows}</tbody></table>
        <p class="note">Downloads are available on each invoice page. This portal has no API.</p>
        """,
    )


@app.get("/portal/invoices/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(invoice_id: str, request: Request) -> HTMLResponse:
    if not _authed(request):
        return RedirectResponse("/portal/", status_code=303)  # type: ignore[return-value]
    invoice = next((i for i in INVOICES if i.id == invoice_id), None)
    if invoice is None:
        raise HTTPException(404, "invoice not found")
    return _page(
        invoice.number,
        f"""
        <h1>{invoice.number}</h1>
        <table><tbody>
          <tr><th>Issued</th><td>{invoice.issued.isoformat()}</td></tr>
          <tr><th>Purchase order</th><td>{invoice.po_number}</td></tr>
          <tr><th>Total</th><td>{invoice.currency} {invoice.total}</td></tr>
        </tbody></table>
        <p><a href="/portal/download/{invoice.id}" data-testid="download">Download PDF</a></p>
        <p><a href="/portal/invoices">Back to invoices</a></p>
        """,
    )


def _pdf_bytes(invoice: PortalInvoice) -> bytes:
    """Render a small synthetic invoice PDF with fpdf2 (same library as the generator)."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Northwind Supplies", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    for label, value in (
        ("Invoice", invoice.number),
        ("Date", invoice.issued.isoformat()),
        ("Purchase order", invoice.po_number),
        ("Currency", invoice.currency),
        ("Total", invoice.total),
        ("Tax ID", "84-1739204"),
        ("Note", "Synthetic document generated for the AURA demo."),
    ):
        pdf.cell(0, 8, f"{label}: {value}", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


@app.get("/portal/download/{invoice_id}")
async def download(invoice_id: str, request: Request) -> Response:
    if not _authed(request):
        return RedirectResponse("/portal/", status_code=303)
    invoice = next((i for i in INVOICES if i.id == invoice_id), None)
    if invoice is None:
        raise HTTPException(404, "invoice not found")
    return Response(
        content=_pdf_bytes(invoice),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{invoice.number}.pdf"',
            "X-Generated": datetime.now(UTC).isoformat(),
        },
    )


@app.get("/portal/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "vendor-portal", "invoices": str(len(INVOICES))}


def seed_dir() -> Path:
    return Path(__file__).resolve().parent
