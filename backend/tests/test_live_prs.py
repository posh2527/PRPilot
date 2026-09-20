from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.github_client import get_open_pull_requests
from app.main import app
from app.routers import pull_requests


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, headers=None, params=None):
        self.requests.append((url, params))
        if url.endswith("/pulls"):
            return FakeResponse([{
                "number": 16,
                "title": "Test PRPilot integration",
                "body": "Fixes #42 and adds coverage for the integration flow.",
                "user": {"login": "posh2527"},
                "html_url": "https://github.com/posh2527/PRPilot-test/pull/16",
                "updated_at": "2026-09-20T12:00:00Z",
            }])
        return FakeResponse([{"filename": "prpilot-test.txt"}])


@pytest.mark.asyncio
async def test_live_github_client_fetches_open_prs_and_files(monkeypatch):
    monkeypatch.setattr("app.github_client.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("app.github_client.get_installation_access_token", lambda installation_id: _token())

    result = await get_open_pull_requests("posh2527", "PRPilot-test", 123)

    assert result[0]["number"] == 16
    assert result[0]["changed_files"] == ["prpilot-test.txt"]


async def _token():
    return "test-installation-token"


def test_get_prs_maps_live_pr_to_frontend_schema(monkeypatch):
    monkeypatch.setattr(settings, "github_app_id", "123")
    monkeypatch.setattr(settings, "github_installation_id", 456)
    monkeypatch.setattr(settings, "github_owner", "posh2527")
    monkeypatch.setattr(settings, "github_repo", "PRPilot-test")
    monkeypatch.setattr(type(settings), "github_private_key", property(lambda self: "test-private-key"))

    async def fake_open_prs(owner, repo, installation_id):
        return [{
            "number": 16,
            "title": "Test PRPilot integration",
            "body": "Fixes #42 and adds coverage for the integration flow.",
            "user": {"login": "posh2527"},
            "html_url": "https://github.com/posh2527/PRPilot-test/pull/16",
            "changed_files": ["prpilot-test.txt"],
            "updated_at": "2026-09-20T12:00:00Z",
        }]

    monkeypatch.setattr(pull_requests.github_client, "get_open_pull_requests", fake_open_prs)
    response = TestClient(app).get("/api/prs")

    assert response.status_code == 200
    pr = response.json()["prs"][0]
    assert pr["repoPrKey"] == "posh2527/PRPilot-test#16"
    assert pr["changed_files"] == ["prpilot-test.txt"]
    assert pr["changed_file_count"] == 1
    assert pr["issue_linked"] is True
    assert pr["author"] == "posh2527"
    assert pr["recommendation"] in {"Needs attention", "Needs fixes", "Ready for detailed review"}
