"""Read-only, evidence-scoped assistant. No generated SQL, write tools or payment actions."""

import json
import re
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.deps import call_context
from app.api.v1.procurement import actor, case_row
from app.core.auth import CurrentPrincipal
from app.core.db import tenant_tx
from app.core.errors import Forbidden
from app.core.limits import charge_run
from app.guardrails.pii import redact
from app.llm.router import CallContext, ModelRouter, get_router
from app.rag.service import answer

router = APIRouter(prefix="/procurement/copilot", tags=["copilot"])


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    case_id: uuid.UUID | None = None


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
        state = row["state"]
        evidence = {
            **state["documents"],
            "status": {"status": state["status"], "revision": state["revision"]},
        }
        for key in ("comparison", "approvals", "payment"):
            if state.get(key):
                evidence[key] = state[key]
        await charge_run(p)
        return await answer_case(body.question, evidence, context, get_router())
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


async def answer_case(
    question: str, evidence: dict[str, Any], context: CallContext, model_router: ModelRouter
) -> dict[str, Any]:
    response = await model_router.run(
        "copilot_case",
        {"question": redact(question), "evidence": redact(json.dumps(evidence))},
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
