"""AURA API app factory."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    account,
    challenge,
    copilot,
    copilot_chat,
    eval_report,
    feedback,
    graph,
    guardrails,
    health,
    knowledge,
    marketing_quality,
    memory,
    models,
    observability,
    onboarding,
    playground,
    procurement,
    prompts,
    quality,
    runs,
)
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.limits import rate_limit
from app.core.logging import configure_logging
from app.core.middleware import BodyLimitMiddleware, RequestContextMiddleware
from app.mcp_server.server import mcp


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # The MCP session manager backs the stateless Streamable HTTP transport at /mcp (§B9).
    async with mcp.session_manager.run():
        yield


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    app = FastAPI(
        title="AURA API",
        version="0.1.0",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(health.router)
    v1.include_router(eval_report.router)  # public: the eval report has no tenant data
    limited = APIRouter(dependencies=[Depends(rate_limit)])
    for r in (
        account.router,
        playground.router,
        prompts.router,
        knowledge.router,
        runs.router,
        procurement.router,
        quality.router,
        marketing_quality.router,
        copilot.router,
        copilot_chat.router,
        graph.router,
        memory.router,
        guardrails.router,
        feedback.router,
        observability.router,
        models.router,
        onboarding.router,
    ):
        limited.include_router(r)
    v1.include_router(limited)
    v1.include_router(challenge.router)  # public, Turnstile + its own rate limit
    app.include_router(v1)
    app.mount("/mcp", mcp.streamable_http_app())

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "authorization",
            "content-type",
            "x-api-key",
            "x-request-id",
            "last-event-id",
            "x-aura-persona",
            "mcp-session-id",
            "mcp-protocol-version",
        ],
        expose_headers=["x-request-id", "retry-after", "x-run-id", "mcp-session-id"],
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=s.max_body_bytes)
    app.add_middleware(RequestContextMiddleware, hsts=s.is_deployed)
    return app


app = create_app()
