"""
app/routers/installations.py – GitHub App installation management endpoints.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import GitHubInstallation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/installations", tags=["Installations"])
github_router = APIRouter(prefix="/api/github", tags=["GitHub App"])


class InstallationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    github_installation_id: int
    account_login: str
    account_type: str
    account_avatar_url: Optional[str] = None
    active: bool


@github_router.get("/install")
def install_github_app():
    """Redirect to the configured GitHub App installation page."""
    if not settings.github_app_slug:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App installation is not configured (missing GITHUB_APP_SLUG)",
        )
    return RedirectResponse(
        url=f"https://github.com/apps/{settings.github_app_slug}/installations/new",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.get("", response_model=List[InstallationOut])
def list_installations(db: Session = Depends(get_db)):
    """List all GitHub App installations."""
    rows = db.query(GitHubInstallation).filter_by(active=True).all()
    return rows


@router.get("/{installation_id}", response_model=InstallationOut)
def get_installation(installation_id: int, db: Session = Depends(get_db)):
    """Get installation details by GitHub installation ID."""
    row = db.query(GitHubInstallation).filter_by(github_installation_id=installation_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found")
    return row
