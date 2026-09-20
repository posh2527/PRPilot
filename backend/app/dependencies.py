"""
app/dependencies.py – FastAPI dependency injectors.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db


def get_settings():
    return settings


def dev_only_guard(s=Depends(get_settings)):
    """
    Dependency that raises HTTP 404 if the app is not in local development mode.
    This prevents development endpoints from being accessible in production.
    """
    from fastapi import HTTPException

    if not (s.is_development and s.local_development_mode):
        raise HTTPException(status_code=404, detail="Not found")
