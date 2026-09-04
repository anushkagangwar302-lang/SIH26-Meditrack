"""Auth routes, JWT principal, and the ABHA+consent gate for intake routes.

Wire later routers with:
    APIRouter(dependencies=[Depends(require_intake_session)])
Auth endpoints themselves are excluded from that dependency.
"""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import (
    claim_idempotency_key,
    get_db,
    idempotency_get,
    idempotency_store,
    lock_row_for_update,
    redis_lock,
    redis_session,
)
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from app.core.security import (
    Role,
    create_access_token,
    create_refresh_token,
    decode_token,
    encrypt_pii,
    hash_otp,
    hmac_lookup,
    verify_otp,
    verify_password,
)
from app.models.consent import Consent, ConsentEvent, ConsentPurpose, ConsentStatus
from app.models.user import AbhaLinkStatus, Clinic, Patient, User
from app.schemas.patient import (
    AbhaOtpRequestIn,
    AbhaOtpRequestOut,
    AbhaOtpVerifyIn,
    ConsentCaptureIn,
    ConsentOut,
    RefreshIn,
    SessionStatusOut,
    StaffLoginIn,
    TokenPair,
)
from app.utils.logger import get_audit_logger, get_logger, get_request_id

logger = get_logger("app.auth")
audit = get_audit_logger()

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)

# Treatment is the minimum purpose that unlocks clinical intake for a kiosk session.
_INTAKE_PURPOSE = ConsentPurpose.treatment


@dataclass
class Principal:
    user: User
    patient: Patient | None
    role: Role
    payload: dict[str, Any]


def _role_of(user: User) -> Role:
    return user.role if isinstance(user.role, Role) else Role(str(user.role))


def _token_pair(user: User, patient: Patient | None, treatment_ok: bool) -> TokenPair:
    settings = get_settings()
    role = _role_of(user)
    extra: dict[str, Any] = {}
    if user.clinic_id:
        extra["cid"] = str(user.clinic_id)
    if patient:
        extra["pid"] = str(patient.id)
    return TokenPair(
        access_token=create_access_token(str(user.id), role, extra),
        refresh_token=create_refresh_token(str(user.id), role),
        expires_in_seconds=settings.JWT_ACCESS_TTL_MINUTES * 60,
        patient_id=patient.id if patient else None,
        abha_linked=bool(patient and patient.abha_link_status == AbhaLinkStatus.linked.value),
        treatment_consent=treatment_ok,
    )


def _consent_is_live(row: Consent | None) -> bool:
    if row is None or row.status != ConsentStatus.granted.value:
        return False
    if row.expires_at is not None and row.expires_at <= datetime.now(timezone.utc):
        return False
    return True


async def _load_treatment_consent(session: AsyncSession, patient_id: UUID) -> Consent | None:
    stmt = select(Consent).where(
        Consent.patient_id == patient_id,
        Consent.purpose == _INTAKE_PURPOSE.value,
    )
    return (await session.execute(stmt)).scalars().first()


async def assert_consents(
    session: AsyncSession,
    patient_id: UUID,
    purposes: tuple[ConsentPurpose, ...],
) -> None:
    """Call before any PII decrypt. Reads current DB state (revokes take effect immediately)."""
    wanted = {p.value for p in purposes}
    stmt = select(Consent).where(Consent.patient_id == patient_id, Consent.purpose.in_(wanted))
    rows = list((await session.execute(stmt)).scalars())
    by_purpose = {r.purpose: r for r in rows}
    missing = []
    for purpose in purposes:
        if not _consent_is_live(by_purpose.get(purpose.value)):
            missing.append(purpose.value)
    if missing:
        raise ForbiddenError(
            code="consent_required",
            message="Required consent is not granted for this session",
        )


async def get_current_principal(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthorizedError()
    payload = decode_token(creds.credentials, "access")
    try:
        user_id = UUID(str(payload["sub"]))
    except ValueError as exc:
        raise UnauthorizedError() from exc
    stmt = (
        select(User)
        .options(selectinload(User.patient))
        .where(User.id == user_id)
    )
    user = (await session.execute(stmt)).scalars().first()
    if user is None or not user.is_active:
        raise UnauthorizedError(code="inactive", message="Not authenticated")
    role = _role_of(user)
    if role.value != payload.get("role"):
        raise UnauthorizedError()
    return Principal(user=user, patient=user.patient, role=role, payload=payload)


async def require_staff(principal: Annotated[Principal, Depends(get_current_principal)]) -> Principal:
    if principal.role not in {Role.kiosk, Role.physician, Role.admin}:
        raise ForbiddenError(code="staff_only", message="Staff role required")
    return principal


async def require_intake_session(
    principal: Annotated[Principal, Depends(get_current_principal)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    """ABHA linked + live treatment consent. Attach to every non-auth clinical router."""
    if principal.role != Role.patient or principal.patient is None:
        raise ForbiddenError(code="patient_session_required", message="Patient kiosk session required")
    patient = principal.patient
    if patient.abha_link_status != AbhaLinkStatus.linked.value:
        raise ForbiddenError(code="abha_required", message="ABHA login is required before intake")
    await assert_consents(session, patient.id, (_INTAKE_PURPOSE,))
    return principal


async def _send_abha_otp(identifier_kind: str, identifier: str) -> str:
    """Ask ABDM (or mock) to send an OTP. `identifier` is PII — never log it."""
    settings = get_settings()
    client_id = settings.ABDM_CLIENT_ID
    secret = settings.ABDM_CLIENT_SECRET.get_secret_value() if settings.ABDM_CLIENT_SECRET else ""
    if not client_id or not secret:
        if settings.is_production:
            raise ServiceUnavailableError(code="abdm_unconfigured", message="ABHA login is unavailable")
        return "mock"
    # Path is environment-specific (sandbox vs prod) — set ABDM_BASE_URL per deployment.
    url = f"{settings.ABDM_BASE_URL.rstrip('/')}/v3/enrollment/request/otp"
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(
                    url,
                    json={"kind": identifier_kind, "value": identifier},
                    headers={"X-Client-Id": client_id},
                )
            if response.status_code >= 500:
                last_error = ServiceUnavailableError(code="abdm_down", message="ABHA login is unavailable")
                continue
            if response.status_code >= 400:
                raise ServiceUnavailableError(code="abdm_rejected", message="ABHA login is unavailable")
            return "abdm"
        except httpx.HTTPError as exc:
            last_error = exc
        if attempt == 0:
            continue
    if settings.is_production:
        raise ServiceUnavailableError(code="abdm_down", message="ABHA login is unavailable") from last_error
    logger.warning("abdm_degraded_mock")
    return "mock"


async def _clinic_or_404(session: AsyncSession, clinic_id: UUID) -> Clinic:
    clinic = await session.get(Clinic, clinic_id)
    if clinic is None or not clinic.is_active:
        raise NotFoundError(code="clinic_not_found", message="Clinic not found")
    return clinic


@router.post("/staff/login", response_model=TokenPair)
async def staff_login(
    body: StaffLoginIn,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    stmt = select(User).options(selectinload(User.patient)).where(User.login_handle == body.login_handle)
    user = (await session.execute(stmt)).scalars().first()
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise UnauthorizedError(code="bad_credentials", message="Not authenticated")
    if not user.is_active or _role_of(user) == Role.patient:
        raise ForbiddenError()
    user.last_login_at = datetime.now(timezone.utc)
    audit.info("staff_login", user_id=str(user.id), role=_role_of(user).value)
    return _token_pair(user, user.patient, False)


@router.post("/abha/otp/request", response_model=AbhaOtpRequestOut)
async def abha_otp_request(
    body: AbhaOtpRequestIn,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AbhaOtpRequestOut:
    settings = get_settings()
    await _clinic_or_404(session, body.clinic_id)
    kind = "abha" if body.abha_number else "aadhaar"
    identifier = body.abha_number or body.aadhaar or ""
    abha_hmac = hmac_lookup(body.abha_number) if body.abha_number else None
    aadhaar_hmac = hmac_lookup(body.aadhaar) if body.aadhaar else None
    abha_enc = encrypt_pii(body.abha_number) if body.abha_number else None
    aadhaar_enc = encrypt_pii(body.aadhaar) if body.aadhaar else None
    delivery = await _send_abha_otp(kind, identifier)
    challenge_id = uuid.uuid4()
    if delivery == "mock":
        otp_plain = (settings.DEV_ABHA_OTP.get_secret_value() if settings.DEV_ABHA_OTP else "") or "246810"
        otp_hash = hash_otp(otp_plain)
    else:
        # ABDM sends the OTP to the patient. We only store a random verifier nonce
        # so verify still has a server-side challenge; production verify should
        # call ABDM confirm API (below).
        otp_hash = hash_otp(secrets.token_hex(8))
    payload = {
        "clinic_id": str(body.clinic_id),
        "abha_hmac": abha_hmac,
        "aadhaar_hmac": aadhaar_hmac,
        "abha_enc": abha_enc,
        "aadhaar_enc": aadhaar_enc,
        "otp_hash": otp_hash,
        "delivery": delivery,
        "kind": kind,
    }
    key = f"{settings.REDIS_PREFIX_SESSION}otp:{challenge_id}"
    await redis_session().set(key, json.dumps(payload), ex=settings.OTP_TTL_SECONDS)
    audit.info("abha_otp_requested", challenge_id=str(challenge_id), clinic_id=str(body.clinic_id))
    return AbhaOtpRequestOut(
        challenge_id=challenge_id,
        expires_in_seconds=settings.OTP_TTL_SECONDS,
        delivery=delivery,
    )


async def _confirm_abdm_otp(otp: str, delivery: str) -> None:
    settings = get_settings()
    if delivery == "mock":
        expected = (settings.DEV_ABHA_OTP.get_secret_value() if settings.DEV_ABHA_OTP else "") or "246810"
        if not verify_otp(otp, hash_otp(expected)):
            raise UnauthorizedError(code="bad_otp", message="Not authenticated")
        return
    client_id = settings.ABDM_CLIENT_ID
    secret = settings.ABDM_CLIENT_SECRET.get_secret_value() if settings.ABDM_CLIENT_SECRET else ""
    url = f"{settings.ABDM_BASE_URL.rstrip('/')}/v3/enrollment/confirm/otp"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                url,
                json={"otp_length": len(otp)},
                headers={"X-Client-Id": client_id or "", "X-Client-Secret": secret},
            )
        if response.status_code >= 400:
            raise UnauthorizedError(code="bad_otp", message="Not authenticated")
    except httpx.HTTPError as exc:
        if settings.is_production:
            raise ServiceUnavailableError(code="abdm_down", message="ABHA login is unavailable") from exc
        if not verify_otp(otp, hash_otp((settings.DEV_ABHA_OTP.get_secret_value() if settings.DEV_ABHA_OTP else "") or "246810")):
            raise UnauthorizedError(code="bad_otp", message="Not authenticated") from exc


async def _link_or_create_patient(
    session: AsyncSession,
    clinic_id: UUID,
    abha_hmac: str | None,
    aadhaar_hmac: str | None,
    abha_enc: str | None,
    aadhaar_enc: str | None,
) -> Patient:
    lock_name = f"abha:{abha_hmac or aadhaar_hmac}"
    async with redis_lock(lock_name, ttl_seconds=20):
        stmt = select(Patient)
        if abha_hmac:
            stmt = stmt.where(Patient.abha_number_hmac == abha_hmac)
        else:
            stmt = stmt.where(Patient.aadhaar_hmac == aadhaar_hmac)
        patient = await lock_row_for_update(session, stmt)
        if patient is not None:
            patient.abha_link_status = AbhaLinkStatus.linked.value
            if abha_hmac and patient.abha_number_hmac is None:
                patient.abha_number_hmac = abha_hmac
                patient.abha_number_enc = abha_enc
            if aadhaar_hmac and patient.aadhaar_hmac is None:
                patient.aadhaar_hmac = aadhaar_hmac
                patient.aadhaar_enc = aadhaar_enc
            if patient.user is None:
                await session.refresh(patient, attribute_names=["user"])
            return patient

        user = User(role=Role.patient.value, clinic_id=clinic_id, is_active=True)
        session.add(user)
        await session.flush()
        patient = Patient(
            user_id=user.id,
            clinic_id=clinic_id,
            abha_number_hmac=abha_hmac,
            abha_number_enc=abha_enc,
            aadhaar_hmac=aadhaar_hmac,
            aadhaar_enc=aadhaar_enc,
            abha_link_status=AbhaLinkStatus.linked.value,
        )
        session.add(patient)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                code="abha_link_race",
                message="Another replica linked this ABHA; retry OTP verify",
            ) from exc
        patient.user = user
        return patient


@router.post("/abha/otp/verify", response_model=TokenPair)
async def abha_otp_verify(
    body: AbhaOtpVerifyIn,
    session: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TokenPair:
    if not idempotency_key:
        raise AppError(code="idempotency_required", message="Idempotency-Key header is required", status_code=400)
    cached = await idempotency_get(f"abha-verify:{idempotency_key}")
    if cached:
        return TokenPair.model_validate_json(cached)
    claimed = await claim_idempotency_key(f"abha-verify:{idempotency_key}")
    if not claimed:
        raise ConflictError(code="idempotency_pending", message="Retry this request shortly")

    settings = get_settings()
    redis_key = f"{settings.REDIS_PREFIX_SESSION}otp:{body.challenge_id}"
    raw = await redis_session().get(redis_key)
    if not raw:
        raise UnauthorizedError(code="otp_expired", message="Not authenticated")
    challenge = json.loads(raw)
    if challenge["clinic_id"] != str(body.clinic_id):
        raise ForbiddenError()
    await _clinic_or_404(session, body.clinic_id)
    await _confirm_abdm_otp(body.otp, challenge.get("delivery", "mock"))
    if challenge.get("delivery") == "mock" and not verify_otp(body.otp, challenge["otp_hash"]):
        raise UnauthorizedError(code="bad_otp", message="Not authenticated")

    patient = await _link_or_create_patient(
        session,
        body.clinic_id,
        challenge.get("abha_hmac"),
        challenge.get("aadhaar_hmac"),
        challenge.get("abha_enc"),
        challenge.get("aadhaar_enc"),
    )
    if patient.user is None:
        loaded = await session.get(User, patient.user_id)
        patient.user = loaded
    treatment = await _load_treatment_consent(session, patient.id)
    pair = _token_pair(patient.user, patient, _consent_is_live(treatment))
    await redis_session().delete(redis_key)
    await idempotency_store(f"abha-verify:{idempotency_key}", pair.model_dump_json())
    audit.info("abha_login", user_id=str(patient.user_id), patient_id=str(patient.id))
    return pair


@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(
    body: RefreshIn,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    payload = decode_token(body.refresh_token, "refresh")
    user = (
        await session.execute(
            select(User).options(selectinload(User.patient)).where(User.id == UUID(str(payload["sub"])))
        )
    ).scalars().first()
    if user is None or not user.is_active:
        raise UnauthorizedError()
    treatment_ok = False
    if user.patient:
        treatment_ok = _consent_is_live(await _load_treatment_consent(session, user.patient.id))
    return _token_pair(user, user.patient, treatment_ok)


@router.post("/consent", response_model=ConsentOut)
async def capture_consent(
    body: ConsentCaptureIn,
    principal: Annotated[Principal, Depends(get_current_principal)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ConsentOut:
    if principal.role != Role.patient or principal.patient is None:
        raise ForbiddenError(code="patient_session_required", message="Patient session required to capture consent")
    if principal.patient.abha_link_status != AbhaLinkStatus.linked.value:
        raise ForbiddenError(code="abha_required", message="ABHA login is required before consent")
    patient_id = principal.patient.id
    now = datetime.now(timezone.utc)
    status = ConsentStatus.granted.value if body.granted else ConsentStatus.denied.value
    async with redis_lock(f"consent:{patient_id}:{body.purpose.value}", ttl_seconds=15):
        stmt = select(Consent).where(
            Consent.patient_id == patient_id,
            Consent.purpose == body.purpose.value,
        )
        row = await lock_row_for_update(session, stmt)
        if row is None:
            row = Consent(
                patient_id=patient_id,
                purpose=body.purpose.value,
                status=status,
                notice_version=body.notice_version,
                capture_channel=body.capture_channel,
                granted_at=now if body.granted else None,
                revoked_at=None if body.granted else now,
            )
            session.add(row)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    code="consent_race",
                    message="Consent was updated concurrently; retry",
                ) from exc
        else:
            row.status = status
            row.notice_version = body.notice_version
            row.capture_channel = body.capture_channel
            if body.granted:
                row.granted_at = now
                row.revoked_at = None
            else:
                row.revoked_at = now
        session.add(
            ConsentEvent(
                consent_id=row.id,
                actor_user_id=principal.user.id,
                action="grant" if body.granted else "deny",
                request_id=get_request_id(),
            )
        )
        await session.flush()
    audit.info(
        "consent_capture",
        patient_id=str(patient_id),
        purpose=body.purpose.value,
        granted=body.granted,
    )
    return ConsentOut.model_validate(row)


@router.get("/session", response_model=SessionStatusOut)
async def session_status(
    principal: Annotated[Principal, Depends(get_current_principal)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SessionStatusOut:
    patient = principal.patient
    abha_linked = bool(patient and patient.abha_link_status == AbhaLinkStatus.linked.value)
    treatment_ok = False
    if patient:
        treatment_ok = _consent_is_live(await _load_treatment_consent(session, patient.id))
    return SessionStatusOut(
        user_id=principal.user.id,
        role=principal.role.value,
        clinic_id=principal.user.clinic_id,
        patient_id=patient.id if patient else None,
        abha_linked=abha_linked,
        treatment_consent=treatment_ok,
        ready_for_intake=principal.role == Role.patient and abha_linked and treatment_ok,
    )


@router.get("/me", response_model=SessionStatusOut)
async def me(
    principal: Annotated[Principal, Depends(get_current_principal)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SessionStatusOut:
    return await session_status(principal, session)


@router.get("/intake-check")
async def intake_check(_principal: Annotated[Principal, Depends(require_intake_session)]) -> dict[str, bool]:
    """Probe for the ABHA+consent gate. Phase 6 routers should use the same Depends."""
    return {"ready": True}
