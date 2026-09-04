"""Patient and consent API schemas.

Inbound identity fields are plaintext for one hop only; services must encrypt
before INSERT. Outbound models never include Aadhaar/ABHA/name/mobile/email.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.consent import ConsentPurpose, ConsentStatus
from app.models.user import AbhaLinkStatus

# Marker in OpenAPI + code review. Values must never be logged.
PII = Annotated[str, Field(json_schema_extra={"x-pii": True})]


class Gender(str, Enum):
    female = "female"
    male = "male"
    other = "other"
    undisclosed = "undisclosed"


class PatientEnrollIn(BaseModel):
    """Kiosk enrollment payload. All identity fields are PII."""

    clinic_id: UUID
    # PII: Aadhaar
    aadhaar: PII | None = Field(default=None, description="PII:Aadhaar — encrypt before persist")
    # PII: ABHA number
    abha_number: PII | None = Field(default=None, description="PII:ABHA — encrypt before persist")
    # PII: ABHA address
    abha_address: PII | None = Field(default=None, description="PII:ABHA address — encrypt before persist")
    # PII: name
    full_name: PII | None = Field(default=None, description="PII:name — encrypt before persist")
    # PII: DOB
    date_of_birth: PII | None = Field(default=None, description="PII:DOB ISO-8601 — encrypt before persist")
    gender: Gender | None = None
    # PII: mobile
    mobile: PII | None = Field(default=None, description="PII:mobile — encrypt before persist")
    # PII: email
    email: PII | None = Field(default=None, description="PII:email — encrypt before persist")
    preferred_language: str = "hi"

    @field_validator("aadhaar", "abha_number", "mobile", "email", "full_name", "abha_address")
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            return None
        return value


class PatientOut(BaseModel):
    """Safe patient view. Decrypt demographics only in services after consent check."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    clinic_id: UUID
    abha_link_status: AbhaLinkStatus
    preferred_language: str
    created_at: datetime


class PatientDemographicsOut(BaseModel):
    """Returned only after ConsentPurpose.treatment (or equivalent) is granted.

    PII fields below are plaintext in transit to the authorised physician/kiosk
    session — still never write them to logs.
    """

    id: UUID
    # PII: name
    full_name: str | None = Field(default=None, description="PII:name")
    # PII: DOB
    date_of_birth: str | None = Field(default=None, description="PII:DOB")
    gender: str | None = None
    abha_link_status: AbhaLinkStatus
    preferred_language: str


class ConsentCaptureIn(BaseModel):
    purpose: ConsentPurpose
    granted: bool
    notice_version: str = Field(min_length=1, max_length=64)
    capture_channel: str = "kiosk"


class ConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    purpose: str
    status: ConsentStatus
    notice_version: str
    granted_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
