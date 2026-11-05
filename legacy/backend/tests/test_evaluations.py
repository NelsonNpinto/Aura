import pytest
from pydantic import ValidationError

from app.evaluation.deterministic import evaluate
from app.schemas.requests import Check


@pytest.mark.parametrize(
    "response,check,passed",
    [
        ("  ", Check(kind="non_empty"), False),
        ("NaN", Check(kind="valid_json"), False),
        ("Infinity", Check(kind="valid_json"), False),
        ('{"ok":true}', Check(kind="valid_json"), True),
        ("```json\n{}\n```", Check(kind="valid_json"), False),
        (
            "Refund within 30 DAYS",
            Check(kind="required_keywords", values=["refund", "30 days"]),
            True,
        ),
        ("Refund available", Check(kind="required_keywords", values=["30 days"]), False),
        ("GUARANTEED returns", Check(kind="forbidden_phrases", values=["guaranteed"]), False),
        ("No return promise", Check(kind="forbidden_phrases", values=["guaranteed"]), True),
        (" 42 ", Check(kind="exact_match", expected="42"), True),
        ("42.", Check(kind="exact_match", expected="42"), False),
        (
            "{}",
            Check(kind="json_schema", schema_definition={"type": "object", "required": ["answer"]}),
            False,
        ),
        (
            '{"answer":"yes"}',
            Check(kind="json_schema", schema_definition={"type": "object", "required": ["answer"]}),
            True,
        ),
    ],
)
def test_checks(response, check, passed):
    result = evaluate(response, [check])[0]
    assert result["passed"] is passed
    assert result["method"] == "deterministic"
    assert result["detail"]


@pytest.mark.parametrize(
    "check",
    [
        {"kind": "required_keywords", "values": []},
        {"kind": "forbidden_phrases", "values": [""]},
        {"kind": "exact_match"},
        {"kind": "json_schema", "schema_definition": {"type": "invalid"}},
        {"kind": "json_schema", "schema_definition": {"$ref": "https://example.com/schema"}},
    ],
)
def test_invalid_check_rejected(check):
    with pytest.raises(ValidationError):
        Check(**check)


def test_persist_evaluation_and_aggregate(client):
    assert client.get("/api/v1/overview").json()["average_check_score"] is None
    response = client.post(
        "/api/v1/evaluations",
        json={
            "name": "Policy checks",
            "response": "Refund available",
            "threshold": 0.75,
            "checks": [{"kind": "non_empty"}, {"kind": "required_keywords", "values": ["30 days"]}],
        },
    )
    assert response.status_code == 201
    run = response.json()
    assert run["score"] == 0.5
    assert run["passed"] is False
    assert client.get("/api/v1/evaluations").json()[0]["id"] == run["id"]
    stats = client.get("/api/v1/overview").json()
    assert stats["evaluation_runs"] == 1
    assert stats["failed_evaluations"] == 1
    assert stats["average_check_score"] == 0.5
    assert stats["faithfulness"] is None


def test_api_rejects_empty_checks_and_invalid_trace(client):
    assert (
        client.post("/api/v1/evaluations", json={"response": "x", "checks": []}).status_code == 422
    )
    assert (
        client.post(
            "/api/v1/evaluations",
            json={
                "trace_id": "missing",
                "response": "x",
                "checks": [{"kind": "non_empty"}],
            },
        ).status_code
        == 404
    )
