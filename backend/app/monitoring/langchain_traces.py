"""Persist local LangChain model calls, including calls made inside RAGAS."""

import logging
import time

from langchain_core.callbacks import BaseCallbackHandler
from sqlalchemy.orm import Session

from app.models.records import Trace

logger = logging.getLogger(__name__)


class LocalModelTraceHandler(BaseCallbackHandler):
    def __init__(self, engine, model, review_id):
        self.engine, self.model, self.review_id = engine, model, review_id
        self.pending = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        prompt = "\n".join(f"{m.type}: {m.content}" for batch in messages for m in batch)
        self.pending[str(run_id)] = (time.perf_counter(), prompt)

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self.pending[str(run_id)] = (time.perf_counter(), "\n".join(prompts))

    def finish(self, run_id, response=None, error=None):
        start, prompt = self.pending.pop(str(run_id), (time.perf_counter(), "(input unavailable)"))
        text, input_tokens, output_tokens = None, None, None
        if response and response.generations and response.generations[0]:
            generation = response.generations[0][0]
            text = generation.text
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None) or {}
            metadata = getattr(message, "response_metadata", None) or {}
            input_tokens = usage.get("input_tokens", metadata.get("prompt_eval_count"))
            output_tokens = usage.get("output_tokens", metadata.get("eval_count"))
        try:
            with Session(self.engine) as session:
                session.add(
                    Trace(
                        model=self.model,
                        prompt=prompt,
                        system="",
                        response=text,
                        configuration={
                            "operation": "ragas_metric",
                            "judge_review_id": self.review_id,
                        },
                        status="error" if error else "success",
                        error=str(error)[:2000] if error else None,
                        latency_ms=(time.perf_counter() - start) * 1000,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                )
                session.commit()
        except Exception:
            logger.exception("Could not persist a RAGAS model trace")

    def on_llm_end(self, response, *, run_id, **kwargs):
        self.finish(run_id, response=response)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self.finish(run_id, error=error)
