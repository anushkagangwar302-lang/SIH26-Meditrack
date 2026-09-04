"""AYUSH-system intake attached to an interview session."""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


class AyushSystem(str, Enum):
    ayurveda = "ayurveda"
    yoga = "yoga"
    unani = "unani"
    siddha = "siddha"
    sowa_rigpa = "sowa_rigpa"
    homeopathy = "homeopathy"


class AyushIntake(TimestampMixin, Base):
    __tablename__ = "ayush_intakes"
    __table_args__ = (UniqueConstraint("session_id", name="uq_ayush_intakes_session"),)

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
    system: Mapped[str] = mapped_column(String(32), nullable=False)
    # Clinical AYUSH observations — may include identifying narrative. Treat as PII if free text names a person.
    prakriti: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vikriti: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agni: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nadi_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    dosha_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    diet_sleep: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    branching_path: Mapped[str | None] = mapped_column(String(64), nullable=True)

    session: Mapped["InterviewSession"] = relationship(back_populates="ayush_intake")
