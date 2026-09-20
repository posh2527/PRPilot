"""
app/routers/repositories.py – Repository management endpoints.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repositories", tags=["Repositories"])


class RepositoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    github_repository_id: int
    owner: str
    name: str
    full_name: str
    private: bool
    description: Optional[str] = None
    active: bool


@router.get("", response_model=List[RepositoryOut])
def list_repositories(db: Session = Depends(get_db)):
    """List all registered repositories."""
    rows = db.query(Repository).filter_by(active=True).all()
    return rows


@router.get("/{owner}/{repo_name}", response_model=RepositoryOut)
def get_repository(owner: str, repo_name: str, db: Session = Depends(get_db)):
    """Get repository details by owner and repo name."""
    row = (
        db.query(Repository)
        .filter(Repository.owner.ilike(owner), Repository.name.ilike(repo_name))
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    return row
