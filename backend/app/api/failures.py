import hmac

from fastapi import APIRouter, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.common import DB, recent, require, serialize
from app.core.config import get_settings
from app.models.platform import Case, Dataset, FailureEvent
from app.schemas.platform import ApproveFailure, FailureInput

router = APIRouter(prefix="/api/v1")


@router.post("/webhooks/ai-failure", status_code=201)
def ingest_failure(
    payload: FailureInput, db: DB, response: Response, authorization: str = Header(default="")
):
    secret = get_settings().webhook_secret
    if not secret:
        raise HTTPException(503, "Configure WEBHOOK_SECRET before enabling ingestion")
    if not hmac.compare_digest(authorization, f"Bearer {secret}"):
        raise HTTPException(401, "Invalid webhook authentication")

    def check_duplicate(existing):
        if (
            any(
                getattr(existing, k) != v
                for k, v in payload.model_dump(exclude={"metadata"}).items()
            )
            or existing.metadata_json != payload.metadata
        ):
            raise HTTPException(409, "Event ID was already used with different content")
        response.status_code = 200
        return {**serialize(existing), "duplicate": True}

    existing = db.scalar(select(FailureEvent).where(FailureEvent.event_id == payload.event_id))
    if existing:
        return check_duplicate(existing)
    row = FailureEvent(
        **payload.model_dump(exclude={"metadata"}), metadata_json=payload.metadata, status="pending"
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return check_duplicate(
            db.scalar(select(FailureEvent).where(FailureEvent.event_id == payload.event_id))
        )
    db.refresh(row)
    return {**serialize(row), "duplicate": False}


@router.get("/failures")
def failures(db: DB):
    return recent(db, FailureEvent)


@router.post("/failures/{failure_id}/approve")
def approve(failure_id: str, payload: ApproveFailure, db: DB):
    require(db, Dataset, payload.dataset_id)
    row = db.scalar(select(FailureEvent).where(FailureEvent.id == failure_id).with_for_update())
    if not row:
        raise HTTPException(404, "Failure not found")
    if row.case_id:
        return {"failure_id": row.id, "case_id": row.case_id, "duplicate": True}
    case = Case(
        dataset_id=payload.dataset_id,
        question=row.question,
        response=row.response,
        expected=payload.expected,
        contexts=[],
        checks=[c.model_dump() for c in payload.checks],
    )
    db.add(case)
    db.flush()
    row.case_id, row.status = case.id, "approved"
    db.commit()
    return {"failure_id": row.id, "case_id": case.id, "duplicate": False}
