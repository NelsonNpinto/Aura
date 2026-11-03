import httpx

from app.services import ollama


def test_generate_persists_usage_and_configuration(client, monkeypatch):
    async def fake_generate(payload):
        assert payload.temperature == 0.3
        return {"response": "The answer is 42", "prompt_eval_count": 12, "eval_count": 5}

    monkeypatch.setattr(ollama, "generate", fake_generate)
    response = client.post(
        "/api/v1/playground/generate",
        json={
            "model": "test-local",
            "prompt": "A question",
            "temperature": 0.3,
            "max_tokens": 80,
        },
    )
    assert response.status_code == 201
    trace = response.json()
    assert trace["input_tokens"] == 12
    assert trace["configuration"]["max_tokens"] == 80
    assert trace["latency_ms"] >= 0
    assert client.get("/api/v1/traces/" + trace["id"]).json()["response"] == "The answer is 42"
    stats = client.get("/api/v1/overview").json()
    assert stats["total_requests"] == 1
    assert stats["model_comparison"][0]["model"] == "test-local"
    assert stats["output_tokens"] == 5
    assert (
        client.post(
            "/api/v1/evaluations",
            json={
                "trace_id": trace["id"],
                "response": "Different answer",
                "checks": [{"kind": "non_empty"}],
            },
        ).status_code
        == 422
    )


def test_failed_generation_is_recorded(client, monkeypatch):
    async def fail(payload):
        raise ollama.OllamaUnavailable("Service offline")

    monkeypatch.setattr(ollama, "generate", fail)
    response = client.post(
        "/api/v1/playground/generate", json={"model": "missing", "prompt": "Hello"}
    )
    assert response.status_code == 502
    trace = client.get("/api/v1/traces").json()[0]
    assert trace["status"] == "error"
    assert trace["error"] == "Service offline"
    assert response.json()["detail"]["trace_id"] == trace["id"]
    stats = client.get("/api/v1/overview").json()
    assert stats["request_errors"] == 1
    assert stats["model_comparison"] == []
    assert stats["input_tokens"] is None


def test_model_discovery_offline_is_actionable(client, monkeypatch):
    async def offline(self, *args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.AsyncClient, "get", offline)
    assert client.get("/api/v1/models").json() == {
        "available": False,
        "models": [],
        "message": "Cannot connect to Ollama",
    }


def test_invalid_generation_configuration(client):
    for payload in [
        {"model": "test", "prompt": " "},
        {"model": "test", "prompt": "Hello", "temperature": 3},
        {"model": "test", "prompt": "Hello", "max_tokens": 0},
    ]:
        assert client.post("/api/v1/playground/generate", json=payload).status_code == 422
    assert client.get("/api/v1/traces").json() == []
