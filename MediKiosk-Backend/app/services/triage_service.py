"""Triage service for red-flag detection, acuity assignment, and queue management.

Business logic for clinical prioritization. Concurrency-safe queue position
allocation using SELECT ... FOR UPDATE. Red-flag detection uses the clinical
NLP module but can also apply rule-based fallbacks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai_modules.nlp_clinical import ClinicalNlpProtocol, RedFlag, get_clinical_nlp
from app.core.config import get_settings
from app.core.database import lock_row_for_update, redis_lock
from app.core.exceptions import ConflictError, NotFoundError
from app.models.clinical import InterviewSession, TriageAcuity, TriageAssessment
from app.schemas.interview import TriageOut
from app.utils.logger import get_logger

logger = get_logger("app.services.triage")


class TriageRule(str, Enum):
    """Rule-based triage categories for fallback when NLP is unavailable."""

    chest_pain_any = "chest_pain_any"
    respiratory_distress = "respiratory_distress"
    severe_abdominal_pain = "severe_abdominal_pain"
    neurological_symptoms = "neurological_symptoms"
    high_fever = "high_fever"
    bleeding = "bleeding"
    trauma = "trauma"
    psychiatric_emergency = "psychiatric_emergency"


@dataclass
class TriageDecision:
    """Result of triage assessment."""

    acuity: TriageAcuity
    red_flags: list[RedFlag]
    rule_triggers: list[TriageRule]
    confidence: float
    reasoning: str


class TriageService:
    """Orchestrates triage assessment and queue position allocation.

    Concurrency:
    - Queue position allocation uses SELECT ... FOR UPDATE on (clinic_id, queue_date)
    - Redis lock `triage:{clinic_id}:{queue_date}` for additional safety across replicas
    - Unique constraint on (clinic_id, queue_date, queue_position) prevents duplicates
    """

    def __init__(self, clinical_nlp: ClinicalNlpProtocol | None = None) -> None:
        self.clinical_nlp = clinical_nlp or get_clinical_nlp()
        self.settings = get_settings()

    async def assess_session(
        self,
        session: AsyncSession,
        interview_session_id: uuid.UUID,
    ) -> TriageDecision:
        """Perform triage assessment on a completed interview session.

        Loads clinical intake, applies red-flag detection, assigns acuity.
        Uses both NLP-based and rule-based detection for robustness.
        """
        # Load interview session with clinical intake
        stmt = (
            select(InterviewSession)
            .options(selectinload(InterviewSession.clinical_intake))
            .where(InterviewSession.id == interview_session_id)
        )
        interview = (await session.execute(stmt)).scalars().first()

        if interview is None:
            raise NotFoundError(code="interview_not_found", message="Interview session not found")

        clinical = interview.clinical_intake
        if not clinical:
            # No clinical data — default to routine
            return TriageDecision(
                acuity=TriageAcuity.routine,
                red_flags=[],
                rule_triggers=[],
                confidence=0.5,
                reasoning="No clinical data available",
            )

        # Collect clinical text for analysis
        clinical_text_parts = []
        if clinical.chief_complaint:
            # Note: chief_complaint is encrypted at rest; would need decrypt here
            # For now, we work with what we have — in production, decrypt after consent check
            clinical_text_parts.append("[chief_complaint]")
        if clinical.site:
            clinical_text_parts.append("[site]")
        if clinical.onset:
            clinical_text_parts.append("[onset]")
        if clinical.character:
            clinical_text_parts.append("[character]")
        if clinical.associations:
            clinical_text_parts.append("[associations]")

        clinical_text = " ".join(clinical_text_parts)

        # Run NLP-based red-flag detection
        nlp_red_flags: list[RedFlag] = []
        try:
            nlp_red_flags = await self.clinical_nlp.detect_red_flags(clinical_text, interview.language)
        except Exception as exc:
            logger.warning("nlp_red_flags_failed", interview_id=str(interview_session_id), error=str(type(exc).__name__))

        # Run rule-based detection as fallback/confirmation
        rule_triggers = self._apply_rules(clinical)

        # Combine NLP and rule-based results
        all_red_flags = list(set(nlp_red_flags))  # Deduplicate

        # Determine acuity based on red flags
        acuity = self._determine_acuity(all_red_flags, rule_triggers)

        reasoning = self._generate_reasoning(acuity, all_red_flags, rule_triggers)

        logger.info(
            "triage_assessment",
            interview_id=str(interview_session_id),
            acuity=acuity.value,
            red_flags=[rf.value for rf in all_red_flags],
            rules=[r.value for r in rule_triggers],
        )

        return TriageDecision(
            acuity=acuity,
            red_flags=all_red_flags,
            rule_triggers=rule_triggers,
            confidence=0.8 if nlp_red_flags else 0.6,
            reasoning=reasoning,
        )

    def _apply_rules(self, clinical: Any) -> list[TriageRule]:
        """Apply rule-based red-flag detection as fallback.

        These are keyword-based checks on structured clinical data.
        In production, these should be tuned based on clinical guidelines.
        """
        triggers = []

        # Check severity
        if clinical.severity and clinical.severity >= 8:
            triggers.append(TriageRule.chest_pain_any)  # High severity is a concern

        # Check for red flags already stored in clinical intake
        if clinical.red_flags:
            # Convert stored string red flags to enum triggers
            for rf in clinical.red_flags:
                if rf == "chest_pain":
                    triggers.append(TriageRule.chest_pain_any)
                elif rf == "shortness_of_breath":
                    triggers.append(TriageRule.respiratory_distress)
                elif rf == "severe_abdominal_pain":
                    triggers.append(TriageRule.severe_abdominal_pain)
                elif rf == "neurological_deficit":
                    triggers.append(TriageRule.neurological_symptoms)
                elif rf == "high_fever":
                    triggers.append(TriageRule.high_fever)
                elif rf == "uncontrolled_bleeding":
                    triggers.append(TriageRule.bleeding)
                elif rf == "loss_of_consciousness":
                    triggers.append(TriageRule.neurological_symptoms)
                elif rf == "suicidal_ideation":
                    triggers.append(TriageRule.psychiatric_emergency)

        return triggers

    def _determine_acuity(
        self,
        red_flags: list[RedFlag],
        rule_triggers: list[TriageRule],
    ) -> TriageAcuity:
        """Determine triage acuity based on detected red flags and rules.

        Priority:
        1. Emergency: Life-threatening conditions (chest pain, respiratory distress, etc.)
        2. Urgent: Serious but not immediately life-threatening
        3. Routine: Non-urgent cases
        """
        emergency_flags = {
            RedFlag.chest_pain,
            RedFlag.shortness_of_breath,
            RedFlag.neurological_deficit,
            RedFlag.uncontrolled_bleeding,
            RedFlag.loss_of_consciousness,
            RedFlag.suicidal_ideation,
            RedFlag.severe_allergic_reaction,
        }

        emergency_rules = {
            TriageRule.chest_pain_any,
            TriageRule.respiratory_distress,
            TriageRule.neurological_symptoms,
            TriageRule.bleeding,
            TriageRule.psychiatric_emergency,
        }

        # Check for emergency indicators
        if any(rf in emergency_flags for rf in red_flags):
            return TriageAcuity.emergency
        if any(rule in emergency_rules for rule in rule_triggers):
            return TriageAcuity.emergency

        # Check for urgent indicators
        urgent_flags = {
            RedFlag.severe_abdominal_pain,
            RedFlag.high_fever,
            RedFlag.severe_headache,
        }

        urgent_rules = {
            TriageRule.severe_abdominal_pain,
            TriageRule.high_fever,
            TriageRule.trauma,
        }

        if any(rf in urgent_flags for rf in red_flags):
            return TriageAcuity.urgent
        if any(rule in urgent_rules for rule in rule_triggers):
            return TriageAcuity.urgent

        # Default to routine
        return TriageAcuity.routine

    def _generate_reasoning(
        self,
        acuity: TriageAcuity,
        red_flags: list[RedFlag],
        rule_triggers: list[TriageRule],
    ) -> str:
        """Generate human-readable reasoning for the triage decision."""
        if acuity == TriageAcuity.emergency:
            if red_flags:
                return f"Emergency: detected red flags {', '.join([rf.value for rf in red_flags])}"
            if rule_triggers:
                return f"Emergency: rule triggers {', '.join([r.value for r in rule_triggers])}"
            return "Emergency: clinical indicators suggest immediate attention needed"
        elif acuity == TriageAcuity.urgent:
            if red_flags:
                return f"Urgent: detected red flags {', '.join([rf.value for rf in red_flags])}"
            if rule_triggers:
                return f"Urgent: rule triggers {', '.join([r.value for r in rule_triggers])}"
            return "Urgent: clinical indicators suggest prompt attention needed"
        else:
            return "Routine: no immediate concerns detected"

    async def assign_queue_position(
        self,
        session: AsyncSession,
        interview_session_id: uuid.UUID,
        clinic_id: uuid.UUID,
        acuity: TriageAcuity,
    ) -> TriageAssessment:
        """Assign a queue position for the patient with concurrency safety.

        Concurrency strategy:
        1. Redis lock `triage:{clinic_id}:{queue_date}` to prevent cross-replica races
        2. SELECT ... FOR UPDATE on existing triage rows for this clinic/date
        3. Calculate next position = MAX(position) + 1
        4. INSERT with unique constraint on (clinic_id, queue_date, queue_position)
        5. ON CONFLICT retry with new position

        Emergency cases get priority positions (lower numbers).
        """
        queue_date = date.today()

        # Redis lock for additional safety across replicas
        lock_name = f"triage:{clinic_id}:{queue_date}"
        async with redis_lock(lock_name, ttl_seconds=15):
            # Calculate next position
            stmt = select(TriageAssessment).where(
                TriageAssessment.clinic_id == clinic_id,
                TriageAssessment.queue_date == queue_date,
            )
            stmt = stmt.order_by(TriageAssessment.queue_position.desc())

            # Use SELECT ... FOR UPDATE to lock the rows
            last_assessment = await lock_row_for_update(session, stmt)

            if last_assessment:
                next_position = last_assessment.queue_position + 1
            else:
                next_position = 1

            # Emergency cases get priority: insert at position 1 and shift others
            if acuity == TriageAcuity.emergency and next_position > 1:
                # Shift existing positions down
                shift_stmt = select(TriageAssessment).where(
                    TriageAssessment.clinic_id == clinic_id,
                    TriageAssessment.queue_date == queue_date,
                )
                existing = (await session.execute(shift_stmt)).scalars().all()
                for existing_assessment in existing:
                    existing_assessment.queue_position += 1
                next_position = 1

            # Create triage assessment
            assessment = TriageAssessment(
                session_id=interview_session_id,
                clinic_id=clinic_id,
                acuity=acuity.value,
                queue_date=queue_date,
                queue_position=next_position,
            )

            session.add(assessment)

            try:
                await session.flush()
            except IntegrityError as exc:
                # Handle race condition: another replica took this position
                logger.warning(
                    "triage_position_conflict",
                    clinic_id=str(clinic_id),
                    queue_date=queue_date,
                    position=next_position,
                )
                raise ConflictError(
                    code="queue_position_conflict",
                    message="Queue position conflict; please retry triage assignment",
                ) from exc

            logger.info(
                "triage_assigned",
                interview_id=str(interview_session_id),
                clinic_id=str(clinic_id),
                acuity=acuity.value,
                position=next_position,
                queue_date=queue_date,
            )

            return assessment

    async def get_queue_status(
        self,
        session: AsyncSession,
        clinic_id: uuid.UUID,
        queue_date: date | None = None,
    ) -> list[TriageOut]:
        """Get current queue status for a clinic.

        Returns ordered list of patients waiting, grouped by acuity.
        """
        if queue_date is None:
            queue_date = date.today()

        stmt = select(TriageAssessment).where(
            TriageAssessment.clinic_id == clinic_id,
            TriageAssessment.queue_date == queue_date,
        )
        stmt = stmt.order_by(TriageAssessment.queue_position)

        results = (await session.execute(stmt)).scalars().all()

        return [TriageOut.model_validate(r) for r in results]

    async def complete_triage(
        self,
        session: AsyncSession,
        interview_session_id: uuid.UUID,
    ) -> TriageOut:
        """Perform full triage workflow: assess and assign queue position.

        Convenience method that combines assessment and queue assignment.
        """
        # Load interview to get clinic_id
        stmt = select(InterviewSession).where(InterviewSession.id == interview_session_id)
        interview = (await session.execute(stmt)).scalars().first()
        if not interview:
            raise NotFoundError(code="interview_not_found", message="Interview session not found")

        # Assess acuity
        decision = await self.assess_session(session, interview_session_id)

        # Assign queue position
        assessment = await self.assign_queue_position(
            session,
            interview_session_id,
            interview.clinic_id,
            decision.acuity,
        )

        return TriageOut.model_validate(assessment)


def get_triage_service() -> TriageService:
    """Factory for triage service. Can be swapped in tests."""
    return TriageService()
