# PRPilot Backend

> **"PRPilot provides automated first-pass review guidance. Maintainers make the final merge, request-changes, or close decision."**

PRPilot is a secure, lightweight, GitHub App-based pull-request review assistant designed for repository maintainers. It listens to GitHub pull-request webhooks, cryptographically verifies signatures, inspects changed files, runs deterministic explainable rule-based heuristics, persists results in SQLite (production-ready for PostgreSQL), and leaves a non-intrusive, auto-updating markdown comment on the pull request.

---

## 1. Project Purpose

Reviewing pull requests can be repetitive and time-consuming. PRPilot helps repository maintainers by acting as a first-pass triage bot:

- **Instant Triaging**: Immediately flags whether PR descriptions match the changed code, whether tests were included, and whether issues were referenced.
- **Explainable Heuristics**: Pure deterministic Python rules with zero AI hallucinations, predictable outcomes, and high auditability.
- **Safety First**: PRPilot **never** auto-merges, approves, closes, or rejects PRs. Maintainers always retain full authority.
- **Deduplicated Markdown Comments**: Maintains a single persistent summary comment on GitHub using the `<!-- prpilot-review-summary -->` marker, updating it as new commits are pushed.

---

## 2. Architecture Diagram

```
+---------------------------------------------------------------------------------+
|                                 GitHub Platform                                 |
|                                                                                 |
|  [Developer PR Event]  --->  [GitHub Webhooks]  --->  [GitHub Issues / PR API]  |
+-------------------------------------|---------------------------^---------------+
                                      | (POST HMAC-SHA256)        |
                                      v                           | (JWT / App Token)
                              +---------------+                   |
                              | ngrok tunnel  |                   |
                              +-------|-------+                   |
                                      |                           |
+-------------------------------------v---------------------------|---------------+
|                             PRPilot FastAPI Backend                             |
|                                                                                 |
|  +-----------------------------------------------------------+  |               |
|  | /api/webhooks/github                                      |  |               |
|  |   - Raw byte verification (hmac.compare_digest)           |  |               |
|  |   - De-duplicate delivery tracking (WebhookDelivery)      |  |               |
|  +-----------------------------|-----------------------------+  |               |
|                                v                                |               |
|  +-----------------------------------------------------------+  |               |
|  | worker.py (FastAPI BackgroundTasks)                       |  |               |
|  |   1. Fetch PR details & changed files (github_client.py) -+--+               |
|  |   2. Rule Engine (analyzer.py)                            |                  |
|  |   3. Persist Analysis (models.py: PullRequestAnalysis)    |                  |
|  |   4. Create / Update GitHub Comment ----------------------+                  |
|  +-----------------------------|------------------------------------------------+
|                                v
|                  +----------------------------+
|                  | SQLite Database            |
|                  | (prpilot.db via SQLAlchemy)|
|                  +-------------^--------------+
|                                |
|  +-----------------------------|------------------------------------------------+
|  | REST API Endpoints:                                                          |
|  |   - GET /health                                                              |
|  |   - GET /api/prs                                                             |
|  |   - GET /api/prs/{owner}/{repo}/{pr_number}                                  |
|  |   - POST /api/dev/seed-samples                                               |
|  +-----------------------------^------------------------------------------------+
+--------------------------------|------------------------------------------------+
                                 | (HTTP fetch credentials: include)
                                 |
+--------------------------------v------------------------------------------------+
|                       PRPilot Frontend Dashboard (:8080)                        |
|                                                                                 |
|  [ PR Review List ]   <--->   [ Live Status Cards ]   <--->   [ Checklist View ] |
+---------------------------------------------------------------------------------+
```

---

## 3. Technology Stack

- **Runtime**: Python 3.11+
- **Web Framework**: FastAPI & Uvicorn
- **Database & ORM**: SQLite (via SQLAlchemy 2.0; PostgreSQL-ready)
- **Settings**: Pydantic Settings (`pydantic-settings`)
- **HTTP Client**: `httpx` (async timeouts, resilient connection handling)
- **Security & Crypto**: `PyJWT`, `cryptography`, `hmac`
- **Session Management**: Starlette `SessionMiddleware`
- **Testing**: `unittest` & `pytest`

---

## 4. Installation & Virtual Environment Setup

### Prerequisites
- Python 3.11+
- Git

### Step-by-Step Setup

```bash
# 1. Clone or navigate to the backend repository
cd backend

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the virtual environment
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# On Linux / macOS:
source venv/bin/activate

# 4. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Configuration (.env)

Copy `.env.example` to `.env`:

```bash
# Windows:
copy .env.example .env
# Linux / macOS:
cp .env.example .env
```

### Configuration Variables

| Variable | Default Value | Description |
|---|---|---|
| `APP_ENV` | `development` | Environment mode (`development` or `production`). |
| `APP_BASE_URL` | `http://127.0.0.1:8000` | Public / local base URL for the backend. |
| `FRONTEND_ORIGIN` | `http://127.0.0.1:8080` | Allowed CORS origin (strict origin matching). |
| `DATABASE_URL` | `sqlite:///./prpilot.db` | SQLAlchemy connection string (swap to `postgresql://...` when scaling). |
| `SESSION_SECRET` | *(Random secret)* | Secret used to sign session cookies. |
| `GITHUB_APP_ID` | `""` | GitHub App ID from your App settings page. |
| `GITHUB_APP_CLIENT_ID` | `""` | GitHub App Client ID (for OAuth / Identification). |
| `GITHUB_APP_CLIENT_SECRET`| `""` | GitHub App Client Secret. |
| `GITHUB_APP_PRIVATE_KEY_PATH`| `./secrets/github-app-private-key.pem` | Path to the downloaded RSA private key (.pem). |
| `GITHUB_WEBHOOK_SECRET` | `""` | Secret configured in GitHub App webhook settings. |
| `GITHUB_OAUTH_CALLBACK_URL` | `http://127.0.0.1:8000/api/auth/github/callback` | OAuth redirect URI. |
| `LOCAL_DEVELOPMENT_MODE` | `true` | Enables dev endpoints (`/api/dev/*`) and unauthenticated local mode. |

---

## 6. Running Locally

### Start the FastAPI Server

```bash
uvicorn app.main:app --reload --port 8000
```

The database tables in SQLite (`prpilot.db`) are created automatically on startup via FastAPI lifespan events.

---

## 7. Verifying the Setup

### Check Health

```bash
curl http://127.0.0.1:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "environment": "development",
  "github_app_configured": false
}
```

### Seed Demo Pull Requests

PRPilot comes with a built-in seed endpoint that instantly loads 3 sample PRs covering all recommendation outcomes:

```bash
curl -X POST http://127.0.0.1:8000/api/dev/seed-samples
```

Expected response:
```json
{
  "seeded": 3,
  "message": "Successfully seeded 3 sample PR analyses (Ready for review, Needs fixes, Needs attention)"
}
```

### Query Pull Requests

```bash
curl http://127.0.0.1:8000/api/prs
```

Expected response:
```json
{
  "prs": [
    {
      "repoPrKey": "prpilot-demo/sample-service#101",
      "owner": "prpilot-demo",
      "repo": "sample-service",
      "pr_number": 101,
      "title": "Fix login validation and token expiry check",
      "author": "alice-dev",
      "description": "Fixes #104. Validates user login credentials, prevents null token bypass, and adds comprehensive test suite.",
      "github_url": "https://github.com/prpilot-demo/sample-service/pull/101",
      "changed_files": [
        "app/auth/service.py",
        "app/auth/validator.py",
        "tests/test_auth_service.py"
      ],
      "changed_file_count": 3,
      "code_file_count": 2,
      "test_file_count": 1,
      "issue_linked": true,
      "description_match": "High",
      "change_relevance": "High",
      "summary": [
        "The changed files appear consistent with the PR description.",
        "The PR includes application code and tests.",
        "A linked issue reference was detected."
      ],
      "checklist": [
        "Review the implementation and test coverage before merging."
      ],
      "recommendation": "Ready for detailed review",
      "timestamp": 1758364800
    },
    ...
  ]
}
```

### Query Single PR Detail

```bash
curl http://127.0.0.1:8000/api/prs/prpilot-demo/sample-service/101
```

---

## 8. Running the Frontend

When running the frontend dashboard at `http://127.0.0.1:8080`:

```javascript
fetch("http://127.0.0.1:8000/api/prs", {
  credentials: "include"
})
```

FastAPI CORS is configured to accept credentials from `http://127.0.0.1:8080` (and `http://localhost:8080` in dev).

---

## 9. Connecting to Real GitHub Webhooks via ngrok

To test live pull requests from GitHub on your local machine:

1. **Start ngrok**:
   ```bash
   ngrok http 8000
   ```
   Note your forwarding URL (e.g., `https://abcdef123.ngrok-free.app`).

2. **Configure Webhook in GitHub App Settings**:
   - **Webhook URL**: `https://YOUR-NGROK-DOMAIN/api/webhooks/github`
   - **Webhook secret**: Enter a strong secret (e.g., `my-super-secret-key-12345`).
   - Copy this value into `.env` as `GITHUB_WEBHOOK_SECRET=my-super-secret-key-12345`.
   - **SSL verification**: Enable SSL verification.

3. **Required GitHub App Permissions**:
   - **Repository permissions**:
     - **Pull requests**: `Read and write` (to inspect files and read PR data).
     - **Issues**: `Read and write` (to create and update PR comments).
     - **Contents**: `Read-only` (optional, to read repository structure).
     - **Metadata**: `Read-only` (default mandatory).
   - **Subscribe to events**:
     - `Pull request`

4. **Generate and Save Private Key**:
   - In GitHub App settings, click **Generate a private key**.
   - Save the downloaded `.pem` file to `backend/secrets/github-app-private-key.pem`.
   - Set `GITHUB_APP_ID` in `.env`.

---

## 10. Security Notes

1. **Raw Body Verification**: Webhook HMAC-SHA256 signatures are calculated against the exact raw byte stream *before* JSON parsing, using constant-time comparison (`hmac.compare_digest`) to prevent timing attacks.
2. **Zero Secret Leakage**: Access tokens, private keys, session secrets, and webhook secrets are never logged, never returned in API responses, and never exposed to the frontend.
3. **Strict CORS**: Credentials are only allowed from the configured `FRONTEND_ORIGIN`. Wildcard origins (`*`) are disallowed with credentials.
4. **Git Safety**: All secrets, `.env`, RSA private keys (`*.pem`), and SQLite database files (`*.db`) are ignored by `.gitignore`.
5. **No AI Injections**: Pure deterministic rules eliminate prompt injection risks from malicious PR titles or descriptions.

---

## 11. API Endpoint Summary

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/health` | System health and GitHub App status | Public |
| `GET` | `/api/prs` | List all analyzed pull requests | Public / Session |
| `GET` | `/api/prs/{owner}/{repo}/{pr_number}` | Detailed analysis for a single PR | Public / Session |
| `POST` | `/api/webhooks/github` | GitHub Webhook receiver (signature verified) | HMAC Header |
| `POST` | `/api/dev/seed-samples` | Seed 3 sample PRs (dev mode only) | Dev Only |
| `POST` | `/api/dev/analyze-sample-pr` | Analyze sample PR payload (dev mode only) | Dev Only |
| `GET` | `/api/auth/github/login` | Initiate GitHub OAuth login | Public |
| `GET` | `/api/auth/github/callback` | Handle OAuth callback & establish session | Public |
| `GET` | `/api/auth/me` | Current authenticated user info | Session |
| `POST` | `/api/auth/logout` | Terminate user session | Session |
| `GET` | `/api/installations` | List GitHub App installations | Public / Session |
| `GET` | `/api/repositories` | List active repositories | Public / Session |

---

## 12. Running Automated Tests

Run the complete test suite:

```bash
python -m unittest tests/test_fastapi_backend.py -v
```

Or using `pytest`:

```bash
pytest tests/test_fastapi_backend.py -v
```

---

## 13. Known Limitations & Future Work

1. **Background Tasks**: Current async worker runs via FastAPI `BackgroundTasks` in-process. For high scale (10,000+ webhooks/minute), migrate worker tasks to Celery / Redis / AWS SQS.
2. **Database Migration**: Currently runs on SQLite for zero-configuration local execution. To switch to PostgreSQL, update `DATABASE_URL=postgresql://user:pass@host:5432/prpilot` (all models and queries are SQLAlchemy standard).
3. **Diff Chunk Scanning**: Currently evaluates changed file paths and PR descriptions. Future versions can parse unified diff line additions to check for sensitive credential leaks (`.env`, hardcoded secrets).
