"""Field-level encryption, JWT, password/OTP hashing.

DPDP Act 2023: Aadhaar/ABHA and other PII are encrypted at rest. Ciphertext
and hashes must never be written to app logs or exception messages. Use
hmac_lookup() for unique indexes — never unique-index plaintext PII.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError

# Argon2 hasher is thread-safe and holds no user data.
_password_hasher = PasswordHasher()


class Role(str, Enum):
    patient = "patient"
    kiosk = "kiosk"
    physician = "physician"
    admin = "admin"


TokenType = Literal["access", "refresh"]


class PIILogGuard:
    """Marker: never interpolate encrypt/decrypt inputs into logs."""


def _aes_key() -> bytes:
    raw = get_settings().FIELD_ENCRYPTION_KEY.get_secret_value()
    key = base64.urlsafe_b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("FIELD_ENCRYPTION_KEY must be 32 bytes urlsafe-base64")
    return key


def _hmac_key() -> bytes:
    raw = get_settings().PII_LOOKUP_HMAC_KEY.get_secret_value()
    key = base64.urlsafe_b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("PII_LOOKUP_HMAC_KEY must be 32 bytes urlsafe-base64")
    return key


def encrypt_pii(plaintext: str) -> str:
    """AES-256-GCM. Output: key_id:nonce_b64:ciphertext_b64 (includes tag)."""
    if not plaintext:
        raise ValueError("encrypt_pii refused empty plaintext")
    settings = get_settings()
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(_aes_key())
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return (
        f"{settings.FIELD_ENCRYPTION_KEY_ID}:"
        f"{base64.urlsafe_b64encode(nonce).decode()}:"
        f"{base64.urlsafe_b64encode(ct).decode()}"
    )


def decrypt_pii(token: str) -> str:
    """Decrypt field ciphertext. Never include token or plaintext in exceptions."""
    try:
        key_id, nonce_b64, ct_b64 = token.split(":", 2)
        nonce = base64.urlsafe_b64decode(nonce_b64)
        ct = base64.urlsafe_b64decode(ct_b64)
        aesgcm = AESGCM(_aes_key())
        return aesgcm.decrypt(nonce, ct, associated_data=None).decode("utf-8")
    except Exception as exc:
        raise ValueError("pii_decrypt_failed") from exc


def hmac_lookup(value: str) -> str:
    """Deterministic HMAC-SHA256 hex for unique constraints (ABHA/Aadhaar)."""
    normalized = value.strip().upper()
    digest = hmac.new(_hmac_key(), normalized.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_otp(otp: str) -> str:
    """One-way hash for OTP at rest. OTP is never stored or logged in plaintext."""
    return hmac.new(_hmac_key(), otp.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_otp(otp: str, otp_hash: str) -> bool:
    expected = hash_otp(otp)
    return hmac.compare_digest(expected, otp_hash)


def _encode_jwt(
    subject: str,
    role: Role,
    token_type: TokenType,
    extra: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if token_type == "access":
        ttl = timedelta(minutes=settings.JWT_ACCESS_TTL_MINUTES)
        secret = settings.JWT_SECRET_KEY.get_secret_value()
    else:
        ttl = timedelta(days=settings.JWT_REFRESH_TTL_DAYS)
        secret = settings.JWT_REFRESH_SECRET_KEY.get_secret_value()
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role.value,
        "typ": token_type,
        "iss": settings.JWT_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str, role: Role, extra: dict[str, Any] | None = None) -> str:
    return _encode_jwt(subject, role, "access", extra)


def create_refresh_token(subject: str, role: Role) -> str:
    return _encode_jwt(subject, role, "refresh")


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    settings = get_settings()
    secret = (
        settings.JWT_SECRET_KEY.get_secret_value()
        if expected_type == "access"
        else settings.JWT_REFRESH_SECRET_KEY.get_secret_value()
    )
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            options={"require": ["sub", "exp", "iat", "typ", "role", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError(code="invalid_token", message="Not authenticated") from exc
    if payload.get("typ") != expected_type:
        raise UnauthorizedError(code="invalid_token", message="Not authenticated")
    return payload
