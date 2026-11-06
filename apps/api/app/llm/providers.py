"""Provider transports. The ONLY module that talks to model SDKs (§A3.7).

Errors are normalised into ProviderError with a `kind` the router uses to decide fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.core.config import get_settings

ErrorKind = Literal[
    "rate_limited",
    "server_error",
    "timeout",
    "connection",
    "not_configured",
    "model_unavailable",
    "bad_request",
    "auth",
]
FALLBACK_KINDS: frozenset[str] = frozenset(
    # model_unavailable: provider retired or renamed the model (HTTP 404) -> try the next one.
    {"rate_limited", "server_error", "timeout", "connection", "not_configured", "model_unavailable"}
)


class ProviderError(Exception):
    def __init__(self, kind: ErrorKind, message: str = "") -> None:
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind = kind


@dataclass
class ProviderRequest:
    model: str
    messages: list[dict[str, Any]]
    temperature: float
    max_tokens: int
    timeout_s: float
    json_mode: bool = False


@dataclass
class ProviderResponse:
    text: str
    tokens_in: int
    tokens_out: int
    raw_model: str | None = None


class Transport(Protocol):
    async def __call__(self, req: ProviderRequest) -> ProviderResponse: ...


def provider_of(model: str) -> str:
    return model.split("/", 1)[0]


# ---------------------------------------------------------------- fake provider (tests/load)


@dataclass
class FakeProvider:
    """Deterministic provider. `scripted` maps model -> list of responses/exceptions (FIFO);
    `by_task_prompt` lets tests key canned JSON on a substring of the last user message."""

    scripted: dict[str, list[str | Exception]] = field(default_factory=dict)
    by_substring: list[tuple[str, str]] = field(default_factory=list)
    calls: list[ProviderRequest] = field(default_factory=list)

    async def __call__(self, req: ProviderRequest) -> ProviderResponse:
        self.calls.append(req)
        queue = self.scripted.get(req.model)
        if queue:
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return self._resp(req, item)
        last = str(req.messages[-1].get("content", "")) if req.messages else ""
        for needle, reply in self.by_substring:
            if needle in last:
                return self._resp(req, reply)
        digest = hashlib.sha256(last.encode()).hexdigest()[:12]
        if req.model == "fake/json" or req.json_mode:
            return self._resp(req, json.dumps({"echo": digest}))
        return self._resp(req, f"[fake:{digest}] {last[:200]}")

    @staticmethod
    def _resp(req: ProviderRequest, text: str) -> ProviderResponse:
        tin = sum(len(str(m.get("content", ""))) for m in req.messages) // 4 + 1
        return ProviderResponse(text, tin, len(text) // 4 + 1, req.model)


# ---------------------------------------------------------------- LiteLLM transport


def _api_key_for(model: str) -> str | None:
    s = get_settings()
    p = provider_of(model)
    secret = {"groq": s.groq_api_key, "gemini": s.gemini_api_key}.get(p)
    return secret.get_secret_value() if secret else None


def provider_configured(model: str) -> bool:
    s = get_settings()
    p = provider_of(model)
    if p == "fake":
        return True
    if p in ("groq", "gemini"):
        return _api_key_for(model) is not None
    if p == "bedrock":
        return s.enable_bedrock
    if p == "ollama":
        return bool(s.ollama_base_url) and not s.is_deployed
    return False


async def litellm_transport(req: ProviderRequest) -> ProviderResponse:
    if not provider_configured(req.model):
        raise ProviderError("not_configured", req.model)
    import litellm
    from litellm import exceptions as lx

    litellm.telemetry = False
    litellm.drop_params = True
    kwargs: dict[str, Any] = {
        "model": req.model,
        "messages": req.messages,
        # Gemini 3 degrades (loops, failures) below temperature 1.0 per Google's guidance;
        # determinism there comes from the exact cache and JSON validation instead.
        "temperature": 1.0 if req.model.startswith("gemini/gemini-3") else req.temperature,
        "max_tokens": req.max_tokens,
        "timeout": req.timeout_s,
        "num_retries": 0,
    }
    if key := _api_key_for(req.model):
        kwargs["api_key"] = key
    if provider_of(req.model) == "ollama":
        kwargs["api_base"] = get_settings().ollama_base_url
    if req.json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=req.timeout_s + 2)
    except TimeoutError as exc:
        raise ProviderError("timeout", req.model) from exc
    except lx.RateLimitError as exc:
        raise ProviderError("rate_limited", type(exc).__name__) from exc
    except lx.Timeout as exc:
        raise ProviderError("timeout", type(exc).__name__) from exc
    except (lx.InternalServerError, lx.ServiceUnavailableError) as exc:
        raise ProviderError("server_error", type(exc).__name__) from exc
    except lx.APIConnectionError as exc:
        raise ProviderError("connection", type(exc).__name__) from exc
    except lx.NotFoundError as exc:
        raise ProviderError("model_unavailable", type(exc).__name__) from exc
    except lx.AuthenticationError as exc:
        raise ProviderError("auth", type(exc).__name__) from exc
    except lx.BadRequestError as exc:
        raise ProviderError("bad_request", type(exc).__name__) from exc
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    return ProviderResponse(
        text=choice.message.content or "",
        tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
        tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
        raw_model=getattr(resp, "model", None),
    )


@dataclass
class Transports:
    """Dispatch by provider prefix. Tests replace `fake` or `default`."""

    fake: Transport = field(default_factory=FakeProvider)
    default: Callable[[ProviderRequest], Awaitable[ProviderResponse]] = litellm_transport

    async def __call__(self, req: ProviderRequest) -> ProviderResponse:
        if provider_of(req.model) == "fake":
            return await self.fake(req)
        return await self.default(req)
