"""Read-only, evidence-scoped assistant. No generated SQL, write tools or payment actions."""

import asyncio
import json
import re
import uuid
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import call_context
from app.api.v1.procurement import actor, case_row
from app.core.auth import CurrentPrincipal
from app.core.db import tenant_tx
from app.core.errors import Forbidden, RateLimited
from app.core.limits import charge_run
from app.guardrails.pii import redact, redact_any
from app.llm.router import CallContext, ModelRouter, RouterError, get_router
from app.rag.service import answer

router = APIRouter(prefix="/procurement/copilot", tags=["copilot"])


class Question(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=500)
    case_id: uuid.UUID | None = None
    case_topic: Literal["status", "match", "payment"] | None = None


class CaseAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=5000)
    evidence_ids: list[str] = Field(max_length=10)
    needs_more_evidence: bool


@router.post("/ask")
async def ask(body: Question, request: Request, p: CurrentPrincipal) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if "vendor" in roles and (not vendor or not body.case_id):
        raise Forbidden("Vendor questions must reference an assigned case")
    context = call_context(request, p)
    if body.case_id:
        async with tenant_tx(p.org_id, p.user_id) as session:
            row = await case_row(session, p, body.case_id, vendor)
        evidence = case_evidence(row["state"])
        if body.case_topic:
            return case_snapshot(evidence, body.case_topic)
        try:
            await charge_run(p)
            async with asyncio.timeout(18):
                case_result = await answer_case(body.question, evidence, context, get_router())
        except (RouterError, RateLimited, TimeoutError):
            return case_snapshot(evidence, "status", fallback=True)
        if not case_result["citation_valid"]:
            return {**case_result, "snapshot": case_snapshot(evidence, "status")}
        return case_result
    result = await answer(
        p,
        redact(body.question),
        router=get_router(),
        ctx=context,
    )
    return {
        "answer": result.text,
        "sources": [
            {"id": str(i), "evidence": asdict(hit)} for i, hit in enumerate(result.sources, 1)
        ],
        "citation_valid": result.citations["valid"],
        "source_only": result.source_only,
        "llm": result.llm,
    }


def case_evidence(state: dict[str, Any]) -> dict[str, Any]:
    documents = state["documents"]
    status = {"status": state["status"], "revision": state["revision"]}
    missing = [kind for kind in ("po", "invoice", "receipt") if kind not in documents]
    if missing:
        status["missing_documents"] = missing
    evidence: dict[str, Any] = {
        **documents,
        "status": status,
        "payment": state.get("payment") or {"recorded": False},
    }
    if approvals := state.get("approvals"):
        evidence["approvals"] = approvals
    if correction := state.get("correction"):
        evidence["correction"] = correction
    if comparison := state.get("comparison"):
        currency = documents.get("po", {}).get("currency")
        same_currency = currency and currency == documents.get("invoice", {}).get("currency")
        findings = []
        for finding in comparison.get("findings", []):
            if finding["code"] == "PRICE_VARIANCE" and same_currency:
                finding = {
                    **finding,
                    "currency": currency,
                    "difference_minor": finding["invoice_minor"] - finding["po_minor"],
                }
            elif finding["code"] == "QUANTITY_SHORTFALL":
                unreceived = Decimal(finding["invoiced"]) - Decimal(finding["received"])
                finding = {**finding, "unreceived_quantity": str(max(Decimal(0), unreceived))}
            findings.append(finding)
        evidence["comparison"] = {**comparison, "findings": findings}
        if state["status"] == "needs_correction" and findings:
            status["explanation"] = (
                "The case is on hold for correction. Resolve the document comparison findings "
                "before approval."
            )
    return evidence


_STATES = {
    "collecting_documents": "The case is waiting for confirmed documents.",
    "needs_correction": "The case is on hold for correction.",
    "awaiting_l1": "The case is waiting for L1 approval.",
    "awaiting_finance": "The case is waiting for finance approval.",
    "approved_for_payment": "Both reviews are complete. Finance can record the payment.",
    "paid": "A simulated payment is recorded.",
}
_DOCUMENTS = {"po": "purchase order", "invoice": "vendor invoice", "receipt": "goods receipt"}


def _money(amount: int, currency: str) -> str:
    return f"{currency} {Decimal(amount) / 100:,.2f}"


def case_snapshot(
    evidence: dict[str, Any], topic: str, *, fallback: bool = False
) -> dict[str, Any]:
    status = evidence["status"]["status"]
    parts = [f"{_STATES.get(status, 'Open Purchasing to review the case stage.')} [status]"]
    ids = ["status"]
    missing = [name for kind, name in _DOCUMENTS.items() if kind not in evidence]
    comparison = evidence.get("comparison")
    if topic in ("status", "match"):
        if evidence.get("correction"):
            parts.append("A reviewer requested a correction. See the review note. [correction]")
            ids.append("correction")
        if missing:
            parts.append("Still needed: " + ", ".join(missing) + ". [status]")
        elif comparison:
            ids.append("comparison")
            if comparison["matched"]:
                parts.append("The three documents match. [comparison]")
            else:
                findings = []
                for finding in comparison["findings"]:
                    code = finding["code"]
                    if code == "QUANTITY_SHORTFALL":
                        shortfall = finding.get("unreceived_quantity", "0")
                        missing_units = (
                            f" The receipt is short by {shortfall}." if Decimal(shortfall) else ""
                        )
                        findings.append(
                            f"Invoiced {finding['invoiced']}, received {finding['received']}, "
                            f"ordered {finding['ordered']}.{missing_units} [comparison]"
                        )
                    elif code == "PRICE_VARIANCE" and finding.get("currency"):
                        currency = finding["currency"]
                        findings.append(
                            f"The invoice unit price is {_money(finding['invoice_minor'], currency)}. "
                            f"The PO unit price is {_money(finding['po_minor'], currency)}. "
                            f"The difference is {_money(abs(finding['difference_minor']), currency)} per unit. [comparison]"
                        )
                    else:
                        label = {
                            "HEADER_MISMATCH": "The PO reference or currency differs.",
                            "NO_PO_LINE": "An invoice item has no matching PO line.",
                            "UNEXPECTED_RECEIPT": "The receipt contains an unordered item or quantity.",
                        }.get(code, "A document line needs review.")
                        findings.append(f"{label} [comparison]")
                parts.extend(findings[:5])
                if len(findings) > 5:
                    parts.append(
                        f"See the comparison for all {len(findings)} findings. [comparison]"
                    )
    if topic == "payment":
        ids.append("payment")
        payment = evidence["payment"]
        currency = payment.get("currency") or evidence.get("invoice", {}).get("currency")
        if payment.get("recorded") is False:
            parts.append("No payment is recorded. [payment]")
        elif currency and payment.get("amount_minor") is not None:
            parts.append(f"Amount recorded: {_money(payment['amount_minor'], currency)}. [payment]")
    return {
        "answer": "\n\n".join(parts),
        "sources": [{"id": key, "evidence": evidence[key]} for key in ids],
        "citation_valid": True,
        "response_mode": "case_snapshot",
        "fallback": fallback,
    }


async def answer_case(
    question: str, evidence: dict[str, Any], context: CallContext, model_router: ModelRouter
) -> dict[str, Any]:
    response = await model_router.run(
        "copilot_case",
        {"question": redact(question), "evidence": json.dumps(redact_any(evidence))},
        context,
    )
    parsed = CaseAnswer.model_validate(
        response.parsed.model_dump() if response.parsed else json.loads(response.text)
    )
    cited = citation_ids(parsed.answer)
    if not cited and parsed.evidence_ids and set(parsed.evidence_ids) <= set(evidence):
        # Some structured-output models return valid references outside the prose. Render
        # those verified identifiers ourselves rather than silently dropping the citations.
        parsed.answer += "\n\nSources: " + " ".join(
            f"[{key}]" for key in dict.fromkeys(parsed.evidence_ids)
        )
        cited = set(parsed.evidence_ids)
    valid = bool(cited) and cited == set(parsed.evidence_ids) and cited <= set(evidence)
    if not valid:
        return {
            "answer": "I could not verify the answer's evidence references. Review the case documents or ask a more specific question.",
            "sources": [],
            "citation_valid": False,
            "needs_more_evidence": True,
            "llm": response.public(),
        }
    return {
        "answer": parsed.answer,
        "sources": [
            {"id": key, "evidence": evidence[key]} for key in dict.fromkeys(parsed.evidence_ids)
        ],
        "citation_valid": True,
        "needs_more_evidence": parsed.needs_more_evidence,
        "llm": response.public(),
    }


def citation_ids(answer_text: str) -> set[str]:
    return set(re.findall(r"\[([A-Za-z0-9_]+)\]", answer_text))
