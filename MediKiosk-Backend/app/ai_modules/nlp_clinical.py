"""Clinical NLP for SOCRATES structuring, red-flag detection, and AYUSH analysis.

External integration: Can be swapped for any clinical NLP service (e.g., medicalNER,
domain-specific LLM). Environment-specific API key if using external vendor.
Retry/circuit-breaker wrapper is centralised here.

All text inputs may contain PII (patient names, addresses) — never log them.
"""

from __future__ import annotations

import asyncio
import re
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

logger = get_logger("app.ai.nlp_clinical")


class RedFlag(str, Enum):
    """Clinical red flags that trigger urgent triage."""

    chest_pain = "chest_pain"
    shortness_of_breath = "shortness_of_breath"
    severe_abdominal_pain = "severe_abdominal_pain"
    neurological_deficit = "neurological_deficit"
    high_fever = "high_fever"
    severe_headache = "severe_headache"
    uncontrolled_bleeding = "uncontrolled_bleeding"
    loss_of_consciousness = "loss_of_consciousness"
    suicidal_ideation = "suicidal_ideation"
    severe_allergic_reaction = "severe_allergic_reaction"


@dataclass
class SocratesStructure:
    """Structured SOCRATES output from clinical text."""

    chief_complaint: str | None
    site: str | None
    onset: str | None
    character: str | None
    radiation: str | None
    associations: str | None
    time_course: str | None
    exacerbating_relieving: str | None
    severity: int | None  # 0-10 scale
    red_flags: list[RedFlag]
    confidence: float


@dataclass
class AyushAnalysis:
    """AYUSH-specific clinical analysis."""

    prakriti: str | None
    vikriti: str | None
    agni: str | None
    dosha_scores: dict[str, float]
    nadi_notes: str | None
    branching_path: str | None
    confidence: float


@dataclass
class EntityExtraction:
    """Extracted clinical entities (medications, allergies, conditions)."""

    medications: list[str]
    allergies: list[str]
    conditions: list[str]
    confidence: float


class NlpError(Exception):
    """Base class for NLP failures. Services catch and degrade."""


class NlpUnavailableError(NlpError):
    """NLP service is down or rate-limited. Fall back to rule-based processing."""


class NlpQuotaExceededError(NlpError):
    """API quota exhausted. Fall back to rule-based processing."""


class ClinicalNlpProtocol(ABC):
    """Protocol for swapping implementations (external vendor vs mock in tests)."""

    @abstractmethod
    async def structure_socrates(self, text: str, language: str = "en") -> SocratesStructure:
        """Extract SOCRATES components from clinical narrative.

        Text may contain PII — never log it. Language defaults to English,
        but Indian languages (hi, ta, te, etc.) should be supported in production.
        """
        ...

    @abstractmethod
    async def detect_red_flags(self, text: str, language: str = "en") -> list[RedFlag]:
        """Identify red-flag phrases that indicate urgent care is needed.

        Text may contain PII — never log it.
        """
        ...

    @abstractmethod
    async def analyze_ayush(self, text: str, system: str, language: str = "en") -> AyushAnalysis:
        """Extract AYUSH-specific clinical observations.

        Text may contain PII — never log it. System is one of ayurveda, yoga,
        unani, siddha, sowa_rigpa, homeopathy.
        """
        ...

    @abstractmethod
    async def extract_entities(self, text: str, language: str = "en") -> EntityExtraction:
        """Extract medications, allergies, and conditions from clinical text.

        Text may contain PII — never log it.
        """
        ...


class MockClinicalNlp(ClinicalNlpProtocol):
    """Development fallback with rule-based red-flag detection.

    Environment-specific: In production, configure an actual NLP service;
    this mock should never be used in live deployments.
    """

    # Simple keyword-based red-flag detection for development
    _RED_FLAG_PATTERNS = {
        RedFlag.chest_pain: [r"chest pain", r"heart pain", r"cardiac"],
        RedFlag.shortness_of_breath: [r"breathless", r"shortness of breath", r"difficulty breathing"],
        RedFlag.severe_abdominal_pain: [r"severe stomach pain", r"acute abdomen", r"rupture"],
        RedFlag.neurological_deficit: [r"stroke", r"paralysis", r"numbness", r"weakness", r"slurring"],
        RedFlag.high_fever: [r"high fever", r"very high temperature", r"fever.*104"],
        RedFlag.severe_headache: [r"worst headache", r"thunderclap", r"severe headache"],
        RedFlag.uncontrolled_bleeding: [r"uncontrolled bleeding", r"hemorrhage", r"heavy bleeding"],
        RedFlag.loss_of_consciousness: [r"fainted", r"unconscious", r"passed out", r"blackout"],
        RedFlag.suicidal_ideation: [r"suicidal", r"kill myself", r"end my life"],
        RedFlag.severe_allergic_reaction: [r"anaphylaxis", r"swelling.*throat", r"difficulty breathing.*allergy"],
    }

    async def structure_socrates(self, text: str, language: str = "en") -> SocratesStructure:
        await asyncio.sleep(0.05)  # Simulate processing
        # Mock: return input as chief complaint, minimal structure
        return SocratesStructure(
            chief_complaint=text[:200] if text else None,
            site=None,
            onset=None,
            character=None,
            radiation=None,
            associations=None,
            time_course=None,
            exacerbating_relieving=None,
            severity=None,
            red_flags=[],
            confidence=0.5,
        )

    async def detect_red_flags(self, text: str, language: str = "en") -> list[RedFlag]:
        await asyncio.sleep(0.02)  # Simulate processing
        text_lower = text.lower()
        detected = []
        for flag, patterns in self._RED_FLAG_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    detected.append(flag)
                    break
        return detected

    async def analyze_ayush(self, text: str, system: str, language: str = "en") -> AyushAnalysis:
        await asyncio.sleep(0.05)  # Simulate processing
        return AyushAnalysis(
            prakriti=None,
            vikriti=None,
            agni=None,
            dosha_scores={},
            nadi_notes=None,
            branching_path=None,
            confidence=0.3,
        )

    async def extract_entities(self, text: str, language: str = "en") -> EntityExtraction:
        await asyncio.sleep(0.03)  # Simulate processing
        # Mock: simple keyword-based extraction
        text_lower = text.lower()
        medications = []
        allergies = []
        conditions = []

        # Very basic medication keywords (production should use proper NER)
        med_keywords = ["paracetamol", "metformin", "amlodipine", "insulin", "aspirin"]
        for med in med_keywords:
            if med in text_lower:
                medications.append(med)

        # Basic allergy keywords
        allergy_keywords = ["allergic", "allergy", "rash", "swelling", "itching"]
        for keyword in allergy_keywords:
            if keyword in text_lower:
                allergies.append(keyword)

        return EntityExtraction(
            medications=medications,
            allergies=allergies,
            conditions=conditions,
            confidence=0.4,
        )


class ExternalClinicalNlp(ClinicalNlpProtocol):
    """External clinical NLP service integration with retry and circuit-breaker.

    Environment-specific:
    - NLP_API_KEY: API key for the clinical NLP service (vendor-specific)
    - NLP_BASE_URL: API base URL (vendor-specific)
    - Scaling: Configure appropriate rate limits per kiosk instance count.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = getattr(settings, "NLP_API_KEY", None)
        self.base_url = getattr(settings, "NLP_BASE_URL", "https://api.example-nlp.com/v1")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(15.0, connect=5.0)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, NlpUnavailableError)),
        reraise=True,
    )
    async def structure_socrates(self, text: str, language: str = "en") -> SocratesStructure:
        if not self.api_key:
            raise NlpUnavailableError("NLP API key not configured")

        client = self._get_client()
        url = f"{self.base_url.rstrip('/')}/socrates"
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        payload = {"text": text, "language": language}

        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 429:
                raise NlpQuotaExceededError("NLP quota exceeded")
            if response.status_code >= 500:
                raise NlpUnavailableError(f"NLP service error: {response.status_code}")
            if response.status_code >= 400:
                raise NlpError(f"NLP request failed: {response.status_code}")

            data = response.json()
            return SocratesStructure(
                chief_complaint=data.get("chief_complaint"),
                site=data.get("site"),
                onset=data.get("onset"),
                character=data.get("character"),
                radiation=data.get("radiation"),
                associations=data.get("associations"),
                time_course=data.get("time_course"),
                exacerbating_relieving=data.get("exacerbating_relieving"),
                severity=data.get("severity"),
                red_flags=[RedFlag(f) for f in data.get("red_flags", [])],
                confidence=float(data.get("confidence", 0.0)),
            )
        except httpx.HTTPError as exc:
            logger.warning("nlp_socrates_network_error", error=str(type(exc).__name__))
            raise NlpUnavailableError("NLP service unavailable") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, NlpUnavailableError)),
        reraise=True,
    )
    async def detect_red_flags(self, text: str, language: str = "en") -> list[RedFlag]:
        if not self.api_key:
            raise NlpUnavailableError("NLP API key not configured")

        client = self._get_client()
        url = f"{self.base_url.rstrip('/')}/red-flags"
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        payload = {"text": text, "language": language}

        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 429:
                raise NlpQuotaExceededError("NLP quota exceeded")
            if response.status_code >= 500:
                raise NlpUnavailableError(f"NLP service error: {response.status_code}")
            if response.status_code >= 400:
                raise NlpError(f"NLP request failed: {response.status_code}")

            data = response.json()
            return [RedFlag(f) for f in data.get("red_flags", [])]
        except httpx.HTTPError as exc:
            logger.warning("nlp_red_flags_network_error", error=str(type(exc).__name__))
            raise NlpUnavailableError("NLP service unavailable") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, NlpUnavailableError)),
        reraise=True,
    )
    async def analyze_ayush(self, text: str, system: str, language: str = "en") -> AyushAnalysis:
        if not self.api_key:
            raise NlpUnavailableError("NLP API key not configured")

        client = self._get_client()
        url = f"{self.base_url.rstrip('/')}/ayush"
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        payload = {"text": text, "system": system, "language": language}

        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 429:
                raise NlpQuotaExceededError("NLP quota exceeded")
            if response.status_code >= 500:
                raise NlpUnavailableError(f"NLP service error: {response.status_code}")
            if response.status_code >= 400:
                raise NlpError(f"NLP request failed: {response.status_code}")

            data = response.json()
            return AyushAnalysis(
                prakriti=data.get("prakriti"),
                vikriti=data.get("vikriti"),
                agni=data.get("agni"),
                dosha_scores=data.get("dosha_scores", {}),
                nadi_notes=data.get("nadi_notes"),
                branching_path=data.get("branching_path"),
                confidence=float(data.get("confidence", 0.0)),
            )
        except httpx.HTTPError as exc:
            logger.warning("nlp_ayush_network_error", error=str(type(exc).__name__))
            raise NlpUnavailableError("NLP service unavailable") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, NlpUnavailableError)),
        reraise=True,
    )
    async def extract_entities(self, text: str, language: str = "en") -> EntityExtraction:
        if not self.api_key:
            raise NlpUnavailableError("NLP API key not configured")

        client = self._get_client()
        url = f"{self.base_url.rstrip('/')}/entities"
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        payload = {"text": text, "language": language}

        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 429:
                raise NlpQuotaExceededError("NLP quota exceeded")
            if response.status_code >= 500:
                raise NlpUnavailableError(f"NLP service error: {response.status_code}")
            if response.status_code >= 400:
                raise NlpError(f"NLP request failed: {response.status_code}")

            data = response.json()
            return EntityExtraction(
                medications=data.get("medications", []),
                allergies=data.get("allergies", []),
                conditions=data.get("conditions", []),
                confidence=float(data.get("confidence", 0.0)),
            )
        except httpx.HTTPError as exc:
            logger.warning("nlp_entities_network_error", error=str(type(exc).__name__))
            raise NlpUnavailableError("NLP service unavailable") from exc


def get_clinical_nlp() -> ClinicalNlpProtocol:
    """Factory returning the configured implementation.

    Environment-specific:
    - Development: Falls back to MockClinicalNlp if NLP_API_KEY is unset
    - Production: Requires NLP_API_KEY; fails fast if missing
    """
    settings = get_settings()
    api_key = getattr(settings, "NLP_API_KEY", None)
    if not api_key or not api_key.get_secret_value():
        if settings.is_production:
            raise ServiceUnavailableError(
                code="nlp_unconfigured",
                message="Clinical NLP unavailable — API key required in production",
            )
        logger.warning("nlp_using_mock")
        return MockClinicalNlp()
    return ExternalClinicalNlp()


async def close_clinical_nlp() -> None:
    """Cleanup function for lifespan shutdown."""
    impl = get_clinical_nlp()
    if isinstance(impl, ExternalClinicalNlp):
        await impl.close()
