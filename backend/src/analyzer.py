"""Simple, rule-based PR analysis. No AI, no network - easy to demo and test."""
import os
import re
from datetime import datetime, timezone

MIN_DESCRIPTION_WORDS = 8

ISSUE_RE = re.compile(r"(?<![\w&])#\d+\b|/issues/\d+", re.I)

DOC_EXT = {".md", ".markdown", ".rst", ".txt", ".adoc"}
DOC_NAMES = {"readme", "license", "changelog", "contributing", "authors", "code_of_conduct"}
DOC_DIRS = {"docs", "doc", "documentation"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e"}
CODE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".php", ".c", ".h",
    ".cpp", ".cs", ".rs", ".kt", ".swift", ".sh", ".html", ".css", ".scss", ".vue", ".sql",
}

STOPWORDS = {
    "this", "that", "with", "from", "into", "have", "has", "will", "when", "then", "them",
    "they", "their", "there", "these", "those", "which", "what", "also", "your", "being",
    "been", "more", "some", "such", "only", "just", "than", "make", "makes", "made", "used",
    "uses", "using", "adds", "added", "add", "fix", "fixes", "fixed", "update", "updates",
    "updated", "change", "changes", "changed", "issue", "closes", "closed", "resolves",
    "pull", "request", "should", "would", "could", "about", "while", "where", "each", "other",
}
GENERIC_PATH_TOKENS = {"src", "test", "tests", "spec", "index", "main", "lib", "init", "docs", "doc"}


# ---------- file classification ----------
def classify_file(path):
    """Return 'test', 'doc', 'code' or 'other'."""
    original_name = path.split("/")[-1]
    parts = path.lower().split("/")
    name = parts[-1]
    stem, ext = os.path.splitext(name)

    if (
        any(p in TEST_DIRS for p in parts[:-1])
        or name.startswith("test_")
        or re.search(r"(_test|_spec|\.test|\.spec)\.[a-z0-9]+$", name)
        or re.search(r"(Test|Tests|Spec)\.\w+$", original_name)
    ):
        return "test"
    if ext in DOC_EXT or stem in DOC_NAMES or any(p in DOC_DIRS for p in parts[:-1]):
        return "doc"
    if ext in CODE_EXT:
        return "code"
    return "other"


def change_scope(kinds):
    if not kinds:
        return "Unknown"
    if kinds == {"doc"}:
        return "Documentation only"
    if kinds == {"test"}:
        return "Tests only"
    if "code" in kinds and "test" in kinds:
        return "Code and tests"
    if "code" in kinds:
        return "Code only"
    if "test" in kinds:
        return "Tests only"
    return "Configuration or other files"


# ---------- description relevance ----------
def _tokens(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")
    return re.findall(r"[a-z]{3,}", text.lower())


def _related(a, b):
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        return a.startswith(b) or b.startswith(a) or a[:5] == b[:5]
    return False


TYPE_WORDS = {
    "test": {"test", "tests", "testing", "unittest", "spec"},
    "doc": {"doc", "docs", "documentation", "readme", "typo", "typos"},
}


def description_match(title, description, files, kinds=frozenset()):
    """Return (label, matched_terms). Label: Good / Partial / Poor / Unclear."""
    words = (description or "").split()
    if len(words) < MIN_DESCRIPTION_WORDS or not files:
        return "Unclear", []
    keywords = {t for t in _tokens(description) if len(t) >= 4 and t not in STOPWORDS}
    file_tokens = {t for f in files for t in _tokens(f) if t not in GENERIC_PATH_TOKENS}
    matched = {k for k in keywords if any(_related(k, ft) for ft in file_tokens)}
    # Description talks about tests/docs and such files really changed -> related.
    for kind, words in TYPE_WORDS.items():
        if kind in kinds and words & set(_tokens(description)):
            matched.add("tests" if kind == "test" else "docs")
    matched = sorted(matched)
    if len(matched) >= 2:
        return "Good", matched
    if len(matched) == 1:
        return "Partial", matched
    return "Poor", []


# ---------- recommendation ----------
def recommend(issue_link, tests_changed, docs_only, match, too_short, has_files):
    if too_short or not has_files or match == "Poor":
        return "Low-value or unclear"
    if issue_link and match == "Good" and (tests_changed or docs_only):
        return "Ready for review"
    return "Needs changes"


SCOPE_SUMMARY = {
    "Code and tests": "Application code and test files were modified.",
    "Code only": "Application code was modified, but no test files were changed.",
    "Tests only": "Only test files were modified.",
    "Documentation only": "Only documentation files were changed.",
    "Configuration or other files": "Only configuration or non-code files were changed.",
    "Unknown": "The list of changed files could not be determined.",
}


def analyze_pr(payload, files):
    pr = payload["pull_request"]
    repo = payload.get("repository") or {}
    full_name = repo.get("full_name") or ""
    owner, _, name = full_name.partition("/")
    owner = owner or (repo.get("owner") or {}).get("login", "unknown")
    name = name or repo.get("name", "unknown")
    number = int(pr.get("number") or payload.get("number"))
    title = pr.get("title") or ""
    description = pr.get("body") or ""

    kinds = {classify_file(f) for f in files}
    scope = change_scope(kinds)
    tests_changed = "test" in kinds
    docs_only = kinds == {"doc"}
    issue_link = bool(ISSUE_RE.search(f"{title}\n{description}"))
    too_short = len(description.split()) < MIN_DESCRIPTION_WORDS
    match, matched_terms = description_match(title, description, files, kinds)
    recommendation = recommend(issue_link, tests_changed, docs_only, match, too_short, bool(files))

    summary = []
    if not description.strip():
        summary.append("The PR description is empty.")
    elif too_short:
        summary.append("The PR description is very short and does not explain the change.")
    elif match == "Good":
        summary.append(f"The PR description matches the changed files (shared terms: {', '.join(matched_terms[:4])}).")
    elif match == "Partial":
        summary.append(f"The PR description only partly matches the changed files (shared term: {matched_terms[0]}).")
    elif match == "Poor":
        summary.append("The PR description does not appear to relate to the changed files.")
    summary.append(SCOPE_SUMMARY[scope])
    summary.append("The PR references an issue." if issue_link else "The PR does not reference an issue (e.g. #123).")

    checklist = []
    checklist.append(
        "Confirm that the linked issue is resolved." if issue_link
        else "Add a link to the related issue (for example, Fixes #123)."
    )
    if tests_changed:
        checklist.append("Ensure all tests pass.")
    elif docs_only:
        checklist.append("Check the documentation for accuracy and broken links.")
    elif files:
        checklist.append("Add or update tests that cover this change.")
    if too_short:
        checklist.append("Expand the PR description to explain what changed and why.")
    elif match in ("Partial", "Poor"):
        checklist.append("Update the description so it reflects the files that were changed.")
    if not files:
        checklist.append("Verify the changed-files list; it could not be retrieved.")

    return {
        "repoPrKey": f"{owner}/{name}#{number}",
        "owner": owner,
        "repo": name,
        "pr_number": number,
        "title": title,
        "author": (pr.get("user") or {}).get("login", "unknown"),
        "url": pr.get("html_url", ""),
        "issue_link": issue_link,
        "tests_changed": tests_changed,
        "change_scope": scope,
        "description_match": match,
        "summary": summary,
        "checklist": checklist,
        "recommendation": recommendation,
        # extra fields (additive - safe for the frontend to ignore)
        "description": description,
        "changed_files": list(files),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
