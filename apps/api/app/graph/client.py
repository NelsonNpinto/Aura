"""Neo4j AuraDB Free access (§B8.2).

`neo4j` is an optional runtime dependency. When the driver is missing, no credentials are
configured, or the instance is paused or unreachable, every call raises `GraphUnavailable` and
callers degrade to an explicit "unavailable" verdict — never a silent pass (§B18).

Generated Cypher is kept read-only by the *server*: it runs inside `execute_read` with a
transaction timeout, so a write fails at the database even if validation misses it. AuraDB Free
has no RBAC, so that is the real control; `guard.py` is the second layer.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger("graph")

READ_TIMEOUT_S = 10.0
WRITE_TIMEOUT_S = 30.0
MAX_ROWS = 100
# A paused AuraDB Free instance can take ~30 s to resume. Don't pay that on every request:
# after a failure the graph is treated as unavailable for this long (§B18, RUNBOOK).
BACKOFF_S = 60.0

_unavailable_until = 0.0
_last_reason = ""


class GraphUnavailable(AppError):
    status_code = 503
    code = "graph_unavailable"


def configured() -> bool:
    s = get_settings()
    return bool(s.neo4j_uri and s.neo4j_username and s.neo4j_password)


def driver_installed() -> bool:
    try:
        import neo4j  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def _mark_unavailable(reason: str) -> None:
    global _unavailable_until, _last_reason
    _unavailable_until = time.monotonic() + BACKOFF_S
    _last_reason = reason
    log.warning("graph.unavailable", reason=reason)


def reset_backoff() -> None:
    """Clear the negative cache (tests, and after a manual AuraDB resume)."""
    global _unavailable_until, _last_reason
    _unavailable_until, _last_reason = 0.0, ""
    _driver.cache_clear()


def availability() -> tuple[bool, str]:
    """(usable, reason). Cheap: never touches the network."""
    if not driver_installed():
        return False, "driver_not_installed"
    if not configured():
        return False, "not_configured"
    if time.monotonic() < _unavailable_until:
        return False, _last_reason or "recent_failure"
    return True, "ok"


@lru_cache
def _driver() -> Any:
    from neo4j import AsyncGraphDatabase

    s = get_settings()
    assert s.neo4j_uri and s.neo4j_username and s.neo4j_password
    return AsyncGraphDatabase.driver(
        s.neo4j_uri,
        auth=(s.neo4j_username, s.neo4j_password.get_secret_value()),
        connection_timeout=10,
        max_connection_pool_size=4,
        connection_acquisition_timeout=15,
    )


def _database() -> str | None:
    # AuraDB Free names the database after the instance id, not "neo4j".
    return get_settings().neo4j_database or None


def _require() -> Any:
    usable, reason = availability()
    if not usable:
        raise GraphUnavailable(f"Knowledge graph unavailable: {reason}", details={"reason": reason})
    return _driver()


def _rows(result: Sequence[Any], limit: int) -> list[dict[str, Any]]:
    return [dict(r) for r in result[:limit]]


async def read(
    cypher: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = READ_TIMEOUT_S,  # noqa: ASYNC109 — Neo4j transaction timeout, enforced
    # server-side, so the query stops at the database; asyncio.timeout would only drop the client.
    limit: int = MAX_ROWS,
) -> list[dict[str, Any]]:
    """Run one read-only query. Raises GraphUnavailable on any transport or server failure.

    The session's access mode is READ and the transaction carries a server-side timeout, so a
    write attempt is refused by the database and a runaway query is stopped there — not merely
    abandoned by the client. `execute_read` cannot carry a timeout (it forwards keyword
    arguments to the transaction function), so the transaction is begun explicitly.
    """
    drv = _require()
    try:
        async with drv.session(database=_database(), default_access_mode="READ") as session:
            tx = await session.begin_transaction(timeout=timeout)
            try:
                result = await tx.run(cypher, params or {})
                records = [record async for record in result]
                await tx.commit()
            finally:
                await tx.close()
    except GraphUnavailable:
        raise
    except Exception as exc:  # paused instance, auth failure, timeout, write attempt
        _mark_unavailable(type(exc).__name__)
        raise GraphUnavailable(
            f"Knowledge graph query failed: {type(exc).__name__}",
            details={"reason": type(exc).__name__},
        ) from exc
    return _rows(records, limit)


async def write_many(statements: Sequence[tuple[str, dict[str, Any]]]) -> int:
    """Apply idempotent MERGE statements in one write transaction. Returns the count applied."""
    drv = _require()

    try:
        async with drv.session(database=_database()) as session:
            tx = await session.begin_transaction(timeout=WRITE_TIMEOUT_S)
            try:
                for cypher, params in statements:
                    await tx.run(cypher, params)
                await tx.commit()
            finally:
                await tx.close()
            return len(statements)
    except Exception as exc:
        _mark_unavailable(type(exc).__name__)
        raise GraphUnavailable(
            f"Knowledge graph write failed: {type(exc).__name__}",
            details={"reason": type(exc).__name__},
        ) from exc


async def ping() -> dict[str, str]:
    """Keep-alive / readiness probe. Never raises."""
    usable, reason = availability()
    if not usable:
        return {"status": "unavailable", "reason": reason}
    try:
        await read("RETURN 1 AS ok", timeout=8.0)
    except GraphUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc.details.get("reason", "error"))}
    return {"status": "ok", "reason": "ok"}
