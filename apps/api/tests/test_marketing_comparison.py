import asyncio
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from app.api.v1 import marketing_quality
from app.core.auth import Principal, get_principal
from app.evaluation.marketing import Reviews, score_case
from app.main import create_app


@pytest.mark.db
async def test_marketing_comparison_keeps_simulation_separate_and_pins_live_config(monkeypatch):
    principal = Principal("comparison-test", "comparison-test", frozenset({"guest"}), "api_key")
    app = create_app()

    async def current_principal():
        return principal

    app.dependency_overrides[get_principal] = current_principal
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        url = "/api/v1/quality/marketing-comparison"
        setup = (await client.get(url)).json()
        demo = setup["simulation"]
        assert setup["live"] is None
        assert demo["baseline"]["gate_passed"]
        assert demo["candidate"]["false_passes"] == ["battery-and-discount-inflated"]
        assert demo["candidate"]["human_calibration"] is None
        model = marketing_quality.load_config().tasks["judge"].chain[0]
        body = {
            "dataset_sha256": setup["dataset_sha256"],
            "baseline": {"prompt_version": 1, "model": model},
            "candidate": {"prompt_version": 2, "model": model},
        }
        assert (await client.post(url, json=body)).status_code == 403
        principal = replace(principal, roles=frozenset({"admin"}))
        stale = await client.post(url, json={**body, "dataset_sha256": "0" * 64})
        assert stale.status_code == 409

        async def test_reviews(path, cases, snapshot):
            return Reviews.model_validate(
                {
                    "dataset_sha256": snapshot,
                    "reviewer": "test-only",
                    "cases": {
                        case.id: {"passed": case.expected_fixture_pass, "reason": "Test fixture"}
                        for case in cases
                    },
                }
            )

        async def no_wait(_seconds):
            pass

        fetch_version = marketing_quality.fetch_version

        async def test_prompt(session, name, version):
            return replace(await fetch_version(session, name, 1), version=version)

        async def test_judge(router, ctx, case):
            task = router.config.tasks["judge"]
            assert task.chain == [model] and task.cache == "none"
            prompt = await router.prompts.resolve(task.prompt.name, task.prompt.label)
            verdict = case.fixture()
            if prompt.version == 2 and case.id == "battery-and-discount-inflated":
                verdict = verdict.model_copy(update={"unsupported_claims": []})
            return {**score_case(case, verdict), "prompt_version": prompt.version}

        monkeypatch.setattr(marketing_quality, "available_models", lambda: [model])
        monkeypatch.setattr(marketing_quality, "load_reviews", test_reviews)
        monkeypatch.setattr(marketing_quality, "fetch_version", test_prompt)
        monkeypatch.setattr(marketing_quality, "judge_case", test_judge)
        monkeypatch.setattr(
            marketing_quality, "asyncio", SimpleNamespace(sleep=no_wait, timeout=asyncio.timeout)
        )
        response = await client.post(url, json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["dataset_sha256"] == setup["dataset_sha256"]
        assert result["baseline"]["gate_passed"]
        assert not result["candidate"]["gate_passed"]
        assert result["candidate"]["human_calibration"]["false_passes"] == [
            "battery-and-discount-inflated"
        ]
