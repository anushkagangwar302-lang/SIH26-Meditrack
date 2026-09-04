"""Consent records — DPDP Act 2023.

Enforcement is not this table alone: every PII read in services MUST load the
matching row with SELECT ... FOR UPDATE (or a repeatable-read transaction)
before decrypting. Recording consent without the check is non-compliant.

Concurrency — grant/revoke:
SELECT ... FOR UPDATE on (patient_id, purpose). Unique constraint prevents
duplicate purpose rows; ON CONFLICT is for first insert only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


class ConsentPurpose(str, Enum):
    """Lawful processing purposes. Add values via migration, not ad-hoc strings."""

    treatment = "treatment"
    abdm_health_records = "abdm_health_records"
    diagnostics_ocr = "diagnostics_ocr"
    voice_processing = "voice_processing"
    research = "research"


class ConsentStatus(str, Enum):
    granted = "granted"
    denied = "denied"
    revoked = "revoked"
    expired = "expired"


class Consent(TimestampMixin, Base):
    __tablename__ = "consents"
    __table_args__ = (UniqueConstraint("patient_id", "purpose", name="uq_consents_patient_purpose"),)

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
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # Version of the notice shown on the kiosk — environment-specific copy, e.g. "dpdp-notice-2026-01"
    notice_version: Mapped[str] = mapped_column(String(64), nullable=False)
    capture_channel: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'kiosk'"))
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="consents")
    events: Mapped[list["ConsentEvent"]] = relationship(back_populates="consent")


class ConsentEvent(Base):
    """Append-only audit. Do not update rows. No PII — patient_id + purpose only."""

    __tablename__ = "consent_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    consent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # Never store Aadhaar/ABHA/name here. Request id for trace only.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

    consent: Mapped[Consent] = relationship(back_populates="events")
