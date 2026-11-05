from types import SimpleNamespace

import httpx
import pytest

from app.core.auth import Principal, get_principal
from app.evaluation.calibration import calibration
from app.main import create_app
from app.schemas.llm_outputs import JudgeOut


def test_calibration_never_invents_labels_and_handles_degenerate_agreement():
    assert calibration([])["agreement"] is None
    assert calibration([{"id": "1", "human": True, "judge": True}])["kappa"] is None
    report = calibration(
        [{"id": "1", "human": False, "judge": True}, {"id": "2", "human": True, "judge": False}]
    )
    assert (
        report["agreement"] == 0
        and report["false_passes"] == ["1"]
        and report["false_fails"] == ["2"]
    )


@pytest.mark.db
async def test_judge_human_label_privacy_and_unscored_failure(org_id, monkeypatch):
    from app.api.v1 import quality

    payload = {
        d: {"score": 0.9, "explanation": "supported"}
        for d in ("correctness", "relevance", "faithfulness", "completeness", "clarity")
    }
    payload["unsupported_claims"] = ["Battery duration not supported"]
    parsed = JudgeOut.model_validate(payload)

    class Router:
        async def run(self, *args):
            return SimpleNamespace(model="test-model", parsed=parsed, prompt_version=1)

    monkeypatch.setattr(quality, "get_router", lambda: Router())
    app = create_app()
    principal = Principal("reviewer", org_id, frozenset({"admin"}), "api_key")

    async def current():
        return principal

    app.dependency_overrides[get_principal] = current
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/api/v1/quality/judge",
            json={"question": "Supported?", "answer": "48 hours", "context": "8 hours"},
        )
        assert result.status_code == 200, result.text
        assert result.json()["passed"] is False  # unsupported claims override a high average score
        rid = result.json()["id"]
        assert (await client.get("/api/v1/quality/judgments")).json()["calibration"][
            "sample_size"
        ] == 0
        label = {"passed": False, "score": 20, "comment": "I checked the source: it says 8 hours"}
        assert (
            await client.post(f"/api/v1/quality/judgments/{rid}/label", json=label)
        ).status_code == 200
        report = (await client.get("/api/v1/quality/judgments")).json()
        assert report["calibration"]["sample_size"] == 1
        assert report["calibration"]["agreement"] == 1
        assert rid not in [
            str(r["id"]) for r in (await client.get("/api/v1/eval-report")).json()["reports"]
        ]
        principal = Principal("reviewer", "other-" + org_id, frozenset({"admin"}), "api_key")
        assert (
            await client.post(f"/api/v1/quality/judgments/{rid}/label", json=label)
        ).status_code == 404
        assert (await client.get("/api/v1/quality/judgments")).json()["judgments"] == []
        principal = Principal("reviewer", org_id, frozenset({"admin"}), "api_key")
        parsed = None
        bad = await client.post(
            "/api/v1/quality/judge", json={"question": "Supported?", "answer": "unknown"}
        )
        assert bad.json()["passed"] is None and bad.json()["score"] is None and bad.json()["error"]
