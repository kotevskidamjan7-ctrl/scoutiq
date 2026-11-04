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
