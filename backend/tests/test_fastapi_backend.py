from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["APP_ENV"] = "development"
os.environ["LOCAL_DEVELOPMENT_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_prpilot.db"
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-webhook-secret-12345"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import analyzer
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.routers import pull_requests

test_engine = create_engine("sqlite:///./test_prpilot.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def compute_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class TestPRPilotFastAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)
        if os.path.exists("./test_prpilot.db"):
            try:
                os.remove("./test_prpilot.db")
            except OSError:
                pass

    def test_01_health_endpoint(self):
        """GET /health returns 200 and expected schema."""
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["environment"], "development")
        self.assertIn("github_app_configured", data)

    def test_02_invalid_webhook_signature_returns_401(self):
        """POST /api/webhooks/github with invalid signature returns 401."""
        payload = json.dumps({"action": "opened", "pull_request": {"number": 1}}).encode("utf-8")
        headers = {
            "X-Hub-Signature-256": "sha256=invalid_hash_value_here",
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "deliv-invalid-sig-001",
            "Content-Type": "application/json",
        }
        response = client.post("/api/webhooks/github", content=payload, headers=headers)
        self.assertEqual(response.status_code, 401)

    def test_03_missing_webhook_signature_returns_401(self):
        """POST /api/webhooks/github with missing signature returns 401."""
        payload = json.dumps({"action": "opened"}).encode("utf-8")
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "deliv-missing-sig-001",
            "Content-Type": "application/json",
        }
        response = client.post("/api/webhooks/github", content=payload, headers=headers)
        self.assertEqual(response.status_code, 401)

    def test_04_valid_webhook_signature_is_accepted(self):
        """POST /api/webhooks/github with valid signature returns 200 {"accepted": true}."""
        payload_dict = {
            "action": "opened",
            "pull_request": {
                "number": 1,
                "title": "Fix authentication bug #42",
                "body": "Fixes #42 - resolves token expiration error in auth flow",
                "html_url": "https://github.com/acme/demo/pull/1",
                "user": {"login": "octocat"},
            },
            "repository": {
                "id": 123456,
                "name": "demo",
                "full_name": "acme/demo",
                "owner": {"login": "acme"},
            },
        }
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        sig = compute_signature("test-webhook-secret-12345", payload_bytes)
        headers = {
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "deliv-valid-sig-001",
            "Content-Type": "application/json",
        }
        response = client.post("/api/webhooks/github", content=payload_bytes, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"accepted": True})

    def test_05_duplicate_delivery_is_ignored(self):
        """Duplicate delivery IDs are safely acknowledged without error."""
        payload_dict = {"zen": "Keep it logically awesome."}
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        sig = compute_signature("test-webhook-secret-12345", payload_bytes)
        headers = {
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "deliv-duplicate-001",
            "Content-Type": "application/json",
        }
        r1 = client.post("/api/webhooks/github", content=payload_bytes, headers=headers)
        self.assertEqual(r1.status_code, 200)
        r2 = client.post("/api/webhooks/github", content=payload_bytes, headers=headers)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json(), {"accepted": True})

    def test_06_analyzer_detects_issue_links(self):
        """Analyzer correctly detects issue links in various formats."""
        res1 = analyzer.analyze_pr("Fix login #101", "Implements fix", ["app/login.py", "tests/test_login.py"])
        self.assertTrue(res1["issue_linked"])

        res2 = analyzer.analyze_pr("Refactor", "Resolves #55 and closes #56", ["app/login.py"])
        self.assertTrue(res2["issue_linked"])

        res3 = analyzer.analyze_pr("Refactor", "No issue mentioned anywhere here.", ["app/login.py"])
        self.assertFalse(res3["issue_linked"])

    def test_07_analyzer_detects_test_files(self):
        """Analyzer correctly categorizes test files vs application code."""
        files = [
            "src/service.py",
            "tests/test_service.py",
            "frontend/component.test.ts",
            "docs/README.md",
        ]
        res = analyzer.analyze_pr("Test PR", "Implements service changes #12", files)
        self.assertEqual(res["code_file_count"], 1)
        self.assertEqual(res["test_file_count"], 2)
        self.assertEqual(res["changed_file_count"], 4)

    def test_08_analyzer_detects_documentation_only_changes(self):
        """Analyzer detects documentation-only changes and flags code mismatch."""
        docs_files = ["docs/architecture.md", "README.rst"]
        res = analyzer.analyze_pr(
            "Fix critical auth login bug",
            "Fixes #99 - database login crash bug resolved in backend",
            docs_files,
        )
        self.assertEqual(res["recommendation"], "Needs attention")
        self.assertEqual(res["description_match"], "Low")

    def test_09_three_sample_prs_produce_three_recommendations(self):
        """Verify the 3 distinct PR recommendations generated by analyzer."""
        r1 = analyzer.analyze_pr(
            "Add user profile settings endpoint",
            "Fixes #201. Adds user profile endpoints and settings with full test suite coverage.",
            ["app/profile.py", "tests/test_profile.py"],
        )
        self.assertEqual(r1["recommendation"], "Ready for detailed review")

        r2 = analyzer.analyze_pr(
            "Update billing charge calculation",
            "Fixes #202. Modifies billing formula for invoice calculation.",
            ["app/billing.py"],
        )
        self.assertEqual(r2["recommendation"], "Needs fixes")

        r3 = analyzer.analyze_pr(
            "Fix database connection crash",
            "Fixes bug",
            ["docs/index.md"],
        )
        self.assertEqual(r3["recommendation"], "Needs attention")

    def test_10_seed_and_get_prs(self):
        """GET /api/prs maps live GitHub PRs into the frontend schema."""
        seed_resp = client.post("/api/dev/seed-samples")
        self.assertEqual(seed_resp.status_code, 200)
        self.assertEqual(seed_resp.json()["seeded"], 3)

        async def fake_open_prs(owner, repo, installation_id):
            return [
                {"number": 101, "title": "Ready PR", "body": "Fixes #1 and adds tests for login flow.", "user": {"login": "alice"}, "changed_files": ["app/login.py", "tests/test_login.py"], "updated_at": "2026-09-20T12:00:00Z"},
                {"number": 102, "title": "Needs fixes PR", "body": "Updates billing code for invoice calculation before release.", "user": {"login": "bob"}, "changed_files": ["app/billing.py"], "updated_at": "2026-09-20T11:00:00Z"},
                {"number": 103, "title": "Docs mismatch PR", "body": "Fixes a database crash in production.", "user": {"login": "charlie"}, "changed_files": ["README.md"], "updated_at": "2026-09-20T10:00:00Z"},
            ]

        with patch.object(settings, "github_app_id", "test-app-id"), patch.object(settings, "github_installation_id", 123), patch.object(settings, "github_owner", "acme"), patch.object(settings, "github_repo", "demo"), patch.object(type(settings), "github_private_key", new=property(lambda self: "test-private-key")), patch.object(pull_requests.github_client, "get_open_pull_requests", fake_open_prs):
            list_resp = client.get("/api/prs")
        self.assertEqual(list_resp.status_code, 200)
        data = list_resp.json()
        self.assertIn("prs", data)
        prs = data["prs"]
        self.assertGreaterEqual(len(prs), 3)

        pr = prs[0]
        required_keys = [
            "repoPrKey",
            "owner",
            "repo",
            "pr_number",
            "title",
            "author",
            "description",
            "github_url",
            "changed_files",
            "changed_file_count",
            "code_file_count",
            "test_file_count",
            "issue_linked",
            "description_match",
            "change_relevance",
            "summary",
            "checklist",
            "recommendation",
            "timestamp",
        ]
        for k in required_keys:
            self.assertIn(k, pr, f"Missing required field {k}")

        recommendations = {p["recommendation"] for p in prs}
        self.assertIn("Ready for detailed review", recommendations)
        self.assertIn("Needs fixes", recommendations)
        self.assertIn("Needs attention", recommendations)

    def test_11_get_single_pr_detail(self):
        """GET /api/prs/{owner}/{repo}/{pr_number} returns the detailed PR."""
        resp = client.get("/api/prs/prpilot-demo/sample-service/101")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["owner"], "prpilot-demo")
        self.assertEqual(data["repo"], "sample-service")
        self.assertEqual(data["pr_number"], 101)
        self.assertEqual(data["recommendation"], "Ready for detailed review")

    def test_12_cors_headers(self):
        """Check CORS preflight for frontend origin."""
        headers = {
            "Origin": "http://127.0.0.1:8080",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type",
        }
        resp = client.options("/api/prs", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://127.0.0.1:8080")
        self.assertEqual(resp.headers.get("access-control-allow-credentials"), "true")


if __name__ == "__main__":
    unittest.main()
