"""
app/config.py – Pydantic Settings for PRPilot.

All values are read from environment variables (or .env file via python-dotenv).
Secrets are never hardcoded here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"
load_dotenv(ENV_FILE, override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────────────────
    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8010"
    frontend_origin: str = "http://127.0.0.1:8080"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./prpilot.db"

    # ── Session ──────────────────────────────────────────────────────────────
    session_secret: str = "change-me-in-production-use-a-long-random-secret"

    # ── GitHub App ───────────────────────────────────────────────────────────
    github_app_id: Optional[str] = None
    github_app_slug: Optional[str] = None
    github_private_key_value: Optional[str] = Field(default=None, validation_alias="GITHUB_PRIVATE_KEY")
    github_app_client_id: Optional[str] = None
    github_app_client_secret: Optional[str] = None
    github_app_private_key_path: str = "./secrets/github-app-private-key.pem"
    github_webhook_secret: Optional[str] = None
    github_oauth_callback_url: str = "http://127.0.0.1:8010/api/auth/github/callback"
    github_installation_id: Optional[int] = None
    github_owner: Optional[str] = None
    github_repo: Optional[str] = None

    # ── Development helpers ───────────────────────────────────────────────────
    local_development_mode: bool = True

    # ── Derived helpers (not from env) ────────────────────────────────────────
    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"

    @property
    def github_app_configured(self) -> bool:
        """True when the minimum GitHub App credentials are available."""
        if not self.github_app_id or not self.github_webhook_secret:
            return False
        key_path = Path(self.github_app_private_key_path)
        return key_path.exists() and key_path.is_file()

    @property
    def github_oauth_configured(self) -> bool:
        """True when the OAuth client settings are available."""
        return bool(self.github_app_client_id and self.github_app_client_secret and self.github_oauth_callback_url)

    @property
    def github_private_key(self) -> Optional[str]:
        """Load private key PEM on first use. Returns None if not configured."""
        if self.github_private_key_value:
            return self.github_private_key_value.replace("\\n", "\n")
        key_path = Path(self.github_app_private_key_path)
        if not key_path.is_absolute():
            key_path = BACKEND_DIR / key_path
        if key_path.exists() and key_path.is_file():
            return key_path.read_text(encoding="utf-8")
        return None


# Single application-wide settings instance
settings = Settings()
