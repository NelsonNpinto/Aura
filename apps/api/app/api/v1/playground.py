from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import call_context
from app.core.auth import Principal, require_roles
from app.core.limits import charge_run
from app.llm.router import get_router
from app.monitoring.tracing import get_tracer
from app.schemas.api import PlaygroundRun

router = APIRouter(tags=["playground"])


@router.get("/playground/tasks")
async def tasks(p: Principal = require_roles("admin")) -> list[dict[str, Any]]:
    cfg = get_router().config
    return [
        {
            "task": name,
            "chain": t.chain,
            "prompt": t.prompt.model_dump(),
            "cache": t.cache,
            "temperature": t.temperature,
            "structured": bool(t.output_schema),
        }
        for name, t in cfg.tasks.items()
    ]


@router.post("/playground/run")
async def run(
    body: PlaygroundRun, request: Request, p: Principal = require_roles("admin")
) -> dict[str, Any]:
    await charge_run(p)
    async with get_tracer().span(
        p.org_id, f"playground:{body.task}", kind="llm", input=body.variables
    ) as sp:
        res = await get_router().run(body.task, body.variables, call_context(request, p))
        sp.set_output(
            res.text,
            model=res.model,
            fallback_reason=res.fallback_reason,
            tokens_in=res.tokens_in,
            tokens_out=res.tokens_out,
        )
        return res.public() | {"trace_id": sp.trace_id}
