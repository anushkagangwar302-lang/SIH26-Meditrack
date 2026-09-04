# MediKiosk-Backend — Phase 1 foundations only.
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

Alembic, auth, AI, routes, workers, and tests are later phases. Do not call `create_all()`.
