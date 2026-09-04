"""Async SQLAlchemy engine, Redis clients, distributed locks, idempotency.

Concurrency choices (apply at every racing write in later phases):
- Unique + ON CONFLICT: ABHA ID linking, idempotent webhook receipts
- SELECT ... FOR UPDATE: consent updates, triage queue position
- Redis lock (SET NX EX + token Lua unlock): OCR job status across replicas

Redis topology (single instance in docker-compose):
- DB 0 session/interview TTL state + WS channel names
- DB 1 Celery broker
- DB 2 Celery results
- DB 3 distributed locks
- DB 4 rate limits + idempotency keys
Prefixes are always applied so we can collapse to DB 0 on Redis Cluster.
Pub/Sub channels are server-global (not DB-scoped) — WS fan-out uses
channel names under REDIS_PREFIX_WS, never in-process dicts.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import DateTime, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, ServiceUnavailableError

# Compare-and-delete so we never unlock another holder's key.
_UNLOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class Base(DeclarativeBase):
    """Declarative base. Tables are created only via Alembic (no create_all)."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# Engine/sessionmaker are constructed in init_engine() during lifespan.
# Holding them on this module is process-local connection infrastructure,
# not request/user state. They are not mutated after startup.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_redis_session: Redis | None = None
_redis_locks: Redis | None = None
_redis_ratelimit: Redis | None = None


def init_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine, _session_factory
    settings = settings or get_settings()
    url = settings.DATABASE_URL.get_secret_value()
    _engine = create_async_engine(
        url,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        pool_pre_ping=True,
        echo=False,
    )
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialised — call init_engine() in lifespan")
    return _engine


def _new_redis(settings: Settings, db: int) -> Redis:
    password = None
    if settings.REDIS_PASSWORD:
        secret = settings.REDIS_PASSWORD.get_secret_value()
        password = secret or None
    return Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=db,
        password=password,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


async def init_redis(settings: Settings | None = None) -> None:
    global _redis_session, _redis_locks, _redis_ratelimit
    settings = settings or get_settings()
    _redis_session = _new_redis(settings, settings.REDIS_DB_SESSION)
    _redis_locks = _new_redis(settings, settings.REDIS_DB_LOCKS)
    _redis_ratelimit = _new_redis(settings, settings.REDIS_DB_RATELIMIT)


def redis_session() -> Redis:
    if _redis_session is None:
        raise RuntimeError("Redis session client not initialised")
    return _redis_session


def redis_locks() -> Redis:
    if _redis_locks is None:
        raise RuntimeError("Redis lock client not initialised")
    return _redis_locks


def redis_ratelimit() -> Redis:
    if _redis_ratelimit is None:
        raise RuntimeError("Redis ratelimit client not initialised")
    return _redis_ratelimit


async def close_connections() -> None:
    global _engine, _session_factory, _redis_session, _redis_locks, _redis_ratelimit
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    for client in (_redis_session, _redis_locks, _redis_ratelimit):
        if client is not None:
            await client.aclose()
    _redis_session = None
    _redis_locks = None
    _redis_ratelimit = None


async def get_db() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Session factory not initialised")
    async with _session_factory() as session:
        yield session


@asynccontextmanager
async def redis_lock(resource: str, ttl_seconds: int | None = None) -> AsyncIterator[str]:
    """Single-instance Redis lock (SET NX EX + token).

    This is not full multi-Redis Redlock. For one Redis (our compose default)
    this is the correct primitive. Multi-region Redlock would need ≥3 independent
    Redis masters — set that only if you split lock nodes across AZs.
    """
    settings = get_settings()
    ttl = ttl_seconds or settings.LOCK_TTL_SECONDS
    token = uuid.uuid4().hex
    key = f"{settings.REDIS_PREFIX_LOCK}{resource}"
    acquired = await redis_locks().set(key, token, nx=True, ex=ttl)
    if not acquired:
        raise ConflictError(
            code="resource_locked",
            message="Another replica is updating this resource; retry",
        )
    try:
        yield token
    finally:
        await redis_locks().eval(_UNLOCK_LUA, 1, key, token)


async def claim_idempotency_key(key: str, ttl_seconds: int | None = None) -> bool:
    """First caller wins. Returns False if this POST was already accepted.

    Use on document upload, summary confirm, ABDM webhook receipt.
    """
    settings = get_settings()
    ttl = ttl_seconds or settings.IDEMPOTENCY_TTL_SECONDS
    redis_key = f"{settings.REDIS_PREFIX_IDEMPOTENCY}{key}"
    created = await redis_ratelimit().set(redis_key, "1", nx=True, ex=ttl)
    return bool(created)


async def hit_rate_limit(bucket: str, limit_per_minute: int) -> bool:
    """Sliding-window-ish fixed window per UTC minute. Returns True if allowed."""
    settings = get_settings()
    redis_key = f"{settings.REDIS_PREFIX_RATELIMIT}{bucket}"
    client = redis_ratelimit()
    count = int(await client.incr(redis_key))
    if count == 1:
        await client.expire(redis_key, 60)
    return count <= limit_per_minute


async def ping_postgres() -> None:
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise ServiceUnavailableError(code="db_unavailable", message="Postgres not ready") from exc


async def ping_redis() -> None:
    try:
        if await redis_session().ping() is not True:
            raise ServiceUnavailableError(code="redis_unavailable", message="Redis not ready")
        if await redis_locks().ping() is not True:
            raise ServiceUnavailableError(code="redis_unavailable", message="Redis locks not ready")
        if await redis_ratelimit().ping() is not True:
            raise ServiceUnavailableError(code="redis_unavailable", message="Redis ratelimit not ready")
    except ServiceUnavailableError:
        raise
    except Exception as exc:
        raise ServiceUnavailableError(code="redis_unavailable", message="Redis not ready") from exc


async def lock_row_for_update(session: AsyncSession, stmt: Any) -> Any:
    """Apply SELECT ... FOR UPDATE. Caller must already be in a transaction."""
    result = await session.execute(stmt.with_for_update())
    return result.scalars().first()
