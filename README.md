# PRPilot

PRPilot is a GitHub pull-request review assistant for maintainers. It helps teams move from an incoming PR to a clear first-pass review by comparing the pull request description with its changed files, checking for tests and linked issues, generating a concise summary and checklist, and producing a review recommendation.

PRPilot is designed to make review triage faster and more consistent while keeping maintainers in control. It does **not** automatically merge or reject pull requests.

## What PRPilot Does

For each pull request, PRPilot can analyze:

- Whether the description matches the files that changed
- Whether the change appears meaningful and relevant
- Whether tests were added or updated
- Whether an issue or bug report is linked
- A short summary of the review findings
- A checklist of suggested fixes or follow-up actions
- A recommendation such as ready for review, needs fixes, or needs attention

## Features

- Maintainer dashboard for reviewing analyzed pull requests
- Status statistics for ready, needs-fixes, and needs-attention PRs
- Filters for quickly triaging the review queue
- Three quick quality signals on every PR card
- Detailed PR analysis view with changed files, summaries, and suggested actions
- Repository insights, including issue/test gaps and estimated review time saved
- GitHub account, organization, and repository selection flow
- Backend-authenticated GitHub connection using secure session cookies
- Local development/demo mode when authentication or backend services are unavailable
- Responsive interface built for desktop demos and smaller screens
- Fallback sample data for reliable hackathon demonstrations

## Architecture

PRPilot is organized around a lightweight frontend and a backend analysis service.

```text
GitHub OAuth
    |
    v
Backend session + GitHub App installations
    |
    v
Vanilla frontend dashboard
    |
    v
Pull-request analysis service
    |
    v
Summary, checklist, quality signals, recommendation
```

### Frontend

The current frontend uses only HTML, CSS, and vanilla JavaScript:

- `frontend/index.html` contains the semantic application structure and onboarding views.
- `frontend/style.css` contains the responsive GitHub-inspired design system.
- `frontend/app.js` handles authentication checks, repository selection, PR fetching, filtering, rendering, and demo fallback behavior.

### Backend direction

The frontend is being connected to a backend that uses SAM CLI for local serverless development and LocalStack for local AWS service emulation. GitHub authentication and sensitive credentials belong in the backend environment, never in frontend code or browser storage.

## Local Frontend Setup

No npm install or build step is required for the current frontend.

From the project root:

```powershell
cd frontend
python -m http.server 8080
```

Open the local dashboard at:

```text
http://127.0.0.1:8080
```

The frontend can run in demo mode without a backend. When the backend is available, it uses the configured authenticated API endpoints and loads pull-request data for the selected repository.

## Backend Development Direction

The frontend is designed to work with backend routes for:

- GitHub authentication and callback handling
- Current authenticated-user checks
- GitHub App installation and repository discovery
- Repository-specific pull-request analysis
- Secure logout and session management

A typical local backend workflow will use SAM CLI to run the service and LocalStack to emulate required AWS resources. Backend setup commands may vary as the service is finalized, so keep infrastructure configuration and secrets outside the frontend directory.

## Project Structure

```text
PRPILOT/
├── frontend/
│   ├── app.js
│   ├── index.html
│   └── style.css
├── .gitignore
└── README.md
```

## Team Contributions

Use this section to record hackathon ownership and contributions.

| Team member | Role | Contributions |
| --- | --- | --- |
| Name | Product / frontend | Dashboard, onboarding, and review experience |
| Name | Backend / infrastructure | API, SAM CLI, and LocalStack integration |
| Name | GitHub integration | OAuth, GitHub App, and repository access |
| Name | Analysis / testing | PR analysis logic, test coverage, and demo validation |

Replace the placeholder names and descriptions with the team’s actual contributions before presenting or submitting the project.

## Safety Boundary

PRPilot provides review guidance only. It does not automatically merge, reject, close, or modify pull requests. Maintainers make every final decision, including whether to merge, request changes, or close a contribution.

## Hackathon Status

PRPilot is an active hackathon project. The frontend is demo-ready, while the SAM CLI and LocalStack-backed backend integration is being developed alongside the GitHub authentication and pull-request analysis services.
