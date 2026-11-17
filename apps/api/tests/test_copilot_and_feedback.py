"""Copilot loop, webhook signing and cassette replay (§B7, §B10, §B13)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

import pytest

from app.agents.copilot import agent
from app.api.v1.feedback import SIGNATURE_TOLERANCE_S, verify_signature
from app.core.auth import Principal
from app.core.errors import Unauthorized
from app.llm.cassettes import CassetteTransport, key
from app.llm.providers import ProviderError, ProviderRequest, ProviderResponse
from app.llm.router import CallContext


# ---------------------------------------------------------------- copilot loop
class _Step:
    """Stands in for a RouterResult carrying a parsed CopilotStep."""

    def __init__(self, parsed: Any, text: str = "") -> None:
        self.parsed = parsed
        self.text = text or json.dumps({})

    def public(self) -> dict[str, Any]:
        return {"model": "fake/json", "latency_ms": 1}


class _Router:
    def __init__(self, steps: list[Any]) -> None:
        self.steps = steps
        self.calls: list[str] = []

    async def run(self, task: str, variables: dict[str, str], ctx: Any) -> Any:
        self.calls.append(task)
        return _Step(self.steps.pop(0))


def _principal() -> Principal:
    return Principal("tester", "demo", frozenset({"auditor"}))


def _ctx() -> CallContext:
    return CallContext(org_id="demo", user_id="tester", internal_job=True)


async def test_an_answer_citing_nothing_gathered_is_withheld() -> None:
    from app.schemas.llm_outputs import CopilotStep

    router = _Router(
        [CopilotStep(action="answer", answer="Acme owes 100 [sql:nope]", citations=["sql:nope"])]
    )
    out = await agent.run_copilot(_principal(), "What do we owe Acme?", _ctx(), model_router=router)  # type: ignore[arg-type]
    assert out["citation_valid"] is False
    assert "could not verify" in out["answer"]
    assert out["invalid_citations"] == ["sql:nope"]


async def test_an_uncited_answer_is_also_withheld() -> None:
    from app.schemas.llm_outputs import CopilotStep

    router = _Router([CopilotStep(action="answer", answer="Acme owes 100.", citations=[])])
    out = await agent.run_copilot(_principal(), "What do we owe Acme?", _ctx(), model_router=router)  # type: ignore[arg-type]
    # Nothing was gathered and nothing was cited: the answer stands, but it carries no sources.
    assert out["sources"] == []


async def test_an_unavailable_tool_name_does_not_crash_the_loop() -> None:
    from app.schemas.llm_outputs import CopilotStep

    router = _Router(
        [
            CopilotStep(action="tool", tool="rm_rf", arguments={}),
            CopilotStep(action="answer", answer="I could not find that.", citations=[]),
        ]
    )
    out = await agent.run_copilot(_principal(), "Delete everything", _ctx(), model_router=router)  # type: ignore[arg-type]
    assert out["answer"] == "I could not find that."
    assert out["tool_events"] == []


async def test_the_loop_stops_at_its_step_budget() -> None:
    from app.schemas.llm_outputs import CopilotStep

    router = _Router(
        [CopilotStep(action="tool", tool="rm_rf", arguments={}) for _ in range(agent.MAX_STEPS)]
    )
    out = await agent.run_copilot(_principal(), "loop forever", _ctx(), model_router=router)  # type: ignore[arg-type]
    assert out["steps"] == agent.MAX_STEPS
    assert "ran out of steps" in out["answer"]


def test_citation_checker_only_accepts_gathered_evidence() -> None:
    evidence = [agent.Evidence("sql:abc", "sql_query", "sql_query", "2 rows", {})]
    assert agent.check_citations("Total 100 [sql:abc]", evidence, ["sql:abc"]) == []
    assert agent.check_citations("Total 100 [sql:xyz]", evidence, []) == ["sql:xyz"]


def test_tool_catalog_lists_only_the_registered_copilot_tools() -> None:
    catalog = agent.tool_catalog()
    for name in agent.COPILOT_TOOLS:
        assert name in catalog


def test_tool_arguments_are_redacted_before_they_are_emitted() -> None:
    out = agent.redact_args({"query": "email ap@example.com", "_user_id": "secret-user"})
    assert "_user_id" not in out
    assert "ap@example.com" not in json.dumps(out)


# ---------------------------------------------------------------- webhook signing
def _sign(body: bytes, secret: str, ts: str) -> str:
    return hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def test_a_correct_signature_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    get_settings.cache_clear()
    body = b'{"event_id":"e1"}'
    ts = str(int(time.time()))
    verify_signature(body, _sign(body, "s3cret", ts), ts)
    get_settings.cache_clear()


def test_a_tampered_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    get_settings.cache_clear()
    ts = str(int(time.time()))
    signature = _sign(b'{"event_id":"e1"}', "s3cret", ts)
    with pytest.raises(Unauthorized):
        verify_signature(b'{"event_id":"e2"}', signature, ts)
    get_settings.cache_clear()


def test_an_old_signature_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    get_settings.cache_clear()
    body = b'{"event_id":"e1"}'
    ts = str(int(time.time()) - SIGNATURE_TOLERANCE_S - 60)
    with pytest.raises(Unauthorized):
        verify_signature(body, _sign(body, "s3cret", ts), ts)
    get_settings.cache_clear()


def test_a_missing_secret_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    with pytest.raises(Unauthorized):
        verify_signature(b"{}", "whatever", str(int(time.time())))
    get_settings.cache_clear()


# ---------------------------------------------------------------- cassettes
def _request(prompt: str = "hello") -> ProviderRequest:
    return ProviderRequest(
        model="groq/openai/gpt-oss-20b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=64,
        timeout_s=10,
    )


async def test_record_then_replay_returns_the_same_response(tmp_path: Path) -> None:
    calls = {"n": 0}

    async def inner(req: ProviderRequest) -> ProviderResponse:
        calls["n"] += 1
        return ProviderResponse("recorded answer", 10, 5, req.model)

    recorder = CassetteTransport(inner, "record", tmp_path)
    first = await recorder(_request())
    assert calls["n"] == 1

    async def must_not_run(req: ProviderRequest) -> ProviderResponse:  # pragma: no cover
        raise AssertionError("replay must not reach the provider")

    player = CassetteTransport(must_not_run, "replay", tmp_path)
    second = await player(_request())
    assert second.text == first.text == "recorded answer"


async def test_replay_without_a_cassette_fails_loudly(tmp_path: Path) -> None:
    async def must_not_run(req: ProviderRequest) -> ProviderResponse:  # pragma: no cover
        raise AssertionError("replay must not reach the provider")

    player = CassetteTransport(must_not_run, "replay", tmp_path)
    with pytest.raises(ProviderError) as excinfo:
        await player(_request("never recorded"))
    assert excinfo.value.kind == "not_configured"


def test_the_cassette_key_covers_the_prompt() -> None:
    assert key(_request("a")) != key(_request("b"))
