from math import ceil

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.common import DB
from app.core.config import get_settings
from app.models.platform import AgentRun, BatchRun, Document, FailureEvent, JudgeReview, SecurityRun
from app.models.records import Trace

router = APIRouter(prefix="/api/v1")


@router.get("/monitoring")
def monitoring(db: DB):
    settings = get_settings()
    rows = list(db.scalars(select(Trace).order_by(Trace.created_at.desc()).limit(1000)))
    latency = sorted(t.latency_ms for t in rows)
    counts = {
        table.__tablename__: db.scalar(select(func.count(table.id)))
        for table in (Document, BatchRun, JudgeReview, AgentRun, FailureEvent, SecurityRun)
    }
    error_count = sum(t.status == "error" for t in rows)
    return {
        "counts": counts,
        "window_requests": len(rows),
        "window_limit": 1000,
        "error_rate": error_count / len(rows) if rows else None,
        "p95_latency_ms": latency[max(0, ceil(len(latency) * 0.95) - 1)] if latency else None,
        "input_tokens": sum(t.input_tokens or 0 for t in rows)
        if any(t.input_tokens is not None for t in rows)
        else None,
        "output_tokens": sum(t.output_tokens or 0 for t in rows)
        if any(t.output_tokens is not None for t in rows)
        else None,
        "cloud_inference_cost_usd": 0 if rows else None,
        "cost_note": "Ollama provider fee only; electricity and hardware are not estimated.",
        "otel_configured": bool(settings.otel_endpoint),
        "langfuse_configured": bool(settings.langfuse_public_key and settings.langfuse_secret_key),
        "api_auth_enabled": bool(settings.api_key),
        "webhook_enabled": bool(settings.webhook_secret),
        "operations": {
            op: sum(t.configuration.get("operation", "generation") == op for t in rows)
            for op in sorted({t.configuration.get("operation", "generation") for t in rows})
        },
        "recent_errors": [
            {"id": t.id, "model": t.model, "error": t.error, "created_at": t.created_at}
            for t in rows
            if t.error
        ][:20],
    }
