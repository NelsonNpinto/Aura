"""Alembic env. Uses the DIRECT (unpooled) URL. Only manages AURA schemas, never `auth`
(Better Auth) or LangGraph's checkpoint tables."""

from __future__ import annotations

from sqlalchemy import create_engine, pool

from alembic import context
from app.core.config import get_settings
from app.models.tables import APP_SCHEMAS, metadata

config = context.config


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    if type_ == "table":
        return obj.schema in APP_SCHEMAS
    return True


def include_name(name, type_, parent_names):  # type: ignore[no-untyped-def]
    if type_ == "schema":
        return name in APP_SCHEMAS
    return True


def run_migrations_online() -> None:
    engine = create_engine(
        get_settings().migration_url,
        poolclass=pool.NullPool,
        connect_args={"prepare_threshold": None},
    )
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=metadata,
            include_schemas=True,
            include_object=include_object,
            include_name=include_name,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
