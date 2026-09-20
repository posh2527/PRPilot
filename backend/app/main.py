"""
app/main.py – FastAPI application entry point for PRPilot.

PRPilot provides automated first-pass review guidance.
Maintainers make the final merge, request-changes, or close decision.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import init_db
from app.routers import auth, dev, installations, pull_requests, repositories, webhooks
from app.schemas import HealthResponse, PRListResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("prpilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context: initialize database tables on startup."""
    logger.info("Initializing database tables...")
    init_db()
    logger.info("Database initialized successfully.")
    logger.info(
        "PRPilot backend started in '%s' mode (GitHub App configured: %s, Local Dev: %s)",
        settings.app_env,
        settings.github_app_configured,
        settings.local_development_mode,
    )
    logger.info("GitHub OAuth configured: %s", settings.github_oauth_configured)
    yield
    logger.info("PRPilot backend shutting down.")


app = FastAPI(
    title="PRPilot Backend",
    description=(
        "PRPilot provides automated first-pass review guidance. "
        "Maintainers make the final merge, request-changes, or close decision."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Session Middleware ────────────────────────────────────────────────────────
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="prpilot_session",
    max_age=14 * 24 * 3600,  # 14 days
    same_site="lax",
    https_only=not settings.is_development,
)

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Strict origin matching as required: do not use ["*"] with allow_credentials=True
origins = [settings.frontend_origin]
if settings.is_development and "127.0.0.1" in settings.frontend_origin:
    origins.append(settings.frontend_origin.replace("127.0.0.1", "localhost"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "X-Requested-With",
        "X-GitHub-Event",
        "X-Hub-Signature-256",
        "X-GitHub-Delivery",
    ],
)

# ── Health Endpoint ───────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health_check():
    """Health check endpoint confirming API status and GitHub App configuration."""
    return HealthResponse(
        status="ok",
        environment=settings.app_env,
        github_app_configured=settings.github_app_configured,
    )


# ── Include Feature Routers ───────────────────────────────────────────────────
app.include_router(webhooks.router)
app.include_router(pull_requests.router)
app.include_router(dev.router)
app.include_router(auth.router)
app.include_router(installations.router)
app.include_router(installations.github_router)
app.include_router(repositories.router)

# Compatibility route: /prs -> alias to /api/prs
@app.get("/prs", response_model=PRListResponse, tags=["Pull Requests"], include_in_schema=False)
async def legacy_list_pull_requests(resp: PRListResponse = None):
    from fastapi import Depends
    from app.database import get_db
    from app.routers.pull_requests import list_pull_requests
    return await list_pull_requests(next(get_db()))
