"""Database engine and tenant-scoped transactions (§B5).

Tenant work runs as role `aura_app` (RLS enforced) with `app.org_id` set via
`set_config(..., true)` — transaction-local, so Neon's pooler can't leak it across requests.
System work (migrations, seed, auth lookups) runs as the owner role.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

APP_ROLE = "aura_app"


@lru_cache
def get_engine() -> AsyncEngine:
    s = get_settings()
    kwargs: dict[str, object] = {
        # PgBouncer transaction pooling (Neon pooled URL) can't keep server-side prepared statements.
        "connect_args": {"prepare_threshold": None, "connect_timeout": 10},
        "pool_pre_ping": True,
    }
    if s.is_deployed:
        # Serverless: let Neon's pooler pool; don't hold idle connections (keeps Neon able to sleep).
        kwargs["poolclass"] = NullPool
    else:
        kwargs.update(pool_size=5, max_overflow=5)
    return create_async_engine(s.database_url, **kwargs)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def tenant_tx(org_id: str, user_id: str | None = None) -> AsyncIterator[AsyncSession]:
    """One transaction under RLS for `org_id`. Commits on success, rolls back on error."""
    if not org_id:
        raise ValueError("org_id required")
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
        await session.execute(
            text(
                "SELECT set_config('app.org_id', :org, true), set_config('app.user_id', :uid, true)"
            ),
            {"org": org_id, "uid": user_id or ""},
        )
        yield session


@asynccontextmanager
async def system_tx() -> AsyncIterator[AsyncSession]:
    """Owner-role transaction (bypasses RLS). Use only for system jobs and auth lookups."""
    async with get_sessionmaker()() as session, session.begin():
        yield session
