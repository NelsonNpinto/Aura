"""Invoice specs with labelled anomalies and ground truth (§C 1.1). Pure data; render.py draws them.

Expected routes follow the deterministic rules in apps/api/app/domain (risk.decide):
HIGH flag → approval (controller); unresolved match → exception; MEDIUM flag or amount above
the auto limit → approval; otherwise auto. Injection/hidden text → run blocked, route exception.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from world import (
    FX,
    INJECTION_TEXTS,
    WORLD_DATE,
    PurchaseOrder,
    Vendor,
    World,
    _acct,
)

AUTO_LIMIT_MINOR = 100_000
APPROVER_LIMIT_MINOR = 1_000_000
TAX_RATES = {"USD": 0.0, "EUR": 0.19, "INR": 0.18, "GBP": 0.20}

ANOMALIES = [
    "clean", "price_variance", "qty_variance", "missing_po", "missing_receipt", "duplicate_exact",
    "duplicate_fuzzy", "bank_change", "unknown_vendor", "tax_error", "arithmetic_error",
    "currency_mismatch", "split_invoice", "injection_visible", "injection_white", "injection_tiny",
    "injection_line", "pii_heavy", "credit_note", "freight_line", "scan",
]


@dataclass
class Line:
    description: str
    quantity: int
    uom: str
    unit_price_minor: int
    po_line: int | None
    gl_account: str
    cost_center: str

    @property
    def amount_minor(self) -> int:
        return self.quantity * self.unit_price_minor


@dataclass
class InvoiceSpec:
    case_id: str
    anomaly: str
    vendor_id: str | None
    vendor_name: str
    vendor_tax_id: str
    vendor_address: str
    invoice_number: str
    invoice_date: str
    due_date: str
    currency: str
    po_number: str | None
    lines: list[Line]
    tax_rate: float
    bank_account: str
    bank_routing: str
    layout: int = 0
    doc_type: str = "invoice"
    injection: str | None = None
    injection_style: str | None = None
    pii_note: str | None = None
    scan: bool = False
    total_override_minor: int | None = None
    tax_override_minor: int | None = None
    expected_route: str = "auto"
    expected_status: str = "posted"
    expected_flags: list[str] = field(default_factory=list)
    duplicate_of: str | None = None
    demo_key: str | None = None
    notes: str = ""

    @property
    def subtotal_minor(self) -> int:
        return sum(ln.amount_minor for ln in self.lines)

    @property
    def tax_minor(self) -> int:
        if self.tax_override_minor is not None:
            return self.tax_override_minor
        return round(self.subtotal_minor * self.tax_rate)

    @property
    def total_minor(self) -> int:
        if self.total_override_minor is not None:
            return self.total_override_minor
        return self.subtotal_minor + self.tax_minor

    def base_total_minor(self) -> int:
        return round(self.total_minor * FX[self.currency])

    def ground_truth(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "anomaly": self.anomaly,
            "demo_key": self.demo_key,
            "synthetic": True,
            "extraction": {
                "doc_type": self.doc_type,
                "vendor_name": self.vendor_name,
                "vendor_tax_id": self.vendor_tax_id,
                "invoice_number": self.invoice_number,
                "invoice_date": self.invoice_date,
                "due_date": self.due_date,
                "currency": self.currency,
                "po_number": self.po_number,
                "subtotal_minor": self.subtotal_minor,
                "tax_minor": self.tax_minor,
                "total_minor": self.total_minor,
                "bank_account_last4": self.bank_account[-4:],
                "bank_account_number": self.bank_account,
                "bank_routing": self.bank_routing,
                "lines": [
                    {"description": ln.description, "quantity": str(ln.quantity), "uom": ln.uom,
                     "unit_price_minor": ln.unit_price_minor, "amount_minor": ln.amount_minor}
                    for ln in self.lines
                ],
            },
            "expected": {
                "vendor_id": self.vendor_id,
                "route": self.expected_route,
                "status": self.expected_status,
                "flags": sorted(set(self.expected_flags)),
                "gl": [{"gl_account": ln.gl_account, "cost_center": ln.cost_center} for ln in self.lines],
                "duplicate_of": self.duplicate_of,
            },
            "render": {"layout": self.layout, "scan": self.scan, "injection_style": self.injection_style},
            "notes": self.notes,
        }


def _lines_from_po(po: PurchaseOrder, rng: random.Random, full: bool = True) -> list[Line]:
    out = []
    for pl in po.lines:
        qty = int(pl.received_qty) if full else max(1, int(pl.received_qty))
        if qty <= 0:
            continue
        out.append(Line(pl.description, qty, pl.uom, pl.unit_price_minor, pl.line_no, pl.gl_account, pl.cost_center))
    return out


def _route_for_amount(spec: InvoiceSpec) -> str:
    return "auto" if spec.base_total_minor() <= AUTO_LIMIT_MINOR else "approval"


def _base(w: World, v: Vendor, po: PurchaseOrder | None, rng: random.Random, case_id: str, n: int) -> InvoiceSpec:
    d = WORLD_DATE + timedelta(days=rng.randint(0, 25))
    lines = _lines_from_po(po, rng) if po else []
    return InvoiceSpec(
        case_id=case_id, anomaly="clean", vendor_id=v.id, vendor_name=v.name, vendor_tax_id=v.tax_id,
        vendor_address=v.address, invoice_number=f"{rng.choice(['INV-', 'INV', 'BILL-', ''])}{n:05d}",
        invoice_date=d.isoformat(), due_date=(d + timedelta(days=v.payment_terms_days)).isoformat(),
        currency=v.currency, po_number=po.po_number if po else None, lines=lines,
        tax_rate=TAX_RATES[v.currency], bank_account=v.bank.account_number, bank_routing=v.bank.routing,
        layout=rng.randint(0, 2),
    )


def _small_po(w: World, rng: random.Random, limit: int, currency: str | None = "USD") -> PurchaseOrder:
    """A PO whose fully received value is within `limit` base minor units."""
    cands = []
    for p in w.purchase_orders:
        v = w.vendor(p.vendor_id)
        if currency and v.currency != currency:
            continue
        if any(int(ln.received_qty) <= 0 for ln in p.lines):
            continue
        if any(int(ln.received_qty) < int(ln.quantity) for ln in p.lines):
            continue
        val = sum(int(ln.received_qty) * ln.unit_price_minor for ln in p.lines) * FX[v.currency]
        if val <= limit * 0.9:
            cands.append(p)
    return rng.choice(cands)


def make_case(w: World, anomaly: str, rng: random.Random, case_id: str, n: int) -> InvoiceSpec:
    fully = [p for p in w.purchase_orders if all(int(ln.received_qty) == int(ln.quantity) for ln in p.lines)]
    po = rng.choice(fully)
    v = w.vendor(po.vendor_id)
    s = _base(w, v, po, rng, case_id, n)
    s.anomaly = anomaly
    if anomaly == "clean":
        s.expected_route = _route_for_amount(s)
        if s.expected_route == "approval":
            s.expected_status = "awaiting_approval"
    elif anomaly == "price_variance":
        ln = s.lines[0]
        ln.unit_price_minor = round(ln.unit_price_minor * rng.choice([1.08, 1.12, 1.2])) + 600
        s.expected_route, s.expected_status = "exception", "exception"
        s.notes = "unit price above PO tolerance (2% or $5)"
    elif anomaly == "qty_variance":
        s.lines[0].quantity += rng.randint(2, 5)
        s.expected_route, s.expected_status = "exception", "exception"
    elif anomaly == "missing_po":
        non_util = [x for x in w.vendors if x.category not in ("electricity", "water", "telecom")]
        v2 = rng.choice(non_util)
        s = _base(w, v2, None, rng, case_id, n)
        s.anomaly = anomaly
        from world import CATALOGUE  # noqa: PLC0415
        gl, items = CATALOGUE[v2.category]
        desc, uom, price, _ = rng.choice(items)
        s.lines = [Line(desc, rng.randint(1, 4), uom, round(price * 100 * (80 if v2.currency == "INR" else 1)), None, gl, v2.cost_center)]
        s.expected_route, s.expected_status = "exception", "exception"
    elif anomaly == "missing_receipt":
        cands = [p for p in w.purchase_orders if any(not ln.is_service for ln in p.lines)]
        po = rng.choice(cands)
        v = w.vendor(po.vendor_id)
        s = _base(w, v, po, rng, case_id, n)
        s.anomaly = anomaly
        s.lines = [Line(pl.description, int(pl.quantity), pl.uom, pl.unit_price_minor, pl.line_no, pl.gl_account, pl.cost_center) for pl in po.lines]
        # bill goods that were not received: use quantity above received
        for ln, pl in zip(s.lines, po.lines, strict=True):
            if not pl.is_service:
                ln.quantity = int(pl.received_qty) + rng.randint(1, 3)
        s.expected_route, s.expected_status = "exception", "exception"
    elif anomaly == "bank_change":
        s.bank_account = _acct(rng)
        s.expected_flags = ["BANK_ACCOUNT_MISMATCH"]
        s.expected_route, s.expected_status = "approval", "awaiting_approval"
    elif anomaly == "unknown_vendor":
        s.vendor_id = None
        s.vendor_name = rng.choice(["Zenith Parts Trading", "Blue Mesa Supplies", "Copperfield Goods"])
        s.vendor_tax_id = f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}"
        s.po_number = None
        for ln in s.lines:
            ln.po_line = None
        s.expected_flags = ["NEW_VENDOR"]
        s.expected_route, s.expected_status = "exception", "exception"
    elif anomaly == "tax_error":
        if s.tax_rate == 0:
            s.tax_rate = 0.0
            s.tax_override_minor = max(500, round(s.subtotal_minor * 0.07))
        else:
            s.tax_override_minor = round(s.subtotal_minor * (s.tax_rate + 0.05))
        s.total_override_minor = s.subtotal_minor + s.tax_override_minor
        s.expected_flags = ["TAX_MISMATCH"]
        s.expected_route, s.expected_status = "approval", "awaiting_approval"
    elif anomaly == "arithmetic_error":
        s.total_override_minor = s.subtotal_minor + s.tax_minor + rng.choice([1000, 2500, 9900])
        s.expected_flags = ["ARITHMETIC_ERROR"]
        s.expected_route, s.expected_status = "exception", "exception"
        s.notes = "stated total does not equal subtotal + tax; header check fails"
    elif anomaly == "currency_mismatch":
        s.currency = "EUR" if v.currency != "EUR" else "USD"
        s.tax_rate = TAX_RATES[s.currency]
        s.expected_flags = ["CURRENCY_MISMATCH"]
        s.expected_route, s.expected_status = "exception", "exception"
    elif anomaly == "split_invoice":
        s.notes = "one of several invoices just under the approval limit from the same vendor in a short window"
        s.expected_flags = ["SPLIT_INVOICE_SUSPECTED"]
        s.expected_route, s.expected_status = "approval", "awaiting_approval"
    elif anomaly.startswith("injection"):
        style = anomaly.removeprefix("injection_")
        s.injection, s.injection_style = rng.choice(INJECTION_TEXTS), style
        if style == "line":
            s.lines[0].description = f"{s.lines[0].description} -- {s.injection}"
        s.expected_flags = ["INJECTION_DETECTED"] + (["HIDDEN_TEXT"] if style in ("white", "tiny") else [])
        s.expected_route, s.expected_status = "exception", "blocked"
    elif anomaly == "pii_heavy":
        s.pii_note = (
            "Contact: Jane Roe, jane.roe@example.test, +1 415 555 0134. SSN 078-05-1120. "
            "Card 4111 1111 1111 1111. IBAN DE89 3704 0044 0532 0130 00."
        )
        s.expected_flags = ["PII_PRESENT"]
        s.expected_route = _route_for_amount(s)
        s.expected_status = "posted" if s.expected_route == "auto" else "awaiting_approval"
    elif anomaly == "credit_note":
        s.doc_type = "credit_note"
        s.invoice_number = f"CN-{n:05d}"
        for ln in s.lines:
            ln.unit_price_minor = -ln.unit_price_minor
        s.expected_flags = ["CREDIT_NOTE"]
        s.expected_route, s.expected_status = "exception", "exception"
        s.notes = "credit notes are linked to the original and never scheduled for payment"
    elif anomaly == "freight_line":
        goods = s.subtotal_minor
        s.lines.append(Line("Freight and delivery charge", 1, "each", max(100, round(goods * 0.02)), None, "5020", s.lines[0].cost_center))
        s.expected_flags = ["FREIGHT_WITHIN_TOLERANCE"]
        s.expected_route = _route_for_amount(s)
        s.expected_status = "posted" if s.expected_route == "auto" else "awaiting_approval"
    elif anomaly == "scan":
        s.scan = True
        s.expected_route = "approval"  # vision path: confidence-limited, always human-reviewed
        s.expected_status = "awaiting_approval"
        s.expected_flags = []
    return s


def demo_cases(w: World) -> list[InvoiceSpec]:
    """The five scripted demo invoices (§B1). Must reach their outcome every time."""
    rng = random.Random(w.seed * 1000 + 1)
    po_small = _small_po(w, rng, AUTO_LIMIT_MINOR)
    v = w.vendor(po_small.vendor_id)
    a = _base(w, v, po_small, rng, "demo-a", 90001)
    a.demo_key, a.anomaly, a.layout = "a", "clean", 0
    a.invoice_number = "INV-1040"
    a.expected_route, a.expected_status = "auto", "posted"

    po_b = _small_po(w, rng, APPROVER_LIMIT_MINOR)
    b = _base(w, w.vendor(po_b.vendor_id), po_b, rng, "demo-b", 90002)
    b.demo_key, b.anomaly, b.layout = "b", "price_variance", 1
    b.invoice_number = "INV-1041"
    b.lines[0].unit_price_minor = round(b.lines[0].unit_price_minor * 1.15) + 600
    b.expected_route, b.expected_status = "exception", "exception"

    po_c = _small_po(w, rng, APPROVER_LIMIT_MINOR)
    c = _base(w, w.vendor(po_c.vendor_id), po_c, rng, "demo-c", 90003)
    c.demo_key, c.anomaly, c.layout = "c", "bank_change", 2
    c.invoice_number = "INV-1042"
    c.bank_account, c.bank_routing = "448812907315", "026009593"
    c.expected_flags = ["BANK_ACCOUNT_MISMATCH"]
    c.expected_route, c.expected_status = "approval", "awaiting_approval"

    po_d = _small_po(w, rng, AUTO_LIMIT_MINOR)
    d = _base(w, w.vendor(po_d.vendor_id), po_d, rng, "demo-d", 90004)
    d.demo_key, d.anomaly, d.layout = "d", "injection_white", 0
    d.invoice_number = "INV-1043"
    d.injection, d.injection_style = INJECTION_TEXTS[0], "white"
    d.expected_flags = ["INJECTION_DETECTED", "HIDDEN_TEXT"]
    d.expected_route, d.expected_status = "exception", "blocked"

    po_e = _small_po(w, rng, APPROVER_LIMIT_MINOR)
    e = _base(w, w.vendor(po_e.vendor_id), po_e, rng, "demo-e", 90005)
    e.demo_key, e.anomaly, e.layout, e.scan = "e", "scan", 1, True
    e.invoice_number = "INV-1044"
    e.expected_route, e.expected_status = "approval", "awaiting_approval"
    return [a, b, c, d, e]


GOLDEN_MIX = {
    # ~120 clean, ~80 anomalies; ≥ 20 injections, ≥ 15 scans (§B13)
    "clean": 120, "price_variance": 6, "qty_variance": 4, "missing_po": 4, "missing_receipt": 4,
    "duplicate_exact": 3, "duplicate_fuzzy": 3, "bank_change": 5, "unknown_vendor": 3, "tax_error": 3,
    "arithmetic_error": 3, "currency_mismatch": 2, "split_invoice": 3, "injection_visible": 5,
    "injection_white": 6, "injection_tiny": 5, "injection_line": 5, "pii_heavy": 3, "credit_note": 2,
    "freight_line": 3, "scan": 15,
}


def golden_cases(w: World) -> list[InvoiceSpec]:
    rng = random.Random(w.seed * 1000 + 2)
    out: list[InvoiceSpec] = []
    n = 10000
    for anomaly, count in GOLDEN_MIX.items():
        for _ in range(count):
            n += 1
            case_id = f"g{n:05d}"
            if anomaly in ("duplicate_exact", "duplicate_fuzzy"):
                prior = next((c for c in out if c.anomaly == "clean" and c.duplicate_of is None and c.expected_route == "auto"), None)
                if prior is None:
                    continue
                s = InvoiceSpec(**{**asdict(prior), "lines": [Line(**asdict(x)) for x in prior.lines]})
                s.case_id, s.anomaly, s.duplicate_of = case_id, anomaly, prior.case_id
                if anomaly == "duplicate_fuzzy":
                    s.invoice_number = prior.invoice_number.replace("-", "") + "A"
                    d = date.fromisoformat(prior.invoice_date) + timedelta(days=rng.randint(2, 10))
                    s.invoice_date = d.isoformat()
                s.expected_flags = ["DUPLICATE_EXACT" if anomaly == "duplicate_exact" else "DUPLICATE_SUSPECTED"]
                s.expected_route, s.expected_status = "approval", "awaiting_approval"
                s.notes = f"duplicate of {prior.case_id}; evaluated in workflow mode after {prior.case_id} is posted"
                out.append(s)
                continue
            out.append(make_case(w, anomaly, rng, case_id, n))
    return out
