"""Model router (§B10): one door for every LLM call.

Per call: resolve prompt by label → render with spotlighting → pick A/B variant → filter chain
(geo, open-weight, configured) → exact cache → per-model token buckets (never wait) → call →
validate structured output (one repair retry) → fall back on 429/5xx/timeout → telemetry.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.context import request_id_var, trace_id_var
from app.core.errors import AppError
from app.core.store import Store, Window, day_bucket, get_store, minute_bucket
from app.llm.config import RouterConfig, TaskSpec, load_config
from app.llm.faults import maybe_inject, parse_faults
from app.llm.geo import gemini_free_allowed
from app.llm.providers import (
    FALLBACK_KINDS,
    ProviderError,
    ProviderRequest,
    Transports,
    provider_of,
)
from app.llm.telemetry import DbSink, LlmCallRecord, TelemetrySink
from app.prompts.registry import DbPromptSource, PromptSource, PromptVersion, render


class RouterError(AppError):
    status_code = 503
    code = "router_exhausted"


class StructuredOutputError(Exception):
    pass


@dataclass
class CallContext:
    org_id: str
    user_id: str | None = None
    run_id: str | None = None
    country: str | None = None
    internal_job: bool = False  # evals/CI: explicit, not a visitor


@dataclass
class Attempt:
    model: str
    status: str
    reason: str | None = None
    latency_ms: int = 0


@dataclass
class RouterResult:
    task: str
    text: str
    parsed: BaseModel | None
    model: str
    provider: str
    prompt_name: str
    prompt_version: int
    variant: str | None
    tokens_in: int
    tokens_out: int
    est_cost_microusd: int
    latency_ms: int
    cache_hit: bool
    fallback_reason: str | None
    attempts: list[Attempt] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "text": self.text,
            "parsed": self.parsed.model_dump() if self.parsed else None,
            "model": self.model,
            "provider": self.provider,
            "prompt": {"name": self.prompt_name, "version": self.prompt_version},
            "variant": self.variant,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "est_cost_microusd": self.est_cost_microusd,
            "latency_ms": self.latency_ms,
            "cache_hit": self.cache_hit,
            "fallback_reason": self.fallback_reason,
            "attempts": [a.__dict__ for a in self.attempts],
        }


def _estimate_tokens(messages: list[dict[str, Any]], max_tokens: int) -> int:
    chars = sum(len(str(m.get("content", ""))) for m in messages)
    return chars // 4 + max_tokens


def stable_variant(task: TaskSpec, run_id: str | None) -> str | None:
    if not task.variants or not run_id:
        return None
    h = int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    acc = 0.0
    for v in task.variants:
        acc += v.weight
        if h <= acc:
            return v.name
    return None


def _parse_json_strict(text_: str) -> Any:
    def _no_const(c: str) -> Any:
        raise ValueError(f"non-finite number {c}")

    return json.loads(text_.strip(), parse_constant=_no_const)


class ModelRouter:
    def __init__(
        self,
        *,
        config: RouterConfig | None = None,
        prompts: PromptSource | None = None,
        transports: Transports | None = None,
        store: Store | None = None,
        sink: TelemetrySink | None = None,
        faults: str | None = None,
        cache_ttl_s: int = 6 * 3600,
        org_daily_tokens: int = 300_000,
    ) -> None:
        s = get_settings()
        self.config = config or load_config()
        self.prompts = prompts or DbPromptSource()
        self.transports = transports or Transports()
        self._store = store
        self.sink = sink or DbSink()
        fault_spec = faults if faults is not None else s.router_fault_injection
        self.faults = parse_faults(fault_spec) if s.app_env != "production" else {}
        self.cache_ttl_s = cache_ttl_s
        self.org_daily_tokens = org_daily_tokens

    @property
    def store(self) -> Store:
        return self._store or get_store()

    # ---------------------------------------------------------------- chain selection
    def _chain(
        self, task: TaskSpec, variant: str | None, ctx: CallContext
    ) -> tuple[list[str], list[Attempt]]:
        s = get_settings()
        chain = list(task.chain)
        if variant:
            v = next(v for v in task.variants if v.name == variant)
            chain = list(v.chain or chain)
        skipped: list[Attempt] = []
        allowed: list[str] = []
        for m in chain:
            spec = self.config.models[m]
            if task.open_weight_only and not spec.open_weight:
                skipped.append(Attempt(m, "skipped", "closed_weights_for_training_task"))
            elif spec.free_tier_geo_restricted and not gemini_free_allowed(
                ctx.country, unknown_allowed=ctx.internal_job or not s.is_deployed
            ):
                skipped.append(Attempt(m, "skipped", "geo_restricted_free_tier"))
            elif spec.local_only and s.is_deployed:
                skipped.append(Attempt(m, "skipped", "local_only"))
            else:
                allowed.append(m)
        return allowed, skipped

    def _cache_key(
        self, task_name: str, chain: list[str], pv: PromptVersion, msgs: list[dict[str, Any]]
    ) -> str:
        blob = json.dumps(
            {"t": task_name, "c": chain, "p": [pv.name, pv.version], "m": msgs}, sort_keys=True
        )
        return "llmcache:" + hashlib.sha256(blob.encode()).hexdigest()

    async def _take_bucket(self, model: str, est_tokens: int, org_id: str) -> str | None:
        spec = self.config.models[model]
        if provider_of(model) == "fake":
            return None
        res = await self.store.take(
            [
                Window(f"tb:{model}:rpm:{minute_bucket()}", spec.rpm, 60),
                Window(f"tb:{model}:rpd:{day_bucket()}", spec.rpd, 86_400 + 60),
                Window(
                    f"tb:{model}:tpm:{minute_bucket()}",
                    spec.tpm,
                    60,
                    cost=min(est_tokens, spec.tpm),
                ),
                Window(
                    f"tok:org:{org_id}:{day_bucket()}",
                    self.org_daily_tokens,
                    86_400 + 60,
                    cost=est_tokens,
                ),
            ]
        )
        if res.allowed:
            return None
        return (
            "org_token_budget"
            if (res.failed_key or "").startswith("tok:org")
            else "bucket_exhausted"
        )

    # ---------------------------------------------------------------- main entry
    async def run(
        self,
        task_name: str,
        variables: dict[str, str],
        ctx: CallContext,
        *,
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> RouterResult:
        if task_name not in self.config.tasks:
            raise AppError(f"unknown task {task_name}", code="unknown_task", status_code=400)
        task = self.config.tasks[task_name]
        variant = stable_variant(task, ctx.run_id)
        label = task.prompt.label
        if variant:
            vlabel = next(v for v in task.variants if v.name == variant).prompt_label
            label = vlabel or label
        pv = await self.prompts.resolve(task.prompt.name, label)
        messages: list[dict[str, Any]] = render(pv, variables) + list(extra_messages or [])
        chain, attempts = self._chain(task, variant, ctx)
        schema = task.schema_model()
        trace_id = trace_id_var.get() or uuid.uuid4().hex
        records: list[LlmCallRecord] = []

        def rec(model: str, status: str, **kw: Any) -> LlmCallRecord:
            r = LlmCallRecord(
                org_id=ctx.org_id,
                task=task_name,
                provider=provider_of(model) if model != "cache" else "cache",
                model=model,
                status=status,
                trace_id=trace_id,
                request_id=request_id_var.get(),
                run_id=ctx.run_id,
                prompt_name=pv.name,
                prompt_version=pv.version,
                variant=variant,
                attempt=len(records) + 1,
                **kw,
            )
            records.append(r)
            return r

        try:
            cache_key = None
            if task.cache == "exact" and task.temperature == 0:
                cache_key = self._cache_key(task_name, chain, pv, messages)
                if cached := await self.store.get(cache_key):
                    data = json.loads(cached)
                    parsed = (
                        schema.model_validate(data["parsed"])
                        if schema and data.get("parsed")
                        else None
                    )
                    rec(data["model"], "ok", cache_hit=True)
                    return RouterResult(
                        task_name,
                        data["text"],
                        parsed,
                        data["model"],
                        provider_of(data["model"]),
                        pv.name,
                        pv.version,
                        variant,
                        0,
                        0,
                        0,
                        0,
                        True,
                        None,
                        [Attempt(data["model"], "cache_hit")],
                    )

            fallback_reason: str | None = None
            for model in chain:
                est = _estimate_tokens(messages, task.max_tokens)
                if why := await self._take_bucket(model, est, ctx.org_id):
                    if why == "org_token_budget":
                        rec(model, "skipped", fallback_reason=fallback_reason, error_type=why)
                        raise RouterError(
                            "Organization daily token budget exhausted",
                            code="budget_exhausted",
                            status_code=429,
                        )
                    attempts.append(Attempt(model, "skipped", why))
                    rec(model, "skipped", fallback_reason=fallback_reason, error_type=why)
                    fallback_reason = f"{model}:{why}"
                    continue
                result = await self._try_model(
                    task, task_name, model, messages, schema, attempts, rec, fallback_reason
                )
                if isinstance(result, RouterResult):
                    result.variant = variant
                    result.prompt_name, result.prompt_version = pv.name, pv.version
                    if cache_key:
                        await self.store.set(
                            cache_key,
                            json.dumps(
                                {
                                    "text": result.text,
                                    "model": result.model,
                                    "parsed": result.parsed.model_dump() if result.parsed else None,
                                }
                            ),
                            self.cache_ttl_s,
                        )
                    return result
                fallback_reason = result
            raise RouterError(
                f"All models failed for task {task_name}",
                details={"attempts": [a.__dict__ for a in attempts]},
            )
        finally:
            await self.sink.write(records)

    async def _try_model(
        self,
        task: TaskSpec,
        task_name: str,
        model: str,
        messages: list[dict[str, Any]],
        schema: type[BaseModel] | None,
        attempts: list[Attempt],
        rec: Any,
        fallback_reason: str | None,
    ) -> RouterResult | str:
        """Returns a RouterResult on success, or the fallback reason string to continue."""
        spec = self.config.models[model]
        convo = list(messages)
        for repair in (False, True):
            t0 = time.perf_counter()
            try:
                maybe_inject(model, self.faults)
                resp = await self.transports(
                    ProviderRequest(
                        model,
                        convo,
                        task.temperature,
                        task.max_tokens,
                        task.timeout_s,
                        json_mode=schema is not None,
                    )
                )
            except ProviderError as exc:
                ms = int((time.perf_counter() - t0) * 1000)
                attempts.append(Attempt(model, "error", exc.kind, ms))
                rec(
                    model,
                    "error",
                    latency_ms=ms,
                    fallback_reason=fallback_reason,
                    error_type=exc.kind,
                )
                if exc.kind in FALLBACK_KINDS:
                    return f"{model}:{exc.kind}"
                return f"{model}:{exc.kind}"  # non-retryable for this model; next model may differ
            ms = int((time.perf_counter() - t0) * 1000)
            cost = spec.cost_microusd(resp.tokens_in, resp.tokens_out)
            parsed: BaseModel | None = None
            if schema is not None:
                try:
                    parsed = schema.model_validate(_parse_json_strict(resp.text))
                except (ValueError, ValidationError) as exc:
                    attempts.append(Attempt(model, "invalid_output", type(exc).__name__, ms))
                    rec(
                        model,
                        "error",
                        latency_ms=ms,
                        tokens_in=resp.tokens_in,
                        tokens_out=resp.tokens_out,
                        est_cost_microusd=cost,
                        fallback_reason=fallback_reason,
                        error_type="invalid_output",
                    )
                    if repair:
                        return f"{model}:invalid_output"
                    convo = [
                        *convo,
                        {"role": "assistant", "content": resp.text[:4000]},
                        {
                            "role": "user",
                            "content": "Your previous output failed validation: "
                            f"{str(exc)[:500]}\nReturn ONLY a single valid JSON object matching the schema.",
                        },
                    ]
                    continue
            attempts.append(Attempt(model, "ok", None, ms))
            rec(
                model,
                "ok",
                latency_ms=ms,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                est_cost_microusd=cost,
                fallback_reason=fallback_reason,
            )
            return RouterResult(
                task_name,
                resp.text,
                parsed,
                model,
                provider_of(model),
                "",
                0,
                None,
                resp.tokens_in,
                resp.tokens_out,
                cost,
                ms,
                False,
                fallback_reason,
                attempts,
            )
        return f"{model}:invalid_output"


_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
