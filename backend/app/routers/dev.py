"""
app/routers/dev.py – Development & demo mode endpoints.

Only enabled when APP_ENV=development and LOCAL_DEVELOPMENT_MODE=true.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import analyzer
from app.database import get_db
from app.dependencies import dev_only_guard
from app.models import GitHubInstallation, PullRequestAnalysis, Repository
from app.schemas import (
    AnalyzeSampleResponse,
    SamplePRPayload,
    SeedSamplesResponse,
)
from app.worker import find_or_create_repository, upsert_analysis

router = APIRouter(
    prefix="/api/dev",
    tags=["Development & Demo"],
    dependencies=[Depends(dev_only_guard)],
)


@router.post("/seed-samples", response_model=SeedSamplesResponse)
def seed_sample_pull_requests(db: Session = Depends(get_db)):
    """
    Seed exactly three sample PR analyses covering the three possible recommendations:
    1. Ready for detailed review
    2. Needs fixes
    3. Needs attention
    """
    inst = db.query(GitHubInstallation).filter_by(github_installation_id=1001).first()
    if not inst:
        inst = GitHubInstallation(
            github_installation_id=1001,
            account_login="prpilot-demo",
            account_type="Organization",
            account_avatar_url="https://avatars.githubusercontent.com/u/9919?s=200&v=4",
            active=True,
        )
        db.add(inst)
        db.flush()

    # Create or get demo repository
    repo = find_or_create_repository(
        db=db,
        github_repository_id=987654321,
        owner="prpilot-demo",
        name="sample-service",
        full_name="prpilot-demo/sample-service",
        private=False,
        description="Demo repository for PRPilot hackathon presentation",
        installation_id=inst.id,
    )

    now = datetime.now(timezone.utc)

    # Sample 1: Ready for detailed review
    # Code changes + test changes + linked issue + high match
    sample_1_files = [
        "app/auth/service.py",
        "app/auth/validator.py",
        "tests/test_auth_service.py",
    ]
    sample_1_title = "Fix login validation and token expiry check"
    sample_1_desc = "Fixes #104. Validates user login credentials, prevents null token bypass, and adds comprehensive test suite."
    sample_1_result = analyzer.analyze_pr(sample_1_title, sample_1_desc, sample_1_files)

    upsert_analysis(
        db=db,
        repository=repo,
        pr_number=101,
        pr_id=100101,
        title=sample_1_title,
        author="alice-dev",
        description=sample_1_desc,
        github_url="https://github.com/prpilot-demo/sample-service/pull/101",
        head_sha="a1b2c3d4e5f67890123456789abcdef012345678",
        file_paths=sample_1_files,
        analysis_result=sample_1_result,
    )

    # Sample 2: Needs fixes
    # Code changes + NO test changes + partial description or missing issue link
    sample_2_files = [
        "app/payment/processor.py",
        "app/payment/stripe_client.py",
    ]
    sample_2_title = "Update stripe payment processor for webhook handling"
    sample_2_desc = "Modifies payment processor logic to handle newer webhook payloads. Needs tests before shipping."
    sample_2_result = analyzer.analyze_pr(sample_2_title, sample_2_desc, sample_2_files)

    upsert_analysis(
        db=db,
        repository=repo,
        pr_number=102,
        pr_id=100102,
        title=sample_2_title,
        author="bob-contributor",
        description=sample_2_desc,
        github_url="https://github.com/prpilot-demo/sample-service/pull/102",
        head_sha="b2c3d4e5f6a7890123456789abcdef0123456789",
        file_paths=sample_2_files,
        analysis_result=sample_2_result,
    )

    # Sample 3: Needs attention
    # Claiming bugfix or code changes but only changed markdown docs, or vague description
    sample_3_files = [
        "docs/setup.md",
        "README.md",
    ]
    sample_3_title = "Resolve critical database connection crash on startup"
    sample_3_desc = "Fixes bug in database connection pool initialization to prevent crash on startup."
    sample_3_result = analyzer.analyze_pr(sample_3_title, sample_3_desc, sample_3_files)

    upsert_analysis(
        db=db,
        repository=repo,
        pr_number=103,
        pr_id=100103,
        title=sample_3_title,
        author="charlie-docs",
        description=sample_3_desc,
        github_url="https://github.com/prpilot-demo/sample-service/pull/103",
        head_sha="c3d4e5f6a7b890123456789abcdef01234567890",
        file_paths=sample_3_files,
        analysis_result=sample_3_result,
    )

    return SeedSamplesResponse(
        seeded=3,
        message="Successfully seeded 3 sample PR analyses (Ready for review, Needs fixes, Needs attention)",
    )


@router.post("/analyze-sample-pr", response_model=AnalyzeSampleResponse)
def analyze_sample_pr(payload: SamplePRPayload, db: Session = Depends(get_db)):
    """
    Analyze and save a custom sample PR without triggering a real GitHub webhook.
    Useful for interactive local testing and hackathon demonstrations.
    """
    full_name = f"{payload.owner}/{payload.repo}"
    repo = find_or_create_repository(
        db=db,
        github_repository_id=hash(full_name) & 0x7FFFFFFF,
        owner=payload.owner,
        name=payload.repo,
        full_name=full_name,
        private=False,
        description="Local sample repository",
        installation_id=None,
    )

    result = analyzer.analyze_pr(
        title=payload.title,
        description=payload.description or "",
        file_paths=payload.changed_files,
    )

    upsert_analysis(
        db=db,
        repository=repo,
        pr_number=payload.pr_number,
        pr_id=None,
        title=payload.title,
        author=payload.author,
        description=payload.description,
        github_url=payload.github_url,
        head_sha=payload.head_sha,
        file_paths=payload.changed_files,
        analysis_result=result,
    )

    return AnalyzeSampleResponse(
        message="Sample PR analyzed and stored successfully",
        repoPrKey=f"{payload.owner}/{payload.repo}#{payload.pr_number}",
        recommendation=result["recommendation"],
    )
