"""Duplicate detection (§B6 intake_guard, §B18). Keys are vendor + normalised invoice number;
the same number from two vendors is not a duplicate."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date

_PREFIX = re.compile(r"^(INVOICE|INV|BILL|NO|NUMBER|#)+")


def normalize_invoice_number(raw: str) -> str:
    s = re.sub(r"[^A-Z0-9]", "", raw.upper())
    s = _PREFIX.sub("", s)
    return s.lstrip("0") or "0"


@dataclass(frozen=True)
class PriorInvoice:
    invoice_id: str
    vendor_id: str
    number: str
    total_minor: int
    currency: str
    invoice_date: date
    status: str = "posted"


@dataclass(frozen=True)
class DuplicateHit:
    kind: str  # exact | fuzzy
    invoice_id: str
    reasons: tuple[str, ...]


def find_duplicates(
    *,
    vendor_id: str,
    number: str,
    total_minor: int,
    currency: str,
    invoice_date: date,
    prior: list[PriorInvoice],
    amount_pct: float = 0.005,
    days: int = 30,
    number_similarity: float = 0.75,
) -> list[DuplicateHit]:
    key = normalize_invoice_number(number)
    hits: list[DuplicateHit] = []
    for p in prior:
        if p.vendor_id != vendor_id or p.status in ("rejected", "cancelled"):
            continue
        pkey = normalize_invoice_number(p.number)
        if pkey == key:
            hits.append(DuplicateHit("exact", p.invoice_id, ("same vendor and normalised number",)))
            continue
        if p.currency != currency:
            continue
        amount_close = abs(p.total_minor - total_minor) <= abs(total_minor) * amount_pct
        date_close = abs((p.invoice_date - invoice_date).days) <= days
        sim = difflib.SequenceMatcher(None, pkey, key).ratio()
        if amount_close and date_close and sim >= number_similarity:
            hits.append(
                DuplicateHit(
                    "fuzzy",
                    p.invoice_id,
                    (
                        f"amount within {amount_pct:.1%}",
                        f"date within {days} days",
                        f"number similarity {sim:.2f}",
                    ),
                )
            )
    return hits
