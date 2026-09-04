"""FastAPI application factory. Health checks live here; domain routes come later."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse

from app.api.v1.auth_routes import router as auth_router
from app.api.v1.abdm_webhooks import router as abdm_webhooks_router
from app.api.v1.documents import router as documents_router
from app.api.v1.interview import router as interview_router
from app.api.v1.summary import router as summary_router
from app.core.config import get_settings
from app.core.database import (
    close_connections,
    hit_rate_limit,
    init_engine,
    init_redis,
    ping_postgres,
    ping_redis,
)
from app.core.exceptions import register_exception_handlers
from app.utils.logger import configure_logging, get_logger, get_request_id, set_request_id

logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(json_output=settings.is_production or not settings.DEBUG, level=settings.LOG_LEVEL)
    init_engine(settings)
    await init_redis(settings)
    logger.info("startup", env=settings.APP_ENV, app=settings.APP_NAME)
    yield
    await close_connections()
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = set_request_id(request.headers.get("x-request-id"))
        settings = get_settings()
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        if path not in {"/healthz", "/readyz"}:
            limit = (
                settings.RATE_LIMIT_AUTH_PER_MINUTE
                if path.startswith(f"{settings.API_V1_PREFIX}/auth")
                else settings.RATE_LIMIT_PUBLIC_PER_MINUTE
            )
            allowed = await hit_rate_limit(f"ip:{client_ip}", limit)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "rate_limited",
                            "message": "Too many requests",
                            "details": {},
                            "request_id": rid,
                        }
                    },
                    headers={"X-Request-ID": rid},
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.get("/healthz")
    async def healthz():
        """Liveness: process is up. Orchestrators should not kill on dependency blips."""
        return {"status": "ok", "request_id": get_request_id()}

    @app.get("/readyz")
    async def readyz():
        """Readiness: Postgres + Redis (session, locks, ratelimit DBs)."""
        await ping_postgres()
        await ping_redis()
        return {"status": "ready", "request_id": get_request_id()}

    app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
    app.include_router(interview_router, prefix=settings.API_V1_PREFIX)
    app.include_router(documents_router, prefix=settings.API_V1_PREFIX)
    app.include_router(summary_router, prefix=settings.API_V1_PREFIX)
    app.include_router(abdm_webhooks_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()
