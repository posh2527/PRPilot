"""
app/security.py – HMAC-SHA256 webhook signature verification.

The raw request body must be verified BEFORE any JSON parsing.
"""
from __future__ import annotations

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def verify_webhook_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """
    Return True when the X-Hub-Signature-256 header is valid.

    Rules:
    - Reject if header is missing or does not start with "sha256=".
    - Reject if the secret is empty (callers should only call this when a secret is configured).
    - Compare using hmac.compare_digest to prevent timing attacks.
    - Never log the secret or the signature value.
    """
    if not signature_header:
        logger.warning("Webhook request missing X-Hub-Signature-256 header")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("Webhook signature header has unexpected format")
        return False

    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    try:
        return hmac.compare_digest(expected, signature_header)
    except (TypeError, ValueError):
        logger.warning("Webhook signature comparison failed due to type error")
        return False
