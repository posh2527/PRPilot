"""
app/analyzer.py – Deterministic, explainable PR analysis engine.

No AI, no network. All rules are expressed in plain Python so they are
easy to audit, test, and explain to maintainers.

Output contract
---------------
{
  "issue_linked": bool,
  "description_match": "High" | "Partial" | "Low",
  "change_relevance": "High" | "Medium" | "Low",
  "summary": [str, ...],
  "checklist": [str, ...],
  "recommendation": "Ready for detailed review" | "Needs fixes" | "Needs attention"
}
"""
from __future__ import annotations

import os
import re
from typing import NamedTuple, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ISSUE_RE = re.compile(
    r"""
    (?<!\w)           # not preceded by a word char
    (
      (?:fixes|closes|resolves)\s+\#\d+ |  # closes #123
      \#\d+            |                   # bare #123
      github\.com/[^/]+/[^/]+/issues/\d+  # full issue URL
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".cs",
    ".go", ".rb", ".php", ".rs", ".kt", ".swift", ".h", ".vue", ".scala",
    ".m", ".mm", ".sh", ".bash", ".zsh", ".fish",
}

DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc", ".markdown"}
DOC_DIRS = {"docs", "doc", "documentation"}
DOC_FILESTEMS = {"readme", "license", "changelog", "contributing", "authors", "code_of_conduct"}

TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e"}
TEST_EXTENSIONS = {".test.js", ".test.ts", ".test.jsx", ".test.tsx",
                   ".spec.js", ".spec.ts", ".spec.jsx", ".spec.tsx"}

# Keywords that suggest a functional code change was claimed in the description
FUNCTIONAL_KEYWORDS = re.compile(
    r"\b(fix(es|ed)?|bug|crash|error|regressi|login|auth|database|api|endpoint|"
    r"feature|implement|refactor|migrat|performance|optimiz)\b",
    re.IGNORECASE,
)

MIN_DESCRIPTION_WORDS = 8


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

class FileKind(NamedTuple):
    code: int
    test: int
    doc: int
    other: int

    @classmethod
    def zero(cls) -> "FileKind":
        return cls(0, 0, 0, 0)


def classify_file(path: str) -> str:
    """Return 'test', 'doc', 'code', or 'other'."""
    parts = path.replace("\\", "/").lower().split("/")
    name = parts[-1]
    stem, ext = os.path.splitext(name)

    # Test detection
    if any(p in TEST_DIRS for p in parts[:-1]):
        return "test"
    if name.startswith("test_") or name.endswith("_test" + ext):
        return "test"
    if re.search(r"(_test|_spec|\.test|\.spec)\.[a-z0-9]+$", name):
        return "test"
    if re.search(r"(Test|Tests|Spec)\.[a-z]+$", parts[-1]):
        return "test"
    # compound extensions like .test.ts
    for te in TEST_EXTENSIONS:
        if path.lower().endswith(te):
            return "test"

    # Doc detection
    if ext in DOC_EXTENSIONS:
        return "doc"
    if stem in DOC_FILESTEMS:
        return "doc"
    if any(p in DOC_DIRS for p in parts[:-1]):
        return "doc"

    # Code detection
    if ext in CODE_EXTENSIONS:
        return "code"

    return "other"


def _count_kinds(file_paths: list[str]) -> FileKind:
    code = test = doc = other = 0
    for p in file_paths:
        k = classify_file(p)
        if k == "code":
            code += 1
        elif k == "test":
            test += 1
        elif k == "doc":
            doc += 1
        else:
            other += 1
    return FileKind(code, test, doc, other)


# ---------------------------------------------------------------------------
# Issue link detection
# ---------------------------------------------------------------------------

def _detect_issue_link(title: str, description: str) -> bool:
    text = f"{title}\n{description or ''}"
    return bool(ISSUE_RE.search(text))


# ---------------------------------------------------------------------------
# Description-match scoring
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "this", "that", "with", "from", "into", "have", "has", "will", "when", "then",
    "they", "their", "there", "these", "those", "which", "what", "also", "your",
    "more", "some", "such", "only", "just", "than", "make", "makes", "made", "used",
    "uses", "using", "adds", "added", "add", "fix", "fixes", "fixed", "update",
    "updates", "updated", "change", "changes", "changed", "issue", "closes", "closed",
    "resolves", "pull", "request", "should", "would", "could", "about", "while",
    "where", "each", "other", "code", "file", "files",
}
_GENERIC_PATH_TOKENS = {
    "src", "index", "main", "lib", "init", "app", "utils", "helper", "helpers",
}

TYPE_WORDS = {
    "test": {"test", "tests", "testing", "unittest", "spec", "suite", "coverage"},
    "doc": {"doc", "docs", "documentation", "readme", "guide"},
}


def _tokenize(text: str) -> set[str]:
    # split camelCase / PascalCase
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")
    tokens = re.findall(r"[a-z]{3,}", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) >= 4}


def _stem_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        return a.startswith(b[:4]) or b.startswith(a[:4])
    return False


def _description_match(
    title: str,
    description: str,
    file_paths: list[str],
    kinds: FileKind,
    docs_only: bool,
) -> str:
    """
    Return "High", "Partial", or "Low".

    Rules:
    - Low if description is empty or too vague (< MIN_DESCRIPTION_WORDS words).
    - Low if description claims a functional/code fix but only doc/config files changed.
    - High if code files changed and title/description reasonably correspond to changed file paths.
    - Partial if code changed but the relationship is weak.
    - Low otherwise.
    """
    word_count = len((description or "").split())
    if word_count < MIN_DESCRIPTION_WORDS or not file_paths:
        return "Low"

    # If description implies a code/API change but only docs changed
    if docs_only and FUNCTIONAL_KEYWORDS.search(f"{title} {description}"):
        return "Low"

    desc_tokens = _tokenize(f"{title} {description}")
    path_tokens = set()
    code_path_tokens = set()
    for fp in file_paths:
        tokens = _tokenize(fp) - _GENERIC_PATH_TOKENS
        path_tokens.update(tokens)
        if classify_file(fp) == "code":
            code_path_tokens.update(tokens)

    matched = {dt for dt in desc_tokens if any(_stem_match(dt, pt) for pt in path_tokens)}

    # Check if test/doc references match file categories
    for kind, words in TYPE_WORDS.items():
        if (kind == "test" and kinds.test > 0) or (kind == "doc" and kinds.doc > 0):
            if words & desc_tokens:
                matched.add(f"kind_{kind}")

    if len(matched) >= 2:
        return "High"
    if len(matched) == 1:
        # If the 1 match directly covers the code file and tests exist, treat as High
        if any(_stem_match(m, cpt) for m in matched for cpt in code_path_tokens):
            if kinds.test > 0 and kinds.code > 0:
                return "High"
        return "Partial"
    return "Low"


# ---------------------------------------------------------------------------
# Change relevance
# ---------------------------------------------------------------------------

def _change_relevance(
    kinds: FileKind,
    issue_linked: bool,
    docs_only: bool,
    description: str,
    title: str,
) -> str:
    """
    Return "High", "Medium", or "Low".

    Rules:
    - Low: doc-only changes claiming a code/functional fix.
    - Low: no code files and description claims a functional change.
    - High: code + tests + issue reference.
    - Medium: code exists but missing tests or issue link.
    """
    if docs_only and FUNCTIONAL_KEYWORDS.search(f"{title} {description}"):
        return "Low"

    if kinds.code == 0 and kinds.test == 0 and FUNCTIONAL_KEYWORDS.search(f"{title} {description}"):
        return "Low"

    if kinds.code > 0 and kinds.test > 0 and issue_linked:
        return "High"

    if kinds.code > 0 or kinds.test > 0:
        return "Medium"

    return "Low"


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

def _recommendation(
    description_match: str,
    change_relevance: str,
    kinds: FileKind,
    issue_linked: bool,
    docs_only: bool,
    description: str,
) -> str:
    """
    Return exactly one of: "Ready for detailed review", "Needs fixes", "Needs attention".
    """
    # Needs attention
    if description_match == "Low":
        return "Needs attention"
    if docs_only:
        return "Needs attention"

    # Ready for detailed review
    if (
        kinds.code > 0
        and kinds.test > 0
        and issue_linked
        and description_match == "High"
    ):
        return "Ready for detailed review"

    # Needs fixes
    return "Needs fixes"


# ---------------------------------------------------------------------------
# Summary & checklist builder
# ---------------------------------------------------------------------------

def _build_summary(
    kinds: FileKind,
    issue_linked: bool,
    description_match: str,
    change_relevance: str,
    docs_only: bool,
    description: str,
) -> list[str]:
    items: list[str] = []

    if not description or len(description.split()) < MIN_DESCRIPTION_WORDS:
        items.append("PRPilot signals that the PR description is missing or very short.")
    elif description_match == "High":
        items.append("The changed files appear consistent with the PR description.")
    elif description_match == "Partial":
        items.append("PRPilot signals that only a partial match was found between the description and changed files.")
    else:
        items.append("PRPilot signals that the description does not clearly relate to the changed files.")

    if docs_only:
        items.append("Only documentation files were changed.")
    elif kinds.code > 0 and kinds.test > 0:
        items.append("The PR includes application code and tests.")
    elif kinds.code > 0:
        items.append("Application code was changed, but no test files were detected.")
    elif kinds.test > 0:
        items.append("Only test files were changed.")
    else:
        items.append("No application code or test files were detected in the changed files.")

    if issue_linked:
        items.append("A linked issue reference was detected.")
    else:
        items.append("No linked issue reference was detected (e.g. Fixes #123).")

    return items


def _build_checklist(
    kinds: FileKind,
    issue_linked: bool,
    description_match: str,
    docs_only: bool,
    recommendation: str,
) -> list[str]:
    items: list[str] = []

    if not issue_linked:
        items.append("Add an issue reference to the PR description (e.g. Fixes #123).")

    if kinds.code > 0 and kinds.test == 0:
        items.append("Add or update tests to cover this change.")

    if description_match in ("Partial", "Low"):
        items.append("Expand or clarify the PR description so it reflects the changes made.")

    if kinds.code > 0 or kinds.test > 0:
        items.append("Review the implementation and test coverage before merging.")

    if docs_only:
        items.append("Check the documentation for accuracy and broken links.")

    if not items:
        items.append("Needs maintainer review.")

    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_pr(
    title: str,
    description: Optional[str],
    file_paths: list[str],
) -> dict:
    """
    Analyze a pull request and return a structured result dict.
    """
    description = description or ""
    kinds = _count_kinds(file_paths)
    docs_only = kinds.code == 0 and kinds.test == 0 and kinds.doc > 0

    issue_linked = _detect_issue_link(title, description)
    desc_match = _description_match(title, description, file_paths, kinds, docs_only)
    change_rel = _change_relevance(kinds, issue_linked, docs_only, description, title)
    rec = _recommendation(desc_match, change_rel, kinds, issue_linked, docs_only, description)
    summary = _build_summary(kinds, issue_linked, desc_match, change_rel, docs_only, description)
    checklist = _build_checklist(kinds, issue_linked, desc_match, docs_only, rec)

    return {
        "issue_linked": issue_linked,
        "description_match": desc_match,
        "change_relevance": change_rel,
        "summary": summary,
        "checklist": checklist,
        "recommendation": rec,
        "changed_file_count": len(file_paths),
        "code_file_count": kinds.code,
        "test_file_count": kinds.test,
    }
