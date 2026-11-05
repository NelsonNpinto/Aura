"""Deterministic three-way match (§B6 `match`, §B18). No LLM: the model only explains results.

Each invoice line is matched to a PO line (PO number, description similarity, price), then
checked against received quantity (GRN) and quantity already billed. Service lines are two-way
(invoice vs PO) and need requester confirmation instead of a receipt.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class LineOutcome(StrEnum):
    MATCHED = "matched"
    PRICE_VARIANCE = "price_variance"
    QTY_VARIANCE = "qty_variance"
    NO_PO = "no_po"
    NO_RECEIPT = "no_receipt"
    UOM_MISMATCH = "uom_mismatch"
    NON_PO_CHARGE = "non_po_charge"  # freight/discount/surcharge not on the PO


UNRESOLVED = {LineOutcome.NO_PO, LineOutcome.NO_RECEIPT, LineOutcome.UOM_MISMATCH}
NON_PO_KEYWORDS = ("freight", "shipping", "delivery charge", "surcharge", "discount", "handling")

# (from_uom, to_uom) -> factor: 1 from = factor to
UOM_FACTORS: dict[tuple[str, str], Decimal] = {
    ("box12", "each"): Decimal(12),
    ("dozen", "each"): Decimal(12),
    ("pack10", "each"): Decimal(10),
    ("case24", "each"): Decimal(24),
    ("kg", "g"): Decimal(1000),
    ("hour", "minute"): Decimal(60),
}


@dataclass(frozen=True)
class Tolerances:
    price_pct: Decimal = Decimal("0.02")
    price_abs_minor: int = 500  # $5.00
    header_pct: Decimal = Decimal("0.005")
    non_po_charge_pct: Decimal = Decimal("0.03")  # freight etc. up to 3% of goods value


@dataclass(frozen=True)
class InvoiceLine:
    index: int
    description: str
    quantity: Decimal
    unit_price_minor: int
    amount_minor: int
    uom: str = "each"
    po_number: str | None = None


@dataclass(frozen=True)
class POLine:
    po_number: str
    line_no: int
    description: str
    quantity: Decimal
    unit_price_minor: int
    uom: str = "each"
    received_qty: Decimal = Decimal(0)
    billed_qty: Decimal = Decimal(0)  # already invoiced on earlier invoices
    is_service: bool = False


@dataclass
class LineMatch:
    index: int
    outcome: LineOutcome
    po_number: str | None = None
    po_line: int | None = None
    similarity: float = 0.0
    invoice_unit_price_minor: int = 0
    po_unit_price_minor: int | None = None
    price_diff_minor: int = 0
    price_tolerance_minor: int = 0
    invoice_qty: Decimal = Decimal(0)
    available_qty: Decimal | None = None
    needs_service_confirmation: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    lines: list[LineMatch]
    header_ok: bool
    invoice_subtotal_minor: int
    expected_total_minor: int
    over_billed: list[str]

    @property
    def unresolved(self) -> bool:
        return any(m.outcome in UNRESOLVED for m in self.lines)

    @property
    def variances(self) -> list[LineMatch]:
        return [
            m
            for m in self.lines
            if m.outcome in (LineOutcome.PRICE_VARIANCE, LineOutcome.QTY_VARIANCE)
        ]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()


def similarity(a: str, b: str) -> float:
    a2, b2 = _norm(a), _norm(b)
    ta, tb = set(a2.split()), set(b2.split())
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return round(max(jac, difflib.SequenceMatcher(None, a2, b2).ratio()), 3)


def convert_qty(qty: Decimal, from_uom: str, to_uom: str) -> Decimal | None:
    f, t = from_uom.lower(), to_uom.lower()
    if f == t:
        return qty
    if (f, t) in UOM_FACTORS:
        return qty * UOM_FACTORS[(f, t)]
    if (t, f) in UOM_FACTORS:
        return qty / UOM_FACTORS[(t, f)]
    return None


def price_tolerance(po_price_minor: int, tol: Tolerances) -> int:
    return max(int(Decimal(po_price_minor) * tol.price_pct), tol.price_abs_minor)


def _is_non_po_charge(desc: str) -> bool:
    d = desc.lower()
    return any(k in d for k in NON_PO_KEYWORDS)


def three_way_match(
    lines: list[InvoiceLine],
    po_lines: list[POLine],
    *,
    invoice_subtotal_minor: int,
    header_po: str | None = None,
    tol: Tolerances | None = None,
) -> MatchResult:
    tol = tol or Tolerances()
    used: set[tuple[str, int]] = set()
    results: list[LineMatch] = []
    goods_value = 0
    billed_now: dict[tuple[str, int], Decimal] = {}

    for ln in lines:
        po_no = ln.po_number or header_po
        cands = [
            p
            for p in po_lines
            if (po_no is None or p.po_number == po_no) and (p.po_number, p.line_no) not in used
        ]
        m = LineMatch(
            ln.index,
            LineOutcome.NO_PO,
            invoice_unit_price_minor=ln.unit_price_minor,
            invoice_qty=ln.quantity,
        )
        if _is_non_po_charge(ln.description) and not any(
            similarity(ln.description, p.description) >= 0.6 for p in cands
        ):
            m.outcome = LineOutcome.NON_PO_CHARGE
            results.append(m)
            continue
        if not cands:
            m.notes.append(
                "no purchase order line available" if po_no else "no PO number on invoice"
            )
            results.append(m)
            continue

        def score(p: POLine, ln: InvoiceLine = ln) -> float:
            sim = similarity(ln.description, p.description)
            price_gap = abs(ln.unit_price_minor - p.unit_price_minor) / max(p.unit_price_minor, 1)
            return sim - min(price_gap, 1.0) * 0.3

        best = max(cands, key=score)
        sim = similarity(ln.description, best.description)
        if sim < 0.35:
            m.notes.append(f"best PO line similarity {sim:.2f} below 0.35")
            results.append(m)
            continue
        used.add((best.po_number, best.line_no))
        m.po_number, m.po_line, m.similarity = best.po_number, best.line_no, sim

        qty = convert_qty(ln.quantity, ln.uom, best.uom)
        if qty is None:
            m.outcome = LineOutcome.UOM_MISMATCH
            m.notes.append(f"no conversion {ln.uom} -> {best.uom}")
            results.append(m)
            continue
        # unit price in PO's UOM
        inv_price = (
            ln.unit_price_minor
            if qty == ln.quantity
            else int(Decimal(ln.amount_minor) / qty)
            if qty
            else ln.unit_price_minor
        )
        m.invoice_unit_price_minor = inv_price
        m.invoice_qty = qty
        m.po_unit_price_minor = best.unit_price_minor
        m.price_diff_minor = inv_price - best.unit_price_minor
        m.price_tolerance_minor = price_tolerance(best.unit_price_minor, tol)
        goods_value += (
            best.unit_price_minor * int(qty)
            if qty == qty.to_integral()
            else int(best.unit_price_minor * qty)
        )

        key = (best.po_number, best.line_no)
        billed_now[key] = billed_now.get(key, Decimal(0)) + qty
        if best.is_service:
            available = best.quantity - best.billed_qty
            m.needs_service_confirmation = True
        else:
            available = best.received_qty - best.billed_qty
        m.available_qty = available

        if not best.is_service and best.received_qty <= 0:
            m.outcome = LineOutcome.NO_RECEIPT
        elif abs(m.price_diff_minor) > m.price_tolerance_minor:
            m.outcome = LineOutcome.PRICE_VARIANCE
        elif qty > available:
            m.outcome = LineOutcome.QTY_VARIANCE
        else:
            m.outcome = LineOutcome.MATCHED
        results.append(m)

    # Non-PO charges: within tolerance of goods value → matched with note; else stays non_po_charge
    for m in results:
        if m.outcome == LineOutcome.NON_PO_CHARGE:
            ln = next(x for x in lines if x.index == m.index)
            limit = int(Decimal(goods_value) * tol.non_po_charge_pct)
            if ln.amount_minor <= limit or ln.amount_minor < 0:
                m.notes.append(f"non-PO charge within {tol.non_po_charge_pct:%} of goods value")
            else:
                m.notes.append(f"non-PO charge {ln.amount_minor} exceeds tolerance {limit}")

    over = [
        f"{po}#{no}"
        for (po, no), q in billed_now.items()
        for p in po_lines
        if p.po_number == po and p.line_no == no and p.billed_qty + q > p.quantity
    ]
    expected = sum(
        (m.po_unit_price_minor or 0) * int(m.invoice_qty)
        if m.invoice_qty == m.invoice_qty.to_integral()
        else int((m.po_unit_price_minor or 0) * m.invoice_qty)
        for m in results
        if m.po_unit_price_minor is not None
    ) + sum(
        next(x for x in lines if x.index == m.index).amount_minor
        for m in results
        if m.outcome == LineOutcome.NON_PO_CHARGE
    )
    # Lines with no PO line are judged per line (no_po), not by the header check.
    unmatched_amount = sum(
        next(x for x in lines if x.index == m.index).amount_minor
        for m in results
        if m.po_unit_price_minor is None and m.outcome != LineOutcome.NON_PO_CHARGE
    )
    comparable = invoice_subtotal_minor - unmatched_amount
    header_ok = abs(comparable - expected) <= int(Decimal(max(expected, 1)) * tol.header_pct)
    return MatchResult(results, header_ok, invoice_subtotal_minor, expected, over)


def non_po_charge_excess(result: MatchResult) -> list[int]:
    return [
        m.index
        for m in result.lines
        if m.outcome == LineOutcome.NON_PO_CHARGE and any("exceeds" in n for n in m.notes)
    ]
