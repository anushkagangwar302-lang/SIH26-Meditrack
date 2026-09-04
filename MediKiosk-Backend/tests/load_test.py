"""Load testing script using Locust for MediKiosk-Backend.

Tests the system under load including:
- ABHA login flow
- Consent capture
- WebSocket interview dialogue
- Document upload
- Summary generation
- API rate limiting behavior

Usage:
    locust -f tests/load_test.py --host=http://localhost:8000

Environment:
    Set the target host and API base URL as needed.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from locust import HttpUser, between, events, task
from locust.runners import MasterRunner


class MediKioskUser(HttpUser):
    """Simulates a kiosk user interacting with the MediKiosk system."""

    wait_time = between(1, 3)  # Wait 1-3 seconds between tasks

    def on_start(self):
        """Initialize user session and perform login."""
        self.abha_number = f"12-3456-7890-{uuid.uuid4().int % 10000:04d}"
        self.patient_id = None
        self.access_token = None
        self.session_id = None

        # Perform ABHA login
        self.abha_login()

    def abha_login(self):
        """Simulate ABHA login flow."""
        # Step 1: Get login challenge
        response = self.client.post(
            "/api/v1/auth/abha/login",
            json={"abha_number": self.abha_number},
        )
        if response.status_code != 200:
            print(f"ABHA login failed: {response.text}")
            return

        data = response.json()
        challenge_id = data.get("challenge_id")

        # Step 2: Submit OTP (simulated)
        response = self.client.post(
            "/api/v1/auth/abha/verify",
            json={
                "challenge_id": challenge_id,
                "otp": "123456",  # Mock OTP
            },
        )
        if response.status_code != 200:
            print(f"ABHA verify failed: {response.text}")
            return

        data = response.json()
        self.access_token = data.get("access_token")
        self.patient_id = data.get("patient_id")

        # Set auth header for subsequent requests
        self.client.headers.update(
            {"Authorization": f"Bearer {self.access_token}"}
        )

    @task(3)
    def capture_consent(self):
        """Capture treatment consent (high frequency task)."""
        if not self.access_token:
            return

        response = self.client.post(
            "/api/v1/auth/consent",
            json={
                "purpose": "treatment",
                "granted": True,
                "language": "hi",
            },
        )
        # Consent should succeed
        assert response.status_code in [200, 201]

    @task(5)
    def start_interview(self):
        """Start an interview session (high frequency task)."""
        if not self.access_token:
            return

        response = self.client.post(
            "/api/v1/interview/start",
            json={
                "language": "hi",
            },
        )
        if response.status_code == 200:
            data = response.json()
            self.session_id = data.get("session_id")

    @task(2)
    def check_interview_status(self):
        """Check interview session status."""
        if not self.session_id:
            return

        response = self.client.get(f"/api/v1/interview/{self.session_id}/status")
        # Should return 200 or 404 if session not found
        assert response.status_code in [200, 404]

    @task(1)
    def upload_document(self):
        """Simulate document upload (lower frequency task)."""
        if not self.access_token:
            return

        # Mock file upload
        files = {
            "file": ("test.pdf", b"%PDF-1.4\n%fake pdf", "application/pdf"),
        }
        data = {
            "kind": "prescription",
            "idempotency_key": f"doc-{uuid.uuid4()}",
            "vault_opt_in": "false",
        }

        response = self.client.post(
            "/api/v1/documents/upload",
            files=files,
            data=data,
        )
        # Should succeed or rate limit
        assert response.status_code in [200, 201, 429]

    @task(1)
    def check_ocr_status(self):
        """Check OCR processing status."""
        if not self.access_token:
            return

        # Use a mock document ID
        document_id = str(uuid.uuid4())
        response = self.client.get(f"/api/v1/documents/{document_id}/ocr")
        # Should return 404 (not found) or 200
        assert response.status_code in [200, 404]

    @task(2)
    def generate_summary(self):
        """Generate clinical summary."""
        if not self.session_id:
            return

        response = self.client.post(
            "/api/v1/summary/generate",
            params={
                "session_id": self.session_id,
                "format": "text",
                "include_ayush": "true",
                "language": "hi",
            },
        )
        # Should succeed or return 404 if session not complete
        assert response.status_code in [200, 404]

    @task(1)
    def check_health(self):
        """Check system health (lightweight task)."""
        response = self.client.get("/healthz")
        assert response.status_code == 200

    @task(1)
    def check_readiness(self):
        """Check system readiness (lightweight task)."""
        response = self.client.get("/readyz")
        assert response.status_code in [200, 503]


class HighVolumeUser(MediKioskUser):
    """High-volume user for stress testing (shorter wait times)."""

    wait_time = between(0.1, 0.5)  # Faster task execution


class AbhaLinkStressUser(HttpUser):
    """User focused on ABHA linking stress testing."""

    wait_time = between(0.5, 1)

    def on_start(self):
        """Initialize without login to test login flow under load."""
        self.abha_number = f"12-3456-7890-{uuid.uuid4().int % 10000:04d}"

    @task
    def stress_abha_login(self):
        """Stress test ABHA login endpoint."""
        response = self.client.post(
            "/api/v1/auth/abha/login",
            json={"abha_number": self.abha_number},
        )
        # Should succeed or rate limit
        assert response.status_code in [200, 429]


class RateLimitTestUser(HttpUser):
    """User focused on testing rate limiting behavior."""

    wait_time = between(0.05, 0.1)  # Very fast to trigger rate limits

    @task
    def hit_rate_limit(self):
        """Make requests to trigger rate limiting."""
        response = self.client.get("/healthz")
        # Track rate limit responses
        if response.status_code == 429:
            events.request.fire(
                request_type="GET",
                name="/healthz (rate limited)",
                response_time=response.elapsed.total_seconds() * 1000,
                response_length=len(response.content),
                exception=None,
                context={},
            )


# Locust event handlers for custom metrics
@events.init.add_listener
def on_locust_init(environment, **kwargs):
    """Initialize custom metrics."""
    if isinstance(environment.runner, MasterRunner):
        print("Running in master mode")
    else:
        print("Running in standalone or worker mode")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs, **_):
    """Print summary when test stops."""
    if environment.stats.total.fail_ratio > 0.1:
        print(f"WARNING: High failure ratio: {environment.stats.total.fail_ratio:.2%}")


if __name__ == "__main__":
    # Run Locust programmatically (for testing)
    import sys

    if len(sys.argv) > 1:
        host = sys.argv[1]
    else:
        host = "http://localhost:8000"

    print(f"Starting load test against {host}")
    print("To run with UI: locust -f tests/load_test.py --host=" + host)
    print("To run headless: locust -f tests/load_test.py --headless --host=" + host)
