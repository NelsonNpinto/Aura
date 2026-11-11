"""Public synthetic workflow reports; private evaluation results are never returned here."""

import hashlib
import json
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import call_context
from app.core.auth import CurrentPrincipal
from app.core.config import datasets_root
from app.core.db import system_tx, tenant_tx
from app.core.errors import Forbidden, NotFound
from app.core.limits import charge_run
from app.evaluation.calibration import calibration
from app.evaluation.finance import run as run_finance
from app.evaluation.judge import JudgeRequest, score_judgment
from app.guardrails.pii import redact
from app.llm.router import get_router
from app.schemas.llm_outputs import JudgeOut

router = APIRouter(tags=["quality"])


@router.get("/quality/finance-fixtures")
async def finance_fixtures() -> dict[str, Any]:
    return await run_finance(live=False, delay=0)


class DraftRequest(BaseModel):
    facts: str = Field(min_length=3, max_length=8000)


@router.post("/quality/marketing-draft")
async def marketing_draft(
    body: DraftRequest, request: Request, p: CurrentPrincipal
) -> dict[str, Any]:
    if not p.has_any("admin", "controller", "approver"):
        raise Forbidden("Quality reviewer access required")
    await charge_run(p)
    result = await get_router().run(
        "marketing_draft", {"facts": redact(body.facts)}, call_context(request, p)
    )
    return {"draft": result.text, "llm": result.public(), "requires_human_approval": True}


@router.post("/quality/judge")
async def judge(body: JudgeRequest, request: Request, p: CurrentPrincipal) -> dict[str, Any]:
    if not p.has_any("admin", "controller", "approver"):
        raise Forbidden("Quality reviewer access required")
    await charge_run(p)
    variables = body.variables()
    result: dict[str, Any] = {
        "input": variables,
        "verdict": None,
        "score": None,
        "passed": None,
        "error": None,
    }
    model = "unavailable"
    try:
        response = await get_router().run("judge", variables, call_context(request, p))
        model = response.model
        if not isinstance(response.parsed, JudgeOut):
            raise ValueError("Judge output is unscored")
        verdict = response.parsed.model_dump()
        if not body.context:
            verdict["faithfulness"] = None
        score, passed = score_judgment(body, response.parsed)
        result.update(
            verdict=verdict,
            score=score,
            passed=passed,
            model=model,
            prompt_version=response.prompt_version,
        )
    except Exception as exc:
        result["error"] = type(exc).__name__
    rid = uuid.uuid4()
    async with tenant_tx(p.org_id, p.user_id) as session:
        await session.execute(
            text(
                "INSERT INTO ai.dataset_runs (id,dataset,dataset_version,mode,provider_mode,case_count,metrics,results,config) VALUES (:id,'adhoc-judge','v1','stored',:model,1,CAST(:m AS jsonb),CAST(:r AS jsonb),CAST(:c AS jsonb))"
            ),
            {
                "id": rid,
                "model": model,
                "m": json.dumps({"score": result["score"], "passed": result["passed"]}),
                "r": json.dumps([result]),
                "c": json.dumps({"org_id": p.org_id, "public_report": False}),
            },
        )
    return {"id": str(rid), **result}


class HumanLabel(BaseModel):
    passed: bool = Field(strict=True)
    score: int = Field(strict=True, ge=0, le=100)
    comment: str = Field(min_length=1, max_length=2000)


@router.post("/quality/judgments/{run_id}/label")
async def label(run_id: uuid.UUID, body: HumanLabel, p: CurrentPrincipal) -> dict[str, str]:
    if not p.has_any("admin", "controller", "approver"):
        raise Forbidden("Human reviewer access required")
    async with tenant_tx(p.org_id, p.user_id) as session:
        exists = (
            await session.execute(
                text(
                    "SELECT id FROM ai.dataset_runs WHERE id=:id AND dataset='adhoc-judge' AND config->>'org_id'=:o"
                ),
                {"id": run_id, "o": p.org_id},
            )
        ).first()
        if not exists:
            raise NotFound("Judgment not found")
        await session.execute(
            text(
                "INSERT INTO ai.judge_labels (org_id,run_id,created_by,passed,score,comment) VALUES (:o,:r,:u,:p,:s,:c) ON CONFLICT (run_id,created_by) DO UPDATE SET passed=excluded.passed,score=excluded.score,comment=excluded.comment,created_at=now()"
            ),
            {
                "o": p.org_id,
                "r": run_id,
                "u": p.user_id,
                "p": body.passed,
                "s": body.score,
                "c": body.comment,
            },
        )
    return {"status": "human_label_saved"}


@router.get("/quality/judgments")
async def judgments(p: CurrentPrincipal) -> dict[str, Any]:
    if not p.has_any("admin", "controller", "approver", "auditor"):
        raise Forbidden("Quality reviewer access required")
    async with tenant_tx(p.org_id, p.user_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id,metrics,results,created_at FROM ai.dataset_runs WHERE dataset='adhoc-judge' AND config->>'org_id'=:o ORDER BY created_at DESC LIMIT 100"
                    ),
                    {"o": p.org_id},
                )
            )
            .mappings()
            .all()
        )
        labels = (
            (await session.execute(text("SELECT run_id,passed,score FROM ai.judge_labels")))
            .mappings()
            .all()
        )
    votes: dict[str, list[bool]] = defaultdict(list)
    for vote in labels:
        votes[str(vote["run_id"])].append(vote["passed"])
    pairs = []
    for row in rows:
        labels_for_case = votes[str(row["id"])]
        judge_pass = row["metrics"].get("passed")
        if (
            not labels_for_case
            or judge_pass is None
            or sum(labels_for_case) * 2 == len(labels_for_case)
        ):
            continue
        pairs.append(
            {
                "id": str(row["id"]),
                "human": sum(labels_for_case) * 2 > len(labels_for_case),
                "judge": judge_pass,
            }
        )
    return {
        "judgments": [dict(row) for row in rows],
        "calibration": calibration(pairs),
        "limits": "Calibration uses at most the latest 100 judgments; tied human votes and unscored judgments are excluded.",
    }


@router.get("/eval-report")
async def reports() -> dict[str, Any]:
    async with system_tx() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id,dataset,dataset_version,mode,provider_mode,git_sha,case_count,metrics,results,created_at,config->>'case_snapshot' AS case_snapshot,config->>'limits' AS limits,config->'gate_passed' AS gate_passed FROM ai.dataset_runs WHERE config->>'public_report'='true' AND config->>'synthetic'='true' ORDER BY created_at DESC LIMIT 20"
                    )
                )
            )
            .mappings()
            .all()
        )
    public_reports = [dict(row) for row in rows]
    artifact = datasets_root() / "reports" / "demo-fixture-2026-11-05.json"
    if not public_reports and artifact.is_file():
        recorded = json.loads(artifact.read_text())
        # This explicitly published artifact contains an actual local fixture run; no private
        # workspace judgments or source documents are imported into this public response.
        public_reports = [
            {
                key: recorded[key]
                for key in (
                    "dataset",
                    "dataset_version",
                    "mode",
                    "provider_mode",
                    "case_count",
                    "metrics",
                    "results",
                    "created_at",
                    "case_snapshot",
                    "gate_passed",
                    "limits",
                )
            }
        ]
        public_reports[0]["id"] = (
            "recorded-" + hashlib.sha256(artifact.read_bytes()).hexdigest()[:16]
        )
        public_reports[0]["limits"] += (
            " Recorded local validation artifact; its original traces remain in the local evaluation database."
        )
    return {
        "reports": public_reports,
        "source": "Stored public synthetic evaluation runs or explicitly published recorded validation artifacts",
        "notice": "Fixture runs measure workflow behavior, not live model accuracy. Human calibration and extraction quality remain unmeasured.",
    }
