from sqlalchemy import create_engine

from alembic import context
from app.core.config import get_settings
from app.database.session import Base, psycopg_url
from app.models import platform, records  # noqa: F401

config = context.config
if context.is_offline_mode():
    context.configure(
        url=psycopg_url(get_settings().database_url),
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(psycopg_url(get_settings().database_url)).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
