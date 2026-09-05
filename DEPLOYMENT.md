# Deploying MediTrack

Two deployable units:

| Unit | Path | Runtime |
| --- | --- | --- |
| Frontend (TanStack Start SSR) | `frontend/dev-server` | Node 22, Nitro output |
| Backend (FastAPI + Celery) | `MediKiosk-Backend` | Python 3.12, Postgres 16, Redis 7 |

The frontend build target is chosen by Nitro through `NITRO_PRESET`; every platform
config below only sets that variable and the build/install commands.

## Required environment

### Frontend

| Variable | Notes |
| --- | --- |
| `VITE_API_BASE_URL` | Public backend URL, e.g. `https://api.example.com`. Empty means same-origin `/api/v1`. |
| `NITRO_PRESET` | Set by the platform config (`vercel`, `netlify`, `node`, ...). |

Only `VITE_`-prefixed variables reach the browser bundle. Never put secrets there.

### Backend

Copy `MediKiosk-Backend/.env.example` and set at minimum:

`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `JWT_REFRESH_SECRET_KEY`,
`FIELD_ENCRYPTION_KEY`, `PII_LOOKUP_HMAC_KEY`, `CORS_ORIGINS`.

Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(64))"`
and `FIELD_ENCRYPTION_KEY` with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Store them in the platform's secret manager — never in the repo.

Run `alembic upgrade head` on every release; each platform config below wires this
as a release/pre-deploy command.

## Platforms

### Vercel (frontend)

Import the repo, set **Root Directory** to `frontend/dev-server`. `vercel.json` there
pins `NITRO_PRESET=vercel`, `npm ci`, and `npm run build`. Add `VITE_API_BASE_URL` as a
project environment variable. The backend is not deployable on Vercel (long-lived
workers, Postgres pooling, OCR binaries) — pair it with Render/Railway/Fly.

### Netlify (frontend)

`netlify.toml` at the repo root sets base `frontend/dev-server`, Node 22 and
`NITRO_PRESET=netlify`. Connect the repo; no further config needed.

### Render (full stack)

`render.yaml` is a Blueprint covering Postgres, Redis, the API, the Celery worker,
Celery beat, and the frontend. Create a new Blueprint instance from the repo and fill
the `sync: false` secrets when prompted.

### Railway (backend)

`MediKiosk-Backend/railway.json` builds the backend Dockerfile, runs migrations before
start and health-checks `/healthz`. Add Postgres and Redis plugins and set the
remaining secrets. Point the service root at `MediKiosk-Backend`.

### Fly.io (backend)

```bash
cd MediKiosk-Backend
fly launch --no-deploy            # reuses fly.toml
fly secrets set JWT_SECRET_KEY=... JWT_REFRESH_SECRET_KEY=... FIELD_ENCRYPTION_KEY=... PII_LOOKUP_HMAC_KEY=...
fly volumes create medikiosk_uploads --size 10
fly deploy
```

`fly.toml` declares the `app`, `worker` and `beat` processes and the uploads volume.

### Heroku / buildpack platforms (backend)

`MediKiosk-Backend/app.json` describes the formation and addons; `Procfile` declares
`release`, `web`, `worker` and `beat`; `runtime.txt` pins Python 3.12.8 and `Aptfile`
installs Tesseract and `libmagic1`.

### Docker / self-hosted (full stack)

```bash
cp MediKiosk-Backend/.env.example MediKiosk-Backend/.env   # then edit
docker compose up -d --build
```

The root `docker-compose.yml` includes the backend compose file (Postgres, Redis,
API replicas, Nginx, worker, beat) and adds the frontend container on port 3000.
Images can also be built individually:

```bash
docker build -t meditrack-frontend ./frontend/dev-server
docker build -t meditrack-backend ./MediKiosk-Backend
```

### Any Node host (frontend)

```bash
cd frontend/dev-server
npm ci && npm run build:node
npm start        # node .output/server/index.mjs, honours PORT/HOST
```

## Post-deploy checks

```bash
curl -f https://<backend>/healthz     # process liveness
curl -f https://<backend>/readyz      # DB + Redis reachable
curl -f https://<frontend>/           # SSR shell
```
