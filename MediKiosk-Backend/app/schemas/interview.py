"""Interview, SOCRATES, AYUSH branch, and triage schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.ayush import AyushSystem
from app.models.clinical import InterviewStatus, TriageAcuity


class InterviewStartIn(BaseModel):
    patient_id: UUID
    clinic_id: UUID
    language: str = "hi"


class InterviewSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    clinic_id: UUID
    status: InterviewStatus
    language: str
    current_step: str
    started_at: datetime
    completed_at: datetime | None


class SocratesUpdateIn(BaseModel):
    """Partial SOCRATES. Clinical free text may incidentally contain PII — treat as PII."""

    chief_complaint: str | None = Field(default=None, description="PII:clinical narrative")
    site: str | None = None
    onset: str | None = None
    character: str | None = None
    radiation: str | None = None
    associations: str | None = None
    time_course: str | None = None
    exacerbating_relieving: str | None = None
    severity: int | None = Field(default=None, ge=0, le=10)
    red_flags: list[str] = Field(default_factory=list)
    # PII: allergies
    allergies: str | None = Field(default=None, description="PII:allergies — encrypt before persist")
    # PII: medications
    medications: str | None = Field(default=None, description="PII:medications — encrypt before persist")


class AyushBranchIn(BaseModel):
    system: AyushSystem
    prakriti: str | None = None
    vikriti: str | None = None
    agni: str | None = None
    nadi_notes: str | None = Field(default=None, description="PII:clinical narrative if identifying")
    dosha_scores: dict = Field(default_factory=dict)
    diet_sleep: dict = Field(default_factory=dict)
    branching_path: str | None = None


class DialogueTurnIn(BaseModel):
    session_id: UUID
    # PII: utterance may include name/phone if spoken — encrypt in Redis snapshot
    utterance: str = Field(description="PII:voice/text utterance")
    step: str


class TriageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    clinic_id: UUID
    acuity: TriageAcuity
    queue_date: date
    queue_position: int
    assigned_at: datetime
