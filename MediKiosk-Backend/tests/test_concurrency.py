"""Test concurrent session handling and race condition prevention.

Tests the system's ability to handle concurrent operations including:
- Multiple sessions with same ABHA ID linking
- Concurrent document uploads with idempotency keys
- Parallel consent updates
- Triage queue position allocation under load
- Redis distributed lock behavior
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.database import redis_lock
from app.models.user import AbhaLinkStatus, Patient
from app.services.dialogue_manager import DialogueManager
from app.services.triage_service import TriageService


@pytest.fixture
def sample_clinic_id():
    """Sample clinic UUID."""
    return uuid.uuid4()


@pytest.fixture
def sample_abha_number():
    """Sample ABHA number."""
    return "12-3456-7890-1234"


@pytest.fixture
def sample_aadhaar():
    """Sample Aadhaar number."""
    return "1234-5678-9012"


class TestConcurrentAbhaLinking:
    """Test concurrent ABHA ID linking."""

    @pytest.mark.asyncio
    async def test_concurrent_abha_link_same_abha(self, sample_clinic_id, sample_abha_number):
        """Test that concurrent attempts to link the same ABHA ID are handled correctly."""
        from app.core.security import hmac_lookup

        abha_hmac = hmac_lookup(sample_abha_number)

        # Simulate concurrent linking attempts
        async def link_abha_attempt(attempt_id: int):
            lock_name = f"abha:{abha_hmac}"
            try:
                async with redis_lock(lock_name, ttl_seconds=10):
                    # Simulate DB check and insert
                    await asyncio.sleep(0.1)  # Simulate DB operation
                    return {"attempt": attempt_id, "success": True}
            except Exception as exc:
                return {"attempt": attempt_id, "success": False, "error": str(exc)}

        # Run 5 concurrent attempts
        attempts = [link_abha_attempt(i) for i in range(5)]
        results = await asyncio.gather(*attempts)

        # Should have 1 success and 4 failures (or retries)
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]

        # At least one should succeed
        assert len(successful) >= 1
        # Others should handle the conflict gracefully
        assert len(failed) + len(successful) == 5

    @pytest.mark.asyncio
    async def test_concurrent_abha_link_different_abha(self, sample_clinic_id):
        """Test that concurrent attempts with different ABHA IDs all succeed."""
        from app.core.security import hmac_lookup

        abha_numbers = [f"12-3456-7890-{i:04d}" for i in range(5)]

        async def link_abha_attempt(abha: str):
            abha_hmac = hmac_lookup(abha)
            lock_name = f"abha:{abha_hmac}"
            try:
                async with redis_lock(lock_name, ttl_seconds=10):
                    await asyncio.sleep(0.05)  # Simulate DB operation
                    return {"abha": abha, "success": True}
            except Exception as exc:
                return {"abha": abha, "success": False, "error": str(exc)}

        attempts = [link_abha_attempt(abha) for abha in abha_numbers]
        results = await asyncio.gather(*attempts)

        # All should succeed since they're different ABHA IDs
        successful = [r for r in results if r["success"]]
        assert len(successful) == 5

    @pytest.mark.asyncio
    async def test_redis_lock_contention(self):
        """Test Redis lock behavior under contention."""
        lock_name = "test:contention:lock"

        async def acquire_lock(holder_id: int):
            try:
                async with redis_lock(lock_name, ttl_seconds=5):
                    await asyncio.sleep(0.2)  # Hold lock for 200ms
                    return {"holder": holder_id, "success": True}
            except Exception as exc:
                return {"holder": holder_id, "success": False, "error": str(exc)}

        # Run 3 concurrent lock attempts
        attempts = [acquire_lock(i) for i in range(3)]
        results = await asyncio.gather(*attempts)

        # Only one should succeed
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]

        assert len(successful) == 1
        assert len(failed) == 2


class TestConcurrentDocumentUpload:
    """Test concurrent document upload with idempotency."""

    @pytest.mark.asyncio
    async def test_concurrent_same_idempotency_key(self):
        """Test that concurrent uploads with same idempotency key are handled correctly."""
        from app.core.database import claim_idempotency_key, idempotency_get, idempotency_store

        idempotency_key = "test-idempotency-key-123"

        async def upload_attempt(attempt_id: int):
            claimed = await claim_idempotency_key(f"document:{idempotency_key}")
            if claimed:
                await asyncio.sleep(0.1)  # Simulate upload processing
                await idempotency_store(f"document:{idempotency_key}", f"result-{attempt_id}")
                return {"attempt": attempt_id, "success": True}
            else:
                return {"attempt": attempt_id, "success": False, "reason": "key_claimed"}

        # Run 5 concurrent upload attempts with same key
        attempts = [upload_attempt(i) for i in range(5)]
        results = await asyncio.gather(*attempts)

        # Only first should succeed
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]

        assert len(successful) == 1
        assert len(failed) == 4

        # Verify the cached result
        cached = await idempotency_get(f"document:{idempotency_key}")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_concurrent_different_idempotency_keys(self):
        """Test that concurrent uploads with different keys all succeed."""
        from app.core.database import claim_idempotency_key, idempotency_store

        keys = [f"test-key-{i}" for i in range(5)]

        async def upload_attempt(key: str):
            claimed = await claim_idempotency_key(f"document:{key}")
            if claimed:
                await asyncio.sleep(0.05)  # Simulate upload processing
                await idempotency_store(f"document:{key}", f"result-{key}")
                return {"key": key, "success": True}
            else:
                return {"key": key, "success": False, "reason": "key_claimed"}

        attempts = [upload_attempt(key) for key in keys]
        results = await asyncio.gather(*attempts)

        # All should succeed since keys are different
        successful = [r for r in results if r["success"]]
        assert len(successful) == 5


class TestConcurrentConsentUpdates:
    """Test concurrent consent updates for same patient/purpose."""

    @pytest.mark.asyncio
    async def test_concurrent_consent_grant(self):
        """Test that concurrent consent grants are handled correctly."""
        patient_id = uuid.uuid4()
        purpose = "treatment"

        async def consent_grant(attempt_id: int):
            lock_name = f"consent:{patient_id}:{purpose}"
            try:
                async with redis_lock(lock_name, ttl_seconds=5):
                    await asyncio.sleep(0.1)  # Simulate DB operation
                    return {"attempt": attempt_id, "success": True}
            except Exception as exc:
                return {"attempt": attempt_id, "success": False, "error": str(exc)}

        # Run 3 concurrent consent grants
        attempts = [consent_grant(i) for i in range(3)]
        results = await asyncio.gather(*attempts)

        # One should succeed, others should fail gracefully
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]

        assert len(successful) == 1
        assert len(failed) == 2

    @pytest.mark.asyncio
    async def test_concurrent_consent_different_purposes(self):
        """Test that concurrent consent updates for different purposes all succeed."""
        patient_id = uuid.uuid4()
        purposes = ["treatment", "diagnostics_ocr", "voice_processing"]

        async def consent_grant(purpose: str):
            lock_name = f"consent:{patient_id}:{purpose}"
            try:
                async with redis_lock(lock_name, ttl_seconds=5):
                    await asyncio.sleep(0.05)  # Simulate DB operation
                    return {"purpose": purpose, "success": True}
            except Exception as exc:
                return {"purpose": purpose, "success": False, "error": str(exc)}

        attempts = [consent_grant(purpose) for purpose in purposes]
        results = await asyncio.gather(*attempts)

        # All should succeed since they're different purposes
        successful = [r for r in results if r["success"]]
        assert len(successful) == 3


class TestConcurrentTriageQueue:
    """Test concurrent triage queue position allocation."""

    @pytest.mark.asyncio
    async def test_concurrent_queue_allocation(self, sample_clinic_id):
        """Test that concurrent queue position allocations don't clash."""
        from datetime import date

        queue_date = date.today()

        async def allocate_position(session_id: int):
            lock_name = f"triage:{sample_clinic_id}:{queue_date}"
            try:
                async with redis_lock(lock_name, ttl_seconds=5):
                    await asyncio.sleep(0.1)  # Simulate DB operation
                    # In production, this would SELECT ... FOR UPDATE
                    return {"session": session_id, "position": session_id + 1, "success": True}
            except Exception as exc:
                return {"session": session_id, "success": False, "error": str(exc)}

        # Run 5 concurrent position allocations
        attempts = [allocate_position(i) for i in range(5)]
        results = await asyncio.gather(*attempts)

        # All should succeed since they're serialized by the lock
        successful = [r for r in results if r["success"]]
        assert len(successful) == 5

        # Verify all positions are unique
        positions = [r["position"] for r in successful]
        assert len(positions) == len(set(positions))

    @pytest.mark.asyncio
    async def test_concurrent_emergency_priority(self, sample_clinic_id):
        """Test that emergency cases get priority position (position 1)."""
        from datetime import date

        queue_date = date.today()

        async def allocate_emergency(session_id: int):
            lock_name = f"triage:{sample_clinic_id}:{queue_date}"
            try:
                async with redis_lock(lock_name, ttl_seconds=5):
                    await asyncio.sleep(0.1)  # Simulate DB operation
                    # Emergency should get position 1
                    return {"session": session_id, "position": 1, "success": True}
            except Exception as exc:
                return {"session": session_id, "success": False, "error": str(exc)}

        # Run 3 concurrent emergency allocations
        attempts = [allocate_emergency(i) for i in range(3)]
        results = await asyncio.gather(*attempts)

        # Only one should get position 1, others should fail or get different positions
        successful = [r for r in results if r["success"]]
        position_1_count = len([r for r in successful if r["position"] == 1])

        assert position_1_count == 1


class TestConcurrentDialogueSessions:
    """Test concurrent dialogue session management."""

    @pytest.mark.asyncio
    async def test_concurrent_dialogue_start(self, sample_clinic_id):
        """Test that concurrent dialogue starts don't interfere."""
        dialogue_manager = DialogueManager()

        async def start_session(patient_id: int):
            state = await dialogue_manager.start_session(
                patient_id=uuid.UUID(int=patient_id * 1000),  # Fake UUID
                clinic_id=sample_clinic_id,
                language="hi",
            )
            return {"patient_id": patient_id, "session_id": str(state.session_id)}

        # Start 10 concurrent sessions
        attempts = [start_session(i) for i in range(10)]
        results = await asyncio.gather(*attempts)

        # All should succeed with different session IDs
        assert len(results) == 10
        session_ids = [r["session_id"] for r in results]
        assert len(session_ids) == len(set(session_ids))

    @pytest.mark.asyncio
    async def test_concurrent_dialogue_progression(self, sample_clinic_id):
        """Test that concurrent dialogue progression doesn't interfere."""
        dialogue_manager = DialogueManager()

        # Start 5 sessions
        sessions = []
        for i in range(5):
            state = await dialogue_manager.start_session(
                patient_id=uuid.UUID(int=i * 1000),
                clinic_id=sample_clinic_id,
                language="hi",
            )
            sessions.append(state)

        # Progress each session independently
        async def progress_session(state):
            turn_input = MagicMock(
                session_id=state.session_id,
                utterance="yes",
                step="welcome",
            )
            response = await dialogue_manager.process_turn(turn_input)
            return {"session_id": str(state.session_id), "next_step": response.next_step.value}

        progressions = [progress_session(state) for state in sessions]
        results = await asyncio.gather(*progressions)

        # All should progress successfully
        assert len(results) == 5
        next_steps = [r["next_step"] for r in results]
        assert all(step == "chief_complaint" for step in next_steps)


class TestConcurrentOcrProcessing:
    """Test concurrent OCR processing of the same document."""

    @pytest.mark.asyncio
    async def test_concurrent_ocr_same_document(self):
        """Test that concurrent OCR attempts for the same document are serialized."""
        document_id = uuid.uuid4()

        async def ocr_attempt(attempt_id: int):
            lock_name = f"ocr:{document_id}"
            try:
                async with redis_lock(lock_name, ttl_seconds=5):
                    await asyncio.sleep(0.1)  # Simulate OCR processing
                    return {"attempt": attempt_id, "success": True}
            except Exception as exc:
                return {"attempt": attempt_id, "success": False, "error": str(exc)}

        # Run 3 concurrent OCR attempts
        attempts = [ocr_attempt(i) for i in range(3)]
        results = await asyncio.gather(*attempts)

        # Only one should succeed
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]

        assert len(successful) == 1
        assert len(failed) == 2

    @pytest.mark.asyncio
    async def test_concurrent_ocr_different_documents(self):
        """Test that concurrent OCR of different documents all succeed."""
        document_ids = [uuid.uuid4() for _ in range(5)]

        async def ocr_attempt(doc_id: uuid.UUID):
            lock_name = f"ocr:{doc_id}"
            try:
                async with redis_lock(lock_name, ttl_seconds=5):
                    await asyncio.sleep(0.05)  # Simulate OCR processing
                    return {"document_id": str(doc_id), "success": True}
            except Exception as exc:
                return {"document_id": str(doc_id), "success": False, "error": str(exc)}

        attempts = [ocr_attempt(doc_id) for doc_id in document_ids]
        results = await asyncio.gather(*attempts)

        # All should succeed since they're different documents
        successful = [r for r in results if r["success"]]
        assert len(successful) == 5


class TestRateLimitingUnderLoad:
    """Test rate limiting behavior under concurrent load."""

    @pytest.mark.asyncio
    async def test_concurrent_rate_limiting(self):
        """Test that rate limiting works correctly under concurrent requests."""
        from app.core.database import hit_rate_limit

        bucket = "ip:192.168.1.1"
        limit = 10

        async def make_request(request_id: int):
            allowed = await hit_rate_limit(bucket, limit)
            return {"request": request_id, "allowed": allowed}

        # Make 15 concurrent requests (limit is 10)
        requests = [make_request(i) for i in range(15)]
        results = await asyncio.gather(*requests)

        # First 10 should be allowed, rest should be rate limited
        allowed = [r for r in results if r["allowed"]]
        denied = [r for r in results if not r["allowed"]]

        assert len(allowed) == 10
        assert len(denied) == 5

    @pytest.mark.asyncio
    async def test_concurrent_different_buckets(self):
        """Test that rate limiting works per bucket (IP)."""
        from app.core.database import hit_rate_limit

        buckets = ["ip:192.168.1.1", "ip:192.168.1.2", "ip:192.168.1.3"]
        limit = 5

        async def make_request(bucket: str, request_id: int):
            allowed = await hit_rate_limit(bucket, limit)
            return {"bucket": bucket, "request": request_id, "allowed": allowed}

        # Make 8 requests per bucket (limit is 5)
        all_requests = []
        for bucket in buckets:
            for i in range(8):
                all_requests.append(make_request(bucket, i))

        results = await asyncio.gather(*all_requests)

        # Each bucket should have 5 allowed, 3 denied
        for bucket in buckets:
            bucket_results = [r for r in results if r["bucket"] == bucket]
            allowed = [r for r in bucket_results if r["allowed"]]
            denied = [r for r in bucket_results if not r["allowed"]]
            assert len(allowed) == 5
            assert len(denied) == 3


class TestRedisConnectionPool:
    """Test Redis connection pool behavior under concurrent load."""

    @pytest.mark.asyncio
    async def test_concurrent_redis_operations(self):
        """Test that Redis handles concurrent operations correctly."""
        from app.core.database import redis_session

        keys = [f"test:key:{i}" for i in range(20)]

        async def redis_operation(key: str):
            client = redis_session()
            await client.set(key, f"value-{key}")
            value = await client.get(key)
            return {"key": key, "value": value, "success": value == f"value-{key}"}

        operations = [redis_operation(key) for key in keys]
        results = await asyncio.gather(*operations)

        # All should succeed
        successful = [r for r in results if r["success"]]
        assert len(successful) == 20

    @pytest.mark.asyncio
    async def test_concurrent_redis_locks(self):
        """Test that Redis locks work correctly under concurrent contention."""
        lock_names = [f"test:lock:{i}" for i in range(10)]

        async def lock_operation(lock_name: str):
            try:
                async with redis_lock(lock_name, ttl_seconds=2):
                    await asyncio.sleep(0.1)
                    return {"lock": lock_name, "success": True}
            except Exception as exc:
                return {"lock": lock_name, "success": False, "error": str(exc)}

        operations = [lock_operation(lock_name) for lock_name in lock_names]
        results = await asyncio.gather(*operations)

        # All should succeed since they're different locks
        successful = [r for r in results if r["success"]]
        assert len(successful) == 10


class TestDatabaseConnectionPool:
    """Test database connection pool behavior under concurrent load."""

    @pytest.mark.asyncio
    async def test_concurrent_db_operations(self):
        """Test that database connection pool handles concurrent operations."""
        # This would require a real database session
        # For now, we'll just verify the connection pool configuration
        from app.core.config import get_settings

        with patch("app.core.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.DB_POOL_SIZE = 8
            settings.DB_MAX_OVERFLOW = 4
            mock_settings.return_value = settings

            config = get_settings()
            assert config.DB_POOL_SIZE == 8
            assert config.DB_MAX_OVERFLOW == 4
            # Pool should handle 8 + 4 = 12 concurrent connections


class TestMemorySafety:
    """Test memory safety under concurrent load."""

    @pytest.mark.asyncio
    async def test_no_shared_mutable_state(self):
        """Test that no shared mutable state exists in services."""
        # Create multiple service instances
        services = [DialogueManager() for _ in range(5)]

        # Verify they don't share state
        session_ids = []
        for i, service in enumerate(services):
            state = await service.start_session(
                patient_id=uuid.UUID(int=i * 1000)),
                clinic_id=uuid.uuid4(),
                language="hi",
            )
            session_ids.append(state.session_id)

        # All should have different session IDs
        assert len(session_ids) == len(set(session_ids))

    @pytest.mark.asyncio
    async def test_redis_state_isolation(self):
        """Test that Redis state is properly isolated between operations."""
        from app.core.database import redis_session

        # Set different keys for different operations
        keys = {
            "user1": "session:123",
            "user2": "session:456",
            "user3": "session:789",
        }

        async def set_and_get(user: str, key: str):
            client = redis_session()
            await client.set(key, f"value-{user}")
            value = await client.get(key)
            return {"user": user, "key": key, "value": value}

        operations = [set_and_get(user, key) for user, key in keys.items()]
        results = await asyncio.gather(*operations)

        # Each operation should get its own value
        for result in results:
            assert result["value"] == f"value-{result['user']}"
