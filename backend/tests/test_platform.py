import json

import numpy as np
import pytest

from app.agents.runner import calculate
from app.core.config import get_settings
from app.core.middleware import _windows
from app.rag import retrieval
from app.services import ollama


@pytest.fixture(autouse=True)
def isolated_limits(monkeypatch):
    _windows.clear()
    monkeypatch.setattr(get_settings(), "request_limit_per_minute", 10000)
    monkeypatch.setattr(get_settings(), "api_key", "")


def dataset_with_case(client, response="Refund in 30 days"):
    dataset = client.post("/api/v1/datasets", json={"name": "Refund policies"}).json()
    case = client.post(
        f"/api/v1/datasets/{dataset['id']}/cases",
        json={
            "question": "What is the refund window?",
            "response": response,
            "checks": [{"kind": "required_keywords", "values": ["30 days"]}],
        },
    )
    assert case.status_code == 201
    return dataset, case.json()


def test_prompt_versions_are_immutable(client):
    payload = {"name": "Support", "template": "Question: {question}", "system": "Be clear"}
    first = client.post("/api/v1/prompts", json=payload).json()
    second = client.post("/api/v1/prompts", json={**payload, "system": "Be precise"}).json()
    assert (first["version"], second["version"]) == (1, 2)
    assert first["id"] != second["id"]
    assert {p["system"] for p in client.get("/api/v1/prompts").json()} == {"Be clear", "Be precise"}


def test_regression_baseline_and_case_drift(client):
    dataset, case = dataset_with_case(client)
    url = f"/api/v1/datasets/{dataset['id']}"
    first = client.post(url + "/run", json={"mode": "stored"}).json()
    assert first["passed"] and first["score"] == 1
    gate = client.put(url + "/baseline", json={"baseline_id": first["id"]})
    assert gate.status_code == 200
    second = client.post(url + "/run", json={"mode": "stored"}).json()
    assert second["gate"]["passed"]
    client.put(
        "/api/v1/cases/" + case["id"],
        json={"question": case["question"], "response": "Unknown", "checks": case["checks"]},
    )
    third = client.post(url + "/run", json={"mode": "stored"}).json()
    assert not third["passed"]
    assert third["gate"]["reason"].startswith("Dataset changed")
    # Original snapshots and case results remain unchanged.
    original = client.get("/api/v1/dataset-runs/" + first["id"]).json()
    assert original["case_snapshot"][0]["response"] == "Refund in 30 days"
    assert original["results"][0]["response"] == "Refund in 30 days"


def test_missing_responses_do_not_create_misleading_run(client):
    dataset = client.post("/api/v1/datasets", json={"name": "Empty response unset"}).json()
    client.post(f"/api/v1/datasets/{dataset['id']}/cases", json={"question": "Question"})
    assert (
        client.post(f"/api/v1/datasets/{dataset['id']}/run", json={"mode": "stored"}).status_code
        == 422
    )
    assert client.get("/api/v1/dataset-runs").json() == []


def test_generation_dataset_failures_are_counted(client, monkeypatch):
    dataset, _ = dataset_with_case(client)

    async def fail(payload):
        raise ollama.OllamaUnavailable("offline")

    monkeypatch.setattr(ollama, "generate", fail)
    run = client.post(
        f"/api/v1/datasets/{dataset['id']}/run", json={"mode": "generate", "model": "test"}
    ).json()
    assert run["errors"] == 1 and run["score"] == 0 and not run["passed"]
    assert (
        client.get("/api/v1/dataset-runs/" + run["id"]).json()["results"][0]["error"] == "offline"
    )


def test_experiments_record_configuration(client):
    dataset, _ = dataset_with_case(client)
    result = client.post(
        "/api/v1/experiments",
        json={
            "name": "A/B",
            "dataset_id": dataset["id"],
            "configurations": [
                {"mode": "stored", "temperature": 0.1},
                {"mode": "stored", "temperature": 0.9},
            ],
        },
    ).json()
    assert len(result["results"]) == 2
    assert result["results"][0]["score"] == 1
    assert result["configurations"][1]["temperature"] == 0.9


def test_document_extraction_duplicate_chunks_and_deletion(client):
    def upload():
        return client.post(
            "/api/v1/documents?index=false",
            files={
                "file": (
                    "policy.md",
                    b"# Refunds\nRefunds are available within 30 days.",
                    "text/markdown",
                )
            },
        )

    first = upload()
    assert first.status_code == 201
    doc = first.json()
    assert upload().json()["duplicate"]
    chunks = client.get(f"/api/v1/documents/{doc['id']}/chunks").json()
    assert "30 days" in chunks[0]["content"]
    found = client.post(
        "/api/v1/knowledge/search", json={"question": "refunds", "strategy": "bm25"}
    ).json()
    assert found[0]["document"] == "policy.md"
    assert (
        client.post(
            "/api/v1/knowledge/search", json={"question": "x", "strategy": "vector"}
        ).status_code
        == 422
    )
    assert client.delete("/api/v1/documents/" + doc["id"]).status_code == 204
    assert (
        client.post(
            "/api/v1/knowledge/search", json={"question": "refunds", "strategy": "bm25"}
        ).json()
        == []
    )


def test_reject_invalid_documents(client):
    for filename, data, code in [
        ("bad.exe", b"bad", 415),
        ("empty.txt", b"  ", 422),
        ("bad.txt", b"\xff", 422),
    ]:
        assert (
            client.post(
                "/api/v1/documents?index=false", files={"file": (filename, data)}
            ).status_code
            == code
        )


def test_vector_index_hybrid_and_scoped_retrieval(client, monkeypatch):
    class Encoder:
        def encode(self, values, **kwargs):
            if isinstance(values, str):
                return np.array([1.0] + [0.0] * 383)
            return np.array([[1.0] + [0.0] * 383 for _ in values])

    monkeypatch.setattr(retrieval, "embedder", lambda: Encoder())
    doc = client.post(
        "/api/v1/documents", files={"file": ("policy.txt", b"Refunds take 30 days.")}
    ).json()
    assert doc["embedding_model"]
    result = client.post(
        "/api/v1/knowledge/search",
        json={"question": "refunds", "strategy": "hybrid", "document_ids": [doc["id"]]},
    ).json()
    assert result[0]["rank_score"] > 0
    assert (
        client.post(
            "/api/v1/knowledge/search",
            json={"question": "refunds", "strategy": "bm25", "document_ids": ["missing"]},
        ).json()
        == []
    )


def verdict(score=1, claims=None):
    return {
        **{
            k: {"score": score, "explanation": "Supported by the given reference"}
            for k in ["correctness", "relevance", "faithfulness", "completeness", "clarity"]
        },
        "unsupported_claims": claims or [],
    }


def mock_judge(monkeypatch, value):
    async def generate(payload):
        assert payload.format
        return {"response": json.dumps(value)}

    monkeypatch.setattr(ollama, "generate", generate)


def create_judge(client):
    return client.post(
        "/api/v1/judge/reviews",
        json={
            "model": "judge-test",
            "question": "Refund window?",
            "response": "30 days",
            "expected": "30 days",
            "contexts": ["Policy: 30 days"],
        },
    )


def test_judge_validation_and_no_false_reliability_claim(client, monkeypatch):
    mock_judge(monkeypatch, {"wrong": "schema"})
    result = create_judge(client).json()
    assert result["score"] is None and result["passed"] is None and result["error"]
    assert client.get("/api/v1/judge/reliability").json()["sample_size"] == 0
    assert (
        client.put(
            f"/api/v1/judge/reviews/{result['id']}/human",
            json={"reviewer": "Human", "score": 1, "passed": True},
        ).status_code
        == 422
    )


def test_judge_unsupported_claims_force_failure(client, monkeypatch):
    mock_judge(monkeypatch, verdict(1, ["Made-up claim"]))
    result = create_judge(client).json()
    assert result["score"] == 1 and result["passed"] is False


def test_human_agreement_false_passes_and_kappa(client, monkeypatch):
    mock_judge(monkeypatch, verdict())
    a, b = create_judge(client).json(), create_judge(client).json()
    for row, label in [(a, False), (b, True)]:
        assert (
            client.put(
                f"/api/v1/judge/reviews/{row['id']}/human",
                json={"reviewer": "Consensus", "score": float(label), "passed": label},
            ).status_code
            == 200
        )
    report = client.get("/api/v1/judge/reliability").json()
    assert report["sample_size"] == 2 and report["agreement"] == 0.5
    assert report["kappa"] == 0 and report["false_passes"] == [a["id"]]
    # Updating a consensus rating does not duplicate the paired sample.
    client.put(
        f"/api/v1/judge/reviews/{a['id']}/human",
        json={"reviewer": "Consensus", "score": 1, "passed": True},
    )
    report = client.get("/api/v1/judge/reliability").json()
    assert report["sample_size"] == 2 and report["agreement"] == 1 and report["kappa"] is None


@pytest.mark.parametrize(
    "expression",
    ['__import__("os").system("id")', "2**100000", "a+2", "[1]", "1/0", "9999999999999999"],
)
def test_calculator_rejects_unsafe_or_unbounded_expressions(expression):
    with pytest.raises((ValueError, SyntaxError, ZeroDivisionError)):
        calculate(expression)


def test_agent_graph_tool_path_and_arguments(client, monkeypatch):
    plans = iter(
        [
            {"tool": "calculator", "arguments": {"expression": "19*7"}, "answer": ""},
            {"tool": "finish", "arguments": {}, "answer": "133"},
        ]
    )

    async def generate(payload):
        return {"response": json.dumps(next(plans))}

    monkeypatch.setattr(ollama, "generate", generate)
    result = client.post(
        "/api/v1/agents/runs",
        json={
            "task": "Calculate 19*7",
            "model": "agent-test",
            "expected_tools": ["calculator"],
            "expected_arguments": [{"expression": "19*7"}],
            "checks": [{"kind": "exact_match", "expected": "133"}],
        },
    ).json()
    assert result["passed"] and result["steps"][0]["result"] == "133"
    assert result["metrics"]["argument_accuracy"] == 1
    assert result["metrics"]["task_completion"] is True


def test_failure_auth_duplicate_conflict_and_approval(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "webhook_secret", "test-secret")
    event = {
        "event_id": "evt-1",
        "source": "app",
        "question": "Refunds?",
        "response": "Never",
        "error": "Policy fail",
    }
    url = "/api/v1/webhooks/ai-failure"
    assert client.post(url, json=event).status_code == 401
    headers = {"Authorization": "Bearer test-secret"}
    first = client.post(url, json=event, headers=headers)
    assert first.status_code == 201
    duplicate = client.post(url, json=event, headers=headers)
    assert duplicate.status_code == 200 and duplicate.json()["id"] == first.json()["id"]
    assert (
        client.post(url, json={**event, "response": "Changed"}, headers=headers).status_code == 409
    )
    dataset = client.post("/api/v1/datasets", json={"name": "Failures"}).json()
    approve = f"/api/v1/failures/{first.json()['id']}/approve"
    payload = {
        "dataset_id": dataset["id"],
        "checks": [{"kind": "required_keywords", "values": ["30 days"]}],
    }
    result = client.post(approve, json=payload).json()
    assert client.post(approve, json=payload).json()["case_id"] == result["case_id"]
    assert len(client.get(f"/api/v1/datasets/{dataset['id']}/cases").json()) == 1


def test_api_auth_separate_from_webhook_auth(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "api_key", "workspace-key")
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/datasets").status_code == 401
    assert (
        client.get(
            "/api/v1/datasets", headers={"Authorization": "Bearer workspace-key"}
        ).status_code
        == 200
    )


def test_marketing_discount_and_human_approval_gate(client):
    bad = client.post(
        "/api/v1/marketing/reviews",
        json={
            "content": "Aura offers 50% off, guaranteed results",
            "brand_keywords": ["Aura"],
            "forbidden_claims": ["guaranteed"],
            "allowed_discounts": ["10%"],
        },
    ).json()
    decision = {"decision": "approved", "reviewer": "Human", "feedback": "Reviewed"}
    assert bad["score"] < 1
    assert (
        client.put(f"/api/v1/marketing/reviews/{bad['id']}/decision", json=decision).status_code
        == 422
    )
    good = client.post(
        "/api/v1/marketing/reviews",
        json={
            "content": "Aura offers 10% off",
            "brand_keywords": ["Aura"],
            "allowed_discounts": ["10%"],
        },
    ).json()
    assert good["score"] == 1 and good["decision"] == "pending"
    assert (
        client.put(f"/api/v1/marketing/reviews/{good['id']}/decision", json=decision).json()[
            "decision"
        ]
        == "approved"
    )


def test_security_pack_is_local_and_saved(client, monkeypatch):
    async def generate(payload):
        return {"response": '{"answer":"I cannot do that."}'}

    monkeypatch.setattr(ollama, "generate", generate)
    result = client.post("/api/v1/security/runs", json={"model": "local-test"}).json()
    assert len(result["results"]) == 6 and result["score"] == 1
    assert len(client.get("/api/v1/traces").json()) == 6
    assert client.get("/api/v1/security/runs").json()[0]["id"] == result["id"]


def test_request_rate_limit(client, monkeypatch):
    _windows.clear()
    monkeypatch.setattr(get_settings(), "request_limit_per_minute", 1)
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 429


def test_ollama_decoding_schema_avoids_large_grammar_repetitions():
    from app.schemas.platform import JudgeVerdict, ToolPlan

    for model in (JudgeVerdict, ToolPlan):
        schema = ollama.decoding_schema(model.model_json_schema())
        assert "maxLength" not in json.dumps(schema)
        assert schema["type"] == "object"
    # The validation model still enforces the original range.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        JudgeVerdict.model_validate(verdict(2))


def test_quality_gate_cli_blocks_bad_outputs(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts/check_quality.py"
    data = tmp_path / "bad.json"
    data.write_text(json.dumps([{"id": "bad", "response": "", "checks": [{"kind": "non_empty"}]}]))
    result = subprocess.run(
        [sys.executable, str(script), str(data)], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["score"] == 0


def test_judge_without_context_does_not_invent_faithfulness(client, monkeypatch):
    mock_judge(monkeypatch, verdict())
    row = client.post(
        "/api/v1/judge/reviews",
        json={"model": "test", "question": "Question", "response": "Answer"},
    ).json()
    assert row["verdict"]["faithfulness"]["score"] is None


def test_agent_can_finish_after_single_tool_budget(client, monkeypatch):
    plans = iter(
        [
            {"tool": "calculator", "arguments": {"expression": "2+3"}, "answer": ""},
            {"tool": "finish", "arguments": {}, "answer": "5"},
        ]
    )

    async def generate(payload):
        if "history" in payload.prompt and "calculator" in payload.prompt:
            assert payload.format["properties"]["tool"]["enum"] == ["finish"]
        return {"response": json.dumps(next(plans))}

    monkeypatch.setattr(ollama, "generate", generate)
    row = client.post(
        "/api/v1/agents/runs",
        json={
            "model": "test",
            "task": "2+3",
            "max_steps": 1,
            "expected_tools": ["calculator"],
            "checks": [{"kind": "exact_match", "expected": "5"}],
        },
    ).json()
    assert row["passed"] and row["metrics"]["task_completion"]


def test_pdf_extraction_from_real_pdf_bytes():
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 700 Td (Refunds within 30 days.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    assert "Refunds within 30 days." in retrieval.extract("policy.pdf", output.getvalue())


def test_langchain_callback_persists_ragas_usage(client):
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    from app.database.session import get_db
    from app.main import app
    from app.monitoring.langchain_traces import LocalModelTraceHandler

    override = app.dependency_overrides[get_db]()
    session = next(override)
    handler = LocalModelTraceHandler(session.get_bind(), "test-ragas-model", "review-test")
    handler.on_chat_model_start(
        {}, [[HumanMessage(content="Evaluate this answer")]], run_id="call-1"
    )
    handler.on_llm_end(
        LLMResult(
            generations=[
                [
                    ChatGeneration(
                        message=AIMessage(
                            content="Supported",
                            usage_metadata={
                                "input_tokens": 8,
                                "output_tokens": 2,
                                "total_tokens": 10,
                            },
                        )
                    )
                ]
            ]
        ),
        run_id="call-1",
    )
    trace = client.get("/api/v1/traces").json()[0]
    assert trace["configuration"]["operation"] == "ragas_metric"
    assert trace["input_tokens"] == 8 and trace["output_tokens"] == 2
    assert trace["response"] == "Supported"
    override.close()
