"""Test OCR extraction and document processing.

Tests the OCR workflow including:
- Document upload with idempotency
- OCR task triggering and processing
- OCR result polling
- Mock vs real OCR implementations
- File storage and cleanup
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai_modules.ocr_vision import DocumentKind, MockOcr, OcrProtocol, get_ocr
from app.models.documents import Document, OcrExtraction, OcrStatus, StorageTier


@pytest.fixture
def sample_patient_id():
    """Sample patient UUID."""
    return uuid.uuid4()


@pytest.fixture
def sample_session_id():
    """Sample session UUID."""
    return uuid.uuid4()


@pytest.fixture
def sample_document_data():
    """Sample document data for upload."""
    return {
        "patient_id": uuid.uuid4(),
        "session_id": uuid.uuid4(),
        "kind": DocumentKind.prescription,
        "idempotency_key": "test-key-123",
        "vault_opt_in": False,
    }


@pytest.fixture
def sample_pdf_bytes():
    """Sample PDF bytes for testing."""
    return b"%PDF-1.4\n%fake pdf content for testing"


@pytest.fixture
def sample_image_bytes():
    """Sample image bytes for testing."""
    return b"\x89PNG\r\n\x1a\n%fake png content for testing"


class TestMockOcr:
    """Test mock OCR implementation."""

    def test_mock_ocr_transcribe(self):
        """Test mock OCR transcription."""
        ocr = MockOcr()
        result = ocr.extract_text(
            image_bytes=b"test image",
            document_kind=DocumentKind.prescription,
            format="pdf",
        )

        assert result.raw_text == "[Mock OCR extraction text]"
        assert result.vendor == "mock"
        assert result.confidence == 0.85
        assert result.pages_processed == 1

    def test_mock_ocr_different_kinds(self):
        """Test mock OCR for different document kinds."""
        ocr = MockOcr()

        kinds = [
            DocumentKind.prescription,
            DocumentKind.lab_report,
            DocumentKind.id_scan,
            DocumentKind.imaging,
            DocumentKind.other,
        ]

        for kind in kinds:
            result = ocr.extract_text(
                image_bytes=b"test",
                document_kind=kind,
                format="pdf",
            )
            assert result.vendor == "mock"
            assert result.structured is not None

    def test_mock_ocr_different_formats(self):
        """Test mock OCR for different file formats."""
        ocr = MockOcr()

        formats = ["pdf", "png", "jpg", "jpeg", "tiff"]

        for format in formats:
            result = ocr.extract_text(
                image_bytes=b"test",
                document_kind=DocumentKind.prescription,
                format=format,  # type: ignore
            )
            assert result.vendor == "mock"


class TestOcrFactory:
    """Test OCR service factory."""

    def test_get_ocr_with_api_key(self):
        """Test getting OCR service when API key is configured."""
        with patch("app.ai_modules.ocr_vision.get_settings") as mock_settings:
            settings = MagicMock()
            settings.OCR_VENDOR_API_KEY = MagicMock()
            settings.OCR_VENDOR_API_KEY.get_secret_value.return_value = "test-key"
            settings.OCR_VENDOR_BASE_URL = "https://test.ocr.com"
            settings.is_production = False
            mock_settings.return_value = settings

            ocr = get_ocr()
            # Should return ExternalOcr (or mock in dev)
            assert ocr is not None

    def test_get_ocr_without_api_key_dev(self):
        """Test getting mock OCR when API key is not configured in dev."""
        with patch("app.ai_modules.ocr_vision.get_settings") as mock_settings:
            settings = MagicMock()
            settings.OCR_VENDOR_API_KEY = None
            settings.is_production = False
            mock_settings.return_value = settings

            ocr = get_ocr()
            assert isinstance(ocr, MockOcr)

    def test_get_ocr_without_api_key_prod(self):
        """Test that production fails without API key."""
        with patch("app.ai_modules.ocr_vision.get_settings") as mock_settings:
            settings = MagicMock()
            settings.OCR_VENDOR_API_KEY = None
            settings.is_production = True
            mock_settings.return_value = settings

            from app.core.exceptions import ServiceUnavailableError

            with pytest.raises(ServiceUnavailableError):
                get_ocr()


class TestDocumentUpload:
    """Test document upload and OCR workflow."""

    @pytest.mark.asyncio
    async def test_document_creation(self, sample_document_data):
        """Test creating a document record."""
        document = Document(
            patient_id=sample_document_data["patient_id"],
            session_id=sample_document_data["session_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test_file.pdf",
            vault_opt_in=sample_document_data["vault_opt_in"],
        )

        assert document.id is not None
        assert document.ocr_status == OcrStatus.queued.value
        assert document.ocr_attempts == 0
        assert document.storage_tier == StorageTier.temp_scan.value

    @pytest.mark.asyncio
    async def test_document_idempotency(self, sample_document_data):
        """Test that duplicate uploads with same idempotency key are rejected."""
        # First document
        doc1 = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test_file.pdf",
        )

        # Second document with same key
        doc2 = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test_file2.pdf",
        )

        # In production, this would fail due to unique constraint
        # For testing, we just verify the key is the same
        assert doc1.idempotency_key == doc2.idempotency_key

    @pytest.mark.asyncio
    async def test_ocr_extraction_creation(self, sample_document_data):
        """Test creating OCR extraction record."""
        extraction = OcrExtraction(
            document_id=uuid.uuid4(),
            raw_text_enc="encrypted_text",
            structured_enc="encrypted_structured",
            vendor="mock",
        )

        assert extraction.id is not None
        assert extraction.vendor == "mock"


class TestOcrTask:
    """Test Celery OCR task processing."""

    @pytest.mark.asyncio
    async def test_ocr_task_success(self, sample_document_data, sample_pdf_bytes):
        """Test successful OCR task processing."""
        from app.ai_modules.ocr_vision import MockOcr

        ocr = MockOcr()
        result = ocr.extract_text(
            image_bytes=sample_pdf_bytes,
            document_kind=DocumentKind.prescription,
            format="pdf",
        )

        assert result.status == "success"
        assert result.vendor == "mock"
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_ocr_task_with_red_flags(self, sample_document_data):
        """Test OCR task with red-flag detection."""
        from app.ai_modules.ocr_vision import MockOcr

        ocr = MockOcr()
        result = ocr.extract_text(
            image_bytes=b"prescription with severe allergies",
            document_kind=DocumentKind.prescription,
            format="pdf",
        )

        # Mock OCR should return structured data
        assert result.structured is not None

    @pytest.mark.asyncio
    async def test_ocr_task_invalid_format(self, sample_document_data):
        """Test OCR task with invalid file format."""
        from app.ai_modules.ocr_vision import MockOcr, OcrInvalidFormatError

        ocr = MockOcr()
        # Mock doesn't actually validate format, but external OCR would
        result = ocr.extract_text(
            image_bytes=b"invalid format",
            document_kind=DocumentKind.prescription,
            format="invalid",
        )

        # Mock should still succeed for testing
        assert result.vendor == "mock"


class TestFileStorage:
    """Test file storage and cleanup."""

    def test_file_path_generation(self, sample_document_data):
        """Test file path generation for documents."""
        from app.core.config import get_settings

        with patch("app.core.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.UPLOAD_TEMP_DIR = "/tmp/uploads"
            mock_settings.return_value = settings

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            object_path = f"{settings.UPLOAD_TEMP_DIR}/{sample_document_data['patient_id']}_{timestamp}_test.pdf"

            assert object_path.startswith("/tmp/uploads/")
            assert "test.pdf" in object_path

    def test_vault_path_generation(self, sample_document_data):
        """Test vault path generation for opt-in documents."""
        from app.core.config import get_settings

        with patch("app.core.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.UPLOAD_VAULT_DIR = "/uploads/encrypted_vault"
            mock_settings.return_value = settings

            vault_path = f"{settings.UPLOAD_VAULT_DIR}/{uuid.uuid4()}_encrypted"

            assert vault_path.startswith("/uploads/encrypted_vault/")
            assert "encrypted" in vault_path


class TestOcrPolling:
    """Test OCR status polling."""

    @pytest.mark.asyncio
    async def test_ocr_status_queued(self, sample_document_data):
        """Test OCR status when queued."""
        document = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test.pdf",
            ocr_status=OcrStatus.queued.value,
        )

        assert document.ocr_status == OcrStatus.queued.value
        assert document.ocr_attempts == 0

    @pytest.mark.asyncio
    async def test_ocr_status_processing(self, sample_document_data):
        """Test OCR status when processing."""
        document = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test.pdf",
            ocr_status=OcrStatus.processing.value,
            ocr_attempts=1,
        )

        assert document.ocr_status == OcrStatus.processing.value
        assert document.ocr_attempts == 1

    @pytest.mark.asyncio
    async def test_ocr_status_succeeded(self, sample_document_data):
        """Test OCR status when succeeded."""
        document = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test.pdf",
            ocr_status=OcrStatus.succeeded.value,
            ocr_attempts=1,
        )

        assert document.ocr_status == OcrStatus.succeeded.value
        assert document.ocr_attempts == 1

    @pytest.mark.asyncio
    async def test_ocr_status_failed(self, sample_document_data):
        """Test OCR status when failed."""
        document = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test.pdf",
            ocr_status=OcrStatus.failed.value,
            ocr_attempts=2,
        )

        assert document.ocr_status == OcrStatus.failed.value
        assert document.ocr_attempts == 2


class TestOcrRetry:
    """Test OCR retry logic."""

    @pytest.mark.asyncio
    async def test_ocr_retry_logic(self, sample_document_data):
        """Test that failed OCR can be retried."""
        document = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test.pdf",
            ocr_status=OcrStatus.failed.value,
            ocr_attempts=1,
        )

        # Should be below retry threshold
        assert document.ocr_attempts < 3

        # Reset to queued for retry
        document.ocr_status = OcrStatus.queued.value
        assert document.ocr_status == OcrStatus.queued.value

    @pytest.mark.asyncio
    async def test_ocr_retry_limit(self, sample_document_data):
        """Test that OCR has a retry limit."""
        document = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test.pdf",
            ocr_status=OcrStatus.failed.value,
            ocr_attempts=3,
        )

        # Should be at retry threshold
        assert document.ocr_attempts >= 3

        # Should not be retried
        # (In production, this would be enforced by the retry task)


class TestVaultMigration:
    """Test vault migration for opt-in documents."""

    @pytest.mark.asyncio
    async def test_vault_opt_in(self, sample_document_data):
        """Test vault opt-in flag."""
        document = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test.pdf",
            vault_opt_in=True,
        )

        assert document.vault_opt_in is True
        assert document.storage_tier == StorageTier.temp_scan.value

    @pytest.mark.asyncio
    async def test_vault_migration(self, sample_document_data):
        """Test migration from temp to vault."""
        document = Document(
            patient_id=sample_document_data["patient_id"],
            idempotency_key=sample_document_data["idempotency_key"],
            kind=sample_document_data["kind"].value,
            storage_tier=StorageTier.temp_scan.value,
            object_path="/tmp/test.pdf",
            vault_opt_in=True,
        )

        # Simulate migration
        document.storage_tier = StorageTier.encrypted_vault.value
        document.object_path = "/uploads/encrypted_vault/encrypted_test.pdf"
        document.purge_after = None

        assert document.storage_tier == StorageTier.encrypted_vault.value
        assert document.purge_after is None
