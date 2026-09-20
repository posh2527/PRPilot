"""Run: python3 -m unittest discover -s tests -v   (no AWS, no network, no pip installs)"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import analyzer  # noqa: E402
import store  # noqa: E402

import importlib.util
spec = importlib.util.spec_from_file_location("src_app", os.path.join(SRC_DIR, "app.py"))
src_app = importlib.util.module_from_spec(spec)
sys.modules["src_app"] = src_app
spec.loader.exec_module(src_app)

# Prevent src from polluting sys.modules['app'] or sys.path
if "app" in sys.modules and getattr(sys.modules["app"], "__file__", "").endswith("src" + os.sep + "app.py"):
    del sys.modules["app"]
if SRC_DIR in sys.path:
    sys.path.remove(SRC_DIR)

DB = {}
store.save_analysis = lambda a: DB.__setitem__(a["repoPrKey"], a)
store.list_analyses = lambda: sorted(DB.values(), key=lambda i: i["updated_at"], reverse=True)


def load(name):
    with open(os.path.join(ROOT, "events", name)) as f:
        return json.load(f)


import hashlib
import hmac

def post(payload, gh_event="pull_request"):
    body = json.dumps(payload)
    headers = {"X-GitHub-Event": gh_event}
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        headers["x-hub-signature-256"] = "sha256=" + hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return src_app.lambda_handler({
        "httpMethod": "POST", "path": "/github-webhook",
        "headers": headers, "body": body,
    }, None)


class AnalyzerTests(unittest.TestCase):
    def test_classify(self):
        c = analyzer.classify_file
        self.assertEqual(c("tests/test_login.py"), "test")
        self.assertEqual(c("src/Login.test.tsx"), "test")
        self.assertEqual(c("src/FooTest.java"), "test")
        self.assertEqual(c("src/contest.py"), "code")
        self.assertEqual(c("README.md"), "doc")
        self.assertEqual(c("docs/conf.py"), "doc")
        self.assertEqual(c("package.json"), "other")

    def test_ready(self):
        a = analyzer.analyze_pr(load("ready.json"), load("ready.json")["changed_files"])
        self.assertEqual(a["recommendation"], "Ready for review")
        self.assertEqual(a["description_match"], "Good")
        self.assertEqual(a["change_scope"], "Code and tests")
        self.assertTrue(a["issue_link"] and a["tests_changed"])
        self.assertEqual(a["repoPrKey"], "acme/shop#12")

    def test_needs_changes(self):
        p = load("needs_changes.json")
        a = analyzer.analyze_pr(p, p["changed_files"])
        self.assertEqual(a["recommendation"], "Needs changes")
        self.assertFalse(a["issue_link"] or a["tests_changed"])

    def test_low_value_short_description(self):
        p = load("low_value.json")
        a = analyzer.analyze_pr(p, p["changed_files"])
        self.assertEqual(a["recommendation"], "Low-value or unclear")
        self.assertEqual(a["change_scope"], "Documentation only")

    def test_unrelated_description_is_low_value(self):
        p = load("ready.json")
        p["pull_request"]["body"] = "Refactors the payment gateway retry logic for failed card transactions #9"
        a = analyzer.analyze_pr(p, ["src/auth/login.py", "tests/test_login.py"])
        self.assertEqual(a["description_match"], "Poor")
        self.assertEqual(a["recommendation"], "Low-value or unclear")

    def test_no_files_is_unclear(self):
        p = load("ready.json")
        a = analyzer.analyze_pr(p, [])
        self.assertEqual(a["recommendation"], "Low-value or unclear")


class HandlerTests(unittest.TestCase):
    def setUp(self):
        DB.clear()

    def test_webhook_then_list_and_upsert(self):
        r = post(load("ready.json"))
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(json.loads(r["body"])["recommendation"], "Ready for review")
        # same PR again (synchronize) -> still one item
        p = load("ready.json"); p["action"] = "synchronize"
        post(p)
        post(load("low_value.json"))
        r = src_app.lambda_handler({"httpMethod": "GET", "path": "/prs"}, None)
        items = json.loads(r["body"])["prs"]
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(len(items), 2)
        self.assertEqual(r["headers"]["Access-Control-Allow-Origin"], "*")

    def test_ignored_and_errors(self):
        p = load("ready.json"); p["action"] = "closed"
        self.assertIn("Ignored", json.loads(post(p)["body"])["message"])
        self.assertEqual(json.loads(post({"zen": "Keep it logically awesome."}, "ping")["body"])["message"], "pong")
        secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
        bad_headers = {"x-hub-signature-256": "sha256=" + hmac.new(secret.encode("utf-8"), b"{nope", hashlib.sha256).hexdigest()} if secret else {}
        bad = src_app.lambda_handler({"httpMethod": "POST", "path": "/github-webhook", "headers": bad_headers, "body": "{nope"}, None)
        self.assertEqual(bad["statusCode"], 400)
        self.assertEqual(post({"action": "opened", "pull_request": {}})["statusCode"], 400)
        empty_headers = {"x-hub-signature-256": "sha256=" + hmac.new(secret.encode("utf-8"), b"", hashlib.sha256).hexdigest()} if secret else {}
        empty = src_app.lambda_handler({"httpMethod": "POST", "path": "/github-webhook", "headers": empty_headers, "body": None}, None)
        self.assertEqual(empty["statusCode"], 400)
        for r in (bad, empty):
            self.assertIn("error", json.loads(r["body"]))
            self.assertIn("Access-Control-Allow-Origin", r["headers"])

    def test_three_events_three_recommendations(self):
        got = [json.loads(post(load(n))["body"])["recommendation"]
               for n in ("ready.json", "needs_changes.json", "low_value.json")]
        self.assertEqual(got, ["Ready for review", "Needs changes", "Low-value or unclear"])
        self.assertEqual(len(DB), 3)

    def test_only_opened_synchronize_reopened(self):
        for action, handled in [("opened", True), ("synchronize", True), ("reopened", True),
                                ("closed", False), ("assigned", False), ("labeled", False),
                                ("unlocked", False), ("edited", False)]:
            p = load("ready.json"); p["action"] = action
            body = json.loads(post(p)["body"])
            self.assertEqual(body["message"] == "PR analyzed successfully", handled, action)

    def test_github_failures_do_not_lose_result(self):
        import github_client
        os.environ["GITHUB_TOKEN"], os.environ["POST_COMMENTS"] = "x", "true"
        orig = github_client.post_or_update_comment
        github_client.post_or_update_comment = lambda a, t: (_ for _ in ()).throw(RuntimeError("403"))
        try:
            r = post(load("ready.json"))
        finally:
            github_client.post_or_update_comment = orig
            os.environ.pop("GITHUB_TOKEN"); os.environ.pop("POST_COMMENTS")
        self.assertEqual(r["statusCode"], 200)
        self.assertIn("failed", json.loads(r["body"])["comment"])
        self.assertIn("acme/shop#12", DB)

    def test_missing_files_falls_back_and_still_saves(self):
        import github_client
        p = load("ready.json"); del p["changed_files"]
        orig = github_client.fetch_changed_files
        github_client.fetch_changed_files = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
        try:
            r = post(p)
        finally:
            github_client.fetch_changed_files = orig
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(json.loads(r["body"])["recommendation"], "Low-value or unclear")

    def test_options_and_404(self):
        r = src_app.lambda_handler({"httpMethod": "OPTIONS", "path": "/prs"}, None)
        self.assertEqual(r["statusCode"], 204)
        self.assertEqual(r["headers"]["Access-Control-Allow-Methods"], "GET, POST, OPTIONS")
        self.assertEqual(r["headers"]["Access-Control-Allow-Origin"], "*")
        r = src_app.lambda_handler({"httpMethod": "OPTIONS", "path": "/github-webhook"}, None)
        self.assertEqual(r["statusCode"], 204)
        self.assertEqual(src_app.lambda_handler({"httpMethod": "GET", "path": "/x"}, None)["statusCode"], 404)

    def test_comment_format(self):
        import github_client
        p = load("ready.json")
        text = github_client.format_comment(analyzer.analyze_pr(p, p["changed_files"]))
        self.assertIn("Ready for review", text)
        self.assertIn(github_client.MARKER, text)


class StoreTests(unittest.TestCase):
    def test_decimal_is_json_safe(self):
        from decimal import Decimal
        out = json.dumps({"n": Decimal("12"), "f": Decimal("1.5")}, default=store.json_default)
        self.assertEqual(json.loads(out), {"n": 12, "f": 1.5})


if __name__ == "__main__":
    unittest.main()
