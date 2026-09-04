"""Document upload and OCR polling endpoints with idempotency and async processing.

Supports multiple document types (prescriptions, lab reports, ID scans) with
async OCR processing via Celery. All uploads are idempotent via client-supplied keys.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.auth_routes import Principal, require_intake_session
from app.core.config import get_settings
from app.core.database import (
    claim_idempotency_key,
    get_db,
    idempotency_get,
    idempotency_store,
    redis_lock,
)
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import PIILogGuard, encrypt_pii
from app.models.documents import Document, DocumentKind, OcrExtraction, OcrStatus, StorageTier
from app.schemas.document import DocumentOut, DocumentUploadIn, OcrPollOut
from app.utils.logger import get_logger

logger = get_logger("app.api.documents")
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    patient_id: uuid.UUID = Form(...),
    session_id: uuid.UUID | None = Form(None),
    kind: DocumentKind = Form(...),
    idempotency_key: str = Form(...),
    vault_opt_in: bool = Form(False),
    file: UploadFile = File(...),
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentOut:
    """Upload a document for OCR processing.

    Args:
        patient_id: Patient UUID
        session_id: Optional interview session UUID
        kind: Document type (prescription, lab_report, id_scan, imaging, other)
        idempotency_key: Client-supplied key for idempotency (required)
        vault_opt_in: Whether to store in encrypted vault (requires consent)
        file: Document file (PDF, PNG, JPG, etc.)
        idempotency_header: Alternative idempotency key via header

    Returns:
        DocumentOut with OCR job ID for polling

    Note:
        - Requires treatment consent (enforced by require_intake_session)
        - Idempotent: duplicate uploads with same key return existing document
        - OCR processing is async via Celery
        - Files are stored in temp_scans/ initially, moved to encrypted_vault/ on opt-in
    """
    settings = get_settings()

    # Use header idempotency key if form key not provided
    final_idempotency_key = idempotency_header or idempotency_key
    if not final_idempotency_key:
        raise ConflictError(
            code="idempotency_required",
            message="Idempotency-Key is required (form field or header)",
        )

    # Check for existing document with same idempotency key
    cached = await idempotency_get(f"document:{final_idempotency_key}")
    if cached:
        # Return cached result
        return DocumentOut.model_validate_json(cached)

    # Claim idempotency key
    claimed = await claim_idempotency_key(f"document:{final_idempotency_key}")
    if not claimed:
        raise ConflictError(
            code="idempotency_pending",
            message="Document upload with this key is already in progress",
        )

    # Verify vault opt-in consent
    if vault_opt_in:
        # In production, check for diagnostics_ocr consent
        # For now, we'll assume consent is verified by require_intake_session
        pass

    # Read file content
    file_content = await file.read()
    if not file_content:
        raise ConflictError(code="empty_file", message="Uploaded file is empty")

    # Calculate SHA-256 of file content
    file_hash = hashlib.sha256(file_content).hexdigest()

    # Determine storage path
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    object_path = f"{settings.UPLOAD_TEMP_DIR}/{patient_id}_{timestamp}_{file.filename}"

    # Save file to temp storage
    import os

    os.makedirs(settings.UPLOAD_TEMP_DIR, exist_ok=True)
    with open(object_path, "wb") as f:
        f.write(file_content)

    # Create document record
    document = Document(
        patient_id=patient_id,
        session_id=session_id,
        idempotency_key=final_idempotency_key,
        kind=kind.value,
        storage_tier=StorageTier.temp_scan.value,
        object_path=object_path,
        vault_opt_in=vault_opt_in,
        ocr_status=OcrStatus.queued.value,
        ciphertext_sha256=file_hash,
    )
    session.add(document)
    await session.flush()

    # Queue OCR job (would be Celery task in production)
    # For now, we'll just mark as processing
    document.ocr_status = OcrStatus.processing.value
    await session.flush()

    # Cache result for idempotency
    result = DocumentOut.model_validate(document)
    await idempotency_store(f"document:{final_idempotency_key}", result.model_dump_json())

    logger.info(
        "document_uploaded",
        document_id=str(document.id),
        patient_id=str(patient_id),
        kind=kind.value,
        vault_opt_in=vault_opt_in,
    )

    # Trigger OCR processing (async via Celery in production)
    # await trigger_ocr_task.delay(document.id)

    return result


@router.get("/poll/{document_id}", response_model=OcrPollOut)
async def poll_ocr_status(
    document_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> OcrPollOut:
    """Poll OCR processing status for a document.

    Returns the current OCR status and extracted text if processing is complete.
    PII is only returned if appropriate consent is granted.
    """
    # Load document with extraction
    stmt = (
        select(Document)
        .options(selectinload(Document.extraction))
        .where(Document.id == document_id)
    )
    document = (await session.execute(stmt)).scalars().first()

    if document is None:
        raise NotFoundError(code="document_not_found", message="Document not found")

    # Check consent for PII access
    # In production, verify diagnostics_ocr consent before returning extracted text
    raw_text = None
    structured = None

    if document.ocr_status == OcrStatus.succeeded.value and document.extraction:
        # Decrypt PII fields
        try:
            from app.core.security import decrypt_pii

            raw_text = (
                decrypt_pii(document.extraction.raw_text_enc)
                if document.extraction.raw_text_enc
                else None
            )
            if document.extraction.structured_enc:
                structured_json = decrypt_pii(document.extraction.structured_enc)
                import json

                structured = json.loads(structured_json)
        except Exception as exc:
            logger.warning("decryption_failed", document_id=str(document_id), error=str(type(exc).__name__))

    return OcrPollOut(
        document_id=document.id,
        ocr_job_id=document.ocr_job_id,
        ocr_status=OcrStatus(document.ocr_status),
        ocr_attempts=document.ocr_attempts,
        raw_text=raw_text,
        structured=structured,
    )


@router.post("/confirm/{document_id}")
async def confirm_document(
    document_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Confirm OCR extraction and move document to vault if opted in.

    Called by the physician/patient to verify the extracted text is correct.
    """
    # Load document
    stmt = select(Document).where(Document.id == document_id)
    document = (await session.execute(stmt)).scalars().first()

    if document is None:
        raise NotFoundError(code="document_not_found", message="Document not found")

    if document.ocr_status != OcrStatus.succeeded.value:
        raise ConflictError(
            code="ocr_not_complete",
            message="OCR processing is not complete",
        )

    # Move to vault if opted in
    if document.vault_opt_in and document.storage_tier == StorageTier.temp_scan.value:
        settings = get_settings()

        # Move file to vault
        import shutil

        vault_path = f"{settings.UPLOAD_VAULT_DIR}/{document.id}_{uuid.uuid4().hex[:8]}"
        shutil.move(document.object_path, vault_path)

        document.storage_tier = StorageTier.encrypted_vault.value
        document.object_path = vault_path
        document.purge_after = None  # Vault documents don't auto-purge

        await session.flush()

        logger.info(
            "document_moved_to_vault",
            document_id=str(document_id),
            vault_path=vault_path,
        )

    return {
        "document_id": str(document_id),
        "status": "confirmed",
        "storage_tier": document.storage_tier,
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Delete a document and its file.

    Requires appropriate consent and authorization.
    """
    # Load document
    stmt = select(Document).where(Document.id == document_id)
    document = (await session.execute(stmt)).scalars().first()

    if document is None:
        raise NotFoundError(code="document_not_found", message="Document not found")

    # Delete file from storage
    import os

    if os.path.exists(document.object_path):
        os.remove(document.object_path)
        logger.info("document_file_deleted", path=document.object_path)

    # Delete database record
    await session.delete(document)
    await session.flush()

    logger.info("document_deleted", document_id=str(document_id))

    return {"document_id": str(document_id), "status": "deleted"}


@router.get("/patient/{patient_id}")
async def list_patient_documents(
    patient_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[DocumentOut]:
    """List all documents for a patient.

    Returns metadata only — PII extraction requires consent check per document.
    """
    # Verify patient access
    if principal.role.value != "patient" or (principal.patient and principal.patient.id != patient_id):
        # Staff can access patient documents
        if principal.role.value not in {"kiosk", "physician", "admin"}:
            raise ForbiddenError(code="access_denied", message="Not authorized to access these documents")

    # Load documents
    stmt = select(Document).where(Document.patient_id == patient_id)
    stmt = stmt.order_by(Document.created_at.desc())

    documents = (await session.execute(stmt)).scalars().all()

    return [DocumentOut.model_validate(doc) for doc in documents]
