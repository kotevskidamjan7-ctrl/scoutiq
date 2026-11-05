# ScoutIQ — AI Football Scouting & Transfer Optimization

University Software Engineering project. Real data (API-Football 2024/25 stats, Transfermarkt valuations to June 2026), position-specific scouting scores, and an OR-Tools MILP squad optimizer.

## Quick start (Windows, Docker Desktop)

```powershell
copy .env.example .env      # then fill in your values
docker compose up --build
```

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health and /api/v1/health/db

## Repository layout

- `backend/` — FastAPI app (`app/`), ingestion, tests
- `frontend/` — React + TypeScript (Phase 6)
- `docs/` — feasibility report scripts, design docs
- `data/`, `raw/` — local datasets and API cache (git-ignored)

## Data sources and attribution

API-Football (api-football.com), Transfermarkt via dcaribou/transfermarkt-datasets (academic, non-commercial use), ClubElo (clubelo.com).

## Frontend (Phase 6)

The web interface lives in `frontend/` (React, TypeScript, Vite, Tailwind).

```powershell
docker compose up -d          # the backend must be running on http://localhost:8000
cd frontend
npm install                   # first time only
npm run dev                   # open http://localhost:5173
npm test                      # unit tests for money parsing and the builder form
```

The dev server forwards `/api` to the backend, so no CORS setup is needed.
