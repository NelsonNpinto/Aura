"""Money as integer minor units + ISO 4217 currency (§B5). Never floats."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MINOR_UNITS: dict[str, int] = {"USD": 2, "EUR": 2, "GBP": 2, "INR": 2, "JPY": 0, "CAD": 2, "AUD": 2}
_NUM = re.compile(r"^\(?-?[\d,.\s']+\)?$")


class MoneyError(ValueError):
    pass


def exponent(currency: str) -> int:
    try:
        return MINOR_UNITS[currency.upper()]
    except KeyError as exc:
        raise MoneyError(f"unsupported currency {currency!r}") from exc


def parse_decimal(raw: str) -> Decimal:
    """Parses '1,234.50', '1.234,50', '(12.00)' (negative), '-12', '1 234.5'. Rejects junk."""
    s = raw.strip().replace("\u00a0", " ")
    for sym in ("$", "€", "£", "₹", "USD", "EUR", "GBP", "INR"):
        s = s.replace(sym, "")
    s = s.strip()
    if not s or not _NUM.match(s):
        raise MoneyError(f"not a number: {raw!r}")
    neg = (s.startswith("(") and s.endswith(")")) or s.startswith("-")
    s = s.strip("()-").replace(" ", "").replace("'", "")
    if "," in s and "." in s:
        dec_sep = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        # '1,234' is thousands; '12,50' is a decimal comma
        dec_sep = "," if len(s.split(",")[-1]) in (1, 2) else ""
    else:
        dec_sep = "."
    thou = {",": ".", ".": ","}.get(dec_sep, ",")
    s = s.replace(thou, "")
    if dec_sep == ",":
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise MoneyError(f"not a number: {raw!r}") from exc
    return -d if neg else d


def to_minor(amount: Decimal | str, currency: str) -> int:
    d = parse_decimal(amount) if isinstance(amount, str) else amount
    q = Decimal(1).scaleb(-exponent(currency))
    return int(
        (d.quantize(q, rounding=ROUND_HALF_UP) * (10 ** exponent(currency))).to_integral_value()
    )


def format_minor(minor: int, currency: str) -> str:
    e = exponent(currency)
    return f"{Decimal(minor).scaleb(-e):,.{e}f} {currency}"


@dataclass(frozen=True)
class FxRate:
    base: str
    quote: str
    on: date
    rate: Decimal  # 1 quote = rate base


class FxTable:
    """Dated FX table: uses the latest rate on or before the invoice date (§B18)."""

    def __init__(self, base: str, rates: list[FxRate]) -> None:
        self.base = base
        self.rates = sorted(rates, key=lambda r: r.on)

    def to_base(self, minor: int, currency: str, on: date) -> int:
        if currency == self.base:
            return minor
        cands = [r for r in self.rates if r.quote == currency and r.on <= on]
        if not cands:
            raise MoneyError(f"no {currency}->{self.base} rate on or before {on}")
        amount = Decimal(minor).scaleb(-exponent(currency)) * cands[-1].rate
        return to_minor(amount, self.base)
