"""Compare the marketing judge on a shared synthetic dataset snapshot."""

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import call_context
from app.core.auth import CurrentPrincipal
from app.core.config import datasets_root, get_settings
from app.core.db import system_tx
from app.core.errors import AppError, Forbidden
from app.core.limits import charge_run
from app.evaluation.marketing import judge_case, load_cases, load_reviews, score_case, summarize
from app.llm.config import load_config
from app.llm.router import ModelRouter
from app.prompts.registry import StaticPromptSource, fetch_version

router = APIRouter(prefix="/quality/marketing-comparison", tags=["quality"])
REVIEWERS = ("admin", "controller", "approver")


class Configuration(BaseModel):
    prompt_version: int = Field(ge=1)
    model: str


class ComparisonRequest(BaseModel):
    baseline: Configuration
    candidate: Configuration
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def available_models() -> list[str]:
    settings = get_settings()
    keys = {"groq": settings.groq_api_key, "gemini": settings.gemini_api_key}
    return [model for model in load_config().tasks["judge"].chain if keys.get(model.split("/")[0])]


def comparison(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    expected: dict[str, bool],
    *,
    simulated: bool,
) -> dict[str, Any]:
    reports = {}
    for key, rows in (("baseline", baseline), ("candidate", candidate)):
        summary = summarize(rows, expected)
        if simulated:
            summary["human_calibration"] = None
        reports[key] = {**summary, "results": rows}
    return reports


@router.get("")
async def setup(p: CurrentPrincipal) -> dict[str, Any]:
    cases, snapshot = await load_cases()
    baseline = [score_case(case, case.fixture()) for case in cases]
    # A deliberately permissive fixture shows how an unsupported claim can get through.
    candidate = [
        score_case(
            case,
            case.fixture().model_copy(update={"unsupported_claims": []})
            if case.id == "battery-and-discount-inflated"
            else case.fixture(),
        )
        for case in cases
    ]
    expected = {case.id: case.expected_fixture_pass for case in cases}
    result = {
        "dataset_sha256": snapshot,
        "cases": [{"id": case.id, "facts": case.facts, "draft": case.draft} for case in cases],
        "simulation": comparison(baseline, candidate, expected, simulated=True),
    }
    if not p.has_any(*REVIEWERS):
        return {**result, "live": None}

    task = load_config().tasks["judge"]
    async with system_tx() as session:
        versions = (
            (
                await session.execute(
                    text("SELECT version FROM ai.prompts WHERE name=:name ORDER BY version DESC"),
                    {"name": task.prompt.name},
                )
            )
            .scalars()
            .all()
        )
        current = (
            await session.execute(
                text("SELECT version FROM ai.prompt_labels WHERE name=:name AND label=:label"),
                {"name": task.prompt.name, "label": task.prompt.label},
            )
        ).scalar_one_or_none()
    models = available_models()
    blocker = None
    try:
        await load_reviews(datasets_root() / "marketing/v1/human-labels.json", cases, snapshot)
    except (OSError, ValueError):
        blocker = "Complete the human review file for this dataset to enable live comparisons."
    if not models:
        blocker = (
            "Configure a judge provider and complete the human review file to run live comparisons."
            if blocker
            else "Configure a Groq or Gemini key to run live comparisons."
        )
    elif not versions or len(versions) * len(models) < 2:
        blocker = blocker or "Add another judge prompt version or configure a second model."
    return {
        **result,
        "live": {"models": models, "versions": versions, "current": current, "blocker": blocker},
    }


@router.post("")
async def run_comparison(
    body: ComparisonRequest, request: Request, p: CurrentPrincipal
) -> dict[str, Any]:
    if not p.has_any(*REVIEWERS):
        raise Forbidden("Quality reviewer access required")
    cases, snapshot = await load_cases()
    if body.dataset_sha256 != snapshot:
        raise AppError("The dataset changed. Refresh AI Quality and try again.", status_code=409)
    if body.baseline == body.candidate:
        raise AppError("Choose two different judge configurations.")
    selections = (body.baseline, body.candidate)
    models = available_models()
    if any(choice.model not in models for choice in selections):
        raise AppError("Choose a configured judge model for each side.")
    try:
        reviews = await load_reviews(
            datasets_root() / "marketing/v1/human-labels.json", cases, snapshot
        )
    except (OSError, ValueError) as exc:
        raise AppError(
            "Complete human reviews for the current dataset before running live."
        ) from exc
    config = load_config()
    task = config.tasks["judge"]
    async with system_tx() as session:
        prompts = [
            await fetch_version(session, task.prompt.name, choice.prompt_version)
            for choice in selections
        ]
    routers = []
    for choice, prompt in zip(selections, prompts, strict=True):
        pinned = task.model_copy(update={"chain": [choice.model], "cache": "none", "variants": []})
        routers.append(
            ModelRouter(
                config=config.model_copy(update={"tasks": {**config.tasks, "judge": pinned}}),
                prompts=StaticPromptSource({prompt.name: prompt}),
            )
        )
    await charge_run(p)
    ctx = call_context(request, p)
    baseline, candidate = [], []
    pause = 9 if body.baseline.model == body.candidate.model else 5
    try:
        async with asyncio.timeout(240):
            for index, case in enumerate(cases):
                if index:
                    await asyncio.sleep(pause)
                baseline.append(await judge_case(routers[0], ctx, case))
                await asyncio.sleep(pause)
                candidate.append(await judge_case(routers[1], ctx, case))
    except TimeoutError as exc:
        raise AppError(
            "Live comparison timed out. No release decision was made.", status_code=504
        ) from exc
    expected = {case_id: review.passed for case_id, review in reviews.cases.items()}
    return {
        **comparison(baseline, candidate, expected, simulated=False),
        "dataset_sha256": snapshot,
        "reviews": {case_id: review.reason for case_id, review in reviews.cases.items()},
    }
