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
from app.core.logging import get_logger

log = get_logger(__name__)

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
    if p == "specialist":
        return bool(s.enable_specialist and s.specialist_space_id and s.hf_token)
    return False


# ---------------------------------------------------------------- specialist (HF ZeroGPU Space)
SPECIALIST_TIMEOUT_S = 18.0  # §B15: 15-20 s, then fall back to the general chain


async def specialist_transport(req: ProviderRequest) -> ProviderResponse:
    """Call the fine-tuned specialist served by a free ZeroGPU Gradio Space.

    Free ZeroGPU gives roughly 5 GPU-minutes a day, and a cold Space can take longer than the
    whole request budget, so the timeout is short and every failure is a normal fallback.
    The Space's HTTP API is called directly; no extra client dependency.
    """
    s = get_settings()
    if not provider_configured(req.model):
        raise ProviderError("not_configured", req.model)
    import httpx

    space = str(s.specialist_space_id).strip("/")
    base = space if space.startswith("http") else f"https://{space.replace('/', '-')}.hf.space"
    token = s.hf_token.get_secret_value() if s.hf_token else ""
    prompt = "\n\n".join(str(m.get("content", "")) for m in req.messages)
    timeout = min(req.timeout_s, SPECIALIST_TIMEOUT_S)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            start = await client.post(
                f"{base}/gradio_api/call/predict",
                headers={"Authorization": f"Bearer {token}"},
                json={"data": [prompt, req.max_tokens]},
            )
            if start.status_code == 429:
                raise ProviderError("rate_limited", "zerogpu_quota")
            if start.status_code >= 500:
                raise ProviderError("server_error", str(start.status_code))
            if start.status_code >= 400:
                raise ProviderError("bad_request", str(start.status_code))
            event_id = start.json().get("event_id")
            if not event_id:
                raise ProviderError("server_error", "no event id")
            result = await client.get(
                f"{base}/gradio_api/call/predict/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            text = _parse_gradio_sse(result.text)
    except ProviderError:
        raise
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise ProviderError("timeout", "specialist") from exc
    except httpx.HTTPError as exc:
        raise ProviderError("connection", type(exc).__name__) from exc
    if not text:
        raise ProviderError("server_error", "empty specialist response")
    return ProviderResponse(text, len(prompt) // 4 + 1, len(text) // 4 + 1, req.model)


def _parse_gradio_sse(body: str) -> str:
    """Gradio's /call endpoint streams `event:`/`data:` lines; take the last complete payload."""
    out = ""
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "null":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list) and parsed:
            out = str(parsed[0])
        elif isinstance(parsed, str):
            out = parsed
    return out


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
        # Groq answers 400 json_validate_failed when the model emits invalid JSON; keep the
        # provider's reason (truncated) so a fallback chain that fails is diagnosable.
        log.warning("provider.bad_request", model=req.model, detail=str(exc)[:300])
        raise ProviderError("bad_request", type(exc).__name__) from exc
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    return ProviderResponse(
        text=choice.message.content or "",
        tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
        tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
        raw_model=getattr(resp, "model", None),
    )


def _default_transport() -> Callable[[ProviderRequest], Awaitable[ProviderResponse]]:
    """LiteLLM, optionally wrapped in cassette record/replay for deterministic CI (§B10)."""
    s = get_settings()
    if s.router_cassette_mode in ("record", "replay"):
        from app.llm.cassettes import wrap

        return wrap(litellm_transport, s.router_cassette_mode, s.router_cassette_dir or None)
    return litellm_transport


@dataclass
class Transports:
    """Dispatch by provider prefix. Tests replace `fake` or `default`."""

    fake: Transport = field(default_factory=FakeProvider)
    default: Callable[[ProviderRequest], Awaitable[ProviderResponse]] = field(
        default_factory=_default_transport
    )

    specialist: Callable[[ProviderRequest], Awaitable[ProviderResponse]] = specialist_transport

    async def __call__(self, req: ProviderRequest) -> ProviderResponse:
        provider = provider_of(req.model)
        if provider == "fake":
            return await self.fake(req)
        if provider == "specialist":
            return await self.specialist(req)
        return await self.default(req)
