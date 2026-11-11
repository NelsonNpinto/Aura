"""Evaluate finance answers against reviewed synthetic evidence and a claim-level judge."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from app.api.v1.copilot import answer_case, citation_ids
from app.core.config import datasets_root, get_settings
from app.core.context import trace_id_var
from app.core.store import MemoryStore
from app.domain.procurement import EvidenceDocument, compare
from app.evaluation.calibration import Reviews, calibration
from app.evaluation.judge import JudgeRequest
from app.llm.router import CallContext, ModelRouter
from app.llm.telemetry import MemorySink
from app.prompts.registry import PromptVersion, StaticPromptSource
from app.schemas.llm_outputs import FinanceVerdict, Strict


class Candidate(Strict):
    id: str
    answer: str = Field(min_length=1, max_length=5000)
    expected_pass: bool = Field(strict=True)
    fixture: FinanceVerdict


class FinanceCase(Strict):
    id: str
    documents: dict[Literal["po", "invoice", "receipt"], EvidenceDocument]
    status: Literal["needs_correction", "awaiting_l1", "approved_for_payment"]
    findings: list[str]
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    question: str = Field(min_length=3, max_length=500)
    required_facts: list[str] = Field(min_length=1, max_length=20)
    candidates: list[Candidate] = Field(min_length=2, max_length=10)

    def evidence(self) -> dict[str, Any]:
        if set(self.documents) != {"po", "invoice", "receipt"}:
            raise ValueError(f"{self.id}: all three purchasing documents are required")
        documents: dict[str, dict[str, Any]] = {
            kind: doc.model_dump(mode="json") for kind, doc in self.documents.items()
        }
        comparison = compare(documents)
        if sorted(x["code"] for x in comparison["findings"]) != sorted(self.findings):
            raise ValueError(f"{self.id}: the expected findings differ from the Purchasing rules")
        if comparison["matched"] == (self.status == "needs_correction"):
            raise ValueError(f"{self.id}: status is inconsistent with the comparison")
        evidence: dict[str, Any] = {
            **documents,
            "comparison": comparison,
            "status": {"status": self.status, "revision": 3},
        }
        if self.approvals:
            evidence["approvals"] = self.approvals
        return evidence


class Dataset(Strict):
    synthetic: Literal[True]
    cases: list[FinanceCase] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_ids(self) -> Dataset:
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Finance case IDs must be unique")
        for case in self.cases:
            if len({candidate.id for candidate in case.candidates}) != len(case.candidates):
                raise ValueError(f"{case.id}: candidate IDs must be unique")
            if {candidate.expected_pass for candidate in case.candidates} != {True, False}:
                raise ValueError(f"{case.id}: include passing and failing reference answers")
        return self


def score(verdict: FinanceVerdict, cited: set[str]) -> tuple[bool | None, str | None]:
    for claim in verdict.claims:
        sources = set(claim.source_ids)
        if not sources <= cited or (claim.verdict == "supported" and not sources):
            return None, "judge_invalid_source"
    passed = (
        bool(verdict.claims)
        and not verdict.missing_required_facts
        and all(claim.verdict == "supported" for claim in verdict.claims)
    )
    return passed, None


async def grade(
    case: FinanceCase,
    answer_text: str,
    evidence: dict[str, Any],
    ctx: CallContext,
    router: ModelRouter | None,
    fixture: FinanceVerdict | None = None,
) -> dict[str, Any]:
    cited = citation_ids(answer_text)
    if not cited or not cited <= evidence.keys():
        return {"passed": False, "citation_valid": False, "reason": "invalid_citation"}
    metadata: dict[str, Any] = {}
    if router is not None:
        request = JudgeRequest(
            question=case.question,
            answer=answer_text,
            context=json.dumps({key: evidence[key] for key in sorted(cited)}),
            reference=json.dumps(case.required_facts),
        )
        response = await router.run("finance_judge", request.variables(), ctx)
        metadata = {
            "model": response.model,
            "prompt_version": response.prompt_version,
            "latency_ms": response.latency_ms,
            "est_cost_microusd": response.est_cost_microusd,
            "fallback_reason": response.fallback_reason,
        }
        verdict = response.parsed
    else:
        verdict = fixture
    if not isinstance(verdict, FinanceVerdict):
        return {"passed": None, "error": "missing_judge_verdict", **metadata}
    passed, error = score(verdict, cited)
    return {
        "passed": passed,
        "citation_valid": True,
        "verdict": verdict.model_dump(),
        "error": error,
        **metadata,
    }


def evaluation_router() -> tuple[ModelRouter, str]:
    settings = get_settings()
    if not (settings.groq_api_key or settings.gemini_api_key):
        raise ValueError("Live finance evaluation requires a Groq or Gemini API key")
    source = (Path(__file__).resolve().parents[1] / "prompts/defaults.yaml").read_bytes()
    defaults = yaml.safe_load(source)
    prompts = {
        name: PromptVersion(
            name, 1, defaults[name]["system"], defaults[name]["template"], defaults[name]["config"]
        )
        for name in ("copilot_case", "finance_judge")
    }
    # Evaluate the checked-out release candidate, isolated from production prompts and telemetry.
    router = ModelRouter(
        prompts=StaticPromptSource(prompts), store=MemoryStore(), sink=MemorySink(), faults=""
    )
    return router, hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest()


async def run(*, live: bool, delay: float, labels_path: Path | None = None) -> dict[str, Any]:
    path = datasets_root() / "finance_copilot/v1/cases.json"
    data = await asyncio.to_thread(path.read_bytes)
    dataset = Dataset.model_validate_json(data)
    canonical = json.dumps(dataset.model_dump(mode="json"), sort_keys=True)
    snapshot = hashlib.sha256(canonical.encode()).hexdigest()
    reviews = None
    if labels_path is not None:
        if not live:
            raise ValueError("Finance human labels require a live run")
        reviews = Reviews.model_validate_json(await asyncio.to_thread(labels_path.read_bytes))
        ids = {
            f"{case.id}/{candidate.id}" for case in dataset.cases for candidate in case.candidates
        }
        if reviews.dataset_sha256 != snapshot or reviews.cases.keys() != ids:
            raise ValueError(
                "Finance reviews must cover every reference answer in the current snapshot"
            )
        if {review.passed for review in reviews.cases.values()} != {True, False}:
            raise ValueError("Finance reviews must include both passing and failing answers")
    router, prompt_sha = evaluation_router() if live else (None, None)
    results: list[dict[str, Any]] = []
    ctx = CallContext(org_id="eval-finance", user_id="system:eval", internal_job=True)
    for case in dataset.cases:
        evidence = case.evidence()
        for candidate in case.candidates:
            if router and results:
                await asyncio.sleep(delay)
            trace_id = uuid.uuid4().hex if live else None
            token = trace_id_var.set(trace_id)
            try:
                verdict = await grade(
                    case, candidate.answer, evidence, ctx, router, candidate.fixture
                )
            except Exception as exc:
                verdict = {"passed": None, "error": type(exc).__name__}
            finally:
                trace_id_var.reset(token)
            results.append(
                {
                    "id": f"{case.id}/{candidate.id}",
                    "kind": "reference_answer",
                    "question": case.question,
                    "expected_pass": candidate.expected_pass,
                    "answer": candidate.answer,
                    "trace_id": trace_id,
                    **verdict,
                }
            )
        if router:
            await asyncio.sleep(delay)
            trace_id = uuid.uuid4().hex
            token = trace_id_var.set(trace_id)
            result: dict[str, Any] = {}
            try:
                generated = await answer_case(case.question, evidence, ctx, router)
                result.update(answer=generated["answer"], copilot=generated["llm"])
                if generated["citation_valid"]:
                    await asyncio.sleep(delay)
                    result.update(await grade(case, generated["answer"], evidence, ctx, router))
                else:
                    result.update(passed=False, citation_valid=False, reason="invalid_citation")
            except Exception as exc:
                result.update(passed=None, error=type(exc).__name__)
            finally:
                trace_id_var.reset(token)
            results.append(
                {
                    "id": f"{case.id}/copilot",
                    "kind": "generated_answer",
                    "question": case.question,
                    "expected_pass": True,
                    "trace_id": trace_id,
                    **result,
                }
            )
    human_calibration = None
    if reviews is not None:
        pairs = [
            {"id": row["id"], "human": reviews.cases[row["id"]].passed, "judge": row["passed"]}
            for row in results
            if row["kind"] == "reference_answer" and row["passed"] is not None
        ]
        human_calibration = {**calibration(pairs), "reviewed_count": len(reviews.cases)}
    return {
        "dataset": "finance_copilot/v1",
        "dataset_sha256": snapshot,
        "prompt_sha256": prompt_sha,
        "git_sha": get_settings().git_sha,
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "live" if live else "fixture",
        "case_count": len(dataset.cases),
        "synthetic": True,
        "human_calibration": human_calibration,
        "false_passes": [
            r["id"] for r in results if r["passed"] is True and not r["expected_pass"]
        ],
        "failed_expected_passes": [
            r["id"] for r in results if r["passed"] is False and r["expected_pass"]
        ],
        "unscored": [r["id"] for r in results if r["passed"] is None],
        "gate_passed": all(r["passed"] is r["expected_pass"] for r in results),
        "results": results,
    }
