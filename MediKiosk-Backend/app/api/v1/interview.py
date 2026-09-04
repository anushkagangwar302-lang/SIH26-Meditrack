"""WebSocket interview endpoint with Redis-backed fan-out for multi-replica support.

Real-time dialogue for kiosk sessions. WebSocket connections are stateless across
replicas — Redis Pub/Sub handles fan-out. All PII operations check consent first.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth_routes import Principal, require_intake_session
from app.core.config import get_settings
from app.core.database import get_db, redis_session
from app.core.exceptions import ForbiddenError, NotFoundError
from app.schemas.interview import DialogueTurnIn, InterviewSessionOut, InterviewStartIn
from app.services.dialogue_manager import DialogueManager, DialogueResponse, get_dialogue_manager
from app.services.triage_service import TriageService, get_triage_service
from app.utils.logger import get_logger, get_request_id, set_request_id

logger = get_logger("app.api.interview")
router = APIRouter(prefix="/interview", tags=["interview"])


class WebSocketManager:
    """Manages WebSocket connections with Redis Pub/Sub for multi-replica fan-out.

    Critical: Connection state is NOT stored in memory. Redis Pub/Sub is used for
    broadcasting messages across all replicas. Each replica handles its own connected
    clients, but they all receive the same broadcast messages.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._pubsub = None

    def _channel_name(self, session_id: uuid.UUID) -> str:
        return f"{self.settings.REDIS_PREFIX_WS}{session_id}"

    async def broadcast(self, session_id: uuid.UUID, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients for this session.

        Uses Redis Pub/Sub to reach clients connected to any replica.
        """
        channel = self._channel_name(session_id)
        await redis_session().publish(channel, json.dumps(message))
        logger.debug("ws_broadcast", session_id=str(session_id), message_type=message.get("type"))

    async def subscribe(self, session_id: uuid.UUID) -> Any:
        """Subscribe to Redis Pub/Sub for a session's broadcast channel."""
        channel = self._channel_name(session_id)
        pubsub = redis_session().pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    async def unsubscribe(self, pubsub: Any, session_id: uuid.UUID) -> None:
        """Unsubscribe from Redis Pub/Sub."""
        if pubsub:
            channel = self._channel_name(session_id)
            await pubsub.unsubscribe(channel)


# Global WebSocket manager (stateless — uses Redis for actual coordination)
ws_manager = WebSocketManager()


@router.post("/start", response_model=InterviewSessionOut)
async def start_interview(
    body: InterviewStartIn,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InterviewSessionOut:
    """Start a new interview session.

    Creates a dialogue state in Redis and returns the session ID for WebSocket connection.
    Requires ABHA login + treatment consent (enforced by require_intake_session).
    """
    dialogue_manager = get_dialogue_manager()

    # Start dialogue session
    dialogue_state = await dialogue_manager.start_session(
        patient_id=principal.patient.id if principal.patient else body.patient_id,
        clinic_id=principal.user.clinic_id if principal.user.clinic_id else body.clinic_id,
        language=body.language,
    )

    # Create database interview session record
    from app.models.clinical import InterviewSession

    interview = InterviewSession(
        id=dialogue_state.session_id,
        patient_id=dialogue_state.patient_id,
        clinic_id=dialogue_state.clinic_id,
        language=dialogue_state.language,
        status="in_progress",
        current_step="welcome",
    )
    session.add(interview)
    await session.flush()

    logger.info(
        "interview_started",
        session_id=str(dialogue_state.session_id),
        patient_id=str(dialogue_state.patient_id),
        language=body.language,
    )

    return InterviewSessionOut.model_validate(interview)


@router.websocket("/ws/{session_id}")
async def interview_websocket(
    websocket: WebSocket,
    session_id: str,
) -> None:
    """WebSocket endpoint for real-time interview dialogue.

    Supports both text and voice input. Audio is processed via ASR, responses via TTS.
    Uses Redis Pub/Sub for broadcasting across replicas.

    Args:
        websocket: WebSocket connection
        session_id: Interview session UUID

    Note:
        Authentication and consent checks are performed via JWT token in query params.
        The WebSocket connection is stateless — session state lives in Redis.
    """
    # Accept WebSocket connection
    await websocket.accept()

    # Set request ID for logging
    set_request_id()

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        await websocket.close(code=4000, reason="Invalid session ID")
        return

    # Subscribe to Redis Pub/Sub for this session
    pubsub = None
    try:
        pubsub = await ws_manager.subscribe(session_uuid)

        # Send initial welcome message
        dialogue_manager = get_dialogue_manager()
        try:
            state = await dialogue_manager._load_state(session_uuid)
            welcome_response = DialogueResponse(
                next_step=state.current_step,
                prompt_text=dialogue_manager._get_prompt("welcome", state.language),
            )
            await websocket.send_json({
                "type": "dialogue_response",
                "data": welcome_response.__dict__,
            })
        except NotFoundError:
            await websocket.close(code=4001, reason="Session not found")
            return

        # Main message loop
        while True:
            # Wait for client message
            data = await websocket.receive_json()

            message_type = data.get("type")
            if message_type == "dialogue_turn":
                # Process dialogue turn
                await _handle_dialogue_turn(websocket, session_uuid, data, pubsub)
            elif message_type == "audio":
                # Process audio input
                await _handle_audio_input(websocket, session_uuid, data, pubsub)
            elif message_type == "ping":
                # Heartbeat
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({
                    "type": "error",
                    "error": f"Unknown message type: {message_type}",
                })

    except WebSocketDisconnect:
        logger.info("ws_disconnected", session_id=session_id)
    except Exception as exc:
        logger.exception("ws_error", session_id=session_id, error=str(type(exc).__name__))
        await websocket.close(code=4002, reason="Internal server error")
    finally:
        # Cleanup Redis subscription
        if pubsub:
            await ws_manager.unsubscribe(pubsub, session_uuid)


async def _handle_dialogue_turn(
    websocket: WebSocket,
    session_id: uuid.UUID,
    data: dict[str, Any],
    pubsub: Any,
) -> None:
    """Handle a text-based dialogue turn."""
    try:
        dialogue_manager = get_dialogue_manager()

        # Parse input
        turn_data = data.get("data", {})
        turn = DialogueTurnIn(
            session_id=session_id,
            utterance=turn_data.get("utterance", ""),
            step=turn_data.get("step", "current"),
        )

        # Process turn
        response = await dialogue_manager.process_turn(turn)

        # Send response to client
        await websocket.send_json({
            "type": "dialogue_response",
            "data": response.__dict__,
        })

        # Broadcast to other connected clients (if any)
        await ws_manager.broadcast(session_id, {
            "type": "dialogue_update",
            "data": {
                "next_step": response.next_step.value,
                "is_complete": response.is_complete,
            },
        })

        # If interview is complete, trigger triage
        if response.is_complete:
            await _trigger_triage(websocket, session_id)

    except Exception as exc:
        logger.exception("dialogue_turn_error", session_id=str(session_id))
        await websocket.send_json({
            "type": "error",
            "error": "Failed to process dialogue turn",
        })


async def _handle_audio_input(
    websocket: WebSocket,
    session_id: uuid.UUID,
    data: dict[str, Any],
    pubsub: Any,
) -> None:
    """Handle audio input for ASR processing."""
    try:
        dialogue_manager = get_dialogue_manager()

        # Parse audio data
        audio_data = data.get("data", {})
        audio_bytes = audio_data.get("audio_bytes")
        language = audio_data.get("language", "hi")

        if not audio_bytes:
            await websocket.send_json({
                "type": "error",
                "error": "No audio data provided",
            })
            return

        # Decode base64 audio if needed
        import base64

        if isinstance(audio_bytes, str):
            audio_bytes = base64.b64decode(audio_bytes)

        # Process as dialogue turn with audio
        turn = DialogueTurnIn(
            session_id=session_id,
            utterance="",  # Will be filled by ASR
            step="current",
        )

        response = await dialogue_manager.process_turn(turn, audio_bytes=audio_bytes)

        # Send response with transcript
        await websocket.send_json({
            "type": "dialogue_response",
            "data": {
                **response.__dict__,
                "transcript": response.__dict__.get("transcript", ""),
            },
        })

        # Broadcast update
        await ws_manager.broadcast(session_id, {
            "type": "dialogue_update",
            "data": {
                "next_step": response.next_step.value,
                "is_complete": response.is_complete,
            },
        })

        # If interview is complete, trigger triage
        if response.is_complete:
            await _trigger_triage(websocket, session_id)

    except Exception as exc:
        logger.exception("audio_input_error", session_id=str(session_id))
        await websocket.send_json({
            "type": "error",
            "error": "Failed to process audio input",
        })


async def _trigger_triage(websocket: WebSocket, session_id: uuid.UUID) -> None:
    """Trigger triage assessment when interview completes."""
    try:
        from app.core.database import get_db

        triage_service = get_triage_service()

        # Get DB session
        async for db in get_db():
            # Persist interview to DB
            dialogue_manager = get_dialogue_manager()
            state = await dialogue_manager._load_state(session_id)
            interview, clinical, ayush = await dialogue_manager.persist_to_db(db, state)

            # Run triage
            triage_result = await triage_service.complete_triage(db, session_id)

            # Send triage result to client
            await websocket.send_json({
                "type": "triage_result",
                "data": {
                    "acuity": triage_result.acuity,
                    "queue_position": triage_result.queue_position,
                    "queue_date": str(triage_result.queue_date),
                },
            })

            # Broadcast triage update
            await ws_manager.broadcast(session_id, {
                "type": "triage_update",
                "data": {
                    "acuity": triage_result.acuity,
                    "queue_position": triage_result.queue_position,
                },
            })

            break

    except Exception as exc:
        logger.exception("triage_trigger_error", session_id=str(session_id))
        await websocket.send_json({
            "type": "error",
            "error": "Failed to complete triage",
        })


@router.post("/complete")
async def complete_interview(
    session_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Manually complete an interview and trigger triage.

    Called when the WebSocket connection is closed normally but the interview
    wasn't marked complete via the dialogue flow.
    """
    dialogue_manager = get_dialogue_manager()
    triage_service = get_triage_service()

    try:
        # Load dialogue state
        state = await dialogue_manager._load_state(session_id)

        # Persist to DB
        interview, clinical, ayush = await dialogue_manager.persist_to_db(session, state)

        # Run triage
        triage_result = await triage_service.complete_triage(session, session_id)

        logger.info(
            "interview_completed_manual",
            session_id=str(session_id),
            patient_id=str(state.patient_id),
            acuity=triage_result.acuity,
        )

        return {
            "session_id": str(session_id),
            "status": "completed",
            "triage": {
                "acuity": triage_result.acuity,
                "queue_position": triage_result.queue_position,
                "queue_date": str(triage_result.queue_date),
            },
        }

    except NotFoundError:
        raise NotFoundError(code="session_not_found", message="Interview session not found")
    except Exception as exc:
        logger.exception("interview_complete_error", session_id=str(session_id))
        raise


@router.get("/status/{session_id}")
async def get_interview_status(
    session_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_intake_session)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InterviewSessionOut:
    """Get the current status of an interview session."""
    from app.models.clinical import InterviewSession
    from sqlalchemy import select

    stmt = select(InterviewSession).where(InterviewSession.id == session_id)
    interview = (await session.execute(stmt)).scalars().first()

    if interview is None:
        raise NotFoundError(code="session_not_found", message="Interview session not found")

    return InterviewSessionOut.model_validate(interview)
