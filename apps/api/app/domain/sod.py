"""Segregation of duties (§B6 human_approval). Re-checked at decision time, never cached."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.approval import ROLE_RANK, Level


@dataclass(frozen=True)
class Approver:
    user_id: str
    roles: frozenset[str]
    limit_minor: int | None = None  # None = no personal limit beyond the role


@dataclass(frozen=True)
class InvoiceParties:
    preparer_id: str | None
    uploader_id: str | None
    vendor_bank_last_editor_id: str | None
    vendor_created_by: str | None = None


@dataclass(frozen=True)
class SodViolation:
    code: str
    message: str


def check_sod(
    approver: Approver, parties: InvoiceParties, required: Level, amount_base_minor: int
) -> list[SodViolation]:
    v: list[SodViolation] = []
    uid = approver.user_id
    if uid and uid in {parties.preparer_id, parties.uploader_id}:
        v.append(SodViolation("SOD_PREPARER", "Approver prepared or uploaded this invoice"))
    if uid and uid == parties.vendor_bank_last_editor_id:
        v.append(SodViolation("SOD_BANK_EDITOR", "Approver last edited this vendor's bank details"))
    if uid and uid == parties.vendor_created_by:
        v.append(SodViolation("SOD_VENDOR_CREATOR", "Approver created this vendor"))
    need = ROLE_RANK.get(required.value, 0)
    have = max((ROLE_RANK.get(r, 0) for r in approver.roles), default=0)
    if required != Level.AUTO and have < need:
        v.append(SodViolation("SOD_ROLE", f"Requires role {required.value}"))
    if approver.limit_minor is not None and amount_base_minor > approver.limit_minor:
        v.append(SodViolation("SOD_LIMIT", "Amount exceeds approver's limit"))
    return v
