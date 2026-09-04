"""FHIR R4 / ABDM-oriented request and response shapes.

Bundles in storage are ciphertext (`FhirBundle.bundle_enc`). These schemas are
the in-memory representation after decrypt + consent check.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FhirCoding(BaseModel):
    system: str
    code: str
    display: str | None = None


class FhirCodeableConcept(BaseModel):
    coding: list[FhirCoding] = Field(default_factory=list)
    text: str | None = None


class FhirResource(BaseModel):
    resourceType: str
    id: str | None = None
    # Remainder is resource-specific. May contain PII: name, identifier, telecom.
    extra: dict[str, Any] = Field(default_factory=dict, description="PII:FHIR resource body")

    model_config = {"extra": "allow"}


class FhirBundleEntry(BaseModel):
    fullUrl: str | None = None
    resource: dict[str, Any] = Field(description="PII:FHIR resource")


class FhirBundleIn(BaseModel):
    resourceType: Literal["Bundle"] = "Bundle"
    type: str = "document"
    entry: list[FhirBundleEntry] = Field(default_factory=list)


class FhirPersistIn(BaseModel):
    patient_id: UUID
    session_id: UUID | None = None
    bundle: FhirBundleIn
    direction: Literal["inbound", "outbound"] = "outbound"
    abdm_request_id: str | None = None


class FhirBundleOut(BaseModel):
    id: UUID
    patient_id: UUID
    bundle_type: str
    direction: str
    abdm_request_id: str | None = None
    # PII: decrypted bundle — service must have checked ABDM/treatment consent.
    bundle: dict[str, Any] = Field(description="PII:FHIR Bundle")


class AbdmWebhookAck(BaseModel):
    inbound_event_id: str
    accepted: bool
    duplicate: bool = False
