"""PRPilot Lambda entrypoint: routing, webhook handling, CORS."""
import base64
import hashlib
import hmac
import json
import logging
import os

import analyzer
import github_client
import store

log = logging.getLogger()
log.setLevel(logging.INFO)

HANDLED_ACTIONS = {"opened", "synchronize", "reopened"}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",  # frontend on :8080 (demo only)
    "Access-Control-Allow-Headers": "Content-Type,X-GitHub-Event,X-Hub-Signature-256",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}


def respond(status, body=None):
    headers = dict(CORS_HEADERS)
    if body is None:
        return {"statusCode": status, "headers": headers, "body": ""}
    headers["Content-Type"] = "application/json"
    return {"statusCode": status, "headers": headers, "body": json.dumps(body, default=store.json_default)}


def _get_body(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return body


def _signature_ok(raw_body, headers):
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        return True  # verification disabled
    sent = headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), raw_body.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sent, expected)


def handle_list_prs():
    return respond(200, {"prs": store.list_analyses()})


def handle_webhook(event):
    raw = _get_body(event)
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    if not _signature_ok(raw, headers):
        return respond(401, {"error": "Invalid webhook signature"})
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return respond(400, {"error": "Body must be valid JSON"})
    if not isinstance(payload, dict) or not payload:
        return respond(400, {"error": "Body must be a non-empty JSON object"})

    gh_event = headers.get("x-github-event") or ("pull_request" if "pull_request" in payload else "")
    if gh_event == "ping":
        return respond(200, {"message": "pong"})
    if gh_event != "pull_request":
        return respond(200, {"message": f"Ignored event '{gh_event or 'unknown'}'"})
    action = payload.get("action")
    if action not in HANDLED_ACTIONS:
        return respond(200, {"message": f"Ignored action '{action}'"})

    pr = payload.get("pull_request") or {}
    if not pr.get("number") or not (payload.get("repository") or {}).get("full_name"):
        return respond(400, {"error": "Missing pull_request.number or repository.full_name"})

    owner, _, repo = payload["repository"]["full_name"].partition("/")
    token = os.environ.get("GITHUB_TOKEN", "")

    # Test events may embed a top-level "changed_files" list; real GitHub payloads
    # don't include file names, so fall back to the GitHub API.
    files = payload.get("changed_files")
    warning = None
    if not isinstance(files, list):
        try:
            files = github_client.fetch_changed_files(owner, repo, pr["number"], token)
        except Exception as exc:  # noqa: BLE001 - never fail the webhook over this
            log.warning("Could not fetch changed files: %s", exc)
            files, warning = [], "changed files unavailable"

    analysis = analyzer.analyze_pr(payload, files)
    try:
        store.save_analysis(analysis)
    except Exception as exc:  # noqa: BLE001
        log.exception("DynamoDB save failed")
        return respond(500, {"error": f"Could not save analysis: {exc}"})

    comment = "disabled"
    if os.environ.get("POST_COMMENTS", "false").lower() == "true" and token:
        try:
            comment = github_client.post_or_update_comment(analysis, token)
        except Exception as exc:  # noqa: BLE001
            log.warning("GitHub comment failed: %s", exc)
            comment = f"failed: {exc}"

    result = {
        "message": "PR analyzed successfully",
        "repoPrKey": analysis["repoPrKey"],
        "recommendation": analysis["recommendation"],
        "comment": comment,
    }
    if warning:
        result["warning"] = warning
    return respond(200, result)


def lambda_handler(event, context):
    method = (event.get("httpMethod") or (event.get("requestContext") or {}).get("http", {}).get("method", "")).upper()
    path = (event.get("path") or event.get("rawPath") or "").rstrip("/")
    log.info("%s %s", method, path)
    try:
        if method == "OPTIONS":
            return respond(204)
        if method == "GET" and path == "/prs":
            return handle_list_prs()
        if method == "POST" and path == "/github-webhook":
            return handle_webhook(event)
        return respond(404, {"error": "Not found"})
    except Exception as exc:  # noqa: BLE001
        log.exception("Unhandled error")
        return respond(500, {"error": str(exc)})
