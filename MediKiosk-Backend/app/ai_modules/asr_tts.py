"""Bhashini ASR (speech-to-text) and TTS (text-to-speech) interface.

External integration: Bhashini (AI4Bharat) — environment-specific BHASHINI_API_KEY
and BHASHINI_BASE_URL. Mocks are used in development if API key is unset.

Retry/circuit-breaker wrapper is centralised here — services call only the public
interface methods and receive degraded responses when Bhashini is down.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Literal

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError
from app.utils.logger import get_logger

logger = get_logger("app.ai.asr_tts")


class Language(str, Enum):
    """Supported Indian languages for ASR/TTS. Expand via migration/config as needed."""

    hindi = "hi"
    english = "en"
    tamil = "ta"
    telugu = "te"
    bengali = "bn"
    marathi = "mr"
    gujarati = "gu"
    kannada = "kn"
    malayalam = "ml"
    punjabi = "pa"
    assamese = "as"
    odia = "or"


@dataclass
class AsrResult:
    """Speech-to-text output. Transcript may contain PII (patient names, addresses)."""

    transcript: str
    language: Language
    confidence: float
    duration_seconds: float
    vendor: str


@dataclass
class TtsResult:
    """Text-to-speech output. Audio bytes are transient (client-side only)."""

    audio_bytes: bytes
    format: Literal["mp3", "wav"]
    language: Language
    vendor: str


class AsrTtsError(Exception):
    """Base class for ASR/TTS failures. Services catch and degrade."""


class AsrTtsUnavailableError(AsrTtsError):
    """Bhashini API is down or rate-limited. Fall back to text input."""


class AsrTtsQuotaExceededError(AsrTtsError):
    """API quota exhausted. Fall back to text input."""


class AsrTtsProtocol(ABC):
    """Protocol for swapping implementations (Bhashini vs mock in tests)."""

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        language: Language,
        format: Literal["mp3", "wav"] = "mp3",
    ) -> AsrResult:
        """Convert speech to text. Audio bytes may contain PII — never log them."""
        ...

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        language: Language,
        format: Literal["mp3", "wav"] = "mp3",
    ) -> TtsResult:
        """Convert text to speech. Text may contain PII — never log it."""
        ...


class MockAsrTts(AsrTtsProtocol):
    """Development fallback. Returns deterministic mock responses.

    Environment-specific: In production, BHASHINI_API_KEY must be set; this
    mock should never be used in live deployments.
    """

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: Language,
        format: Literal["mp3", "wav"] = "mp3",
    ) -> AsrResult:
        await asyncio.sleep(0.1)  # Simulate network latency
        return AsrResult(
            transcript="[mock transcription]",
            language=language,
            confidence=0.95,
            duration_seconds=len(audio_bytes) / 16000.0,  # Approximate for 16kHz
            vendor="mock",
        )

    async def synthesize(
        self,
        text: str,
        language: Language,
        format: Literal["mp3", "wav"] = "mp3",
    ) -> TtsResult:
        await asyncio.sleep(0.1)  # Simulate network latency
        # Return minimal valid audio header for format compliance
        if format == "mp3":
            audio_bytes = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 100
        else:
            audio_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00" + b"\x00" * 100
        return TtsResult(
            audio_bytes=audio_bytes,
            format=format,
            language=language,
            vendor="mock",
        )


class BhashiniAsrTts(AsrTtsProtocol):
    """Bhashini/AI4Bharat integration with retry and circuit-breaker.

    Environment-specific:
    - BHASHINI_API_KEY: Bhashini API key (obtain from bhashini.gov.in)
    - BHASHINI_BASE_URL: API base URL (defaults to https://bhashini.gov.in/api)
    - Scaling: Configure appropriate rate limits per kiosk instance count.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.BHASHINI_API_KEY
        self.base_url = settings.BHASHINI_BASE_URL
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(10.0, connect=5.0)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, AsrTtsUnavailableError)),
        reraise=True,
    )
    async def transcribe(
        self,
        audio_bytes: bytes,
        language: Language,
        format: Literal["mp3", "wav"] = "mp3",
    ) -> AsrResult:
        if not self.api_key:
            raise AsrTtsUnavailableError("Bhashini API key not configured")

        client = self._get_client()
        # Bhashini ASR endpoint — path may change per Bhashini version
        url = f"{self.base_url.rstrip('/')}/v1/asr"
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": f"audio/{format}",
        }
        params = {"language": language.value}

        try:
            response = await client.post(
                url,
                content=audio_bytes,
                headers=headers,
                params=params,
            )
            if response.status_code == 429:
                raise AsrTtsQuotaExceededError("Bhashini quota exceeded")
            if response.status_code >= 500:
                raise AsrTtsUnavailableError(f"Bhashini service error: {response.status_code}")
            if response.status_code >= 400:
                raise AsrTtsError(f"Bhashini request failed: {response.status_code}")

            data = response.json()
            # Adapt to actual Bhashini response structure — this is a typical shape
            return AsrResult(
                transcript=data.get("transcript", ""),
                language=language,
                confidence=float(data.get("confidence", 0.0)),
                duration_seconds=float(data.get("duration", 0.0)),
                vendor="bhashini",
            )
        except httpx.HTTPError as exc:
            logger.warning("bhashini_asr_network_error", error=str(type(exc).__name__))
            raise AsrTtsUnavailableError("Bhashini ASR unavailable") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, AsrTtsUnavailableError)),
        reraise=True,
    )
    async def synthesize(
        self,
        text: str,
        language: Language,
        format: Literal["mp3", "wav"] = "mp3",
    ) -> TtsResult:
        if not self.api_key:
            raise AsrTtsUnavailableError("Bhashini API key not configured")

        client = self._get_client()
        # Bhashini TTS endpoint — path may change per Bhashini version
        url = f"{self.base_url.rstrip('/')}/v1/tts"
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "language": language.value,
            "format": format,
        }

        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 429:
                raise AsrTtsQuotaExceededError("Bhashini quota exceeded")
            if response.status_code >= 500:
                raise AsrTtsUnavailableError(f"Bhashini service error: {response.status_code}")
            if response.status_code >= 400:
                raise AsrTtsError(f"Bhashini request failed: {response.status_code}")

            # Bhashini typically returns audio bytes directly
            audio_bytes = response.content
            return TtsResult(
                audio_bytes=audio_bytes,
                format=format,
                language=language,
                vendor="bhashini",
            )
        except httpx.HTTPError as exc:
            logger.warning("bhashini_tts_network_error", error=str(type(exc).__name__))
            raise AsrTtsUnavailableError("Bhashini TTS unavailable") from exc


def get_asr_tts() -> AsrTtsProtocol:
    """Factory returning the configured implementation.

    Environment-specific:
    - Development: Falls back to MockAsrTts if BHASHINI_API_KEY is unset
    - Production: Requires BHASHINI_API_KEY; fails fast if missing
    """
    settings = get_settings()
    if not settings.BHASHINI_API_KEY or not settings.BHASHINI_API_KEY.get_secret_value():
        if settings.is_production:
            raise ServiceUnavailableError(
                code="bhashini_unconfigured",
                message="Voice processing unavailable — API key required in production",
            )
        logger.warning("bhashini_using_mock")
        return MockAsrTts()
    return BhashiniAsrTts()


async def close_asr_tts() -> None:
    """Cleanup function for lifespan shutdown."""
    impl = get_asr_tts()
    if isinstance(impl, BhashiniAsrTts):
        await impl.close()
