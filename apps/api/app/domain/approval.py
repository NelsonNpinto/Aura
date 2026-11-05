"""Approval matrix (§B6). Amounts compare in the org's base currency, minor units."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.flags import Flag, Severity


class Level(StrEnum):
    AUTO = "auto"
    APPROVER = "approver"
    CONTROLLER = "controller"


ROLE_RANK = {"approver": 1, "controller": 2, "admin": 2}


@dataclass(frozen=True)
class ApprovalMatrix:
    auto_limit_minor: int = 100_000  # $1,000
    approver_limit_minor: int = 1_000_000  # $10,000
    currency: str = "USD"

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> ApprovalMatrix:
        return cls(
            int(d["auto_limit_minor"]),
            int(d["approver_limit_minor"]),
            str(d.get("currency", "USD")),
        )


@dataclass(frozen=True)
class Requirement:
    level: Level
    callback_verification: bool
    reasons: tuple[str, ...]


def required_approval(amount_base_minor: int, flags: list[Flag], m: ApprovalMatrix) -> Requirement:
    reasons: list[str] = []
    bank_change = any(f.code == "BANK_ACCOUNT_MISMATCH" for f in flags)
    high = [f.code for f in flags if f.severity == Severity.HIGH]
    medium = [f.code for f in flags if f.severity == Severity.MEDIUM]
    if bank_change:
        reasons.append("bank detail change requires controller + call-back")
    if high:
        reasons.append(f"HIGH flags: {', '.join(sorted(set(high)))}")
    if amount_base_minor > m.approver_limit_minor:
        reasons.append(f"amount above approver limit {m.approver_limit_minor}")
    if reasons:
        return Requirement(Level.CONTROLLER, bank_change, tuple(reasons))
    if medium:
        reasons.append(f"MEDIUM flags: {', '.join(sorted(set(medium)))}")
    if amount_base_minor > m.auto_limit_minor:
        reasons.append(f"amount above auto-approve limit {m.auto_limit_minor}")
    if reasons:
        return Requirement(Level.APPROVER, False, tuple(reasons))
    return Requirement(Level.AUTO, False, ("within auto-approve limit, no flags",))
