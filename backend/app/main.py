"""ScoutIQ FastAPI application entry point."""

from fastapi import FastAPI

from app.api import admin, assistant, auth, errors, health, improve, optimize, players, scenarios
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AI football scouting and transfer optimization API.",
)

app.include_router(health.router, prefix=settings.api_prefix)
errors.register(app)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(optimize.router, prefix=settings.api_prefix)
app.include_router(improve.router, prefix=settings.api_prefix)
app.include_router(players.router, prefix=settings.api_prefix)
app.include_router(scenarios.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(assistant.router, prefix=settings.api_prefix)
