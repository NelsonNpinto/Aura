import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def psycopg_url(url):
    """Hosted Postgres hands out postgresql:// URLs, which SQLAlchemy resolves to
    psycopg2. This project installs psycopg 3, so accept either spelling rather
    than failing at import with a missing-driver error."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


# Serverless instances are short-lived and numerous; a per-instance pool would
# hold idle connections the platform never reuses. Pool normally everywhere else.
_serverless = bool(os.environ.get("VERCEL"))
engine = create_engine(
    psycopg_url(get_settings().database_url),
    pool_pre_ping=True,
    **({"poolclass": NullPool} if _serverless else {}),
)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    with SessionLocal() as session:
        yield session
