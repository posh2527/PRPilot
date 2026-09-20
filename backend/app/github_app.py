"""
app/github_app.py – GitHub App authentication.

Generates short-lived RS256 JWTs and exchanges them for installation access tokens.
Tokens are kept server-side only and are NEVER returned to the frontend.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx
import jwt  # PyJWT

from app.config import settings

logger = logging.getLogger(__name__)

# GitHub API base URL – override in tests if needed
GITHUB_API_BASE = "https://api.github.com"

# JWT max lifetime per GitHub documentation (10 minutes minus a small buffer)
_JWT_LIFETIME_SECONDS = 540  # 9 minutes


class GitHubAppError(Exception):
    """Raised when GitHub App authentication fails."""


def _generate_jwt() -> str:
    """
    Create a short-lived RS256 JWT signed with the GitHub App private key.

    Raises GitHubAppError if the private key or App ID is not configured.
    """
    private_key = settings.github_private_key
    app_id = settings.github_app_id

    if not private_key:
        raise GitHubAppError(
            "GitHub App private key not found. "
            f"Set GITHUB_APP_PRIVATE_KEY_PATH (currently: {settings.github_app_private_key_path})"
        )
    if not app_id:
        raise GitHubAppError("GITHUB_APP_ID is not configured.")

    now = int(time.time())
    payload = {
        "iat": now - 60,  # issued 60 s in the past to account for clock skew
        "exp": now + _JWT_LIFETIME_SECONDS,
        "iss": str(app_id),
    }
    token: str = jwt.encode(payload, private_key, algorithm="RS256")
    # PyJWT >= 2.x returns str; older versions returned bytes
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


async def get_installation_access_token(installation_id: int) -> str:
    """
    Exchange a GitHub App JWT for a short-lived installation access token.

    The token is returned as a plain string and must NEVER be passed to the frontend.
    Raises GitHubAppError on failure.
    """
    app_jwt = _generate_jwt()
    url = f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PRPilot/1.0",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, headers=headers)

    if response.status_code == 401:
        # The JWT may have expired; surface a clear error (do NOT log the JWT)
        raise GitHubAppError(
            f"GitHub returned 401 when requesting installation token for installation {installation_id}. "
            "Check that GITHUB_APP_ID and private key are correct."
        )

    if response.status_code != 201:
        raise GitHubAppError(
            f"GitHub returned HTTP {response.status_code} for installation token request."
        )

    data = response.json()
    token = data.get("token")
    if not token:
        raise GitHubAppError("GitHub returned an installation token response without a token field.")

    # SECURITY: log only non-sensitive metadata, never the token itself
    expires_at = data.get("expires_at", "unknown")
    logger.info("Installation token obtained for installation_id=%d, expires_at=%s", installation_id, expires_at)

    return token
