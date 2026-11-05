"""PII detection and redaction (§B11). Runs before external LLM calls, logs and traces.

Keeps last4 for display where that is useful (accounts, cards). Deterministic, regex + checksum based.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _iban_ok(raw: str) -> bool:
    s = raw.replace(" ", "").upper()
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in rearranged)
    return int(num) % 97 == 1


@dataclass(frozen=True)
class PiiKind:
    name: str
    pattern: re.Pattern[str]
    keep_last4: bool = False
    validate: Callable[[str], bool] | None = None


_KINDS: list[PiiKind] = [
    PiiKind("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    PiiKind(
        "IBAN",
        re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b"),
        keep_last4=True,
        validate=_iban_ok,
    ),
    PiiKind(
        "CARD",
        re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
        keep_last4=True,
        validate=lambda s: _luhn_ok(re.sub(r"\D", "", s)),
    ),
    PiiKind("SSN", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
    PiiKind("EIN", re.compile(r"\b\d{2}-\d{7}\b")),
    PiiKind("GSTIN", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")),
    PiiKind("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    PiiKind(
        "ROUTING_ACCOUNT",
        re.compile(r"(?i)\b(?:acct|account|a/c|routing|aba)[\s#:no.]*([0-9]{6,17})\b"),
        keep_last4=True,
    ),
    PiiKind(
        "PHONE", re.compile(r"(?<!\w)\+?\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b")
    ),
]


@dataclass(frozen=True)
class PiiFinding:
    kind: str
    start: int
    end: int
    last4: str | None


def find_pii(text: str) -> list[PiiFinding]:
    findings: list[PiiFinding] = []
    taken: list[tuple[int, int]] = []
    for kind in _KINDS:
        for m in kind.pattern.finditer(text):
            span = m.span(1) if m.lastindex else m.span()
            value = text[span[0] : span[1]]
            if kind.validate and not kind.validate(value):
                continue
            if any(not (span[1] <= a or span[0] >= b) for a, b in taken):
                continue
            digits = re.sub(r"[^0-9A-Za-z]", "", value)
            findings.append(
                PiiFinding(kind.name, span[0], span[1], digits[-4:] if kind.keep_last4 else None)
            )
            taken.append(span)
    return sorted(findings, key=lambda f: f.start)


BUSINESS_IDS = frozenset({"EIN", "GSTIN"})  # vendor tax IDs printed on invoices: business data


def redact(text: str, keep: frozenset[str] = frozenset()) -> str:
    out, cursor = [], 0
    for f in find_pii(text):
        if f.kind in keep:
            continue
        out.append(text[cursor : f.start])
        out.append(f"[{f.kind}…{f.last4}]" if f.last4 else f"[{f.kind}]")
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out)


def redact_any(value: Any) -> Any:
    """Recursively redact strings inside JSON-like structures."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_any(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_any(v) for v in value]
    return value
