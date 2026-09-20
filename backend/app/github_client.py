"""
app/github_client.py – GitHub REST API service.

All HTTP calls use installation access tokens obtained via github_app.py.
Tokens are NEVER passed to the frontend or logged.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.github_app import GitHubAppError, get_installation_access_token

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"

# Stable marker that identifies a PRPilot comment.
# Do NOT change this string after deployment – it is the de-duplication key.
PRPILOT_MARKER = "<!-- prpilot-review-summary -->"

_DEFAULT_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "PRPilot/1.0",
}


def _auth_headers(token: str) -> dict[str, str]:
    return {**_DEFAULT_HEADERS, "Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_pull_request(
    owner: str, repo: str, number: int, installation_id: int
) -> dict[str, Any]:
    """
    Fetch PR metadata from GitHub.

    Returns a dict with: title, body, author, html_url, head_sha, draft, state.
    Raises httpx.HTTPError or GitHubAppError on failure.
    """
    token = await get_installation_access_token(installation_id)
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=_auth_headers(token))
        response.raise_for_status()
        data = response.json()

    return {
        "title": data.get("title", ""),
        "body": data.get("body") or "",
        "author": (data.get("user") or {}).get("login", ""),
        "html_url": data.get("html_url", ""),
        "head_sha": (data.get("head") or {}).get("sha", ""),
        "draft": data.get("draft", False),
        "state": data.get("state", ""),
        "number": data.get("number", number),
        "id": data.get("id"),
    }


async def get_pull_request_files(
    owner: str, repo: str, number: int, installation_id: int
) -> list[str]:
    """
    Return the list of file paths changed by a pull request.

    Paginates through up to 5 pages (500 files max – sufficient for an MVP).
    Raises httpx.HTTPError or GitHubAppError on failure.
    """
    token = await get_installation_access_token(installation_id)
    return await get_pull_request_files_with_token(owner, repo, number, token)


async def get_pull_request_files_with_token(
    owner: str, repo: str, number: int, token: str
) -> list[str]:
    """Return changed file paths using an already-issued installation token."""
    file_paths: list[str] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for page in range(1, 6):
            url = (
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}/files"
                f"?per_page=100&page={page}"
            )
            response = await client.get(url, headers=_auth_headers(token))
            response.raise_for_status()
            batch = response.json()
            file_paths.extend(f["filename"] for f in batch)
            if len(batch) < 100:
                break  # last page

    return file_paths


async def get_open_pull_requests(
    owner: str, repo: str, installation_id: int
) -> list[dict[str, Any]]:
    """Fetch all open pull requests and their changed files from GitHub."""
    token = await get_installation_access_token(installation_id)
    headers = _auth_headers(token)
    pull_requests: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for page in range(1, 6):
            response = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
                headers=headers,
                params={"state": "open", "per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list):
                raise GitHubAppError("GitHub returned an unexpected pull request response.")

            for pull_request in batch:
                number = pull_request.get("number")
                if not number:
                    continue
                pull_request["changed_files"] = await get_pull_request_files_with_token(
                    owner, repo, int(number), token
                )
                pull_requests.append(pull_request)

            if len(batch) < 100:
                break

    return pull_requests


async def create_or_update_review_comment(
    owner: str,
    repo: str,
    number: int,
    analysis: dict[str, Any],
    installation_id: int,
) -> str:
    """
    Post or update the single PRPilot review comment on the PR.

    Strategy:
    1. List all issue comments.
    2. Find an existing comment that contains PRPILOT_MARKER.
    3. PATCH it if found; POST a new one otherwise.

    Returns "created" or "updated".
    Never raises – errors are logged safely (token not exposed).
    """
    try:
        token = await get_installation_access_token(installation_id)
    except GitHubAppError as exc:
        logger.warning("Cannot post comment – GitHub App auth failed: %s", exc)
        return "skipped:auth_error"

    body = _render_comment(analysis)
    base_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # --- fetch existing comments ---
        try:
            list_resp = await client.get(
                f"{base_url}/{number}/comments?per_page=100",
                headers=_auth_headers(token),
            )
            list_resp.raise_for_status()
            existing_comments = list_resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Could not list PR comments: %s", exc)
            return "skipped:list_error"

        # --- check for existing PRPilot comment ---
        for comment in existing_comments:
            comment_body = comment.get("body") or ""
            if PRPILOT_MARKER in comment_body:
                comment_id = comment["id"]
                try:
                    patch_resp = await client.patch(
                        f"{base_url}/comments/{comment_id}",
                        headers=_auth_headers(token),
                        json={"body": body},
                    )
                    patch_resp.raise_for_status()
                    logger.info("Updated PRPilot comment #%d on %s/%s#%d", comment_id, owner, repo, number)
                    return "updated"
                except httpx.HTTPError as exc:
                    logger.warning("Could not update PR comment: %s", exc)
                    return "skipped:update_error"

        # --- create a new comment ---
        try:
            post_resp = await client.post(
                f"{base_url}/{number}/comments",
                headers=_auth_headers(token),
                json={"body": body},
            )
            post_resp.raise_for_status()
            logger.info("Created PRPilot comment on %s/%s#%d", owner, repo, number)
            return "created"
        except httpx.HTTPError as exc:
            logger.warning("Could not create PR comment: %s", exc)
            return "skipped:post_error"


# ---------------------------------------------------------------------------
# Comment renderer
# ---------------------------------------------------------------------------

def _recommendation_badge(rec: str) -> str:
    badges = {
        "Ready for detailed review": "🟢 **Ready for detailed maintainer review**",
        "Needs fixes": "🟡 **Needs fixes before review**",
        "Needs attention": "🔴 **Needs attention – please review the checklist**",
    }
    return badges.get(rec, f"ℹ️ **{rec}**")


def _render_comment(analysis: dict[str, Any]) -> str:
    """Render the Markdown PR comment body."""
    summary_bullets = "\n".join(f"- {s}" for s in (analysis.get("summary") or []))
    checklist_bullets = "\n".join(f"- {c}" for c in (analysis.get("checklist") or []))
    issue_status = "Present" if analysis.get("issue_linked") else "Not detected"

    return (
        f"{PRPILOT_MARKER}\n"
        f"## PRPilot Review Summary\n\n"
        f"PRPilot provides automated first-pass review guidance.  \n"
        f"Maintainers make the final merge decision.\n\n"
        f"### Quick checks\n\n"
        f"| Check | Result |\n"
        f"|---|---|\n"
        f"| Description-change match | {analysis.get('description_match', '–')} |\n"
        f"| Linked issue | {issue_status} |\n"
        f"| Code files changed | {analysis.get('code_file_count', 0)} |\n"
        f"| Test files changed | {analysis.get('test_file_count', 0)} |\n"
        f"| Change relevance | {analysis.get('change_relevance', '–')} |\n\n"
        f"### What PRPilot found\n\n"
        f"{summary_bullets or '– No summary available.'}\n\n"
        f"### Suggested actions\n\n"
        f"{checklist_bullets or '– No actions at this time.'}\n\n"
        f"### Recommendation\n\n"
        f"{_recommendation_badge(analysis.get('recommendation', 'Needs attention'))}\n"
    )
