from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


def new_id():
    return str(uuid4())


def now():
    return datetime.now(UTC)


class Trace(Base):
    __tablename__ = "traces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    model: Mapped[str] = mapped_column(String(200), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    system: Mapped[str] = mapped_column(Text, default="")
    configuration: Mapped[dict] = mapped_column(JSON)
    response: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float] = mapped_column(Float)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    name: Mapped[str] = mapped_column(String(200))
    trace_id: Mapped[str | None] = mapped_column(ForeignKey("traces.id"), index=True)
    response: Mapped[str] = mapped_column(Text)
    configuration: Mapped[dict] = mapped_column(JSON)
    results: Mapped[list] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)
    passed: Mapped[bool]
