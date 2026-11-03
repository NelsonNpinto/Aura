import asyncio
import math

from fastapi import HTTPException

from app.core.config import get_settings
from app.models.platform import JudgeReview
from app.models.records import new_id
from app.monitoring.langchain_traces import LocalModelTraceHandler
from app.monitoring.telemetry import observation


def compute(payload, engine=None, review_id=None):
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_ollama import ChatOllama
        from ragas import EvaluationDataset, evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import (
            Faithfulness,
            LLMContextPrecisionWithReference,
            LLMContextRecall,
            ResponseRelevancy,
        )
        from ragas.run_config import RunConfig
    except ImportError as exc:
        raise HTTPException(503, "RAGAS requires the rag dependency extra") from exc
    if not payload.contexts or not payload.expected:
        raise HTTPException(
            422, "RAGAS context precision/recall require contexts and a reference answer"
        )
    settings = get_settings()
    llm = LangchainLLMWrapper(
        ChatOllama(
            model=payload.model,
            base_url=settings.ollama_base_url,
            temperature=0,
            num_predict=2048,
            seed=42,
            callbacks=[LocalModelTraceHandler(engine, payload.model, review_id)]
            if engine is not None
            else None,
        )
    )
    embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name=settings.embedding_model, model_kwargs={"device": "cpu"})
    )
    dataset = EvaluationDataset.from_list(
        [
            {
                "user_input": payload.question,
                "response": payload.response,
                "retrieved_contexts": payload.contexts,
                "reference": payload.expected,
            }
        ]
    )
    result = evaluate(
        dataset,
        metrics=[
            Faithfulness(),
            ResponseRelevancy(),
            LLMContextPrecisionWithReference(),
            LLMContextRecall(),
        ],
        llm=llm,
        embeddings=embeddings,
        run_config=RunConfig(timeout=180, max_retries=1, max_workers=1),
        raise_exceptions=True,
        show_progress=False,
    )
    return {k: float(v) if math.isfinite(float(v)) else None for k, v in result.scores[0].items()}


async def ragas_score(payload, db):
    error, values = None, {}
    review_id = new_id()
    try:
        with observation("ragas_judge", payload.model):
            values = await asyncio.to_thread(compute, payload, db.get_bind(), review_id)
    except HTTPException:
        raise
    except Exception as exc:
        error = f"RAGAS scoring failed: {type(exc).__name__}: {str(exc)[:300]}"
    complete = bool(values) and all(v is not None for v in values.values())
    score = sum(values.values()) / len(values) if complete else None
    row = JudgeReview(
        id=review_id,
        question=payload.question,
        expected=payload.expected,
        response=payload.response,
        contexts=payload.contexts,
        configuration=payload.model_dump(exclude={"question", "expected", "response", "contexts"}),
        verdict={"metrics": values, "method": "RAGAS local LLM estimates"},
        score=score,
        passed=(score >= payload.threshold) if score is not None else None,
        engine="ragas",
        error=error,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
