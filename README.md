# SIH26 MediTrack

Healthcare kiosk intake. Backend lives in [`MediKiosk-Backend/`](MediKiosk-Backend/),
frontend in [`frontend/dev-server/`](frontend/dev-server/).

## Local development

```bash
# backend (Postgres 16 + Redis 7 required, see MediKiosk-Backend/docker-compose.yml)
cd MediKiosk-Backend
cp .env.example .env
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload

# frontend (Node 22)
cd frontend/dev-server
cp .env.example .env
npm ci
npm run dev
```

Or run everything at once:

```bash
cp MediKiosk-Backend/.env.example MediKiosk-Backend/.env
docker compose up -d --build
```

## Deployment

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for Vercel, Netlify, Render, Railway, Fly.io,
Heroku, Docker and plain-Node instructions.
