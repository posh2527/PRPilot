"""
app/models.py – SQLAlchemy ORM models.

Uses SQLite now; DATABASE_URL can be pointed at PostgreSQL without changes here.
All DateTime columns store UTC timestamps.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    github_user_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    github_login: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    installations: Mapped[list["GitHubInstallation"]] = relationship(
        "GitHubInstallation", back_populates="owner_user"
    )

    def __repr__(self) -> str:
        return f"<User {self.github_login}>"


# ---------------------------------------------------------------------------
# GitHubInstallation
# ---------------------------------------------------------------------------
class GitHubInstallation(Base):
    __tablename__ = "github_installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    github_installation_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    account_login: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(64), nullable=False, default="Organization")
    account_avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner_user: Mapped["User | None"] = relationship("User", back_populates="installations")
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository", back_populates="installation"
    )

    def __repr__(self) -> str:
        return f"<GitHubInstallation {self.account_login} #{self.github_installation_id}>"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    github_repository_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    installation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("github_installations.id", ondelete="SET NULL"), nullable=True
    )
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    installation: Mapped["GitHubInstallation | None"] = relationship(
        "GitHubInstallation", back_populates="repositories"
    )
    analyses: Mapped[list["PullRequestAnalysis"]] = relationship(
        "PullRequestAnalysis", back_populates="repository"
    )

    def __repr__(self) -> str:
        return f"<Repository {self.full_name}>"


# ---------------------------------------------------------------------------
# PullRequestAnalysis
# ---------------------------------------------------------------------------
class PullRequestAnalysis(Base):
    __tablename__ = "pull_request_analyses"
    __table_args__ = (
        UniqueConstraint("repository_id", "github_pr_number", name="uq_repo_pr"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    repository_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    github_pr_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Changed files stored as JSON array of file paths
    changed_files_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Counts
    changed_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    code_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    test_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Analysis flags
    issue_linked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description_match: Mapped[str] = mapped_column(String(32), nullable=False, default="Low")
    change_relevance: Mapped[str] = mapped_column(String(32), nullable=False, default="Low")

    # JSON columns for lists
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    checklist_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    recommendation: Mapped[str] = mapped_column(String(64), nullable=False, default="Needs attention")
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    repository: Mapped["Repository"] = relationship("Repository", back_populates="analyses")

    # ── Helpers ─────────────────────────────────────────────────────────────
    @property
    def changed_files(self) -> list[str]:
        if not self.changed_files_json:
            return []
        try:
            return json.loads(self.changed_files_json)
        except (ValueError, TypeError):
            return []

    @changed_files.setter
    def changed_files(self, value: list[str]) -> None:
        self.changed_files_json = json.dumps(value)

    @property
    def summary(self) -> list[str]:
        if not self.summary_json:
            return []
        try:
            return json.loads(self.summary_json)
        except (ValueError, TypeError):
            return []

    @summary.setter
    def summary(self, value: list[str]) -> None:
        self.summary_json = json.dumps(value)

    @property
    def checklist(self) -> list[str]:
        if not self.checklist_json:
            return []
        try:
            return json.loads(self.checklist_json)
        except (ValueError, TypeError):
            return []

    @checklist.setter
    def checklist(self, value: list[str]) -> None:
        self.checklist_json = json.dumps(value)

    def __repr__(self) -> str:
        return f"<PullRequestAnalysis repo={self.repository_id} pr=#{self.github_pr_number}>"


# ---------------------------------------------------------------------------
# WebhookDelivery
# ---------------------------------------------------------------------------
class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    github_delivery_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<WebhookDelivery {self.github_delivery_id} {self.status}>"
