"""
app/schemas.py – Pydantic response/request schemas for the PRPilot API.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str
    environment: str
    github_app_configured: bool


# ---------------------------------------------------------------------------
# Pull Request Analysis – outbound (API response)
# ---------------------------------------------------------------------------
class PRAnalysisOut(BaseModel):
    """Frontend-compatible PR analysis payload."""

    model_config = ConfigDict(from_attributes=True)

    repoPrKey: str
    owner: str
    repo: str
    pr_number: int
    title: str
    author: str
    description: Optional[str] = None
    github_url: Optional[str] = None
    changed_files: List[str] = []
    changed_file_count: int = 0
    code_file_count: int = 0
    test_file_count: int = 0
    issue_linked: bool = False
    description_match: str
    change_relevance: str
    summary: List[str] = []
    checklist: List[str] = []
    recommendation: str
    timestamp: int  # Unix epoch

    @classmethod
    def from_orm_model(cls, row) -> "PRAnalysisOut":
        """Build from a PullRequestAnalysis ORM row."""
        return cls(
            repoPrKey=f"{row.repository.owner}/{row.repository.name}#{row.github_pr_number}",
            owner=row.repository.owner,
            repo=row.repository.name,
            pr_number=row.github_pr_number,
            title=row.title,
            author=row.author,
            description=row.description,
            github_url=row.github_url,
            changed_files=row.changed_files,
            changed_file_count=row.changed_file_count,
            code_file_count=row.code_file_count,
            test_file_count=row.test_file_count,
            issue_linked=row.issue_linked,
            description_match=row.description_match,
            change_relevance=row.change_relevance,
            summary=row.summary,
            checklist=row.checklist,
            recommendation=row.recommendation,
            timestamp=int(row.updated_at.timestamp()) if row.updated_at else 0,
        )


class PRListResponse(BaseModel):
    prs: List[PRAnalysisOut]


class PRDetailResponse(PRAnalysisOut):
    pass


# ---------------------------------------------------------------------------
# Dev endpoints
# ---------------------------------------------------------------------------
class SeedSamplesResponse(BaseModel):
    seeded: int
    message: str


class SamplePRPayload(BaseModel):
    """Minimal PR payload accepted by POST /api/dev/analyze-sample-pr."""

    owner: str = "demo-owner"
    repo: str = "demo-repo"
    pr_number: int = 99
    title: str = "Demo PR"
    description: Optional[str] = None
    author: str = "demo-user"
    github_url: str = "https://github.com/demo-owner/demo-repo/pull/99"
    head_sha: Optional[str] = None
    changed_files: List[str] = []


class AnalyzeSampleResponse(BaseModel):
    message: str
    repoPrKey: str
    recommendation: str


# ---------------------------------------------------------------------------
# Webhook accepted
# ---------------------------------------------------------------------------
class WebhookAcceptedResponse(BaseModel):
    accepted: bool


# ---------------------------------------------------------------------------
# Auth (OAuth, future)
# ---------------------------------------------------------------------------
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    github_login: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class MeResponse(BaseModel):
    user: Optional[UserOut] = None
    authenticated: bool
