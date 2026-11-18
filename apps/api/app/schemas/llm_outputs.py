"""Pydantic models for structured router outputs. Bounded fields; extra keys rejected."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Lenient(BaseModel):
    """Extraction outputs: models add harmless extra keys and print numbers as numbers.
    Extra keys are dropped and numbers coerced to strings; bounds still apply, and every value is
    cross-checked against the source afterwards (extraction.normalize)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True, coerce_numbers_to_str=True)


class DocClassification(Strict):
    doc_type: Literal["invoice", "credit_note", "statement", "other"]
    confidence: float = Field(ge=0, le=1)


class EvidenceSpan(Lenient):
    page: int = Field(default=1, ge=1, le=200)
    snippet: str = Field(default="", max_length=300)


class ExtractedLine(Lenient):
    description: str = Field(max_length=500)
    quantity: str = Field(max_length=32)
    unit_price: str = Field(max_length=32)
    amount: str = Field(max_length=32)
    uom: str | None = Field(default=None, max_length=16)
    evidence: EvidenceSpan | str | None = None


class InvoiceExtractionOut(Lenient):
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
    bank_routing: str | None = Field(default=None, max_length=32)
    lines: list[ExtractedLine] = Field(default_factory=list, max_length=200)
    evidence: dict[str, EvidenceSpan | str | None] = Field(default_factory=dict)


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


class FinanceClaim(Strict):
    claim: str = Field(min_length=1, max_length=600)
    verdict: Literal["supported", "contradicted", "insufficient_evidence"]
    source_ids: list[str] = Field(max_length=10)
    reason: str = Field(min_length=1, max_length=600)


class FinanceVerdict(Strict):
    claims: list[FinanceClaim] = Field(max_length=30)
    missing_required_facts: list[str] = Field(max_length=20)


class CopilotStep(Strict):
    """One step of the copilot's bounded tool loop (§B7).

    `action` is either `tool` (call one tool and continue) or `answer` (final answer with
    citations into the evidence collected so far).
    """

    action: Literal["tool", "answer"]
    reasoning: str = Field(default="", max_length=600)
    tool: str | None = Field(default=None, max_length=64)
    arguments: dict[str, object] | None = None
    answer: str | None = Field(default=None, max_length=4000)
    citations: list[str] = Field(default_factory=list, max_length=20)


class GlCoderOut(Strict):
    """Fine-tuned GL coder response (§B15)."""

    gl_account: str = Field(min_length=1, max_length=20)
    cost_center: str = Field(min_length=1, max_length=20)
    rationale: str = Field(default="", max_length=400)
