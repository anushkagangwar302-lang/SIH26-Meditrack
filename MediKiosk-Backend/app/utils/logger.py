"""Structured JSON logging with request IDs.

Two streams:
- logger name `app` — operational logs (stdout)
- logger name `audit` — consent/access events (stdout with stream=audit)

Processors redact keys that look like PII. Never log encrypt_pii inputs.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from contextvars import ContextVar

import structlog

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE_KEY = re.compile(
    r"(aadhaar|abha|pan|password|secret|token|authorization|otp|mobile|phone|email|name)",
    re.IGNORECASE,
)


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str | None = None) -> str:
    rid = value or uuid.uuid4().hex
    _request_id.set(rid)
    return rid


def _drop_pii(_: object, __: str, event_dict: dict) -> dict:
    redacted = {}
    for key, value in event_dict.items():
        if _SENSITIVE_KEY.search(str(key)):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = value
    return redacted


def _add_request_id(_: object, __: str, event_dict: dict) -> dict:
    event_dict["request_id"] = get_request_id()
    return event_dict


def configure_logging(json_output: bool = True, level: str = "INFO") -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        _drop_pii,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def get_audit_logger() -> structlog.stdlib.BoundLogger:
    """Compliance stream. Callers must pass subject ids, never raw Aadhaar/ABHA."""
    return structlog.get_logger("audit").bind(stream="audit")
