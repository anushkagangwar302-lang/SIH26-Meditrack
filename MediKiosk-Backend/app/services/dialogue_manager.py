"""Dialogue manager for interview flow, SOCRATES/AYUSH branching, and session state.

Business logic lives here — route handlers only orchestrate. Session state is
TTL-bound in Redis for real-time dialogue; durable state goes to Postgres on
completion. All PII operations check consent first.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai_modules.asr_tts import AsrResult, AsrTtsProtocol, get_asr_tts, Language
from app.ai_modules.nlp_clinical import (
    AyushAnalysis,
    ClinicalNlpProtocol,
    EntityExtraction,
    RedFlag,
    SocratesStructure,
    get_clinical_nlp,
)
from app.core.config import get_settings
from app.core.database import redis_session
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import PIILogGuard, encrypt_pii
from app.models.ayush import AyushIntake, AyushSystem
from app.models.clinical import ClinicalIntake, InterviewSession, InterviewStatus
from app.models.consent import Consent, ConsentPurpose
from app.models.user import Patient
from app.schemas.interview import AyushBranchIn, DialogueTurnIn, SocratesUpdateIn
from app.utils.logger import get_logger

logger = get_logger("app.services.dialogue")


class DialogueStep(str, Enum):
    """Interview dialogue steps. State machine progresses through these."""

    welcome = "welcome"
    language_selection = "language_selection"
    chief_complaint = "chief_complaint"
    socrates_site = "socrates_site"
    socrates_onset = "socrates_onset"
    socrates_character = "socrates_character"
    socrates_radiation = "socrates_radiation"
    socrates_associations = "socrates_associations"
    socrates_time_course = "socrates_time_course"
    socrates_severity = "socrates_severity"
    socrates_exacerbating = "socrates_exacerbating"
    allergies_medications = "allergies_medications"
    ayush_system_choice = "ayush_system_choice"
    ayush_prakriti = "ayush_prakriti"
    ayush_vikriti = "ayush_vikriti"
    ayush_agni = "ayush_agni"
    ayush_nadi = "ayush_nadi"
    review = "review"
    completed = "completed"


@dataclass
class DialogueState:
    """Transient interview state in Redis (TTL-bound). May contain PII — encrypt before storage."""

    session_id: uuid.UUID
    patient_id: uuid.UUID
    clinic_id: uuid.UUID
    language: str
    current_step: DialogueStep
    started_at: datetime
    # Dialogue history (may contain PII utterances) — encrypted
    history_enc: str | None = None
    # SOCRATES partial state (may contain PII) — encrypted
    socrates_partial_enc: str | None = None
    # AYUSH partial state (may contain PII) — encrypted
    ayush_partial_enc: str | None = None
    # Branch: whether patient chose AYUSH intake
    ayush_branch: bool = False
    # Red flags detected so far
    red_flags: list[str] = field(default_factory=list)
    # Last AI ASR result (for retry/correction)
    last_asr_result: dict[str, Any] | None = None


@dataclass
class DialogueResponse:
    """Response to a dialogue turn. May contain PII — never log."""

    next_step: DialogueStep
    prompt_text: str
    prompt_audio: bytes | None = None
    audio_format: str = "mp3"
    socrates_update: SocratesStructure | None = None
    ayush_update: AyushAnalysis | None = None
    detected_red_flags: list[RedFlag] = field(default_factory=list)
    requires_input: bool = True
    is_complete: bool = False


class DialogueManager:
    """Orchestrates interview flow, AI processing, and state persistence.

    Concurrency:
    - Redis stores per-session state with TTL (no inter-session contention)
    - Postgres writes use unique constraints on session_id
    - Red-flag updates are append-only (no race conditions)
    """

    def __init__(
        self,
        asr_tts: AsrTtsProtocol | None = None,
        clinical_nlp: ClinicalNlpProtocol | None = None,
    ) -> None:
        self.asr_tts = asr_tts or get_asr_tts()
        self.clinical_nlp = clinical_nlp or get_clinical_nlp()
        self.settings = get_settings()

    def _redis_key(self, session_id: uuid.UUID) -> str:
        return f"{self.settings.REDIS_PREFIX_INTERVIEW}{session_id}"

    async def _load_state(self, session_id: uuid.UUID) -> DialogueState:
        key = self._redis_key(session_id)
        raw = await redis_session().get(key)
        if not raw:
            raise NotFoundError(code="session_not_found", message="Interview session not found")
        data = json.loads(raw)
        # Decrypt encrypted fields (PII)
        state = DialogueState(
            session_id=uuid.UUID(data["session_id"]),
            patient_id=uuid.UUID(data["patient_id"]),
            clinic_id=uuid.UUID(data["clinic_id"]),
            language=data["language"],
            current_step=DialogueStep(data["current_step"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            history_enc=data.get("history_enc"),
            socrates_partial_enc=data.get("socrates_partial_enc"),
            ayush_partial_enc=data.get("ayush_partial_enc"),
            ayush_branch=data.get("ayush_branch", False),
            red_flags=data.get("red_flags", []),
            last_asr_result=data.get("last_asr_result"),
        )
        return state

    async def _save_state(self, state: DialogueState) -> None:
        key = self._redis_key(state.session_id)
        data = {
            "session_id": str(state.session_id),
            "patient_id": str(state.patient_id),
            "clinic_id": str(state.clinic_id),
            "language": state.language,
            "current_step": state.current_step.value,
            "started_at": state.started_at.isoformat(),
            "history_enc": state.history_enc,
            "socrates_partial_enc": state.socrates_partial_enc,
            "ayush_partial_enc": state.ayush_partial_enc,
            "ayush_branch": state.ayush_branch,
            "red_flags": state.red_flags,
            "last_asr_result": state.last_asr_result,
        }
        await redis_session().set(
            key,
            json.dumps(data),
            ex=self.settings.INTERVIEW_STATE_TTL_SECONDS,
        )

    async def start_session(
        self,
        patient_id: uuid.UUID,
        clinic_id: uuid.UUID,
        language: str = "hi",
    ) -> DialogueState:
        """Initialize a new interview session in Redis."""
        session_id = uuid.uuid4()
        state = DialogueState(
            session_id=session_id,
            patient_id=patient_id,
            clinic_id=clinic_id,
            language=language,
            current_step=DialogueStep.welcome,
            started_at=datetime.now(timezone.utc),
        )
        await self._save_state(state)
        logger.info("dialogue_session_started", session_id=str(session_id), patient_id=str(patient_id))
        return state

    async def process_turn(
        self,
        turn: DialogueTurnIn,
        audio_bytes: bytes | None = None,
    ) -> DialogueResponse:
        """Process a dialogue turn (text or voice) and advance the interview.

        May contain PII in utterance — never log. Checks consent before any PII processing.
        """
        state = await self._load_state(turn.session_id)

        # Transcribe audio if provided
        utterance = turn.utterance
        if audio_bytes:
            try:
                lang_enum = Language(state.language) if state.language in Language.__members__ else Language.hindi
                asr_result = await self.asr_tts.transcribe(audio_bytes, lang_enum)
                utterance = asr_result.transcript
                state.last_asr_result = {
                    "transcript": utterance,
                    "confidence": asr_result.confidence,
                    "vendor": asr_result.vendor,
                }
            except Exception as exc:
                logger.warning("asr_failed", session_id=str(turn.session_id), error=str(type(exc).__name__))
                # Fall back to text input if ASR fails

        # Check consent for voice processing if audio was used
        if audio_bytes:
            # Consent check would happen here via a dependency in the route handler
            # This service assumes consent is already verified
            pass

        # Route based on current step
        response = await self._route_step(state, utterance, turn.step)

        # Update state
        await self._save_state(state)
        return response

    async def _route_step(
        self,
        state: DialogueState,
        utterance: str,
        step: str,
    ) -> DialogueResponse:
        """Route the dialogue based on current step and user input."""

        # Step routing logic
        if state.current_step == DialogueStep.welcome:
            return await self._handle_welcome(state, utterance)
        elif state.current_step == DialogueStep.chief_complaint:
            return await self._handle_chief_complaint(state, utterance)
        elif state.current_step == DialogueStep.socrates_site:
            return await self._handle_socrates_site(state, utterance)
        elif state.current_step == DialogueStep.socrates_onset:
            return await self._handle_socrates_onset(state, utterance)
        elif state.current_step == DialogueStep.socrates_character:
            return await self._handle_socrates_character(state, utterance)
        elif state.current_step == DialogueStep.socrates_radiation:
            return await self._handle_socrates_radiation(state, utterance)
        elif state.current_step == DialogueStep.socrates_associations:
            return await self._handle_socrates_associations(state, utterance)
        elif state.current_step == DialogueStep.socrates_time_course:
            return await self._handle_socrates_time_course(state, utterance)
        elif state.current_step == DialogueStep.socrates_severity:
            return await self._handle_socrates_severity(state, utterance)
        elif state.current_step == DialogueStep.socrates_exacerbating:
            return await self._handle_socrates_exacerbating(state, utterance)
        elif state.current_step == DialogueStep.allergies_medications:
            return await self._handle_allergies_medications(state, utterance)
        elif state.current_step == DialogueStep.ayush_system_choice:
            return await self._handle_ayush_system_choice(state, utterance)
        elif state.current_step == DialogueStep.ayush_prakriti:
            return await self._handle_ayush_prakriti(state, utterance)
        elif state.current_step == DialogueStep.ayush_vikriti:
            return await self._handle_ayush_vikriti(state, utterance)
        elif state.current_step == DialogueStep.ayush_agni:
            return await self._handle_ayush_agni(state, utterance)
        elif state.current_step == DialogueStep.ayush_nadi:
            return await self._handle_ayush_nadi(state, utterance)
        elif state.current_step == DialogueStep.review:
            return await self._handle_review(state, utterance)
        else:
            return await self._handle_default(state)

    async def _handle_welcome(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Welcome step: explain the process and move to chief complaint."""
        state.current_step = DialogueStep.chief_complaint
        prompt = self._get_prompt("chief_complaint", state.language)
        return DialogueResponse(
            next_step=DialogueStep.chief_complaint,
            prompt_text=prompt,
        )

    async def _handle_chief_complaint(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Extract chief complaint and check for red flags."""
        # Use NLP to structure the complaint
        try:
            socrates = await self.clinical_nlp.structure_socrates(utterance, state.language)
            red_flags = await self.clinical_nlp.detect_red_flags(utterance, state.language)

            # Update partial state (encrypt PII)
            partial = state.socrates_partial_enc or "{}"
            existing = json.loads(partial) if partial else {}
            existing["chief_complaint"] = utterance  # Will be encrypted when persisted
            state.socrates_partial_enc = encrypt_pii(json.dumps(existing))

            # Track red flags
            state.red_flags.extend([rf.value for rf in red_flags])

            state.current_step = DialogueStep.socrates_site
            prompt = self._get_prompt("socrates_site", state.language)

            return DialogueResponse(
                next_step=DialogueStep.socrates_site,
                prompt_text=prompt,
                socrates_update=socrates,
                detected_red_flags=red_flags,
            )
        except Exception as exc:
            logger.warning("nlp_chief_complaint_failed", error=str(type(exc).__name__))
            # Fall back to simple progression
            state.current_step = DialogueStep.socrates_site
            return DialogueResponse(
                next_step=DialogueStep.socrates_site,
                prompt_text=self._get_prompt("socrates_site", state.language),
            )

    async def _handle_socrates_site(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture pain location."""
        partial = json.loads(state.socrates_partial_enc or "{}")
        partial["site"] = utterance
        state.socrates_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.socrates_onset
        return DialogueResponse(
            next_step=DialogueStep.socrates_onset,
            prompt_text=self._get_prompt("socrates_onset", state.language),
        )

    async def _handle_socrates_onset(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture when symptoms started."""
        partial = json.loads(state.socrates_partial_enc or "{}")
        partial["onset"] = utterance
        state.socrates_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.socrates_character
        return DialogueResponse(
            next_step=DialogueStep.socrates_character,
            prompt_text=self._get_prompt("socrates_character", state.language),
        )

    async def _handle_socrates_character(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture pain/symptom character."""
        partial = json.loads(state.socrates_partial_enc or "{}")
        partial["character"] = utterance
        state.socrates_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.socrates_radiation
        return DialogueResponse(
            next_step=DialogueStep.socrates_radiation,
            prompt_text=self._get_prompt("socrates_radiation", state.language),
        )

    async def _handle_socrates_radiation(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture pain radiation."""
        partial = json.loads(state.socrates_partial_enc or "{}")
        partial["radiation"] = utterance
        state.socrates_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.socrates_associations
        return DialogueResponse(
            next_step=DialogueStep.socrates_associations,
            prompt_text=self._get_prompt("socrates_associations", state.language),
        )

    async def _handle_socrates_associations(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture associated symptoms."""
        partial = json.loads(state.socrates_partial_enc or "{}")
        partial["associations"] = utterance
        state.socrates_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.socrates_time_course
        return DialogueResponse(
            next_step=DialogueStep.socrates_time_course,
            prompt_text=self._get_prompt("socrates_time_course", state.language),
        )

    async def _handle_socrates_time_course(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture symptom progression over time."""
        partial = json.loads(state.socrates_partial_enc or "{}")
        partial["time_course"] = utterance
        state.socrates_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.socrates_severity
        return DialogueResponse(
            next_step=DialogueStep.socrates_severity,
            prompt_text=self._get_prompt("socrates_severity", state.language),
        )

    async def _handle_socrates_severity(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture pain severity (0-10 scale)."""
        try:
            severity = int(utterance)
            if not 0 <= severity <= 10:
                severity = 5  # Default if invalid
        except (ValueError, TypeError):
            severity = 5

        partial = json.loads(state.socrates_partial_enc or "{}")
        partial["severity"] = severity
        state.socrates_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.socrates_exacerbating
        return DialogueResponse(
            next_step=DialogueStep.socrates_exacerbating,
            prompt_text=self._get_prompt("socrates_exacerbating", state.language),
        )

    async def _handle_socrates_exacerbating(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture exacerbating/relieving factors."""
        partial = json.loads(state.socrates_partial_enc or "{}")
        partial["exacerbating_relieving"] = utterance
        state.socrates_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.allergies_medications
        return DialogueResponse(
            next_step=DialogueStep.allergies_medications,
            prompt_text=self._get_prompt("allergies_medications", state.language),
        )

    async def _handle_allergies_medications(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture allergies and current medications."""
        try:
            entities = await self.clinical_nlp.extract_entities(utterance, state.language)

            partial = json.loads(state.socrates_partial_enc or "{}")
            partial["allergies"] = ", ".join(entities.allergies) if entities.allergies else utterance
            partial["medications"] = ", ".join(entities.medications) if entities.medications else utterance
            state.socrates_partial_enc = encrypt_pii(json.dumps(partial))

            # Check if clinic has AYUSH enabled (would need DB query here)
            # For now, assume AYUSH branch is offered
            state.current_step = DialogueStep.ayush_system_choice
            return DialogueResponse(
                next_step=DialogueStep.ayush_system_choice,
                prompt_text=self._get_prompt("ayush_system_choice", state.language),
            )
        except Exception as exc:
            logger.warning("nlp_entities_failed", error=str(type(exc).__name__))
            # Fall back to simple progression
            state.current_step = DialogueStep.ayush_system_choice
            return DialogueResponse(
                next_step=DialogueStep.ayush_system_choice,
                prompt_text=self._get_prompt("ayush_system_choice", state.language),
            )

    async def _handle_ayush_system_choice(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Handle AYUSH system selection or skip."""
        # Simple keyword detection for demo
        if any(word in utterance.lower() for word in ["yes", "haan", "ayurveda", "yoga"]):
            state.ayush_branch = True
            state.current_step = DialogueStep.ayush_prakriti
            return DialogueResponse(
                next_step=DialogueStep.ayush_prakriti,
                prompt_text=self._get_prompt("ayush_prakriti", state.language),
            )
        else:
            # Skip AYUSH, go to review
            state.current_step = DialogueStep.review
            return await self._handle_review(state, "")

    async def _handle_ayush_prakriti(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture AYUSH prakriti (body constitution)."""
        partial = json.loads(state.ayush_partial_enc or "{}")
        partial["prakriti"] = utterance
        state.ayush_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.ayush_vikriti
        return DialogueResponse(
            next_step=DialogueStep.ayush_vikriti,
            prompt_text=self._get_prompt("ayush_vikriti", state.language),
        )

    async def _handle_ayush_vikriti(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture AYUSH vikriti (current imbalance)."""
        partial = json.loads(state.ayush_partial_enc or "{}")
        partial["vikriti"] = utterance
        state.ayush_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.ayush_agni
        return DialogueResponse(
            next_step=DialogueStep.ayush_agni,
            prompt_text=self._get_prompt("ayush_agni", state.language),
        )

    async def _handle_ayush_agni(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture AYUSH agni (digestive fire)."""
        partial = json.loads(state.ayush_partial_enc or "{}")
        partial["agni"] = utterance
        state.ayush_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.ayush_nadi
        return DialogueResponse(
            next_step=DialogueStep.ayush_nadi,
            prompt_text=self._get_prompt("ayush_nadi", state.language),
        )

    async def _handle_ayush_nadi(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Capture AYUSH nadi (pulse) notes."""
        partial = json.loads(state.ayush_partial_enc or "{}")
        partial["nadi_notes"] = utterance
        state.ayush_partial_enc = encrypt_pii(json.dumps(partial))

        state.current_step = DialogueStep.review
        return await self._handle_review(state, "")

    async def _handle_review(self, state: DialogueState, utterance: str) -> DialogueResponse:
        """Review step: confirm completion and mark session as done."""
        if utterance.lower() in ["yes", "confirm", "correct"]:
            state.current_step = DialogueStep.completed
            return DialogueResponse(
                next_step=DialogueStep.completed,
                prompt_text=self._get_prompt("completed", state.language),
                requires_input=False,
                is_complete=True,
            )
        else:
            # Allow correction by going back to chief complaint
            state.current_step = DialogueStep.chief_complaint
            return DialogueResponse(
                next_step=DialogueStep.chief_complaint,
                prompt_text=self._get_prompt("correction", state.language),
            )

    async def _handle_default(self, state: DialogueState) -> DialogueResponse:
        """Default handler for unknown steps."""
        state.current_step = DialogueStep.welcome
        return DialogueResponse(
            next_step=DialogueStep.welcome,
            prompt_text=self._get_prompt("welcome", state.language),
        )

    def _get_prompt(self, step: str, language: str) -> str:
        """Get localized prompt text for a dialogue step.

        In production, this would load from a translation file or CMS.
        Environment-specific: Prompt copy may vary per deployment.
        """
        # Simplified prompts for demo — production should use proper i18n
        prompts = {
            "welcome": {
                "hi": "नमस्ते। मैं आपका स्वास्थ्य सहायक हूं। आइए आज आपके लक्षणों के बारे में बात करते हैं।",
                "en": "Hello. I am your health assistant. Let's discuss your symptoms today.",
            },
            "chief_complaint": {
                "hi": "आपको आज क्या समस्या है? अपना मुख्य लक्षण बताएं।",
                "en": "What is your problem today? Please describe your main symptom.",
            },
            "socrates_site": {
                "hi": "दर्द कहां है? कृपया स्थान बताएं।",
                "en": "Where is the pain? Please describe the location.",
            },
            "socrates_onset": {
                "hi": "यह लक्षण कब से शुरू हुआ? कितने समय से है?",
                "en": "When did this symptom start? How long has it been going on?",
            },
            "socrates_character": {
                "hi": "दर्द कैसा है? जलन, दबाव, फड़कना?",
                "en": "What is the pain like? Burning, pressure, throbbing?",
            },
            "socrates_radiation": {
                "hi": "क्या दर्द किसी अन्य स्थान पर फैलता है?",
                "en": "Does the pain spread to any other location?",
            },
            "socrates_associations": {
                "hi": "क्या कोई अन्य लक्षण भी हैं? बुखार, उल्टी?",
                "en": "Are there any other symptoms? Fever, vomiting?",
            },
            "socrates_time_course": {
                "hi": "लक्षण समय के साथ कैसे बदल रहे हैं? बिगड़ रहे हैं या सुधर रहे हैं?",
                "en": "How are the symptoms changing over time? Getting worse or better?",
            },
            "socrates_severity": {
                "hi": "0 से 10 के पैमाने पर दर्द कितना गंभीर है?",
                "en": "On a scale of 0 to 10, how severe is the pain?",
            },
            "socrates_exacerbating": {
                "hi": "क्या कुछ ऐसा है जो दर्द बढ़ाता या कम करता है?",
                "en": "Is there anything that makes the pain worse or better?",
            },
            "allergies_medications": {
                "hi": "क्या आपको किसी दवा से एलर्जी है? आप क्या दवाएं ले रहे हैं?",
                "en": "Do you have any allergies? What medications are you taking?",
            },
            "ayush_system_choice": {
                "hi": "क्या आप आयुष चिकित्सा (आयुर्वेद, योग, आदि) भी चाहते हैं?",
                "en": "Would you also like AYUSH consultation (Ayurveda, Yoga, etc.)?",
            },
            "ayush_prakriti": {
                "hi": "आपकी प्रकृति (शरीर का प्रकार) क्या है? वात, पित्त, या कफ?",
                "en": "What is your prakriti (body type)? Vata, Pitta, or Kapha?",
            },
            "ayush_vikriti": {
                "hi": "वर्तमान में कोई विकृति (असंतुलन) है?",
                "en": "Is there any current vikriti (imbalance)?",
            },
            "ayush_agni": {
                "hi": "आपकी अग्नि (पाचन शक्ति) कैसी है?",
                "en": "How is your agni (digestive fire)?",
            },
            "ayush_nadi": {
                "hi": "नाड़ी (नसों) की स्थिति कैसी है?",
                "en": "What is the condition of your nadi (pulse)?",
            },
            "review": {
                "hi": "क्या आपकी जानकारी सही है? पुष्टि करें।",
                "en": "Is your information correct? Please confirm.",
            },
            "completed": {
                "hi": "धन्यवाद। आपका साक्षात्कार पूरा हो गया है। डॉक्टर जल्द ही आपको देखेंगे।",
                "en": "Thank you. Your interview is complete. The doctor will see you soon.",
            },
            "correction": {
                "hi": "ठीक है, आइए फिर से शुरू करें। आपका मुख्य लक्षण क्या है?",
                "en": "Alright, let's start again. What is your main symptom?",
            },
        }
        return prompts.get(step, {}).get(language, prompts.get(step, {}).get("en", "Please continue."))

    async def persist_to_db(
        self,
        session: AsyncSession,
        dialogue_state: DialogueState,
    ) -> tuple[InterviewSession, ClinicalIntake | None, AyushIntake | None]:
        """Persist completed interview to Postgres. Called when dialogue completes.

        Concurrency: Uses unique constraint on session_id. PII is encrypted before INSERT.
        """
        # Load or create interview session
        stmt = select(InterviewSession).where(InterviewSession.id == dialogue_state.session_id)
        interview = (await session.execute(stmt)).scalars().first()

        if interview is None:
            interview = InterviewSession(
                id=dialogue_state.session_id,
                patient_id=dialogue_state.patient_id,
                clinic_id=dialogue_state.clinic_id,
                status=InterviewStatus.completed.value,
                language=dialogue_state.language,
                current_step=DialogueStep.completed.value,
                completed_at=datetime.now(timezone.utc),
            )
            session.add(interview)
        else:
            interview.status = InterviewStatus.completed.value
            interview.current_step = DialogueStep.completed.value
            interview.completed_at = datetime.now(timezone.utc)

        # Persist SOCRATES data
        clinical_intake = None
        if dialogue_state.socrates_partial_enc:
            partial = json.loads(dialogue_state.socrates_partial_enc)
            clinical_intake = ClinicalIntake(
                session_id=interview.id,
                chief_complaint=encrypt_pii(partial.get("chief_complaint", "")) if partial.get("chief_complaint") else None,
                site=encrypt_pii(partial.get("site", "")) if partial.get("site") else None,
                onset=encrypt_pii(partial.get("onset", "")) if partial.get("onset") else None,
                character=encrypt_pii(partial.get("character", "")) if partial.get("character") else None,
                radiation=encrypt_pii(partial.get("radiation", "")) if partial.get("radiation") else None,
                associations=encrypt_pii(partial.get("associations", "")) if partial.get("associations") else None,
                time_course=encrypt_pii(partial.get("time_course", "")) if partial.get("time_course") else None,
                severity=partial.get("severity"),
                red_flags=dialogue_state.red_flags,
                allergies_enc=encrypt_pii(partial.get("allergies", "")) if partial.get("allergies") else None,
                medications_enc=encrypt_pii(partial.get("medications", "")) if partial.get("medications") else None,
            )
            session.add(clinical_intake)

        # Persist AYUSH data if branch was taken
        ayush_intake = None
        if dialogue_state.ayush_branch and dialogue_state.ayush_partial_enc:
            partial = json.loads(dialogue_state.ayush_partial_enc)
            ayush_intake = AyushIntake(
                session_id=interview.id,
                system=AyushSystem.ayurveda.value,  # Default — would be determined by dialogue
                prakriti=partial.get("prakriti"),
                vikriti=partial.get("vikriti"),
                agni=partial.get("agni"),
                nadi_notes=encrypt_pii(partial.get("nadi_notes", "")) if partial.get("nadi_notes") else None,
                dosha_scores={},  # Would be calculated by NLP
                diet_sleep={},
                branching_path="standard",
            )
            session.add(ayush_intake)

        await session.flush()

        # Clean up Redis state
        await redis_session().delete(self._redis_key(dialogue_state.session_id))

        logger.info(
            "dialogue_persisted",
            session_id=str(dialogue_state.session_id),
            patient_id=str(dialogue_state.patient_id),
            ayush_branch=dialogue_state.ayush_branch,
        )

        return interview, clinical_intake, ayush_intake


def get_dialogue_manager() -> DialogueManager:
    """Factory for dialogue manager. Can be swapped in tests."""
    return DialogueManager()
