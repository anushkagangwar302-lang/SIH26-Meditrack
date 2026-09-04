"""User, clinic, and patient identity.

Concurrency — ABHA linking:
Use INSERT ... ON CONFLICT (abha_number_hmac) DO NOTHING / DO UPDATE of link
status inside a transaction. Never check-then-insert in Python.

PII columns are marked `# PII:` — ciphertext or HMAC only, never plaintext.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.security import Role


class AbhaLinkStatus(str, Enum):
    unlinked = "unlinked"
    pending = "pending"
    linked = "linked"
    failed = "failed"


class Clinic(TimestampMixin, Base):
    __tablename__ = "clinics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # Environment-specific clinic code assigned at onboard — not a secret, must be unique.
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ayush_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    users: Mapped[list["User"]] = relationship(back_populates="clinic")
    patients: Mapped[list["Patient"]] = relationship(back_populates="clinic")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    role: Mapped[Role] = mapped_column(String(32), nullable=False, index=True)
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Staff credentials only. Patients authenticate via ABHA OTP — password_hash stays null.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    clinic: Mapped[Clinic | None] = relationship(back_populates="users")
    patient: Mapped[Patient | None] = relationship(back_populates="user", uselist=False)


class Patient(TimestampMixin, Base):
    """One patient row per kiosk subject. Identity fields are encrypted at rest."""

    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_patients_user_id"),
        UniqueConstraint("aadhaar_hmac", name="uq_patients_aadhaar_hmac"),
        UniqueConstraint("abha_number_hmac", name="uq_patients_abha_number_hmac"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # PII: Aadhaar — AES-GCM ciphertext (security.encrypt_pii). Never log.
    aadhaar_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PII: Aadhaar lookup HMAC (security.hmac_lookup). Unique for ON CONFLICT linking.
    aadhaar_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # PII: ABHA number — ciphertext.
    abha_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PII: ABHA number HMAC. Race-safe link target: ON CONFLICT (abha_number_hmac).
    abha_number_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # PII: ABHA address (e.g. user@sbx) — ciphertext.
    abha_address_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    # PII: legal name — ciphertext.
    full_name_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PII: date of birth ISO-8601 — ciphertext (not a native date column).
    date_of_birth_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Sensitive demographic; not a unique identifier.
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # PII: mobile — ciphertext.
    mobile_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PII: mobile HMAC for optional lookup (not unique nationally — duplicates possible).
    mobile_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # PII: email — ciphertext.
    email_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    abha_link_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'unlinked'"),
    )
    preferred_language: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'hi'"))

    user: Mapped[User] = relationship(back_populates="patient")
    clinic: Mapped[Clinic] = relationship(back_populates="patients")
    consents: Mapped[list["Consent"]] = relationship(back_populates="patient")
