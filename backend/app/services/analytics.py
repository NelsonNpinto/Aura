from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.platform import BatchRun, JudgeReview
from app.models.records import EvaluationRun, Trace


def overview(db: Session):
    total, latency, input_tokens, output_tokens = db.execute(
        select(
            func.count(Trace.id),
            func.avg(Trace.latency_ms),
            func.sum(Trace.input_tokens),
            func.sum(Trace.output_tokens),
        )
    ).one()
    runs, score = db.execute(
        select(func.count(EvaluationRun.id), func.avg(EvaluationRun.score))
    ).one()
    failures = db.scalar(select(func.count(Trace.id)).where(Trace.status == "error"))
    failed_checks = db.scalar(
        select(func.count(EvaluationRun.id)).where(EvaluationRun.passed.is_(False))
    )
    comparison = db.execute(
        select(
            Trace.model,
            func.count(Trace.id),
            func.avg(Trace.latency_ms),
        )
        .where(Trace.status == "success")
        .group_by(Trace.model)
    ).all()
    judgments = list(
        db.scalars(
            select(JudgeReview).where(JudgeReview.error.is_(None), JudgeReview.score.is_not(None))
        )
    )

    def average_dimension(dimension, ragas_name):
        values = []
        for review in judgments:
            if review.engine == "local_judge":
                value = review.verdict.get(dimension, {}).get("score")
            else:
                value = review.verdict.get("metrics", {}).get(ragas_name)
            if value is not None:
                values.append(value)
        return sum(values) / len(values) if values else None

    dataset_runs = db.scalar(select(func.count(BatchRun.id)))
    unsupported = sum(bool(r.verdict.get("unsupported_claims")) for r in judgments)
    return {
        "total_requests": total,
        "evaluation_runs": runs + dataset_runs,
        "dataset_runs": dataset_runs,
        "judge_reviews": len(judgments),
        "unsupported_claim_reviews": unsupported,
        "average_check_score": score,
        "request_errors": failures,
        "failed_evaluations": failed_checks,
        "average_latency_ms": latency,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "faithfulness": average_dimension("faithfulness", "faithfulness"),
        "answer_relevance": average_dimension("relevance", "answer_relevancy"),
        "estimated_cost": 0 if total else None,
        "model_comparison": [
            {"model": m, "requests": n, "latency_ms": t} for m, n, t in comparison
        ],
    }
