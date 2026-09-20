"""
app/routers/auth.py – Optional GitHub OAuth authentication.

Follows security standards:
- Cryptographic state parameter verification to prevent CSRF.
- OAuth token exchange performed strictly server-side.
- Tokens are never exposed to the frontend.
- Session stored via encrypted/signed Starlette session cookie.
"""
from __future__ import annotations

import logging
import secrets
import urllib.parse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas import MeResponse, UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.get("/github/login")
def github_login(request: Request):
    """
    Redirect the user to GitHub to initiate the OAuth flow.
    A cryptographically secure state token is stored in the session.
    """
    if not settings.github_app_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured (missing GITHUB_APP_CLIENT_ID)",
        )

    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    params = {
        "client_id": settings.github_app_client_id,
        "redirect_uri": settings.github_oauth_callback_url,
        "scope": "read:user user:email",
        "state": state,
    }
    redirect_url = f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=redirect_url)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Handle GitHub OAuth callback.
    Verifies state token, exchanges code for token server-side, and establishes session.
    """
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state")

    stored_state = request.session.get("oauth_state")
    if not stored_state or not secrets.compare_digest(stored_state, state):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state (CSRF detected)")

    # Clear state from session
    request.session.pop("oauth_state", None)

    # Exchange code for access token (server-side only)
    token_url = "https://github.com/login/oauth/access_token"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            token_url,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_app_client_id,
                "client_secret": settings.github_app_client_secret,
                "code": code,
                "redirect_uri": settings.github_oauth_callback_url,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to exchange OAuth code")

        data = resp.json()
        access_token = data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth response contained no access token")

        # Fetch authenticated user profile
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "PRPilot/1.0",
            },
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch GitHub user info")

        gh_user = user_resp.json()

    # Find or create user in database
    user = db.query(User).filter_by(github_user_id=gh_user["id"]).first()
    if not user:
        user = User(
            github_user_id=gh_user["id"],
            github_login=gh_user["login"],
            display_name=gh_user.get("name"),
            avatar_url=gh_user.get("avatar_url"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.github_login = gh_user["login"]
        user.display_name = gh_user.get("name")
        user.avatar_url = gh_user.get("avatar_url")
        db.commit()

    # Establish authenticated session
    request.session["user_id"] = user.id

    # Redirect to frontend origin
    return RedirectResponse(url=f"{settings.frontend_origin}/?login=success")


@router.get("/me", response_model=MeResponse)
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Return the currently authenticated user profile or unauthenticated status."""
    user_id = request.session.get("user_id")
    if not user_id:
        return MeResponse(user=None, authenticated=False)

    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        request.session.clear()
        return MeResponse(user=None, authenticated=False)

    return MeResponse(
        user=UserOut(
            id=user.id,
            github_login=user.github_login,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
        ),
        authenticated=True,
    )


@router.post("/logout")
def logout(request: Request):
    """Clear session data to log out."""
    request.session.clear()
    return {"message": "Logged out successfully"}
