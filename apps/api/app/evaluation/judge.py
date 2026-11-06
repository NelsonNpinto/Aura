"""Shared judge input and decision policy for the workbench and regression suite."""

from pydantic import BaseModel, Field

from app.guardrails.pii import redact
from app.schemas.llm_outputs import JudgeOut


class JudgeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)
    context: str = Field(default="", max_length=12000)
    reference: str = Field(default="", max_length=4000)

    def variables(self) -> dict[str, str]:
        return {key: redact(value) for key, value in self.model_dump().items()}


def score_judgment(body: JudgeRequest, verdict: JudgeOut) -> tuple[float | None, bool | None]:
    if not (body.context or body.reference):
        return None, None
    scores = [verdict.correctness, verdict.relevance]
    if body.context and verdict.faithfulness is not None:
        scores.append(verdict.faithfulness)
    scores.extend([verdict.completeness, verdict.clarity])
    score = sum(item.score for item in scores) / len(scores)
    return score, score >= 0.8 and not verdict.unsupported_claims
