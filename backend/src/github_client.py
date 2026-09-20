"""Minimal GitHub REST client (stdlib only)."""
import json
import os
import urllib.request

MARKER = "<!-- prpilot-analysis -->"


def _api():
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def _request(method, url, token, data=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PRPilot",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode() or "null")


def fetch_changed_files(owner, repo, number, token=""):
    """Webhook payloads don't include file names, so ask the GitHub API."""
    names = []
    for page in range(1, 6):
        url = f"{_api()}/repos/{owner}/{repo}/pulls/{number}/files?per_page=100&page={page}"
        batch = _request("GET", url, token)
        names.extend(f["filename"] for f in batch)
        if len(batch) < 100:
            break
    return names


def format_comment(a):
    def bullets(items):
        return "\n".join(f"- {i}" for i in items)

    return (
        f"{MARKER}\n"
        f"## PRPilot analysis\n"
        f"**Recommendation:** {a['recommendation']}\n\n"
        f"| Check | Result |\n|---|---|\n"
        f"| Description match | {a['description_match']} |\n"
        f"| Tests changed | {'Yes' if a['tests_changed'] else 'No'} |\n"
        f"| Issue link | {'Yes' if a['issue_link'] else 'No'} |\n"
        f"| Scope | {a['change_scope']} |\n\n"
        f"**Summary**\n{bullets(a['summary'])}\n\n"
        f"**Checklist**\n{bullets('[ ] ' + c for c in a['checklist'])}\n"
    )


def post_or_update_comment(a, token):
    """Create the PRPilot comment, or edit it if one already exists. Returns 'created'/'updated'."""
    base = f"{_api()}/repos/{a['owner']}/{a['repo']}/issues"
    body = format_comment(a)
    existing = _request("GET", f"{base}/{a['pr_number']}/comments?per_page=100", token) or []
    for c in existing:
        if MARKER in (c.get("body") or ""):
            _request("PATCH", f"{base}/comments/{c['id']}", token, {"body": body})
            return "updated"
    _request("POST", f"{base}/{a['pr_number']}/comments", token, {"body": body})
    return "created"
