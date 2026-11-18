"""Assignment workflow: explicit evidence, deterministic matching, mandatory human stages."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.errors import Conflict, Forbidden

PURCHASING_DEMO_ORG = "purchasing-demo"


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sku: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, le=1000000, max_digits=12, decimal_places=3)
    unit_price_minor: int = Field(strict=True, ge=0, le=1000000000)


class EvidenceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    number: str = Field(min_length=1, max_length=80)
    po_number: str = Field(min_length=1, max_length=80)
    currency: Literal["INR", "USD", "EUR", "GBP"]
    lines: list[Line] = Field(min_length=1, max_length=100)
    tax_minor: int = Field(default=0, strict=True, ge=0, le=1000000000)
    total_minor: int = Field(strict=True, ge=0, le=100000000000)
    source_document_id: str | None = Field(default=None, max_length=64)

    @field_validator("lines")
    @classmethod
    def unique_skus(cls, lines: list[Line]) -> list[Line]:
        if len({x.sku for x in lines}) != len(lines):
            raise ValueError("Combine repeated SKU quantities before confirming")
        return lines

    @model_validator(mode="after")
    def arithmetic(self) -> EvidenceDocument:
        total = sum(x.quantity * x.unit_price_minor for x in self.lines) + self.tax_minor
        if total != self.total_minor:
            raise ValueError("Line amounts plus tax must equal the total in minor units")
        return self


def compare(documents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [k for k in ("po", "invoice", "receipt") if k not in documents]
    if missing:
        return {"matched": False, "missing": missing, "findings": []}
    po, invoice, receipt = (
        EvidenceDocument.model_validate(documents[k]) for k in ("po", "invoice", "receipt")
    )
    findings: list[dict[str, Any]] = []
    for kind, doc in (("invoice", invoice), ("receipt", receipt)):
        if doc.po_number != po.po_number or doc.currency != po.currency:
            findings.append({"code": "HEADER_MISMATCH", "document": kind})
    orders = {x.sku: x for x in po.lines}
    received = {x.sku: x for x in receipt.lines}
    for line in invoice.lines:
        ordered, delivered = orders.get(line.sku), received.get(line.sku)
        if not ordered:
            findings.append({"code": "NO_PO_LINE", "sku": line.sku})
            continue
        if not delivered or line.quantity > delivered.quantity or line.quantity > ordered.quantity:
            findings.append(
                {
                    "code": "QUANTITY_SHORTFALL",
                    "sku": line.sku,
                    "ordered": str(ordered.quantity),
                    "invoiced": str(line.quantity),
                    "received": str(delivered.quantity if delivered else 0),
                }
            )
        if line.unit_price_minor != ordered.unit_price_minor:
            findings.append(
                {
                    "code": "PRICE_VARIANCE",
                    "sku": line.sku,
                    "po_minor": ordered.unit_price_minor,
                    "invoice_minor": line.unit_price_minor,
                }
            )
    for line in receipt.lines:
        if line.sku not in orders or line.quantity > orders[line.sku].quantity:
            findings.append({"code": "UNEXPECTED_RECEIPT", "sku": line.sku})
    return {
        "matched": not findings,
        "missing": [],
        "findings": findings,
        "policy": "Exact unit prices; invoiced quantity may not exceed ordered or received quantity",
    }


def transition(
    state: dict[str, Any], action: str, actor: str, roles: frozenset[str], comment: str
) -> dict[str, Any]:
    """Called under a row lock. Every approval binds to the current document revision."""
    status = state["status"]
    stage = {"awaiting_l1": "l1", "awaiting_finance": "finance"}.get(status)
    if not stage or action not in (stage, "reject"):
        raise Conflict("Approval stage is not ready", code="stage_not_ready")
    required = {"approver"} if stage == "l1" else {"finance", "controller"}
    if not roles & required:
        raise Forbidden("This review requires a designated reviewer")
    uploaders = {d["actor"] for d in state.get("evidence", {}).values()}
    if state.get("created_by"):
        uploaders.add(state["created_by"])
    if actor in uploaders or any(a["actor"] == actor for a in state["approvals"]):
        raise Forbidden(
            "Uploader and reviewers must be distinct people", code="segregation_of_duties"
        )
    decision = {"stage": stage, "actor": actor, "comment": comment, "revision": state["revision"]}
    if action == "reject":
        state["correction"] = decision
        state["approvals"] = []
        state["status"] = "needs_correction"
    else:
        if not compare(state["documents"])["matched"]:
            raise Conflict("Resolve document discrepancies first")
        state["approvals"].append(decision)
        state["status"] = "awaiting_finance" if action == "l1" else "approved_for_payment"
    return state
