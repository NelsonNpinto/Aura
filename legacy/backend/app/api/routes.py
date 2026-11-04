from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.evaluation.deterministic import evaluate
from app.models.records import EvaluationRun, Trace
from app.schemas.requests import EvaluationRequest, GenerateRequest
from app.services import ollama
from app.services.analytics import overview

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_db)]


def serialize(record):
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}


@router.get("/health")
def health(db: DB):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, "Database unavailable") from exc
    return {"status": "ok", "database": "connected", "database_engine": db.get_bind().dialect.name}


@router.get("/models")
async def models():
    return await ollama.list_models()


@router.get("/overview")
def get_overview(db: DB):
    return overview(db)


@router.post("/playground/generate", status_code=201)
async def generate(payload: GenerateRequest, db: DB):
    from app.services.generation import generate_record

    record = await generate_record(payload, db)
    if record.status == "error":
        raise HTTPException(502, {"message": record.error, "trace_id": record.id})
    return serialize(record)


@router.get("/traces")
def traces(db: DB):
    return [
        serialize(t) for t in db.scalars(select(Trace).order_by(Trace.created_at.desc()).limit(100))
    ]


@router.get("/traces/{trace_id}")
def trace(trace_id: str, db: DB):
    record = db.get(Trace, trace_id)
    if not record:
        raise HTTPException(404, "Trace not found")
    return serialize(record)


@router.post("/evaluations", status_code=201)
def create_evaluation(payload: EvaluationRequest, db: DB):
    if payload.trace_id:
        source = db.get(Trace, payload.trace_id)
        if not source:
            raise HTTPException(404, "Trace not found")
        if source.response != payload.response:
            raise HTTPException(422, "Evaluation response must match its linked trace")
    results = evaluate(payload.response, payload.checks)
    score = sum(r["passed"] for r in results) / len(results)
    run = EvaluationRun(
        name=payload.name,
        response=payload.response,
        trace_id=payload.trace_id,
        configuration=payload.model_dump(exclude={"response", "name", "trace_id"}),
        results=results,
        score=score,
        passed=score >= payload.threshold,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return serialize(run)


@router.get("/evaluations")
def evaluations(db: DB):
    return [
        serialize(r)
        for r in db.scalars(
            select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(100)
        )
    ]
