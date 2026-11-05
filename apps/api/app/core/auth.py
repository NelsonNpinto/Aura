"""Identity (§B11, 0.4): Better Auth JWTs verified via JWKS, or hashed API keys for scripts."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Request
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import system_tx, tenant_tx
from app.core.errors import Forbidden, Unauthorized

Role = Literal[
    "guest",
    "clerk",
    "approver",
    "controller",
    "auditor",
    "admin",
    "vendor",
    "purchasing",
    "receiving",
    "finance",
]
ROLES: frozenset[str] = frozenset(
    {
        "guest",
        "clerk",
        "approver",
        "controller",
        "auditor",
        "admin",
        "vendor",
        "purchasing",
        "receiving",
        "finance",
    }
)
DEMO_ORG_ID = "demo"


@dataclass(frozen=True)
class Principal:
    user_id: str
    org_id: str
    roles: frozenset[str] = field(default_factory=frozenset)
    kind: Literal["jwt", "api_key"] = "jwt"
    email: str | None = None

    @property
    def is_guest(self) -> bool:
        return self.roles <= {"guest"}

    def has_any(self, *roles: str) -> bool:
        return bool(self.roles & set(roles)) or "admin" in self.roles


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(get_settings().aura_jwks_url, cache_keys=True, lifespan=600, timeout=5)


def _principal_from_claims(claims: dict[str, object]) -> Principal:
    sub, org = claims.get("sub"), claims.get("org_id")
    if not isinstance(sub, str) or not sub:
        raise Unauthorized("Token has no subject")
    if not isinstance(org, str) or not org:
        raise Forbidden("No active organization", code="no_active_org")
    raw = claims.get("roles") or []
    items: list[object] = (
        [r.strip() for r in raw.split(",")]
        if isinstance(raw, str)
        else list(raw)
        if isinstance(raw, list)
        else []
    )
    roles = frozenset(r for r in items if isinstance(r, str) and r in ROLES)
    if not roles:
        raise Forbidden("No recognised role in this organization", code="no_role")
    email = claims.get("email")
    return Principal(sub, org, roles, "jwt", email if isinstance(email, str) else None)


def verify_jwt(token: str, *, key: object | None = None) -> Principal:
    s = get_settings()
    try:
        signing_key = key or _jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,  # type: ignore[arg-type]
            algorithms=["EdDSA", "ES256", "RS256"],
            audience=s.aura_jwt_audience,
            issuer=s.aura_jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized(
            "Invalid or expired token", details={"reason": type(exc).__name__}
        ) from exc
    return _principal_from_claims(claims)


# ---- API keys -------------------------------------------------------------------------------

_hasher = PasswordHasher()
API_KEY_PREFIX = "aura_"


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, lookup_prefix, argon2_hash). Only the hash is stored."""
    prefix = secrets.token_hex(5)
    secret = secrets.token_urlsafe(32)
    full = f"{API_KEY_PREFIX}{prefix}_{secret}"
    return full, prefix, _hasher.hash(full)


def parse_api_key(raw: str) -> str | None:
    if not raw.startswith(API_KEY_PREFIX):
        return None
    parts = raw[len(API_KEY_PREFIX) :].split("_", 1)
    if len(parts) != 2 or len(parts[0]) != 10:
        return None
    return parts[0]


async def verify_api_key(raw: str) -> Principal:
    prefix = parse_api_key(raw)
    if prefix is None:
        raise Unauthorized("Malformed API key")
    async with system_tx() as s:
        row = (
            await s.execute(
                text(
                    "SELECT id, org_id, user_id, key_hash, roles FROM core.api_keys "
                    "WHERE prefix = :p AND revoked_at IS NULL"
                ),
                {"p": prefix},
            )
        ).first()
        if row is None:
            raise Unauthorized("Unknown API key")
        try:
            await asyncio.to_thread(_hasher.verify, row.key_hash, raw)
        except VerifyMismatchError as exc:
            raise Unauthorized("Unknown API key") from exc
        await s.execute(
            text("UPDATE core.api_keys SET last_used_at = :t WHERE id = :id"),
            {"t": datetime.now(UTC), "id": row.id},
        )
    roles = frozenset(r for r in (row.roles or []) if r in ROLES)
    return Principal(row.user_id, row.org_id, roles, "api_key")


# ---- FastAPI dependencies ------------------------------------------------------------------


async def get_principal(request: Request) -> Principal:
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    auth = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key")
    if api_key:
        principal = await verify_api_key(api_key)
    elif auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token.startswith(API_KEY_PREFIX):
            principal = await verify_api_key(token)
        else:
            principal = await asyncio.to_thread(verify_jwt, token)
    else:
        raise Unauthorized("Authentication required")
    async with tenant_tx(principal.org_id, principal.user_id) as session:
        membership = (
            await session.execute(
                text("SELECT role FROM ap.procurement_members WHERE user_id=:u"),
                {"u": principal.user_id},
            )
        ).first()
    if membership:
        if principal.kind == "jwt":
            async with system_tx() as owner:
                current = (
                    await owner.execute(
                        text(
                            'SELECT role FROM auth.member WHERE "organizationId"=:o AND "userId"=:u'
                        ),
                        {"o": principal.org_id, "u": principal.user_id},
                    )
                ).first()
            if not current or membership.role not in current.role.split(","):
                raise Forbidden("Workspace access was revoked or changed")
        principal = replace(principal, roles=frozenset({membership.role}))
    if (
        "vendor" in principal.roles
        and request.url.path not in ("/api/v1/me", "/api/v1/usage")
        and not request.url.path.startswith("/api/v1/procurement/")
    ):
        raise Forbidden("Vendor accounts can access only their procurement workspace")
    request.state.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_roles(*roles: str):  # type: ignore[no-untyped-def]
    async def _dep(principal: CurrentPrincipal) -> Principal:
        if not principal.has_any(*roles):
            raise Forbidden(f"Requires one of roles: {', '.join(roles)}")
        return principal

    return Depends(_dep)
