"""initial clinical identity consent documents schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "clinics",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("ayush_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_clinic_id", "users", ["clinic_id"])

    op.create_table(
        "patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        # PII: Aadhaar ciphertext
        sa.Column("aadhaar_enc", sa.Text(), nullable=True),
        # PII: Aadhaar HMAC (unique, ON CONFLICT linking)
        sa.Column("aadhaar_hmac", sa.String(length=64), nullable=True),
        # PII: ABHA number ciphertext
        sa.Column("abha_number_enc", sa.Text(), nullable=True),
        # PII: ABHA HMAC (unique, ON CONFLICT linking)
        sa.Column("abha_number_hmac", sa.String(length=64), nullable=True),
        # PII: ABHA address ciphertext
        sa.Column("abha_address_enc", sa.Text(), nullable=True),
        # PII: name ciphertext
        sa.Column("full_name_enc", sa.Text(), nullable=True),
        # PII: DOB ciphertext
        sa.Column("date_of_birth_enc", sa.Text(), nullable=True),
        sa.Column("gender", sa.String(length=32), nullable=True),
        # PII: mobile ciphertext
        sa.Column("mobile_enc", sa.Text(), nullable=True),
        # PII: mobile HMAC
        sa.Column("mobile_hmac", sa.String(length=64), nullable=True),
        # PII: email ciphertext
        sa.Column("email_enc", sa.Text(), nullable=True),
        sa.Column("abha_link_status", sa.String(length=32), server_default=sa.text("'unlinked'"), nullable=False),
        sa.Column("preferred_language", sa.String(length=16), server_default=sa.text("'hi'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_patients_user_id"),
        sa.UniqueConstraint("aadhaar_hmac", name="uq_patients_aadhaar_hmac"),
        sa.UniqueConstraint("abha_number_hmac", name="uq_patients_abha_number_hmac"),
    )
    op.create_index("ix_patients_clinic_id", "patients", ["clinic_id"])
    op.create_index("ix_patients_mobile_hmac", "patients", ["mobile_hmac"])

    op.create_table(
        "consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notice_version", sa.String(length=64), nullable=False),
        sa.Column("capture_channel", sa.String(length=32), server_default=sa.text("'kiosk'"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patient_id", "purpose", name="uq_consents_patient_purpose"),
    )
    op.create_index("ix_consents_patient_id", "consents", ["patient_id"])

    op.create_table(
        "consent_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("consent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["consent_id"], ["consents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consent_events_consent_id", "consent_events", ["consent_id"])

    op.create_table(
        "interview_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kiosk_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'in_progress'"), nullable=False),
        sa.Column("language", sa.String(length=16), server_default=sa.text("'hi'"), nullable=False),
        sa.Column("current_step", sa.String(length=64), server_default=sa.text("'welcome'"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["kiosk_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interview_sessions_patient_id", "interview_sessions", ["patient_id"])
    op.create_index("ix_interview_sessions_clinic_id", "interview_sessions", ["clinic_id"])

    op.create_table(
        "clinical_intakes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chief_complaint", sa.Text(), nullable=True),
        sa.Column("site", sa.Text(), nullable=True),
        sa.Column("onset", sa.Text(), nullable=True),
        sa.Column("character", sa.Text(), nullable=True),
        sa.Column("radiation", sa.Text(), nullable=True),
        sa.Column("associations", sa.Text(), nullable=True),
        sa.Column("time_course", sa.Text(), nullable=True),
        sa.Column("exacerbating_relieving", sa.Text(), nullable=True),
        sa.Column("severity", sa.Integer(), nullable=True),
        sa.Column("red_flags", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        # PII: allergies ciphertext
        sa.Column("allergies_enc", sa.Text(), nullable=True),
        # PII: medications ciphertext
        sa.Column("medications_enc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_clinical_intakes_session"),
    )

    op.create_table(
        "ayush_intakes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("system", sa.String(length=32), nullable=False),
        sa.Column("prakriti", sa.String(length=64), nullable=True),
        sa.Column("vikriti", sa.String(length=64), nullable=True),
        sa.Column("agni", sa.String(length=64), nullable=True),
        sa.Column("nadi_notes", sa.Text(), nullable=True),
        sa.Column("dosha_scores", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("diet_sleep", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("branching_path", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_ayush_intakes_session"),
    )

    op.create_table(
        "triage_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("acuity", sa.String(length=32), nullable=False),
        sa.Column("queue_date", sa.Date(), nullable=False),
        sa.Column("queue_position", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_triage_assessments_session"),
        sa.UniqueConstraint("clinic_id", "queue_date", "queue_position", name="uq_triage_queue_slot"),
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("storage_tier", sa.String(length=32), server_default=sa.text("'temp_scan'"), nullable=False),
        sa.Column("object_path", sa.Text(), nullable=False),
        sa.Column("vault_opt_in", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ocr_job_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ocr_status", sa.String(length=32), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("ocr_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ciphertext_sha256", sa.String(length=64), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_documents_idempotency_key"),
        sa.UniqueConstraint("ocr_job_id", name="uq_documents_ocr_job_id"),
    )
    op.create_index("ix_documents_patient_id", "documents", ["patient_id"])
    op.create_index("ix_documents_session_id", "documents", ["session_id"])
    op.create_index("ix_documents_ocr_status", "documents", ["ocr_status"])

    op.create_table(
        "ocr_extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        # PII: OCR text ciphertext
        sa.Column("raw_text_enc", sa.Text(), nullable=True),
        # PII: structured OCR JSON ciphertext
        sa.Column("structured_enc", sa.Text(), nullable=True),
        sa.Column("vendor", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_ocr_extractions_document"),
    )

    op.create_table(
        "abdm_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("inbound_event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("signature_ok", sa.Boolean(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        # PII: webhook payload ciphertext (often includes ABHA)
        sa.Column("payload_enc", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inbound_event_id", name="uq_abdm_webhook_inbound_event_id"),
    )

    op.create_table(
        "fhir_bundles",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("bundle_type", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        # PII: FHIR Bundle JSON ciphertext
        sa.Column("bundle_enc", sa.Text(), nullable=False),
        sa.Column("abdm_request_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("abdm_request_id"),
    )
    op.create_index("ix_fhir_bundles_patient_id", "fhir_bundles", ["patient_id"])


def downgrade() -> None:
    op.drop_index("ix_fhir_bundles_patient_id", table_name="fhir_bundles")
    op.drop_table("fhir_bundles")
    op.drop_table("abdm_webhook_events")
    op.drop_table("ocr_extractions")
    op.drop_index("ix_documents_ocr_status", table_name="documents")
    op.drop_index("ix_documents_session_id", table_name="documents")
    op.drop_index("ix_documents_patient_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("triage_assessments")
    op.drop_table("ayush_intakes")
    op.drop_table("clinical_intakes")
    op.drop_index("ix_interview_sessions_clinic_id", table_name="interview_sessions")
    op.drop_index("ix_interview_sessions_patient_id", table_name="interview_sessions")
    op.drop_table("interview_sessions")
    op.drop_index("ix_consent_events_consent_id", table_name="consent_events")
    op.drop_table("consent_events")
    op.drop_index("ix_consents_patient_id", table_name="consents")
    op.drop_table("consents")
    op.drop_index("ix_patients_mobile_hmac", table_name="patients")
    op.drop_index("ix_patients_clinic_id", table_name="patients")
    op.drop_table("patients")
    op.drop_index("ix_users_clinic_id", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_table("users")
    op.drop_table("clinics")
