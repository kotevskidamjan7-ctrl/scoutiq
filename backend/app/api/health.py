"""Health checks: is the API up, and can it reach PostgreSQL?"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    try:
        version = db.execute(text("SELECT version()")).scalar_one()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=f"Database unreachable: {exc.__class__.__name__}")
    return {"status": "ok", "database": version}
