"""
app/routers/webhooks.py – GitHub Webhook receiver.

Follows strict GitHub webhook security guidelines:
1. Read raw body as bytes BEFORE any JSON parsing.
2. Verify HMAC-SHA256 signature using constant-time comparison.
3. Reject invalid or missing signatures with HTTP 401.
4. Check for duplicate delivery IDs.
5. Dispatch async background tasks and return HTTP 200 {"accepted": true} immediately.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.schemas import WebhookAcceptedResponse
from app.security import verify_webhook_signature
from app.worker import (
    delivery_already_processed,
    process_installation_event,
    process_pull_request_event,
    save_delivery,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

HANDLED_PR_ACTIONS = {
    "opened",
    "reopened",
    "synchronize",
    "edited",
    "ready_for_review",
}


def _run_async_worker(payload: dict[str, Any], delivery_id: str, event_name: str) -> None:
    """
    Background worker wrapper with its own dedicated database session.
    Ensures safe, isolated execution in FastAPI BackgroundTasks.
    """
    import asyncio

    db = SessionLocal()
    try:
        if event_name == "pull_request":
            # Run async worker function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    process_pull_request_event(
                        db=db,
                        payload=payload,
                        delivery_id=delivery_id,
                        event_name=event_name,
                    )
                )
            finally:
                loop.close()
        elif event_name in ("installation", "installation_repositories"):
            process_installation_event(db, payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background task failed for delivery %s: %s", delivery_id, exc)
    finally:
        db.close()


@router.post("/github", response_model=WebhookAcceptedResponse)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(None, alias="X-GitHub-Delivery"),
):
    """
    GitHub Webhook receiver endpoint.

    Secure pipeline:
    - Reads raw body bytes first
    - Verifies HMAC signature
    - Parses JSON
    - Handles ping, installation, and pull_request events
    - Dispatches work to BackgroundTasks and responds immediately
    """
    # 1. Read raw request body as bytes
    raw_body: bytes = await request.body()

    # 2. Verify signature before parsing JSON
    secret = settings.github_webhook_secret
    if secret:
        if not x_hub_signature_256 or not verify_webhook_signature(raw_body, x_hub_signature_256, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing webhook signature",
            )
    else:
        # In non-dev mode, missing webhook secret configuration must reject requests
        if not settings.local_development_mode:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Webhook secret not configured on server",
            )
        # If signature header is provided but secret is not set, we cannot verify it
        if x_hub_signature_256:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Webhook secret not configured to verify incoming signature",
            )

    # 3. Parse JSON safely
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be valid JSON",
        )

    event_name = (x_github_event or payload.get("event") or "").lower()
    delivery_id = x_github_delivery or f"dev-deliv-{hash(raw_body) & 0x7FFFFFFF}"

    # 4. Handle ping events
    if event_name == "ping":
        logger.info("Received GitHub ping event (zen: %s)", payload.get("zen", ""))
        return WebhookAcceptedResponse(accepted=True)

    # 5. Check duplicate delivery ID
    if delivery_already_processed(db, delivery_id):
        logger.info("Ignoring duplicate webhook delivery: %s", delivery_id)
        return WebhookAcceptedResponse(accepted=True)

    # 6. Check if action should be processed
    if event_name == "pull_request":
        action = payload.get("action", "")
        if action not in HANDLED_PR_ACTIONS:
            logger.info("Ignoring unhandled PR action '%s' for delivery %s", action, delivery_id)
            save_delivery(db, delivery_id, event_name, action)
            return WebhookAcceptedResponse(accepted=True)

        # Enqueue background analysis
        background_tasks.add_task(_run_async_worker, payload, delivery_id, event_name)

    elif event_name in ("installation", "installation_repositories"):
        action = payload.get("action", "")
        save_delivery(db, delivery_id, event_name, action)
        background_tasks.add_task(_run_async_worker, payload, delivery_id, event_name)

    else:
        logger.info("Unhandled event type '%s'", event_name)
        save_delivery(db, delivery_id, event_name, payload.get("action"))

    return WebhookAcceptedResponse(accepted=True)
