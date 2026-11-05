"""Turn model output (or a fixture) into a validated invoice with per-field confidence.

Confidence comes from cross-checks, not the model's self-report: a value that cannot be found
in the source text is marked unverified (§B18 hallucinated field)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

from app.core.config import datasets_root
from app.domain.money import MoneyError, parse_decimal, to_minor

HEADER_FIELDS = (
    "vendor_name",
    "vendor_tax_id",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "po_number",
    "subtotal",
    "tax",
    "total",
    "bank_account",
    "bank_routing",
)


@dataclass
class ExtractedInvoice:
    doc_type: str
    vendor_name: str | None
    vendor_tax_id: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    currency: str | None
    po_number: str | None
    subtotal_minor: int | None
    tax_minor: int | None
    total_minor: int | None
    bank_account: str | None
    bank_routing: str | None
    lines: list[dict[str, Any]]
    confidence: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    unverified: list[str] = field(default_factory=list)
    path: str = "text"

    def public(self) -> dict[str, Any]:
        d = {
            k: getattr(self, k)
            for k in (
                "doc_type",
                "vendor_name",
                "vendor_tax_id",
                "invoice_number",
                "invoice_date",
                "due_date",
                "currency",
                "po_number",
                "subtotal_minor",
                "tax_minor",
                "total_minor",
                "lines",
                "confidence",
                "evidence",
                "unverified",
                "path",
            )
        }
        d["bank_account_last4"] = (self.bank_account or "")[-4:] or None
        return d


def _date(v: Any) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%b %d, %Y", "%d-%m-%Y"):
            try:
                from datetime import datetime

                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _minor(v: Any, currency: str | None) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v
    try:
        return to_minor(parse_decimal(re.sub(r"[^\d.,()\-\s']", "", str(v))), currency or "USD")
    except (MoneyError, InvalidOperation, ValueError):
        return None


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _found(value: Any, source: str, source_digits: str) -> bool:
    if value is None or value == "":
        return True
    v = str(value).strip()
    if v.lower() in source.lower():
        return True
    d = _digits(v)
    return bool(d) and len(d) >= 3 and d in source_digits


def normalize(
    raw: dict[str, Any], *, source_text: str | None, path: str, doc_type_hint: str
) -> ExtractedInvoice:
    cur = (raw.get("currency") or "").strip().upper()[:3] or None
    if cur and not re.fullmatch(r"[A-Z]{3}", cur):
        cur = None
    lines = []
    for ln in raw.get("lines") or []:
        try:
            qty = Decimal(str(ln.get("quantity", "0")).replace(",", "").strip() or "0")
        except InvalidOperation:
            qty = Decimal(0)
        up = _minor(ln.get("unit_price", ln.get("unit_price_minor")), cur)
        amt = _minor(ln.get("amount", ln.get("amount_minor")), cur)
        lines.append(
            {
                "description": str(ln.get("description", ""))[:500],
                "quantity": str(qty.normalize()) if qty == qty.to_integral() else str(qty),
                "uom": (ln.get("uom") or "each").lower()[:16],
                "unit_price_minor": up,
                "amount_minor": amt,
            }
        )
    inv = ExtractedInvoice(
        doc_type=raw.get("doc_type") or doc_type_hint,
        vendor_name=(raw.get("vendor_name") or None),
        vendor_tax_id=(raw.get("vendor_tax_id") or None),
        invoice_number=(
            str(raw.get("invoice_number")).strip() if raw.get("invoice_number") else None
        ),
        invoice_date=_date(raw.get("invoice_date")),
        due_date=_date(raw.get("due_date")),
        currency=cur,
        po_number=(str(raw.get("po_number")).strip() if raw.get("po_number") else None),
        subtotal_minor=_minor(raw.get("subtotal", raw.get("subtotal_minor")), cur),
        tax_minor=_minor(raw.get("tax", raw.get("tax_minor")), cur),
        total_minor=_minor(raw.get("total", raw.get("total_minor")), cur),
        bank_account=(
            _digits(str(raw.get("bank_account") or raw.get("bank_account_number") or "")) or None
        ),
        bank_routing=(_digits(str(raw.get("bank_routing") or "")) or None),
        lines=lines,
        evidence=raw.get("evidence") or {},
        path=path,
    )
    base = {"text": 0.95, "vision": 0.75, "fixture": 1.0}[path]
    src = source_text or ""
    src_d = _digits(src)
    for f in HEADER_FIELDS:
        rawv = raw.get(f)
        if f == "bank_account":
            rawv = inv.bank_account
        conf = base if rawv not in (None, "") else 0.0
        if path == "text" and rawv not in (None, "") and not _found(rawv, src, src_d):
            inv.unverified.append(f)
            conf = 0.3
        inv.confidence[f] = conf
    if path == "text":
        for i, ln in enumerate(lines):
            desc = str(ln["description"] or "")
            if desc and desc[:20].lower() not in src.lower():
                inv.unverified.append(f"lines[{i}].description")
    return inv


@lru_cache
def _fixtures() -> dict[str, dict[str, Any]]:
    """sha256 → ground-truth extraction, for provider_mode=fake (deterministic CI and replay)."""
    root = datasets_root()
    out: dict[str, dict[str, Any]] = {}
    for f in (root / "demo" / "cases.jsonl", root / "golden_invoices" / "v1" / "cases.jsonl"):
        if f.exists():
            for line in f.read_text().splitlines():
                c = json.loads(line)
                out[c["file"]["sha256"]] = c
    return out


def fixture_for(sha256: str) -> dict[str, Any] | None:
    return _fixtures().get(sha256)
