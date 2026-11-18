"""Vendor onboarding rules (§B5.3, Phase 5) — deterministic, no model calls.

The second workflow pack reuses the platform: the same tool gateway, guardrails, audit chain and
eval harness. Only the domain rules are new, and they live here so they can be unit-tested
table-driven, exactly like the three-way match.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

REQUIRED_DOCUMENTS = ("registration_certificate", "tax_certificate", "bank_proof")
TAX_ID_PATTERNS = {
    "US_EIN": re.compile(r"^\d{2}-\d{7}$"),
    "IN_GSTIN": re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"),
    "IN_PAN": re.compile(r"^[A-Z]{5}\d{4}[A-Z]$"),
    "EU_VAT": re.compile(r"^[A-Z]{2}[0-9A-Z]{8,12}$"),
}
# Mock sanctions list: synthetic names only. A real deployment would call a licensed provider.
SANCTIONS_LIST = (
    "orion shell holdings",
    "northwind proxy ltd",
    "greyline trading fze",
)


class Route(StrEnum):
    AUTO = "auto"
    APPROVAL = "approval"
    REJECT = "reject"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Assessment:
    route: Route
    score: int
    findings: tuple[Finding, ...]
    required_role: str | None

    def public(self) -> dict[str, Any]:
        return {
            "route": self.route.value,
            "score": self.score,
            "required_role": self.required_role,
            "findings": [asdict(f) for f in self.findings],
        }


def normalize_name(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).casefold()
    stripped = re.sub(
        r"\b(inc|incorporated|ltd|limited|llc|plc|gmbh|pvt|private|fze|co)\b", " ", folded
    )
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def account_hash(routing: str, account_number: str) -> str:
    return hashlib.sha256(f"{routing}:{account_number}".encode()).hexdigest()


def tax_id_valid(tax_id: str, scheme: str | None = None) -> bool:
    value = (tax_id or "").strip().upper()
    if not value:
        return False
    if scheme:
        pattern = TAX_ID_PATTERNS.get(scheme)
        return bool(pattern and pattern.match(value))
    return any(p.match(value) for p in TAX_ID_PATTERNS.values())


def sanctions_match(name: str) -> str | None:
    target = normalize_name(name)
    for listed in SANCTIONS_LIST:
        if normalize_name(listed) == target:
            return listed
    return None


def assess(
    *,
    legal_name: str,
    tax_id: str,
    tax_scheme: str | None,
    documents: dict[str, Any],
    bank: dict[str, Any],
    existing_vendor_names: list[str] | None = None,
    employee_bank_hashes: list[str] | None = None,
) -> Assessment:
    """Deterministic onboarding assessment. Nothing here depends on a model."""
    findings: list[Finding] = []
    score = 0

    missing = [d for d in REQUIRED_DOCUMENTS if not documents.get(d)]
    if missing:
        score += 25
        findings.append(
            Finding(
                "KYC_DOCUMENTS_MISSING",
                "HIGH",
                f"Missing: {', '.join(missing)}",
                {"missing": missing},
            )
        )

    if not tax_id_valid(tax_id, tax_scheme):
        score += 20
        findings.append(
            Finding(
                "TAX_ID_INVALID",
                "HIGH",
                "Tax identifier does not match a known format",
                {"scheme": tax_scheme},
            )
        )

    if listed := sanctions_match(legal_name):
        score += 60
        findings.append(
            Finding(
                "SANCTIONS_MATCH",
                "HIGH",
                "Legal name matches the screening list",
                {"matched": listed},
            )
        )

    routing, number = str(bank.get("routing") or ""), str(bank.get("account_number") or "")
    if not (routing and number):
        score += 20
        findings.append(Finding("BANK_DETAILS_MISSING", "HIGH", "Bank details are incomplete"))
    else:
        digest = account_hash(routing, number)
        if digest in set(employee_bank_hashes or []):
            score += 60
            findings.append(
                Finding(
                    "VENDOR_EMPLOYEE_CONFLICT",
                    "HIGH",
                    "Proposed bank account belongs to an employee",
                    {"last4": number[-4:]},
                )
            )
        if not bank.get("verified_by_callback"):
            score += 15
            findings.append(
                Finding(
                    "BANK_NOT_VERIFIED",
                    "MEDIUM",
                    "Bank details have not been verified by documented call-back",
                )
            )

    target = normalize_name(legal_name)
    duplicates = [n for n in (existing_vendor_names or []) if normalize_name(n) == target]
    if duplicates:
        score += 15
        findings.append(
            Finding(
                "DUPLICATE_VENDOR",
                "MEDIUM",
                "A vendor with the same normalised name already exists",
                {"matches": duplicates[:3]},
            )
        )

    if any(f.code == "SANCTIONS_MATCH" for f in findings):
        return Assessment(Route.REJECT, min(score, 100), tuple(findings), "controller")
    if any(f.severity == "HIGH" for f in findings):
        return Assessment(Route.APPROVAL, min(score, 100), tuple(findings), "controller")
    if findings:
        return Assessment(Route.APPROVAL, min(score, 100), tuple(findings), "approver")
    return Assessment(Route.AUTO, 0, (), None)
