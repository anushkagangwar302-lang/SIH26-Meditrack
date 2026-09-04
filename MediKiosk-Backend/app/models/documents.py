"""Document uploads, OCR jobs, ABDM webhook receipts, stored FHIR.

Concurrency:
- Document POST: UNIQUE idempotency_key + ON CONFLICT DO NOTHING (return existing).
- OCR status: Redis lock `ocr:{document_id}` then UPDATE; unique ocr_job_id.
- Webhooks: UNIQUE inbound_event_id + ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


class DocumentKind(str, Enum):
    prescription = "prescription"
    lab_report = "lab_report"
    id_scan = "id_scan"
    imaging = "imaging"
    other = "other"


class StorageTier(str, Enum):
    temp_scan = "temp_scan"
    encrypted_vault = "encrypted_vault"


class OcrStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_documents_idempotency_key"),
        UniqueConstraint("ocr_job_id", name="uq_documents_ocr_job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interview_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Client-supplied key for flaky kiosk retries. Not PII.
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_tier: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'temp_scan'"))
    object_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Vault is populated only on explicit opt-in (consent diagnostics_ocr + vault_opt_in).
    vault_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ocr_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        server_default=text("gen_random_uuid()"),
    )
    ocr_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'queued'"))
    ocr_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # SHA-256 of ciphertext bytes — not the document content.
    ciphertext_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    extraction: Mapped["OcrExtraction | None"] = relationship(back_populates="document", uselist=False)


class OcrExtraction(TimestampMixin, Base):
    __tablename__ = "ocr_extractions"
    __table_args__ = (UniqueConstraint("document_id", name="uq_ocr_extractions_document"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # PII: OCR text of prescriptions/labs/IDs — ciphertext.
    raw_text_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PII: structured extraction JSON — ciphertext of JSON, not JSONB plaintext.
    structured_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True)

    document: Mapped[Document] = relationship(back_populates="extraction")


class AbdmWebhookEvent(TimestampMixin, Base):
    __tablename__ = "abdm_webhook_events"
    __table_args__ = (UniqueConstraint("inbound_event_id", name="uq_abdm_webhook_inbound_event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # Idempotency for ABDM retries — ON CONFLICT (inbound_event_id) DO NOTHING.
    inbound_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # PII: raw webhook body often contains ABHA — ciphertext.
    payload_enc: Mapped[str] = mapped_column(Text, nullable=False)


class FhirBundle(TimestampMixin, Base):
    __tablename__ = "fhir_bundles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interview_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    bundle_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    # PII: FHIR resources include names, identifiers, ABHA — ciphertext of the Bundle JSON.
    bundle_enc: Mapped[str] = mapped_column(Text, nullable=False)
    abdm_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
