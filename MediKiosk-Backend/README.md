# MediKiosk-Backend — Phases 0–3 (foundations, data layer, auth/consent).
# Full setup, scaling, and go-live checklist land in Phase 9.

This repository folder is the FastAPI backend for SIH26 MediTrack.

## Phase 1 quick start (connectivity)

```bash
cd MediKiosk-Backend
cp .env.example .env
# Replace every CHANGE_ME value. Generate encryption/JWT keys:
python3 -c "import os,base64,secrets; print('JWT', secrets.token_urlsafe(64)); print('JWT_R', secrets.token_urlsafe(64)); print('ENC', base64.urlsafe_b64encode(os.urandom(32)).decode()); print('HMAC', base64.urlsafe_b64encode(os.urandom(32)).decode())"
docker compose up --build
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/readyz
```

## Phase 2 — migrations

Never call `create_all()`. Apply schema with Alembic (uses `DATABASE_URL` from `.env`, swapped to psycopg2):

```bash
cd MediKiosk-Backend
alembic upgrade head
```

Auth, AI, remaining routes, workers, and tests are later phases.

## Phase 3 — auth & consent

1. `alembic upgrade head` (includes `users.login_handle`).
2. Insert an active `clinics` row and a staff user (`role=kiosk|physician|admin`, `login_handle`, `password_hash` via Argon2) before staff login.
3. Patient flow: `POST /api/v1/auth/abha/otp/request` → `POST /api/v1/auth/abha/otp/verify` (header `Idempotency-Key`) → `POST /api/v1/auth/consent` with `purpose=treatment` → `GET /api/v1/auth/intake-check`.
4. Later clinical routers must use `Depends(require_intake_session)`.
5. With empty ABDM keys, development uses `DEV_ABHA_OTP` (default `246810`). Production refuses a configured mock OTP.