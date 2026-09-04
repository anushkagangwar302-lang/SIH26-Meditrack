"""Test interview dialogue flow and SOCRATES/AYUSH branching logic.

Tests the complete interview flow from welcome to completion, including:
- Dialogue state progression through SOCRATES steps
- AYUSH branching logic
- Red-flag detection integration
- Redis state management
- Database persistence
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.clinical import InterviewSession, InterviewStatus
from app.models.consent import Consent, ConsentPurpose, ConsentStatus
from app.models.user import Patient, User
from app.services.dialogue_manager import (
    DialogueManager,
    DialogueResponse,
    DialogueStep,
    DialogueState,
)
from app.services.triage_service import TriageService


@pytest.fixture
def mock_asr_tts():
    """Mock ASR/TTS service."""
    service = AsyncMock()
    service.transcribe.return_value = MagicMock(
        transcript="mock transcription",
        language="hi",
        confidence=0.95,
        duration_seconds=5.0,
        vendor="mock",
    )
    service.synthesize.return_value = MagicMock(
        audio_bytes=b"mock audio",
        format="mp3",
        language="hi",
        vendor="mock",
    )
    return service


@pytest.fixture
def mock_clinical_nlp():
    """Mock clinical NLP service."""
    service = AsyncMock()
    service.structure_socrates.return_value = MagicMock(
        chief_complaint="headache",
        site="head",
        onset="2 days ago",
        character="throbbing",
        radiation=None,
        associations=None,
        time_course="worse in morning",
        severity=7,
        red_flags=[],
        confidence=0.8,
    )
    service.detect_red_flags.return_value = []
    service.analyze_ayush.return_value = MagicMock(
        prakriti="vata",
        vikriti=None,
        agni="mandagni",
        nadi_notes="pulse irregular",
        dosha_scores={},
        branching_path="standard",
        confidence=0.7,
    )
    service.extract_entities.return_value = MagicMock(
        medications=["paracetamol"],
        allergies=["none"],
        conditions=["headache"],
        confidence=0.6,
    )
    return service


@pytest.fixture
def dialogue_manager(mock_asr_tts, mock_clinical_nlp):
    """Create dialogue manager with mocked services."""
    return DialogueManager(
        asr_tts=mock_asr_tts,
        clinical_nlp=mock_clinical_nlp,
    )


@pytest.fixture
def sample_patient_id():
    """Sample patient UUID."""
    return uuid.uuid4()


@pytest.fixture
def sample_clinic_id():
    """Sample clinic UUID."""
    return uuid.uuid4()


@pytest.mark.asyncio
async def test_start_session(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test starting a new interview session."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )

    assert state.session_id is not None
    assert state.patient_id == sample_patient_id
    assert state.clinic_id == sample_clinic_id
    assert state.language == "hi"
    assert state.current_step == DialogueStep.welcome
    assert state.ayush_branch is False
    assert len(state.red_flags) == 0


@pytest.mark.asyncio
async def test_welcome_step(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test welcome step progression."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )

    turn_input = MagicMock(
        session_id=state.session_id,
        utterance="yes",
        step="welcome",
    )

    response = await dialogue_manager.process_turn(turn_input)

    assert response.next_step == DialogueStep.chief_complaint
    assert response.requires_input is True
    assert response.is_complete is False


@pytest.mark.asyncio
async def test_chief_complaint_step(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test chief complaint step with NLP integration."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )
    state.current_step = DialogueStep.chief_complaint

    turn_input = MagicMock(
        session_id=state.session_id,
        utterance="I have a severe headache",
        step="chief_complaint",
    )

    response = await dialogue_manager.process_turn(turn_input)

    assert response.next_step == DialogueStep.socrates_site
    assert response.socrates_update is not None
    assert response.socrates_update.chief_complaint is not None


@pytest.mark.asyncio
async def test_socrates_progression(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test progression through SOCRATES steps."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )

    # Progress through SOCRATES steps
    socrates_steps = [
        DialogueStep.chief_complaint,
        DialogueStep.socrates_site,
        DialogueStep.socrates_onset,
        DialogueStep.socrates_character,
        DialogueStep.socrates_radiation,
        DialogueStep.socrates_associations,
        DialogueStep.socrates_time_course,
        DialogueStep.socrates_severity,
        DialogueStep.socrates_exacerbating,
    ]

    for step in socrates_steps:
        state.current_step = step
        turn_input = MagicMock(
            session_id=state.session_id,
            utterance="mock response",
            step=step.value,
        )
        response = await dialogue_manager.process_turn(turn_input)
        assert response.requires_input is True
        assert response.is_complete is False


@pytest.mark.asyncio
async def test_ayush_branch_yes(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test AYUSH branch when patient chooses AYUSH."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )
    state.current_step = DialogueStep.ayush_system_choice

    turn_input = MagicMock(
        session_id=state.session_id,
        utterance="yes",
        step="ayush_system_choice",
    )

    response = await dialogue_manager.process_turn(turn_input)

    assert response.next_step == DialogueStep.ayush_prakriti
    assert state.ayush_branch is True


@pytest.mark.asyncio
async def test_ayush_branch_no(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test skipping AYUSH branch."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )
    state.current_step = DialogueStep.ayush_system_choice

    turn_input = MagicMock(
        session_id=state.session_id,
        utterance="no",
        step="ayush_system_choice",
    )

    response = await dialogue_manager.process_turn(turn_input)

    assert response.next_step == DialogueStep.review
    assert state.ayush_branch is False


@pytest.mark.asyncio
async def test_review_confirmation(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test review step with confirmation."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )
    state.current_step = DialogueStep.review

    turn_input = MagicMock(
        session_id=state.session_id,
        utterance="yes",
        step="review",
    )

    response = await dialogue_manager.process_turn(turn_input)

    assert response.next_step == DialogueStep.completed
    assert response.requires_input is False
    assert response.is_complete is True


@pytest.mark.asyncio
async def test_review_correction(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test review step with correction (goes back to chief complaint)."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )
    state.current_step = DialogueStep.review

    turn_input = MagicMock(
        session_id=state.session_id,
        utterance="no",
        step="review",
    )

    response = await dialogue_manager.process_turn(turn_input)

    assert response.next_step == DialogueStep.chief_complaint
    assert response.requires_input is True
    assert response.is_complete is False


@pytest.mark.asyncio
async def test_audio_input(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test audio input with ASR processing."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )
    state.current_step = DialogueStep.chief_complaint

    audio_bytes = b"mock audio data"
    turn_input = MagicMock(
        session_id=state.session_id,
        utterance="",  # Will be filled by ASR
        step="chief_complaint",
    )

    response = await dialogue_manager.process_turn(turn_input, audio_bytes=audio_bytes)

    assert response.next_step == DialogueStep.socrates_site
    assert state.last_asr_result is not None
    assert state.last_asr_result["vendor"] == "mock"


@pytest.mark.asyncio
async def test_red_flag_detection(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test red-flag detection during chief complaint."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )
    state.current_step = DialogueStep.chief_complaint

    # Mock NLP to return red flags
    dialogue_manager.clinical_nlp.detect_red_flags.return_value = [
        MagicMock(value="chest_pain"),
        MagicMock(value="shortness_of_breath"),
    ]

    turn_input = MagicMock(
        session_id=state.session_id,
        utterance="chest pain and difficulty breathing",
        step="chief_complaint",
    )

    response = await dialogue_manager.process_turn(turn_input)

    assert len(response.detected_red_flags) > 0
    assert len(state.red_flags) > 0


@pytest.mark.asyncio
async def test_multilingual_prompts(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test prompt generation for different languages."""
    languages = ["hi", "en", "ta"]

    for language in languages:
        state = await dialogue_manager.start_session(
            patient_id=sample_patient_id,
            clinic_id=sample_clinic_id,
            language=language,
        )

        prompt = dialogue_manager._get_prompt("welcome", language)
        assert prompt is not None
        assert len(prompt) > 0


@pytest.mark.asyncio
async def test_localized_error_handling(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test error handling with localized responses."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )

    # Mock NLP failure
    dialogue_manager.clinical_nlp.structure_socrates.side_effect = Exception("NLP error")

    turn_input = MagicMock(
        session_id=state.session_id,
        utterance="headache",
        step="chief_complaint",
    )

    response = await dialogue_manager.process_turn(turn_input)

    # Should still progress despite NLP failure
    assert response.next_step == DialogueStep.socrates_site


@pytest.mark.asyncio
async def test_concurrent_dialogue_states(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test that concurrent dialogue sessions don't interfere with each other."""
    # Start multiple sessions
    session_1 = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )

    session_2 = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="en",
    )

    # Verify they have different session IDs
    assert session_1.session_id != session_2.session_id

    # Verify they have different states
    assert session_1.language == "hi"
    assert session_2.language == "en"

    # Progress each independently
    session_1.current_step = DialogueStep.chief_complaint
    session_2.current_step = DialogueStep.socrates_site

    turn_1 = MagicMock(session_id=session_1.session_id, utterance="headache", step="chief_complaint")
    turn_2 = MagicMock(session_id=session_2.session_id, utterance="yes", step="socrates_site")

    response_1 = await dialogue_manager.process_turn(turn_1)
    response_2 = await dialogue_manager.process_turn(turn_2)

    # Verify independent progression
    assert response_1.next_step == DialogueStep.socrates_site
    assert response_2.next_step == DialogueStep.socrates_onset


@pytest.mark.asyncio
async def test_dialogue_state_serialization(dialogue_manager, sample_patient_id, sample_clinic_id):
    """Test that dialogue state can be serialized and deserialized."""
    state = await dialogue_manager.start_session(
        patient_id=sample_patient_id,
        clinic_id=sample_clinic_id,
        language="hi",
    )

    # Add some data
    state.socrates_partial_enc = "encrypted_data"
    state.ayush_branch = True
    state.red_flags = ["chest_pain"]

    # Save and reload
    await dialogue_manager._save_state(state)
    reloaded_state = await dialogue_manager._load_state(state.session_id)

    assert reloaded_state.session_id == state.session_id
    assert reloaded_state.patient_id == state.patient_id
    assert reloaded_state.ayush_branch == state.ayush_branch
    assert reloaded_state.red_flags == state.red_flags
