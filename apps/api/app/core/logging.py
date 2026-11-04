"""Structured JSON logging with request IDs. Every string value passes the PII redactor."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.core.context import request_id_var, trace_id_var
from app.guardrails.pii import redact_any


def _add_context(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    if rid := request_id_var.get():
        event.setdefault("request_id", rid)
    if tid := trace_id_var.get():
        event.setdefault("trace_id", tid)
    return event


def _redact(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    return {k: redact_any(v) for k, v in event.items()}


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_context,
            structlog.processors.format_exc_info,
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "aura") -> Any:
    return structlog.get_logger(name)
