"""
app/worker.py – Webhook processing logic (separated from the HTTP layer).

This module contains the business logic that runs after a webhook is validated.
It is deliberately separated from the router so it can later be moved to
a background queue (Celery, SQS, Lambda) without touching the HTTP layer.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app import analyzer
from app.config import settings
from app.models import GitHubInstallation, PullRequestAnalysis, Repository, WebhookDelivery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Delivery tracking
# ---------------------------------------------------------------------------

def delivery_already_processed(db: Session, delivery_id: str) -> bool:
    row = db.query(WebhookDelivery).filter_by(github_delivery_id=delivery_id).first()
    return row is not None and row.status == "processed"


def save_delivery(db: Session, delivery_id: str, event_name: str, action: str | None) -> WebhookDelivery:
    row = db.query(WebhookDelivery).filter_by(github_delivery_id=delivery_id).first()
    if row is None:
        row = WebhookDelivery(
            github_delivery_id=delivery_id,
            event_name=event_name,
            action=action,
            status="received",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def mark_delivery_processed(db: Session, delivery_id: str) -> None:
    row = db.query(WebhookDelivery).filter_by(github_delivery_id=delivery_id).first()
    if row:
        row.status = "processed"
        row.processed_at = datetime.now(timezone.utc)
        db.commit()


def mark_delivery_failed(db: Session, delivery_id: str, error: str) -> None:
    row = db.query(WebhookDelivery).filter_by(github_delivery_id=delivery_id).first()
    if row:
        row.status = "failed"
        row.error_message = error[:2000]
        db.commit()


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------

def find_or_create_repository(
    db: Session,
    github_repository_id: int,
    owner: str,
    name: str,
    full_name: str,
    private: bool,
    description: str | None,
    installation_id: int | None,
) -> Repository:
    repo = (
        db.query(Repository)
        .filter_by(github_repository_id=github_repository_id)
        .first()
    )
    db_installation_id: int | None = None
    if installation_id is not None:
        inst = db.query(GitHubInstallation).filter_by(github_installation_id=installation_id).first()
        if inst:
            db_installation_id = inst.id

    if repo is None:
        repo = Repository(
            github_repository_id=github_repository_id,
            installation_id=db_installation_id,
            owner=owner,
            name=name,
            full_name=full_name,
            private=private,
            description=description,
            active=True,
        )
        db.add(repo)
        db.commit()
        db.refresh(repo)
    return repo


# ---------------------------------------------------------------------------
# Analysis upsert
# ---------------------------------------------------------------------------

def upsert_analysis(
    db: Session,
    repository: Repository,
    pr_number: int,
    pr_id: int | None,
    title: str,
    author: str,
    description: str | None,
    github_url: str | None,
    head_sha: str | None,
    file_paths: list[str],
    analysis_result: dict,
) -> PullRequestAnalysis:
    """Create or update a PullRequestAnalysis record (upsert by repository_id + github_pr_number)."""
    row = (
        db.query(PullRequestAnalysis)
        .filter_by(repository_id=repository.id, github_pr_number=pr_number)
        .first()
    )

    if row is None:
        row = PullRequestAnalysis(repository_id=repository.id, github_pr_number=pr_number)
        db.add(row)

    row.github_pr_id = pr_id
    row.title = title
    row.author = author
    row.description = description
    row.github_url = github_url
    row.head_sha = head_sha
    row.changed_files = file_paths
    row.changed_file_count = analysis_result["changed_file_count"]
    row.code_file_count = analysis_result["code_file_count"]
    row.test_file_count = analysis_result["test_file_count"]
    row.issue_linked = analysis_result["issue_linked"]
    row.description_match = analysis_result["description_match"]
    row.change_relevance = analysis_result["change_relevance"]
    row.summary = analysis_result["summary"]
    row.checklist = analysis_result["checklist"]
    row.recommendation = analysis_result["recommendation"]
    row.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Pull-request webhook processor
# ---------------------------------------------------------------------------

async def process_pull_request_event(
    db: Session,
    payload: dict[str, Any],
    delivery_id: str,
    event_name: str,
) -> None:
    """
    Full processing pipeline for a pull_request webhook event.

    Steps:
    1. Check for duplicate delivery.
    2. Save delivery record.
    3. Extract PR data.
    4. Find or create repository record.
    5. Obtain installation token (if GitHub App is configured).
    6. Fetch changed files from GitHub (or use empty list in demo mode).
    7. Analyze the PR.
    8. Upsert PullRequestAnalysis.
    9. Create or update the PRPilot GitHub comment.
    10. Mark delivery as processed.
    """
    action = payload.get("action", "")

    # 1. Duplicate check
    if delivery_already_processed(db, delivery_id):
        logger.info("Duplicate delivery ignored: %s", delivery_id)
        return

    # 2. Save delivery record
    save_delivery(db, delivery_id, event_name, action)

    try:
        # 3. Extract PR data
        pr = payload.get("pull_request") or {}
        repo_data = payload.get("repository") or {}
        installation_data = payload.get("installation") or {}

        github_installation_id: int | None = installation_data.get("id")
        full_name: str = repo_data.get("full_name") or ""
        owner, _, repo_name = full_name.partition("/")
        repo_name = repo_name or repo_data.get("name", "")

        pr_number = int(pr.get("number") or 0)
        pr_id = pr.get("id")
        title = pr.get("title") or ""
        description = pr.get("body") or ""
        author = (pr.get("user") or {}).get("login", "")
        github_url = pr.get("html_url") or ""
        head_sha = (pr.get("head") or {}).get("sha")

        # 4. Find or create repository
        repository = find_or_create_repository(
            db=db,
            github_repository_id=int(repo_data.get("id") or 0),
            owner=owner,
            name=repo_name,
            full_name=full_name,
            private=bool(repo_data.get("private")),
            description=repo_data.get("description"),
            installation_id=github_installation_id,
        )

        # 5 & 6. Fetch changed files
        file_paths: list[str] = []
        comment_status = "skipped:no_github_app"

        if settings.github_app_configured and github_installation_id:
            try:
                from app.github_client import (
                    create_or_update_review_comment,
                    get_pull_request_files,
                )

                file_paths = await get_pull_request_files(
                    owner, repo_name, pr_number, github_installation_id
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not fetch changed files: %s", exc)
                file_paths = []
        else:
            logger.info(
                "GitHub App not configured – skipping file fetch for %s#%d",
                full_name,
                pr_number,
            )

        # 7. Analyze
        analysis_result = analyzer.analyze_pr(title, description, file_paths)

        # 8. Upsert
        upsert_analysis(
            db=db,
            repository=repository,
            pr_number=pr_number,
            pr_id=pr_id,
            title=title,
            author=author,
            description=description,
            github_url=github_url,
            head_sha=head_sha,
            file_paths=file_paths,
            analysis_result=analysis_result,
        )

        # 9. Post/update GitHub comment
        if settings.github_app_configured and github_installation_id:
            try:
                from app.github_client import create_or_update_review_comment

                comment_payload = {**analysis_result, "owner": owner, "repo": repo_name}
                comment_status = await create_or_update_review_comment(
                    owner=owner,
                    repo=repo_name,
                    number=pr_number,
                    analysis=comment_payload,
                    installation_id=github_installation_id,
                )
            except Exception as exc:  # noqa: BLE001
                # Log safely – never expose token
                logger.warning("Comment creation failed: %s", exc)
                comment_status = "failed"

        logger.info(
            "Processed %s#%d – recommendation=%s comment=%s",
            full_name,
            pr_number,
            analysis_result["recommendation"],
            comment_status,
        )

        # 10. Mark processed
        mark_delivery_processed(db, delivery_id)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Error processing webhook delivery %s", delivery_id)
        mark_delivery_failed(db, delivery_id, str(exc))


# ---------------------------------------------------------------------------
# Installation event processor
# ---------------------------------------------------------------------------

def process_installation_event(db: Session, payload: dict[str, Any]) -> None:
    """Handle installation created/deleted/suspended events."""
    action = payload.get("action", "")
    installation = payload.get("installation") or {}
    account = installation.get("account") or {}
    github_installation_id = installation.get("id")

    if not github_installation_id:
        return

    row = (
        db.query(GitHubInstallation)
        .filter_by(github_installation_id=github_installation_id)
        .first()
    )

    if action == "created":
        if row is None:
            row = GitHubInstallation(
                github_installation_id=github_installation_id,
                account_login=account.get("login", ""),
                account_type=account.get("type", "Organization"),
                account_avatar_url=account.get("avatar_url"),
                active=True,
            )
            db.add(row)
            db.commit()
            logger.info("Recorded new installation %d for %s", github_installation_id, account.get("login"))

    elif action in ("deleted", "unsuspend"):
        if row:
            row.active = action != "deleted"
            row.suspended_at = None if action == "unsuspend" else None
            db.commit()

    elif action == "suspend":
        if row:
            row.active = False
            row.suspended_at = datetime.now(timezone.utc)
            db.commit()
