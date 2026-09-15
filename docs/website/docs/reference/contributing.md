---
sidebar_position: 3
---

# Contributing

ReqTrackManager is open source. This page is a short pointer, not a full contributor guide — the real, up-to-date instructions live in the repository itself and are kept in sync with the actual codebase, rather than duplicated here where they'd drift.

## Local setup

```bash
cd tests/container
docker compose up --build -d
```

brings up the full dev/evaluation stack (Postgres, MinIO, MailHog, Keycloak, backend, frontend) with sensible defaults and no secrets to configure — this is the stack contributors and CI both use, deliberately kept separate from the production Compose file. See [Installation & Deployment → Quick start](../installation-deployment/quick-start.md) for the full walkthrough, including demo data.

## Test suites

- **Backend**: `pytest` (from `backend/`, or `docker compose exec backend pytest -q`) — runs against its own dedicated test database, isolated from anything manually seeded in the dev stack.
- **Frontend**: `npm run storybook` / `npm run test-storybook` (component-level, real Chromium via Playwright) — from `frontend/`.
- **End-to-end**: the Playwright suite (`tests/playwright/`) drives a real browser against the full running stack.

## Linting

- Backend: `ruff check app` (from `backend/`).
- Frontend: `npm run lint` (ESLint — TypeScript, React Hooks, Fast Refresh rules).

## Continuous integration

Every push and pull request to `main` runs frontend lint/type-check/build plus the Storybook suite, the full backend pytest suite plus `ruff`, and the full Playwright E2E suite — all against the same Docker Compose stack described above. Passing builds are tagged with a computed SemVer and published as container images.

## Where to find the full guide

The complete contributor workflow — backend/frontend setup outside Docker, every test-suite invocation, dependency-update discipline, and how to reproduce CI locally with `act` — lives in [`docs/development.md`](https://github.com/ballardr/reqtrackmanager/blob/main/docs/development.md) in the repository. Start there before opening a pull request.
