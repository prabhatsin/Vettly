# Voice Interview Platform

Candidates upload a résumé and take a voice interview with an AI interviewer. Employers see scored reports and replays.

## Stack
FastAPI (api) · LiveKit Agents (agent) · Next.js (web) · Postgres · Redis · LiveKit server

## Prerequisites
Docker, Python 3.11+, Node 20+

## Setup (once)
1. Copy `.env.example` to `.env` and fill in real values.
   Special characters in the password must be URL-encoded inside `DATABASE_URL` (`@` becomes `%40`).
2. Create `web/.env.local` with `NEXT_PUBLIC_API_URL=http://localhost:8000`.
3. API: `cd api && python -m venv api_venv && source api_venv/bin/activate && pip install -r requirements.txt`
4. Web: `cd web && npm install`

## Run
```
docker compose up -d                          # Postgres, Redis, LiveKit
cd api && uvicorn app.main:app --reload       # API on :8000
cd web && npm run dev                         # Web on :3000
```

## Check it works
- `http://localhost:3000` shows green badges for API, Postgres, Redis
- `http://localhost:8000/docs` shows Swagger
- `curl localhost:7880` returns `OK`

## Troubleshooting
- Port 5432 or 6379 already in use: a local Postgres/Redis is running. Stop and disable it, or change the host port in `docker-compose.yml`.
- `docker.sock` error: Docker is not running.