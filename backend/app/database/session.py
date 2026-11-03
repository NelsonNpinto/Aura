import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


# Serverless instances are short-lived and numerous; a per-instance pool would
# hold idle connections the platform never reuses. Pool normally everywhere else.
_serverless = bool(os.environ.get("VERCEL"))
engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    **({"poolclass": NullPool} if _serverless else {}),
)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    with SessionLocal() as session:
        yield session
