# CI

The single source of truth for continuous integration is
[`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml).

The old `github_actions_ci.yml` template lived here but was never wired up; it has
been retired so the repository does not carry two diverging pipeline definitions.
Job layout, versions, and commands are documented in the workflow itself.

## Jobs

| Job | What it does |
|---|---|
| `backend-tests` | Full `pytest tests -n auto -q` suite in `backend/` on Python 3.11 and 3.12 |
| `frontend` | `npm ci` → `npm run typecheck` → `npm run build` → `npm test` on Node 24 |
| `lint` | `ruff check backend` with the config in `backend/pyproject.toml` |
| `docker-build` | Builds the root `Dockerfile` (no run, no secrets) |

For `main` branch protection, mark the four jobs as required (the backend
matrix yields two checks, so five check names in total):
`Backend tests (Python 3.11)`, `Backend tests (Python 3.12)`,
`Frontend (Node 24)`, `Ruff lint`, and `Docker build`.

## Local equivalents

```bash
# One-time: dev/test tools (pytest, xdist, subtests, asyncio, ruff) into the
# venv created by backend/deploy/install.sh
backend/.venv/bin/pip install -r backend/requirements-dev.txt

# Backend full suite (same command as CI)
cd backend && .venv/bin/pytest tests -n auto -q && cd ..

# Frontend (Node 24 required; tests import TypeScript sources directly)
cd frontend && npm run typecheck && npm run build && npm test && cd ..

# Lint
backend/.venv/bin/ruff check backend
```

Development-only tools are pinned in `backend/requirements-dev.txt`.
`backend/deploy/install.sh` installs runtime dependencies only, so install that
file once before running the commands above.
