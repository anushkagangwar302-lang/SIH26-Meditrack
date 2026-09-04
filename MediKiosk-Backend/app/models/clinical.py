"""Clinical intake (SOCRATES) and triage queue.

Concurrency — triage queue position:
Allocate position with SELECT ... FOR UPDATE on the clinic's queue-day row
(or INSERT ... ON CONFLICT (clinic_id, queue_date, queue_position) and retry).
Do not MAX(position)+1 without a lock — replicas will clash.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


class InterviewStatus(str, Enum):
    in_progress = "in_progress"
    completed = "completed"
    abandoned = "abandoned"


class TriageAcuity(str, Enum):
    emergency = "emergency"
    urgent = "urgent"
    routine = "routine"


class InterviewSession(TimestampMixin, Base):
    __tablename__ = "interview_sessions"

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
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kiosk_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'in_progress'"))
    language: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'hi'"))
    current_step: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'welcome'"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    clinical_intake: Mapped["ClinicalIntake | None"] = relationship(back_populates="session", uselist=False)
    ayush_intake: Mapped["AyushIntake | None"] = relationship(back_populates="session", uselist=False)
    triage: Mapped["TriageAssessment | None"] = relationship(back_populates="session", uselist=False)


class ClinicalIntake(TimestampMixin, Base):
    """SOCRATES structured history. Live dialogue state lives in Redis (TTL), this is durable."""

    __tablename__ = "clinical_intakes"
    __table_args__ = (UniqueConstraint("session_id", name="uq_clinical_intakes_session"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interview_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Clinical text — may incidentally contain PII if the patient names themselves. Treat as PII.
    chief_complaint: Mapped[str | None] = mapped_column(Text, nullable=True)
    site: Mapped[str | None] = mapped_column(Text, nullable=True)
    onset: Mapped[str | None] = mapped_column(Text, nullable=True)
    character: Mapped[str | None] = mapped_column(Text, nullable=True)
    radiation: Mapped[str | None] = mapped_column(Text, nullable=True)
    associations: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_course: Mapped[str | None] = mapped_column(Text, nullable=True)
    exacerbating_relieving: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    red_flags: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # PII: allergy / medication names tied to the person — ciphertext.
    allergies_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    medications_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[InterviewSession] = relationship(back_populates="clinical_intake")


class TriageAssessment(TimestampMixin, Base):
    __tablename__ = "triage_assessments"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_triage_assessments_session"),
        UniqueConstraint(
            "clinic_id",
            "queue_date",
            "queue_position",
            name="uq_triage_queue_slot",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interview_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
    )
    acuity: Mapped[str] = mapped_column(String(32), nullable=False)
    queue_date: Mapped[date] = mapped_column(Date, nullable=False)
    queue_position: Mapped[int] = mapped_column(Integer, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    session: Mapped[InterviewSession] = relationship(back_populates="triage")
