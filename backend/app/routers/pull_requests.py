"""
app/routers/pull_requests.py – Pull Request analysis query endpoints.
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import PullRequestAnalysis, Repository
from app.schemas import PRAnalysisOut, PRDetailResponse, PRListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prs", tags=["Pull Requests"])


@router.get("", response_model=PRListResponse)
def list_pull_requests(db: Session = Depends(get_db)):
    """
    Return all stored PR analyses, sorted by most recently updated.
    Compatible with PRPilot frontend dashboard.
    """
    analyses = (
        db.query(PullRequestAnalysis)
        .options(joinedload(PullRequestAnalysis.repository))
        .order_by(PullRequestAnalysis.updated_at.desc())
        .all()
    )

    pr_items: List[PRAnalysisOut] = []
    for a in analyses:
        if a.repository:
            pr_items.append(PRAnalysisOut.from_orm_model(a))

    return PRListResponse(prs=pr_items)


@router.get("/{repository_owner}/{repository_name}/{pr_number}", response_model=PRDetailResponse)
def get_pull_request_analysis(
    repository_owner: str,
    repository_name: str,
    pr_number: int,
    db: Session = Depends(get_db),
):
    """
    Return detailed analysis result for a specific pull request.
    """
    repo = (
        db.query(Repository)
        .filter(
            Repository.owner.ilike(repository_owner),
            Repository.name.ilike(repository_name),
        )
        .first()
    )

    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repository_owner}/{repository_name}' not found",
        )

    analysis = (
        db.query(PullRequestAnalysis)
        .options(joinedload(PullRequestAnalysis.repository))
        .filter(
            PullRequestAnalysis.repository_id == repo.id,
            PullRequestAnalysis.github_pr_number == pr_number,
        )
        .first()
    )

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis for PR #{pr_number} not found in '{repository_owner}/{repository_name}'",
        )

    return PRDetailResponse.from_orm_model(analysis)
