"""Flag catalogue. Severity drives deterministic routing (§B6 risk_route)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


SEVERITY: dict[str, Severity] = {
    # HIGH → controller
    "BANK_ACCOUNT_MISMATCH": Severity.HIGH,
    "INJECTION_DETECTED": Severity.HIGH,
    "HIDDEN_TEXT": Severity.HIGH,
    "DUPLICATE_EXACT": Severity.HIGH,
    "DUPLICATE_SUSPECTED": Severity.HIGH,
    "VENDOR_EMPLOYEE_CONFLICT": Severity.HIGH,
    "SHARED_BANK_ACCOUNT": Severity.HIGH,
    "SPLIT_INVOICE_SUSPECTED": Severity.HIGH,
    "OVER_BILLING": Severity.HIGH,
    # MEDIUM → approver
    "PRICE_VARIANCE_WITHIN_APPROVAL": Severity.MEDIUM,
    "LOW_EXTRACTION_CONFIDENCE": Severity.MEDIUM,
    "UNVERIFIED_FIELD": Severity.MEDIUM,
    "NEW_VENDOR": Severity.MEDIUM,
    "VENDOR_AMBIGUOUS": Severity.MEDIUM,
    "GRAPH_UNAVAILABLE": Severity.MEDIUM,
    "TAX_MISMATCH": Severity.MEDIUM,
    "ARITHMETIC_ERROR": Severity.MEDIUM,
    "PII_PRESENT": Severity.LOW,
    "FREIGHT_WITHIN_TOLERANCE": Severity.LOW,
}


@dataclass(frozen=True)
class Flag:
    code: str
    evidence: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    @property
    def severity(self) -> Severity:
        return SEVERITY.get(self.code, Severity.MEDIUM)  # unknown codes never pass silently
