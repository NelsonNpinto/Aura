from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents.runner import run_agent
from app.api.common import DB, recent, require, save, serialize
from app.evaluation.judge import judge, reliability
from app.models.platform import AgentRun, HumanReview, JudgeReview, MarketingReview, SecurityRun
from app.schemas.platform import (
    AgentInput,
    ApprovalInput,
    HumanInput,
    JudgeInput,
    MarketingInput,
    SecurityInput,
)
from app.security.packs import SECURITY_CASES, marketing, run_security

router = APIRouter(prefix="/api/v1")


@router.post("/judge/reviews", status_code=201)
async def create_judge(payload: JudgeInput, db: DB):
    return serialize(await judge(payload, db))


@router.get("/judge/reviews")
def judge_reviews(db: DB):
    return recent(db, JudgeReview)


@router.get("/human-reviews")
def human_reviews(db: DB):
    return recent(db, HumanReview)


@router.put("/judge/reviews/{review_id}/human")
def human(review_id: str, payload: HumanInput, db: DB):
    review = require(db, JudgeReview, review_id)
    if review.error or review.passed is None:
        raise HTTPException(422, "Cannot pair a human rating with an invalid judge result")
    row = db.scalar(select(HumanReview).where(HumanReview.judge_review_id == review_id))
    if row is None:
        row = HumanReview(judge_review_id=review_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    try:
        return save(db, row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent review; refresh and retry") from exc


@router.get("/judge/reliability")
def calibration(db: DB):
    return reliability(db)


@router.get("/agents/runs")
def agent_runs(db: DB):
    return recent(db, AgentRun)


@router.post("/agents/runs", status_code=201)
async def agent_run(payload: AgentInput, db: DB):
    return serialize(await run_agent(payload, db))


@router.get("/security/cases")
def security_cases():
    return SECURITY_CASES


@router.get("/security/runs")
def security_runs(db: DB):
    return recent(db, SecurityRun)


@router.post("/security/runs", status_code=201)
async def security_run(payload: SecurityInput, db: DB):
    return serialize(await run_security(payload, db))


@router.get("/marketing/reviews")
def marketing_reviews(db: DB):
    return recent(db, MarketingReview)


@router.post("/marketing/reviews", status_code=201)
def marketing_review(payload: MarketingInput, db: DB):
    return serialize(marketing(payload, db))


@router.put("/marketing/reviews/{review_id}/decision")
def marketing_decision(review_id: str, payload: ApprovalInput, db: DB):
    row = require(db, MarketingReview, review_id)
    if payload.decision == "approved" and row.score < 1:
        raise HTTPException(422, "Resolve failed policy checks before approving content")
    row.decision, row.reviewer, row.feedback = payload.decision, payload.reviewer, payload.feedback
    return save(db, row)
