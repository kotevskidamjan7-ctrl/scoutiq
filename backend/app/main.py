"""ScoutIQ FastAPI application entry point."""

from fastapi import FastAPI

from app.api import health, optimize
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AI football scouting and transfer optimization API.",
)

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(optimize.router, prefix=settings.api_prefix)
