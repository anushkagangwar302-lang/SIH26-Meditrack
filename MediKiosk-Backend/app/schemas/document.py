"""Document upload and OCR polling schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.documents import DocumentKind, OcrStatus, StorageTier


class DocumentUploadIn(BaseModel):
    patient_id: UUID
    session_id: UUID | None = None
    kind: DocumentKind
    # Required so flaky kiosk retries do not double-store. Unique in DB (ON CONFLICT).
    idempotency_key: str = Field(min_length=8, max_length=128)
    vault_opt_in: bool = False
    # SHA-256 of the ciphertext the client (or API) produced — not plaintext bytes.
    ciphertext_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    session_id: UUID | None
    kind: str
    storage_tier: StorageTier
    vault_opt_in: bool
    ocr_job_id: UUID
    ocr_status: OcrStatus
    created_at: datetime


class OcrPollOut(BaseModel):
    document_id: UUID
    ocr_job_id: UUID
    ocr_status: OcrStatus
    ocr_attempts: int
    # PII: extracted text — only populated after diagnostics_ocr consent in the service layer.
    raw_text: str | None = Field(default=None, description="PII:OCR text")
    structured: dict | None = Field(default=None, description="PII:OCR structured fields")
