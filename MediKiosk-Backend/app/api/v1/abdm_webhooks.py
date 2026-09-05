"""ABDM webhook endpoints with signature verification and idempotency.

Handles incoming webhooks from ABDM HIE-CM for data synchronization and
acknowledgment. All webhooks are verified via HMAC-SHA256 signature.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import (
    claim_idempotency_key,
    get_db,
    idempotency_get,
    idempotency_store,
)
from app.core.exceptions import ForbiddenError
from app.core.security import PIILogGuard, encrypt_pii
from app.models.documents import AbdmWebhookEvent
from app.schemas.fhir import AbdmWebhookAck
from app.services.fhir_service import FhirService, get_fhir_service
from app.utils.logger import get_logger

logger = get_logger("app.api.abdm_webhooks")
router = APIRouter(prefix="/abdm", tags=["abdm"])


@router.post("/webhook", response_model=AbdmWebhookAck)
async def receive_abdm_webhook(
    request: Request,
    x_hmac_sha256: Annotated[str, Header(alias="X-HMAC-SHA256")],
    x_timestamp: Annotated[str, Header(alias="X-TIMESTAMP")],
    session: Annotated[AsyncSession, Depends(get_db)],
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> AbdmWebhookAck:
    """Receive and process ABDM HIE-CM webhook.

    Args:
        request: FastAPI request with webhook payload
        x_hmac_sha256: HMAC-SHA256 signature for verification
        x_timestamp: Timestamp for replay attack prevention
        x_request_id: Optional request ID for idempotency

    Returns:
        Acknowledgment response

    Note:
        - Signature is verified using ABDM_WEBHOOK_SECRET
        - Payload is encrypted at rest (contains PII)
        - Idempotent via unique request ID
        - Duplicate webhooks are acknowledged but not reprocessed
    """
    fhir_service = get_fhir_service()
    settings = get_settings()

    # Read raw payload
    payload_bytes = await request.body()
    payload = await request.json()

    # Extract or generate request ID for idempotency
    request_id = x_request_id or payload.get("requestId") or payload.get("transactionId") or str(uuid.uuid4())

    # Check for duplicate webhook
    cached = await idempotency_get(f"abdm_webhook:{request_id}")
    if cached:
        # Return cached acknowledgment
        ack = AbdmWebhookAck.model_validate_json(cached)
        ack.duplicate = True
        return ack

    # Claim idempotency key
    claimed = await claim_idempotency_key(f"abdm_webhook:{request_id}")
    if not claimed:
        # Another replica is processing this webhook
        return AbdmWebhookAck(
            inbound_event_id=request_id,
            accepted=False,
            duplicate=True,
        )

    # Verify signature
    signature_ok = await fhir_service.verify_abdm_webhook_signature(
        payload_bytes,
        x_hmac_sha256,
        x_timestamp,
    )

    if not signature_ok:
        logger.warning("abdm_webhook_signature_invalid", request_id=request_id)
        await idempotency_store(
            f"abdm_webhook:{request_id}",
            AbdmWebhookAck(
                inbound_event_id=request_id,
                accepted=False,
                duplicate=False,
            ).model_dump_json(),
        )
        raise ForbiddenError(code="invalid_signature", message="Webhook signature verification failed")

    # Process webhook
    try:
        response = await fhir_service.process_abdm_webhook(
            session,
            payload,
            x_hmac_sha256,
            x_timestamp,
        )

        # Persist webhook event record
        webhook_event = AbdmWebhookEvent(
            inbound_event_id=request_id,
            event_type=payload.get("eventType", "unknown"),
            signature_ok=signature_ok,
            processed_at=None,  # Will be set after processing
            payload_enc=encrypt_pii(payload_bytes.decode("utf-8")),
        )
        session.add(webhook_event)
        await session.flush()

        # Mark as processed
        webhook_event.processed_at = response.get("timestamp")
        await session.flush()

        # Create acknowledgment
        ack = AbdmWebhookAck(
            inbound_event_id=request_id,
            accepted=True,
            duplicate=False,
        )

        # Cache acknowledgment
        await idempotency_store(f"abdm_webhook:{request_id}", ack.model_dump_json())

        logger.info(
            "abdm_webhook_processed",
            request_id=request_id,
            event_type=payload.get("eventType"),
            accepted=True,
        )

        return ack

    except Exception as exc:
        logger.exception("abdm_webhook_processing_error", request_id=request_id)

        # Still acknowledge to prevent ABDM retries, but mark as not accepted
        ack = AbdmWebhookAck(
            inbound_event_id=request_id,
            accepted=False,
            duplicate=False,
        )

        await idempotency_store(f"abdm_webhook:{request_id}", ack.model_dump_json())

        return ack


@router.get("/webhook/status/{event_id}")
async def get_webhook_status(
    event_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Get the processing status of an ABDM webhook event.

    Args:
        event_id: Webhook event ID (inbound_event_id)

    Returns:
        Webhook event status

    Note:
        - Requires appropriate authorization (would add auth dependency in production)
        - Returns processing status and timestamp
    """
    from sqlalchemy import select

    stmt = select(AbdmWebhookEvent).where(AbdmWebhookEvent.inbound_event_id == event_id)
    event = (await session.execute(stmt)).scalars().first()

    if not event:
        return {
            "event_id": event_id,
            "found": False,
            "status": "not_found",
        }

    return {
        "event_id": event_id,
        "found": True,
        "status": "processed" if event.processed_at else "pending",
        "event_type": event.event_type,
        "signature_ok": event.signature_ok,
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
        "created_at": event.created_at.isoformat(),
    }


@router.post("/webhook/test")
async def test_webhook_endpoint(
    request: Request,
) -> dict[str, str]:
    """Test endpoint for ABDM webhook connectivity.

    Does not require signature verification. Used for health checks and
    initial ABDM integration testing.

    Args:
        request: FastAPI request

    Returns:
        Test acknowledgment

    Note:
        - This endpoint should be disabled or secured in production
        - Currently enabled for development/testing purposes
    """
    from datetime import datetime, timezone

    payload = await request.json()

    logger.info(
        "abdm_webhook_test",
        payload_keys=list(payload.keys()) if isinstance(payload, dict) else "non_dict",
    )

    return {
        "status": "received",
        "message": "Test webhook received successfully",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health")
async def abdm_health_check() -> dict[str, str]:
    """Health check endpoint for ABDM integration.

    Returns the current status of ABDM configuration and connectivity.
    """
    settings = get_settings()

    status = {
        "status": "healthy",
        "abdm_configured": bool(settings.ABDM_CLIENT_ID and settings.ABDM_CLIENT_SECRET),
        "webhook_secret_configured": bool(settings.ABDM_WEBHOOK_SECRET),
        "environment": settings.APP_ENV,
    }

    if not status["abdm_configured"]:
        status["status"] = "degraded"
        status["message"] = "ABDM credentials not configured"

    if not status["webhook_secret_configured"]:
        status["status"] = "degraded"
        status["message"] = "ABDM webhook secret not configured"

    return status
