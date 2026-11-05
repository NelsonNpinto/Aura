"""Global rate limiter and the budget governor (§B4, 0.8). Redis-enforced, one command per check."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.core.auth import Principal
from app.core.config import get_settings
from app.core.errors import RateLimited
from app.core.middleware import client_ip
from app.core.store import Window, day_bucket, get_store, minute_bucket, seconds_to_utc_midnight


async def rate_limit(request: Request) -> None:
    """Per-client-IP fixed window. Returns 429 + Retry-After when exceeded."""
    s = get_settings()
    ip = client_ip(request.headers, request.client.host if request.client else None)
    res = await get_store().take(
        [Window(f"rl:ip:{ip}:{minute_bucket()}", s.rate_limit_per_minute, 60)]
    )
    if not res.allowed:
        raise RateLimited(
            "Too many requests",
            headers={"Retry-After": str(res.retry_after_s)},
            details={"retry_after_s": res.retry_after_s},
        )


@dataclass(frozen=True)
class BudgetKeys:
    global_key: str
    org_key: str
    user_key: str


def budget_keys(p: Principal) -> BudgetKeys:
    day = day_bucket()
    return BudgetKeys(
        f"budget:global:{day}", f"budget:org:{p.org_id}:{day}", f"budget:user:{p.user_id}:{day}"
    )


def _limits(p: Principal) -> tuple[int, int, int]:
    s = get_settings()
    user_limit = s.guest_daily_runs if p.is_guest else s.org_daily_runs
    return s.daily_run_budget, s.org_daily_runs, user_limit


async def charge_run(p: Principal) -> None:
    """Consume one run from global, org and user daily budgets, or raise budget_exhausted."""
    k = budget_keys(p)
    g, o, u = _limits(p)
    ttl = seconds_to_utc_midnight() + 60
    res = await get_store().take(
        [Window(k.global_key, g, ttl), Window(k.org_key, o, ttl), Window(k.user_key, u, ttl)]
    )
    if not res.allowed:
        scope = (res.failed_key or "").split(":")[1] if res.failed_key else "global"
        raise RateLimited(
            f"Daily demo budget exhausted ({scope}). Recorded runs remain available.",
            code="budget_exhausted",
            headers={"Retry-After": str(res.retry_after_s)},
            details={"scope": scope, "retry_after_s": res.retry_after_s},
        )


async def usage_snapshot(p: Principal) -> dict[str, object]:
    k = budget_keys(p)
    g, o, u = _limits(p)
    used = await get_store().peek([k.global_key, k.org_key, k.user_key])
    return {
        "day_utc": day_bucket(),
        "resets_in_s": seconds_to_utc_midnight(),
        "global": {"used": used[0], "limit": g, "remaining": max(g - used[0], 0)},
        "org": {"used": used[1], "limit": o, "remaining": max(o - used[1], 0)},
        "user": {"used": used[2], "limit": u, "remaining": max(u - used[2], 0)},
    }
