import logging
from contextlib import contextmanager

from opentelemetry import trace

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_langfuse = None


def configure():
    global _langfuse
    _langfuse = None
    settings = get_settings()
    if settings.otel_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": "aura-api"}))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
        )
        trace.set_tracer_provider(provider)
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
        )


@contextmanager
def observation(name, model=""):
    with trace.get_tracer("aura").start_as_current_span(name) as span:
        span.set_attribute("gen_ai.request.model", model)
        # No prompts/content are exported by default; local traces retain the full input.
        if _langfuse:
            with _langfuse.start_as_current_observation(
                name=name, as_type="span", metadata={"model": model}
            ):
                yield span
        else:
            yield span
