"""Tool gateway: the single policy enforcement point for every tool call (§B9).

1. validate arguments against the registered JSON Schema
2. check agent, user role and org
3. require an approval token for financial tools on non-auto routes
4. Redis rate limit
5. execute (in-process ERP tools, or the ERP MCP server over Streamable HTTP)
6. redact the output
7. audit event + telemetry

A denial returns to the agent as a structured ToolDenied error and is logged and audited.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from app.audit.chain import AuditEvent, append
from app.core.config import get_settings
from app.core.db import tenant_tx
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.store import Window, get_store
from app.guardrails.pii import redact_any

log = get_logger("tools")
REGISTRY_PATH = Path(__file__).with_name("tools.yaml")


class ToolDenied(AppError):
    status_code = 403
    code = "tool_denied"


class ToolFailed(AppError):
    status_code = 502
    code = "tool_failed"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    source: str
    description: str
    risk: str
    allowed_roles: frozenset[str]
    allowed_agents: frozenset[str]
    rate_limit: int
    input_schema: dict[str, Any]
    requires_approval: bool = False
    idempotent: bool = False
    enabled: bool = True
    redact_input: tuple[str, ...] = ()
    version: int = 1


@dataclass
class ToolContext:
    org_id: str
    actor_id: str
    roles: frozenset[str]
    agent: str
    run_id: str | None = None
    route: str | None = None
    approval_token: str | None = None
    audit: bool = True
    events: list[dict[str, Any]] = field(default_factory=list)


@lru_cache
def registry() -> dict[str, ToolSpec]:
    raw = yaml.safe_load(REGISTRY_PATH.read_text())["tools"]
    out = {}
    for name, d in raw.items():
        schema = d["input"]
        Draft202012Validator.check_schema(schema)
        out[name] = ToolSpec(
            name=name,
            source=d["source"],
            description=d["description"],
            risk=d["risk"],
            allowed_roles=frozenset(d["allowed_roles"]),
            allowed_agents=frozenset(d["allowed_agents"]),
            rate_limit=int(d.get("rate_limit", 60)),
            input_schema=schema,
            requires_approval=bool(d.get("requires_approval", False)),
            idempotent=bool(d.get("idempotent", False)),
            enabled=bool(d.get("enabled", True)),
            redact_input=tuple(d.get("redact_input", [])),
        )
    return out


def erp_org_token(org_id: str) -> str:
    s = get_settings().erp_service_token
    root = s.get_secret_value() if s else ""
    return hmac.new(root.encode(), org_id.encode(), hashlib.sha256).hexdigest()


def _redacted_args(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    out = dict(args)
    for k in spec.redact_input:
        if out.get(k):
            out[k] = "[redacted]"
    return redact_any(out)


async def _execute(spec: ToolSpec, org_id: str, args: dict[str, Any]) -> dict[str, Any]:
    if spec.source != "mcp:erp":
        raise ToolFailed(f"No executor for {spec.source}")
    url = get_settings().erp_mcp_url
    if not url:
        from erp_mock import tools as erp  # in-process (tests/local dev): same code as the server

        try:
            return await erp.call(spec.name, org_id, args)
        except erp.ErpError as e:
            return {"error": {"code": e.code, "message": e.message}}
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"x-org-id": org_id, "authorization": f"Bearer {erp_org_token(org_id)}"}
    async with streamablehttp_client(url, headers=headers, timeout=20) as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        res = await s.call_tool(spec.name, args)
    if res.isError:
        text = " ".join(getattr(c, "text", "") for c in res.content)
        return {"error": {"code": "mcp_error", "message": text[:500]}}
    if res.structuredContent is not None:
        sc = res.structuredContent
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    text = "".join(getattr(c, "text", "") for c in res.content)
    return json.loads(text) if text else {}


async def _audit(ctx: ToolContext, spec: ToolSpec | None, name: str, decision: str, args: dict[str, Any],
                 output: Any, details: dict[str, Any]) -> None:
    if not ctx.audit:
        return
    async with tenant_tx(ctx.org_id, ctx.actor_id) as s:
        await append(s, ctx.org_id, AuditEvent(
            action="tool.call", actor_type="agent" if ctx.agent != "human" else "human", actor_id=ctx.actor_id,
            run_id=ctx.run_id, tool=name, decision=decision, input=args, output=output,
            target_type="tool", target_id=name, details={**details, "agent": ctx.agent, "risk": spec.risk if spec else None},
        ))


async def call_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    spec = registry().get(name)
    started = time.monotonic()

    async def deny(code: str, msg: str) -> None:
        log.warning("tool.denied", tool=name, code=code, agent=ctx.agent, org_id=ctx.org_id)
        ctx.events.append({"tool": name, "decision": "denied", "code": code})
        await _audit(ctx, spec, name, "denied", _redacted_args(spec, args) if spec else {}, None, {"code": code, "message": msg})
        raise ToolDenied(msg, code="tool_denied", details={"tool": name, "reason": code})

    if spec is None or not spec.enabled:
        await deny("unknown_tool", f"Tool {name} is not registered or disabled")
        raise AssertionError  # unreachable
    errors = sorted(Draft202012Validator(spec.input_schema, format_checker=FormatChecker()).iter_errors(args), key=str)
    if errors:
        await deny("invalid_arguments", f"Invalid arguments: {errors[0].message[:200]}")
    if ctx.agent not in spec.allowed_agents:
        await deny("agent_not_allowed", f"Agent {ctx.agent} may not call {name}")
    if not (ctx.roles & spec.allowed_roles):
        await deny("role_not_allowed", f"Role not permitted to call {name}")
    if spec.risk == "financial" and spec.requires_approval and ctx.route not in (None, "auto") and not ctx.approval_token:
        await deny("approval_required", f"{name} needs a signed approval token on route {ctx.route}")
    rl = await get_store().take([Window(f"tool:{ctx.org_id}:{name}:{int(time.time() // 60)}", spec.rate_limit, 120)])
    if not rl.allowed:
        await deny("rate_limited", f"Rate limit for {name} exceeded")
    try:
        result = await _execute(spec, ctx.org_id, args)
    except Exception as exc:  # transport or server failure: structured, audited, never silent
        log.error("tool.failed", tool=name, error=type(exc).__name__)
        await _audit(ctx, spec, name, "error", _redacted_args(spec, args), None, {"error": type(exc).__name__})
        raise ToolFailed(f"{name} failed: {type(exc).__name__}", details={"tool": name}) from exc
    out = redact_any(result)
    ms = int((time.monotonic() - started) * 1000)
    decision = "error" if isinstance(out, dict) and "error" in out else "allowed"
    ctx.events.append({"tool": name, "decision": decision, "latency_ms": ms})
    await _audit(ctx, spec, name, decision, _redacted_args(spec, args), out, {"latency_ms": ms})
    return out
