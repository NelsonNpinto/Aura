"""Evaluate the marketing judge against synthetic fixtures or human-reviewed cases."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.core.config import datasets_root, get_settings
from app.evaluation.calibration import Reviews, calibration
from app.evaluation.judge import JudgeRequest, score_judgment
from app.schemas.llm_outputs import JudgeOut

if TYPE_CHECKING:
    from app.llm.router import CallContext, ModelRouter


class MarketingCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    synthetic: Literal[True]
    facts: str = Field(min_length=1, max_length=12000)
    draft: str = Field(min_length=1, max_length=8000)
    expected_fixture_pass: bool = Field(strict=True)
    fixture_unsupported_claims: list[str]

    def request(self) -> JudgeRequest:
        return JudgeRequest(
            question="Is this marketing draft suitable to send based on the product facts?",
            answer=self.draft,
            context=self.facts,
        )

    def fixture(self) -> JudgeOut:
        # Every fixture has high rubric scores so unsupported claims must override them.
        rubric = {"score": 0.95, "explanation": "Synthetic rubric fixture"}
        return JudgeOut.model_validate(
            {
                **dict.fromkeys(
                    ("correctness", "relevance", "faithfulness", "completeness", "clarity"),
                    rubric,
                ),
                "unsupported_claims": self.fixture_unsupported_claims,
            }
        )


async def load_cases() -> tuple[list[MarketingCase], str]:
    path = datasets_root() / "marketing/v1/cases.json"
    cases = TypeAdapter(list[MarketingCase]).validate_json(await asyncio.to_thread(path.read_bytes))
    ids = {case.id for case in cases}
    if not cases or len(ids) != len(cases):
        raise ValueError("Marketing cases must have unique IDs and the dataset must be nonempty")
    canonical = json.dumps([case.model_dump() for case in cases], sort_keys=True)
    return cases, hashlib.sha256(canonical.encode()).hexdigest()


async def load_reviews(path: Path, cases: list[MarketingCase], snapshot: str) -> Reviews:
    reviews = Reviews.model_validate_json(await asyncio.to_thread(path.read_bytes))
    if reviews.dataset_sha256 != snapshot or reviews.cases.keys() != {case.id for case in cases}:
        raise ValueError("Human reviews must cover every case in the current dataset snapshot")
    if {review.passed for review in reviews.cases.values()} != {True, False}:
        raise ValueError("Human reviews must include both passing and failing cases")
    return reviews


async def run(labels_path: Path | None = None, delay: float = 2.1) -> dict[str, Any]:
    cases, snapshot = await load_cases()
    expected = {case.id: case.expected_fixture_pass for case in cases}
    live = labels_path is not None
    label_sha256 = None
    if labels_path is not None:
        reviews = await load_reviews(labels_path, cases, snapshot)
        expected = {case_id: review.passed for case_id, review in reviews.cases.items()}
        label_sha256 = hashlib.sha256(reviews.model_dump_json().encode()).hexdigest()
    if set(expected.values()) != {True, False}:
        raise ValueError("The marketing suite requires both passing and failing cases")

    results: list[dict[str, Any]] = []
    if live:
        results = await _live_results(cases, delay)
    else:
        for case in cases:
            results.append(score_case(case, case.fixture()))

    summary = summarize(results, expected)
    return {
        "dataset": "marketing/v1",
        "dataset_sha256": snapshot,
        "label_sha256": label_sha256,
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": get_settings().git_sha,
        "mode": "live" if live else "fixture",
        "case_count": len(cases),
        **summary,
        "human_calibration": summary["human_calibration"] if live else None,
        "results": results,
    }


def summarize(results: list[dict[str, Any]], expected: dict[str, bool]) -> dict[str, Any]:
    pairs = []
    for result in results:
        result["expected_pass"] = expected[result["id"]]
        if result["passed"] is not None:
            pairs.append(
                {"id": result["id"], "human": result["expected_pass"], "judge": result["passed"]}
            )
    comparison = calibration(pairs)
    errors = len(expected) - len(pairs)
    return {
        "errors": errors,
        "false_passes": comparison["false_passes"],
        "false_fails": comparison["false_fails"],
        "human_calibration": comparison,
        "gate_passed": errors == 0 and comparison["agreement"] == 1,
    }


def score_case(case: MarketingCase, verdict: JudgeOut) -> dict[str, Any]:
    score, passed = score_judgment(case.request(), verdict)
    return {
        "id": case.id,
        "score": score,
        "passed": passed,
        "unsupported_claims": verdict.unsupported_claims,
    }


async def _live_results(cases: list[MarketingCase], delay: float) -> list[dict[str, Any]]:
    from app.llm.config import load_config
    from app.llm.router import CallContext, ModelRouter

    settings = get_settings()
    if not (settings.groq_api_key or settings.gemini_api_key):
        raise ValueError("Live marketing evaluation requires a Groq or Gemini API key")
    config = load_config()
    task = config.tasks["judge"].model_copy(update={"cache": "none"})
    router = ModelRouter(
        config=config.model_copy(update={"tasks": {**config.tasks, "judge": task}})
    )
    ctx = CallContext(org_id="eval-marketing", user_id="system:eval", internal_job=True)
    results = []
    for index, case in enumerate(cases):
        if index:
            await asyncio.sleep(delay)
        results.append(await judge_case(router, ctx, case))
    return results


async def judge_case(router: ModelRouter, ctx: CallContext, case: MarketingCase) -> dict[str, Any]:
    try:
        response = await router.run("judge", case.request().variables(), ctx)
        if not isinstance(response.parsed, JudgeOut):
            raise ValueError("Judge output is unscored")
        return {
            **score_case(case, response.parsed),
            "model": response.model,
            "prompt_version": response.prompt_version,
            "fallback_reason": response.fallback_reason,
            "latency_ms": response.latency_ms,
            "est_cost_microusd": response.est_cost_microusd,
        }
    except Exception as exc:
        return {"id": case.id, "passed": None, "error": type(exc).__name__}
