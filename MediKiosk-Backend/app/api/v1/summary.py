"""Summary endpoints for clinical summary generation and retrieval.

Provides physician-readable summaries from completed interview sessions.
Supports multiple output formats (text, structured JSON, FHIR). All PII
operations require consent verification.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth_routes import Principal, require_intake_session
from app.core.database import get_db
from app.core.exceptions import ForbiddenError, NotFoundError
from app.services.summary_engine import (
    ClinicalSummary,
    SummaryEngine,
    SummaryFormat,
    SummaryRequest,
    get_summary_engine,
)
from app.utils.logger import get_logger

logger = get_logger("app.api.summary")
router = APIRouter(prefix="/summary", tags=["summary"])


@router.post("/generate")
async def generate_summary(
    session_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
    format: str = Query("text", description="Output format"),
    include_ayush: bool = Query(True, description="Include AYUSH data"),
    language: str = Query("en", description="Summary language"),
) -> dict[str, str] | dict[str, object]:
    """Generate a clinical summary for a completed interview session.

    Args:
        session_id: Interview session UUID
        format: Output format (text, structured, fhir)
        include_ayush: Whether to include AYUSH assessment data
        language: Summary language (en, hi, etc.)

    Returns:
        Formatted clinical summary (text or structured JSON)

    Note:
        - Requires treatment consent (enforced by require_intake_session)
        - PII is decrypted only after consent verification
        - Text format is physician-readable, structured is machine-readable
    """
    summary_engine = get_summary_engine()

    # Convert string format to enum
    try:
        format_enum = SummaryFormat(format)
    except ValueError:
        format_enum = SummaryFormat.text

    request = SummaryRequest(
        session_id=session_id,
        format=format_enum,
        include_ayush=include_ayush,
        language=language,
    )

    try:
        result = await summary_engine.generate_and_format(
            session,
            request,
            check_consent=True,
        )

        logger.info(
            "summary_generated",
            session_id=str(session_id),
            format=format_enum.value,
            patient_id=str(principal.patient.id) if principal.patient else None,
        )

        if format_enum == SummaryFormat.text:
            return {"summary": result}
        else:
            return result

    except NotFoundError:
        raise NotFoundError(code="session_not_found", message="Interview session not found")
    except Exception as exc:
        logger.exception("summary_generation_error", session_id=str(session_id))
        raise


@router.get("/patient/{patient_id}")
async def get_patient_summaries(
    patient_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(10, ge=1, le=50, description="Maximum number of summaries"),
) -> list[dict[str, object]]:
    """Get historical clinical summaries for a patient.

    Returns structured summaries for the patient's completed interview sessions.
    Requires appropriate consent for PII access.

    Args:
        patient_id: Patient UUID
        limit: Maximum number of historical summaries to return

    Returns:
        List of structured clinical summaries
    """
    summary_engine = get_summary_engine()

    # Verify patient access
    if principal.role.value == "patient":
        if not principal.patient or principal.patient.id != patient_id:
            raise ForbiddenError(code="access_denied", message="Not authorized to access these summaries")
    # Staff can access patient summaries (would need role-based filtering in production)

    try:
        summaries = await summary_engine.get_patient_history(
            session,
            patient_id,
            limit=limit,
        )

        # Convert to structured format
        result = []
        for summary in summaries:
            result.append(summary_engine.format_as_structured(summary))

        logger.info(
            "patient_summaries_retrieved",
            patient_id=str(patient_id),
            count=len(result),
            limit=limit,
        )

        return result

    except Exception as exc:
        logger.exception("patient_summaries_error", patient_id=str(patient_id))
        raise


@router.get("/session/{session_id}")
async def get_session_summary(
    session_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    format: str = Query("structured", description="Output format"),
) -> dict[str, str] | dict[str, object]:
    """Get a clinical summary for a specific interview session.

    Similar to POST /generate but uses GET for idempotent retrieval.
    """
    summary_engine = get_summary_engine()

    # Convert string format to enum
    try:
        format_enum = SummaryFormat(format)
    except ValueError:
        format_enum = SummaryFormat.structured

    request = SummaryRequest(
        session_id=session_id,
        format=format_enum,
        include_ayush=True,
        language="en",
    )

    try:
        result = await summary_engine.generate_and_format(
            db_session,
            request,
            check_consent=True,
        )

        logger.info(
            "session_summary_retrieved",
            session_id=str(session_id),
            format=format_enum.value,
        )

        if format_enum == SummaryFormat.text:
            return {"summary": result}
        else:
            return result

    except NotFoundError:
        raise NotFoundError(code="session_not_found", message="Interview session not found")
    except Exception as exc:
        logger.exception("session_summary_error", session_id=str(session_id))
        raise


@router.post("/fhir/{session_id}")
async def generate_fhir_summary(
    session_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Generate a FHIR R4 bundle from a completed interview session.

    Converts clinical data to FHIR R4 format for ABDM integration or
    external system exchange.

    Args:
        session_id: Interview session UUID

    Returns:
        FHIR R4 bundle as structured JSON

    Note:
        - Requires ABDM health records consent (enforced by require_intake_session)
        - FHIR bundle is encrypted at rest in the database
        - This endpoint generates the bundle; actual ABDM push is separate
    """
    from app.services.fhir_service import FhirService, get_fhir_service

    fhir_service = get_fhir_service()

    try:
        # Load interview session to get patient_id
        from app.models.clinical import InterviewSession
        from sqlalchemy import select

        stmt = select(InterviewSession).where(InterviewSession.id == session_id)
        interview = (await db_session.execute(stmt)).scalars().first()

        if not interview:
            raise NotFoundError(code="session_not_found", message="Interview session not found")

        # Generate FHIR bundle
        conversion_result = await fhir_service.generate_fhir_bundle(
            db_session,
            interview.patient_id,
            session_id,
            bundle_type="document",
            direction="outbound",
        )

        # Persist FHIR bundle
        fhir_record = await fhir_service.persist_fhir_bundle(
            db_session,
            interview.patient_id,
            conversion_result.bundle,
            conversion_result.bundle_type,
            direction="outbound",
            session_id=session_id,
        )

        logger.info(
            "fhir_summary_generated",
            session_id=str(session_id),
            fhir_id=str(fhir_record.id),
            patient_id=str(interview.patient_id),
        )

        return {
            "fhir_id": str(fhir_record.id),
            "bundle": conversion_result.bundle,
            "bundle_type": conversion_result.bundle_type,
            "resource_count": conversion_result.resource_count,
        }

    except NotFoundError:
        raise
    except Exception as exc:
        logger.exception("fhir_summary_error", session_id=str(session_id))
        raise


@router.post("/push-abdm/{session_id}")
async def push_to_abdm(
    session_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    hip_id: str | None = Query(None, description="Health Information Provider ID"),
) -> dict[str, str | bool]:
    """Generate FHIR bundle and push to ABDM HIE-CM.

    Combines FHIR generation and ABDM push in a single operation.

    Args:
        session_id: Interview session UUID
        hip_id: Optional HIP ID (defaults to config)

    Returns:
        Push result with success status and ABDM request ID

    Note:
        - Requires ABDM health records consent
        - ABDM credentials must be configured
        - Idempotent via ABDM request ID
    """
    from app.services.fhir_service import FhirService, get_fhir_service

    fhir_service = get_fhir_service()

    try:
        # Load interview session
        from app.models.clinical import InterviewSession
        from sqlalchemy import select

        stmt = select(InterviewSession).where(InterviewSession.id == session_id)
        interview = (await db_session.execute(stmt)).scalars().first()

        if not interview:
            raise NotFoundError(code="session_not_found", message="Interview session not found")

        # Generate and push
        fhir_record, push_result = await fhir_service.generate_and_push_bundle(
            db_session,
            interview.patient_id,
            session_id,
            hip_id,
        )

        logger.info(
            "abdm_push_completed",
            session_id=str(session_id),
            fhir_id=str(fhir_record.id),
            success=push_result.success,
            abdm_request_id=push_result.abdm_request_id,
        )

        return {
            "success": push_result.success,
            "fhir_id": str(fhir_record.id),
            "abdm_request_id": push_result.abdm_request_id,
            "error_message": push_result.error_message,
            "status_code": push_result.status_code,
        }

    except NotFoundError:
        raise
    except Exception as exc:
        logger.exception("abdm_push_error", session_id=str(session_id))
        raise
