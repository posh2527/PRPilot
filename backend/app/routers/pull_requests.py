"""
app/routers/pull_requests.py – Pull Request analysis query endpoints.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app import analyzer, github_client
from app.config import settings
from app.models import PullRequestAnalysis, Repository
from app.schemas import PRAnalysisOut, PRDetailResponse, PRListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prs", tags=["Pull Requests"])


@router.get("", response_model=PRListResponse)
async def list_pull_requests(db: Session = Depends(get_db)):
    """
    Return live open pull requests from the configured GitHub App installation.
    """
    missing = [
        name for name, value in (
            ("GITHUB_APP_ID", settings.github_app_id),
            ("GITHUB_INSTALLATION_ID", settings.github_installation_id),
            ("GITHUB_OWNER", settings.github_owner),
            ("GITHUB_REPO", settings.github_repo),
        ) if not value
    ]
    if missing or not settings.github_private_key:
        analyses = (
            db.query(PullRequestAnalysis)
            .options(joinedload(PullRequestAnalysis.repository))
            .order_by(PullRequestAnalysis.updated_at.desc())
            .all()
        )
        if analyses:
            return PRListResponse(prs=[PRAnalysisOut.from_orm_model(a) for a in analyses if a.repository])

        if settings.local_development_mode:
            from app.routers.dev import seed_sample_pull_requests
            seed_sample_pull_requests(db=db)
            analyses = (
                db.query(PullRequestAnalysis)
                .options(joinedload(PullRequestAnalysis.repository))
                .order_by(PullRequestAnalysis.updated_at.desc())
                .all()
            )
            return PRListResponse(prs=[PRAnalysisOut.from_orm_model(a) for a in analyses if a.repository])

        if not settings.github_private_key:
            missing.append("GITHUB_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Live GitHub PR integration is not configured: missing {', '.join(missing)}",
        )

    try:
        github_prs = await github_client.get_open_pull_requests(
            settings.github_owner,
            settings.github_repo,
            settings.github_installation_id,
        )
    except github_client.GitHubAppError as exc:
        logger.warning("GitHub App authentication failed while listing pull requests: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub App authentication failed.") from exc
    except httpx.HTTPError as exc:
        logger.warning("GitHub API request failed while listing pull requests: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub API request failed.") from exc

    return PRListResponse(prs=[map_github_pull_request(item) for item in github_prs])


def map_github_pull_request(pull_request: dict) -> PRAnalysisOut:
    """Map GitHub pull-request data to the frontend response contract."""
    owner = settings.github_owner or ""
    repo = settings.github_repo or ""
    number = int(pull_request.get("number") or 0)
    title = pull_request.get("title") or "Untitled pull request"
    description = pull_request.get("body") or ""
    changed_files = [path for path in pull_request.get("changed_files", []) if isinstance(path, str)]
    analysis = analyzer.analyze_pr(title, description, changed_files)
    timestamp = parse_github_timestamp(pull_request.get("updated_at") or pull_request.get("created_at"))
    return PRAnalysisOut(
        repoPrKey=f"{owner}/{repo}#{number}",
        owner=owner,
        repo=repo,
        pr_number=number,
        title=title,
        author=(pull_request.get("user") or {}).get("login", "Unknown contributor"),
        description=description,
        github_url=pull_request.get("html_url"),
        changed_files=changed_files,
        changed_file_count=analysis["changed_file_count"],
        code_file_count=analysis["code_file_count"],
        test_file_count=analysis["test_file_count"],
        issue_linked=analysis["issue_linked"],
        description_match=analysis["description_match"],
        change_relevance=analysis["change_relevance"],
        summary=analysis["summary"],
        checklist=analysis["checklist"],
        recommendation=analysis["recommendation"],
        timestamp=timestamp,
    )


def parse_github_timestamp(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return 0


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
