import hmac
import logging
import time
from collections import defaultdict, deque
from uuid import uuid4

from fastapi import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

logger = logging.getLogger("aura.requests")
_windows = defaultdict(deque)


async def safeguards(request: Request, call_next):
    settings = get_settings()
    request_id = str(uuid4())
    if request.url.path.startswith("/api/v1"):
        raw = request.headers.get("content-length", "0")
        if not raw.isdigit() or int(raw) > 12 * 1024 * 1024:
            return JSONResponse({"detail": "Request body exceeds 12 MB"}, status_code=413)
        if settings.api_key and request.url.path not in (
            "/api/v1/health",
            "/api/v1/webhooks/ai-failure",
        ):
            if not hmac.compare_digest(
                request.headers.get("authorization", ""), f"Bearer {settings.api_key}"
            ):
                return JSONResponse(
                    {"detail": "API key required. Enter it in Settings."}, status_code=401
                )
        now = time.monotonic()
        ip = request.client.host if request.client else "local"
        window = _windows[ip]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= settings.request_limit_per_minute:
            return JSONResponse(
                {"detail": "Rate limit exceeded; retry in a minute"},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        window.append(now)
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    logger.info(
        "request_id=%s method=%s path=%s status=%s latency_ms=%.2f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - start) * 1000,
    )
    return response
