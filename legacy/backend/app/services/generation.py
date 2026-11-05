import time

from app.models.records import Trace
from app.monitoring.telemetry import observation
from app.services import ollama


async def generate_record(payload, db, operation="generation", metadata=None):
    record = Trace(
        model=payload.model,
        prompt=payload.prompt,
        system=payload.system,
        configuration={
            **payload.model_dump(exclude={"prompt", "system"}),
            "operation": operation,
            **(metadata or {}),
        },
        status="success",
        latency_ms=0,
    )
    started = time.perf_counter()
    with observation(operation, payload.model) as span:
        try:
            data = await ollama.generate(payload)
            record.response = data["response"]
            record.input_tokens = data.get("prompt_eval_count")
            record.output_tokens = data.get("eval_count")
            span.set_attribute("aura.success", True)
        except ollama.OllamaUnavailable as exc:
            record.status, record.error = "error", str(exc)
            span.set_attribute("aura.success", False)
        record.latency_ms = round((time.perf_counter() - started) * 1000, 2)
        db.add(record)
        db.commit()
        db.refresh(record)
        span.set_attribute("aura.request_id", record.id)
        span.set_attribute("aura.latency_ms", record.latency_ms)
        if record.input_tokens is not None:
            span.set_attribute("gen_ai.usage.input_tokens", record.input_tokens)
        if record.output_tokens is not None:
            span.set_attribute("gen_ai.usage.output_tokens", record.output_tokens)
    return record
