"""Pydantic models for structured router outputs. Bounded fields; extra keys rejected."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DocClassification(Strict):
    doc_type: Literal["invoice", "credit_note", "statement", "other"]
    confidence: float = Field(ge=0, le=1)


class EvidenceSpan(Strict):
    page: int = Field(ge=1, le=200)
    snippet: str = Field(max_length=300)


class ExtractedLine(Strict):
    description: str = Field(max_length=500)
    quantity: str = Field(max_length=32)
    unit_price: str = Field(max_length=32)
    amount: str = Field(max_length=32)
    uom: str | None = Field(default=None, max_length=16)
    evidence: EvidenceSpan | None = None


class InvoiceExtractionOut(Strict):
    vendor_name: str | None = Field(default=None, max_length=200)
    vendor_tax_id: str | None = Field(default=None, max_length=40)
    invoice_number: str | None = Field(default=None, max_length=64)
    invoice_date: str | None = Field(default=None, max_length=32)
    due_date: str | None = Field(default=None, max_length=32)
    currency: str | None = Field(default=None, max_length=3)
    po_number: str | None = Field(default=None, max_length=64)
    subtotal: str | None = Field(default=None, max_length=32)
    tax: str | None = Field(default=None, max_length=32)
    total: str | None = Field(default=None, max_length=32)
    bank_account: str | None = Field(default=None, max_length=64)
    lines: list[ExtractedLine] = Field(default_factory=list, max_length=200)
    evidence: dict[str, EvidenceSpan] = Field(default_factory=dict)


class GlLine(Strict):
    line_index: int = Field(ge=0, le=500)
    gl_account: str = Field(max_length=16)
    cost_center: str = Field(max_length=16)
    rationale: str = Field(max_length=400)


class GlCodingOut(Strict):
    lines: list[GlLine] = Field(max_length=200)


class RubricScore(Strict):
    score: float = Field(ge=0, le=1)
    explanation: str = Field(max_length=800)


class JudgeOut(Strict):
    correctness: RubricScore
    relevance: RubricScore
    faithfulness: RubricScore | None = None
    completeness: RubricScore
    clarity: RubricScore
    unsupported_claims: list[str] = Field(default_factory=list, max_length=50)
