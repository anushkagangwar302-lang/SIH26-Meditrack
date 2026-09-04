"""Structured API errors. Tracebacks never leave the process; PII never in bodies."""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.logger import get_request_id, get_logger

logger = get_logger("app.exceptions")

# Redact common Indian PII patterns if they ever appear in exception strings.
_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_ABHA = re.compile(r"\b\d{2}-\d{4}-\d{4}-\d{4}\b")
_MOBILE = re.compile(r"\b[6-9]\d{9}\b")


def sanitize_public_text(text: str) -> str:
    text = _AADHAAR.sub("[redacted]", text)
    text = _ABHA.sub("[redacted]", text)
    text = _MOBILE.sub("[redacted]", text)
    return text


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = sanitize_public_text(message)
        self.status_code = status_code
        self.details = details or {}


class UnauthorizedError(AppError):
    def __init__(self, *, code: str = "unauthorized", message: str = "Not authenticated") -> None:
        super().__init__(code=code, message=message, status_code=401)


class ForbiddenError(AppError):
    def __init__(self, *, code: str = "forbidden", message: str = "Not allowed") -> None:
        super().__init__(code=code, message=message, status_code=403)


class NotFoundError(AppError):
    def __init__(self, *, code: str = "not_found", message: str = "Not found") -> None:
        super().__init__(code=code, message=message, status_code=404)


class ConflictError(AppError):
    def __init__(self, *, code: str = "conflict", message: str = "Conflict") -> None:
        super().__init__(code=code, message=message, status_code=409)


class RateLimitedError(AppError):
    def __init__(self, *, code: str = "rate_limited", message: str = "Too many requests") -> None:
        super().__init__(code=code, message=message, status_code=429)


class ServiceUnavailableError(AppError):
    def __init__(self, *, code: str = "unavailable", message: str = "Service unavailable") -> None:
        super().__init__(code=code, message=message, status_code=503)


def _body(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": sanitize_public_text(message),
            "details": details or {},
            "request_id": get_request_id(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        logger.warning("app_error", code=exc.code, status=exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.status_code, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic errors can echo request bodies; drop input values.
        safe_errors = []
        for err in exc.errors():
            safe_errors.append(
                {"loc": err.get("loc"), "type": err.get("type"), "msg": err.get("msg")}
            )
        logger.info("validation_error")
        return JSONResponse(
            status_code=422,
            content=_body(422, "validation_error", "Invalid request", {"errors": safe_errors}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.status_code, "http_error", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
        # Log type only — str(exc) may contain upstream PII.
        logger.exception("unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=_body(500, "internal_error", "An unexpected error occurred"),
        )
