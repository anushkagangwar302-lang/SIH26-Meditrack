"""OCR vision for extracting text from prescriptions, lab reports, and ID scans.

External integration: OCR vendor (e.g., Tesseract, Google Vision, AWS Textract).
Environment-specific OCR_VENDOR_API_KEY and OCR_VENDOR_BASE_URL.
Retry/circuit-breaker wrapper is centralised here.

All document images may contain PII (names, addresses, medical IDs) — never log them.
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

logger = get_logger("app.ai.ocr_vision")


class DocumentKind(str, Enum):
    """Types of documents for OCR processing."""

    prescription = "prescription"
    lab_report = "lab_report"
    id_scan = "id_scan"
    imaging = "imaging"
    other = "other"


@dataclass
class OcrResult:
    """OCR extraction output. Text may contain PII — never log it."""

    raw_text: str
    structured: dict
    confidence: float
    vendor: str
    pages_processed: int


class OcrError(Exception):
    """Base class for OCR failures. Services catch and degrade."""


class OcrUnavailableError(OcrError):
    """OCR service is down or rate-limited. Fall back to manual entry."""


class OcrQuotaExceededError(OcrError):
    """API quota exhausted. Fall back to manual entry."""


class OcrInvalidFormatError(OcrError):
    """Document format not supported by OCR vendor."""


class OcrProtocol(ABC):
    """Protocol for swapping implementations (external vendor vs mock in tests)."""

    @abstractmethod
    async def extract_text(
        self,
        image_bytes: bytes,
        document_kind: DocumentKind,
        format: Literal["pdf", "png", "jpg", "jpeg", "tiff"] = "pdf",
    ) -> OcrResult:
        """Extract text and structured data from document image.

        Image bytes may contain PII — never log them. Document kind helps
        the vendor apply domain-specific models (e.g., prescription layout).
        """
        ...


class MockOcr(OcrProtocol):
    """Development fallback. Returns deterministic mock responses.

    Environment-specific: In production, OCR_VENDOR_API_KEY must be set;
    this mock should never be used in live deployments.
    """

    async def extract_text(
        self,
        image_bytes: bytes,
        document_kind: DocumentKind,
        format: Literal["pdf", "png", "jpg", "jpeg", "tiff"] = "pdf",
    ) -> OcrResult:
        await asyncio.sleep(0.2)  # Simulate processing time

        # Mock structured output based on document kind
        if document_kind == DocumentKind.prescription:
            structured = {
                "medications": [
                    {"name": "Paracetamol 500mg", "dosage": "1 tablet", "frequency": "3 times daily"},
                    {"name": "Amoxicillin 250mg", "dosage": "1 capsule", "frequency": "2 times daily"},
                ],
                "prescriber": "Dr. [Mock]",
                "date": "2026-09-04",
            }
        elif document_kind == DocumentKind.lab_report:
            structured = {
                "test_name": "Complete Blood Count",
                "values": [
                    {"parameter": "Hemoglobin", "value": "13.5 g/dL", "reference": "12-16 g/dL"},
                    {"parameter": "WBC", "value": "7500 /μL", "reference": "4000-11000 /μL"},
                ],
                "lab": "[Mock Laboratory]",
            }
        elif document_kind == DocumentKind.id_scan:
            structured = {
                "document_type": "Aadhaar Card",
                "id_number": "[REDACTED]",
                "name": "[REDACTED]",
            }
        else:
            structured = {}

        return OcrResult(
            raw_text="[Mock OCR extraction text]",
            structured=structured,
            confidence=0.85,
            vendor="mock",
            pages_processed=1,
        )


class ExternalOcr(OcrProtocol):
    """External OCR vendor integration with retry and circuit-breaker.

    Environment-specific:
    - OCR_VENDOR_API_KEY: API key for the OCR service (vendor-specific)
    - OCR_VENDOR_BASE_URL: API base URL (vendor-specific)
    - Scaling: Configure appropriate rate limits per kiosk instance count.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.OCR_VENDOR_API_KEY
        self.base_url = settings.OCR_VENDOR_BASE_URL
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(30.0, connect=10.0)  # OCR can be slow
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError, OcrUnavailableError)),
        reraise=True,
    )
    async def extract_text(
        self,
        image_bytes: bytes,
        document_kind: DocumentKind,
        format: Literal["pdf", "png", "jpg", "jpeg", "tiff"] = "pdf",
    ) -> OcrResult:
        if not self.api_key:
            raise OcrUnavailableError("OCR vendor API key not configured")
        if not self.base_url:
            raise OcrUnavailableError("OCR vendor base URL not configured")

        client = self._get_client()
        # Vendor-specific endpoint — adapt to actual API
        url = f"{self.base_url.rstrip('/')}/extract"
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": f"image/{format}",
        }
        params = {"document_kind": document_kind.value}

        try:
            response = await client.post(
                url,
                content=image_bytes,
                headers=headers,
                params=params,
            )
            if response.status_code == 429:
                raise OcrQuotaExceededError("OCR vendor quota exceeded")
            if response.status_code >= 500:
                raise OcrUnavailableError(f"OCR vendor service error: {response.status_code}")
            if response.status_code == 415:
                raise OcrInvalidFormatError(f"OCR vendor does not support format: {format}")
            if response.status_code >= 400:
                raise OcrError(f"OCR vendor request failed: {response.status_code}")

            data = response.json()
            # Adapt to actual vendor response structure
            return OcrResult(
                raw_text=data.get("text", ""),
                structured=data.get("structured", {}),
                confidence=float(data.get("confidence", 0.0)),
                vendor="external",
                pages_processed=int(data.get("pages", 1)),
            )
        except httpx.HTTPError as exc:
            logger.warning("ocr_vendor_network_error", error=str(type(exc).__name__))
            raise OcrUnavailableError("OCR vendor unavailable") from exc


def get_ocr() -> OcrProtocol:
    """Factory returning the configured implementation.

    Environment-specific:
    - Development: Falls back to MockOcr if OCR_VENDOR_API_KEY is unset
    - Production: Requires OCR_VENDOR_API_KEY and OCR_VENDOR_BASE_URL; fails fast if missing
    """
    settings = get_settings()
    if not settings.OCR_VENDOR_API_KEY or not settings.OCR_VENDOR_API_KEY.get_secret_value():
        if settings.is_production:
            raise ServiceUnavailableError(
                code="ocr_unconfigured",
                message="OCR processing unavailable — API key required in production",
            )
        logger.warning("ocr_using_mock")
        return MockOcr()
    if not settings.OCR_VENDOR_BASE_URL:
        if settings.is_production:
            raise ServiceUnavailableError(
                code="ocr_unconfigured",
                message="OCR processing unavailable — base URL required in production",
            )
        logger.warning("ocr_using_mock_missing_url")
        return MockOcr()
    return ExternalOcr()


async def close_ocr() -> None:
    """Cleanup function for lifespan shutdown."""
    impl = get_ocr()
    if isinstance(impl, ExternalOcr):
        await impl.close()
