from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.records import new_id, now


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Prompt(Record, Base):
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("name", "version"),)
    name: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[int] = mapped_column(Integer)
    system: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(Text)
    configuration: Mapped[dict] = mapped_column(JSON)


class Dataset(Record, Base):
    __tablename__ = "evaluation_datasets"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)


class Case(Record, Base):
    __tablename__ = "evaluation_cases"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("evaluation_datasets.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    expected: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)
    contexts: Mapped[list] = mapped_column(JSON)
    checks: Mapped[list] = mapped_column(JSON)


class BatchRun(Record, Base):
    __tablename__ = "dataset_runs"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("evaluation_datasets.id"), index=True)
    configuration: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)
    passed: Mapped[bool]
    latency_ms: Mapped[float] = mapped_column(Float)
    errors: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    baseline_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_runs.id"))
    gate: Mapped[dict] = mapped_column(JSON)
    case_snapshot: Mapped[list] = mapped_column(JSON)


class CaseResult(Record, Base):
    __tablename__ = "evaluation_results"
    run_id: Mapped[str] = mapped_column(ForeignKey("dataset_runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("evaluation_cases.id"), index=True)
    trace_id: Mapped[str | None] = mapped_column(ForeignKey("traces.id"))
    judge_review_id: Mapped[str | None] = mapped_column(
        ForeignKey("judge_reviews.id", name="fk_evaluation_results_judge_review_id")
    )
    response: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    passed: Mapped[bool]
    latency_ms: Mapped[float] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    results: Mapped[list] = mapped_column(JSON)


class RegressionTest(Record, Base):
    __tablename__ = "regression_tests"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("evaluation_datasets.id"), unique=True)
    baseline_id: Mapped[str] = mapped_column(ForeignKey("dataset_runs.id"))
    thresholds: Mapped[dict] = mapped_column(JSON)


class Document(Record, Base):
    __tablename__ = "documents"
    name: Mapped[str] = mapped_column(String(250))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    content: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(250))
    chunk_count: Mapped[int] = mapped_column(Integer)


class Chunk(Record, Base):
    __tablename__ = "document_chunks"
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(Vector(384).with_variant(JSON(), "sqlite"))


class JudgeReview(Record, Base):
    __tablename__ = "judge_reviews"
    question: Mapped[str] = mapped_column(Text)
    expected: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    contexts: Mapped[list] = mapped_column(JSON)
    configuration: Mapped[dict] = mapped_column(JSON)
    verdict: Mapped[dict] = mapped_column(JSON)
    passed: Mapped[bool | None]
    score: Mapped[float | None] = mapped_column(Float)
    trace_id: Mapped[str | None] = mapped_column(ForeignKey("traces.id"))
    engine: Mapped[str] = mapped_column(String(30))
    error: Mapped[str | None] = mapped_column(Text)


class HumanReview(Record, Base):
    __tablename__ = "human_reviews"
    judge_review_id: Mapped[str] = mapped_column(ForeignKey("judge_reviews.id"), unique=True)
    reviewer: Mapped[str] = mapped_column(String(100))
    passed: Mapped[bool]
    score: Mapped[float] = mapped_column(Float)
    feedback: Mapped[str] = mapped_column(Text)


class Experiment(Record, Base):
    __tablename__ = "experiments"
    name: Mapped[str] = mapped_column(String(200))
    dataset_id: Mapped[str] = mapped_column(ForeignKey("evaluation_datasets.id"))
    configurations: Mapped[list] = mapped_column(JSON)
    results: Mapped[list] = mapped_column(JSON)


class AgentRun(Record, Base):
    __tablename__ = "agent_runs"
    task: Mapped[str] = mapped_column(Text)
    configuration: Mapped[dict] = mapped_column(JSON)
    steps: Mapped[list] = mapped_column(JSON)
    response: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSON)
    passed: Mapped[bool]


class FailureEvent(Record, Base):
    __tablename__ = "failure_events"
    event_id: Mapped[str] = mapped_column(String(200), unique=True)
    source: Mapped[str] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    error: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("evaluation_cases.id"))


class SecurityRun(Record, Base):
    __tablename__ = "security_test_runs"
    model: Mapped[str] = mapped_column(String(200))
    configuration: Mapped[dict] = mapped_column(JSON)
    results: Mapped[list] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)


class MarketingReview(Record, Base):
    __tablename__ = "marketing_reviews"
    content: Mapped[str] = mapped_column(Text)
    configuration: Mapped[dict] = mapped_column(JSON)
    results: Mapped[list] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(20), default="pending")
    reviewer: Mapped[str | None] = mapped_column(String(100))
    feedback: Mapped[str | None] = mapped_column(Text)
