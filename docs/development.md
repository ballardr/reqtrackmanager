# Development Guide

This guide covers running ReqTrackManager locally to try it out or hack on it, plus the day-to-day contributor workflow: backend/frontend setup outside Docker, running the test suites, linting, and CI. For deploying a real instance, see [deployment.md](deployment.md); for the product itself, see the [README](../README.md) and [user-guide.md](user-guide.md).

## Quick start — local development / evaluation

Use the dedicated dev/test stack, **not** the root `docker-compose.yml` (that one is production-oriented and requires real secrets — see [deployment.md](deployment.md)):

```bash
cd tests/container
docker compose up --build
```

This starts Postgres (its own `reqtrack_test` database, isolated from any production instance), MinIO (S3-compatible file storage), MailHog (SMTP catcher), Keycloak (a real OIDC provider, for testing per-organisation SSO end-to-end), the backend, and the frontend. On first boot the backend automatically runs database migrations and creates a bootstrap **server admin** user and default organisation.

Once healthy:

- **Frontend UI**: http://localhost:3000
- **Backend API / Swagger UI**: http://localhost:8000/docs
- **Backend OpenAPI schema (JSON)**: http://localhost:8000/openapi.json
- **Health check**: http://localhost:8000/health
- **Prometheus metrics**: http://localhost:8000/metrics
- **MCP server** (AI-assistant access to requirements — see [mcp-server.md](mcp-server.md)): http://localhost:8100/mcp
- **MailHog UI** (view sent notification emails): http://localhost:8025
- **MinIO console** (view uploaded files): http://localhost:9001

Default bootstrap admin login: `admin@example.com` / `ChangeMe123!`.

**Never point this stack at the internet, and never confuse it with the production stack** (`docker-compose.yml`, repo root) — see [deployment.md](deployment.md#two-separate-compose-stacks) for why they're kept deliberately separate.

### Demo data

To populate the running stack with a realistic, presentable dataset (a fictional drone-inspection company, two projects at different lifecycle stages, requirements at varied statuses, an approved and a pending change request, discussion threads, custom fields, and a branded report template):

```bash
cd tests/container && docker compose exec backend python scripts/seed_demo_data.py
```

Idempotent (skips if already seeded) and API-driven, same as the E2E persona dataset (`scripts/seed_e2e_dataset.py`) — this is a separate script with separate, screenshot-friendly content, not a variant of the E2E fixtures. Login as `demo.admin@example.com` / `DemoDemo123!` afterward; see the script's own docstring for the other seeded personas and their roles. This is also the dataset the README's screenshots are captured from.

There's no organisation-deletion endpoint (see [docs/soc2/policies/data-retention-and-disposal-policy.md](soc2/policies/data-retention-and-disposal-policy.md)), so this script only skips rather than resets existing demo data. A future public demo instance that resets nightly would do the reset at the database level instead — `docker compose down -v && docker compose up -d --build` against a dedicated demo compose stack, then re-run the seed script — the same pattern used below to get back to a clean slate.

## Backend

```bash
cd tests/container
docker compose up -d db   # needs the dev/test Postgres running (reqtrack_test)

cd ../../backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://reqtrack:reqtrack@localhost:5432/reqtrack_test
uvicorn app.main:app --reload --port 8000
```

Migrations run automatically on startup. To run them manually: `alembic upgrade head` (from `backend/`).

**Backend tests** must run against a `*_test`-suffixed database — `tests/conftest.py` refuses to start otherwise, since the suite drops and recreates the entire schema at the start of every run (running it against the wrong database would destroy real data):

```bash
cd tests/container && docker compose up -d db   # provides reqtrack_test
cd ../../backend && source .venv/bin/activate
DATABASE_URL=postgresql://reqtrack:reqtrack@localhost:5432/reqtrack_test pytest -q
```

Or run them inside the dev/test stack's own backend container, which already has `DATABASE_URL` pointed at `reqtrack_test`:

```bash
cd tests/container && docker compose exec backend pytest -q
```

Note: every test truncates all tables, including the bootstrap admin user, so after a pytest run the dev/test stack's own backend/frontend will have no data left to browse — `docker compose restart backend` re-runs migrations and re-creates the bootstrap admin if you also want to use the UI or run Playwright afterward (Playwright itself doesn't need this if you haven't run pytest since the stack last started).

**Linting** (N-E-04): `ruff` is configured in `backend/pyproject.toml` — `ruff check app` (or `tests`) from `backend/`. `B008` (function calls in argument defaults) is deliberately disabled since FastAPI's `Depends(...)` dependency-injection idiom is exactly that pattern.

## Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000, proxies to VITE_API_BASE_URL (default http://localhost:8000)
npm run build    # type-checks with tsc, then builds
npm run lint     # ESLint (N-E-07): TypeScript + React Hooks + Fast Refresh rules
npm run storybook       # component explorer at http://localhost:6006, with a light/dark theme toggle
npm run build-storybook # static Storybook build
npm run test-storybook  # runs every story as an automated test (real Chromium via Playwright), both themes included
```

## End-to-end tests

Requires the dev/test stack running:

```bash
cd tests/container && docker compose up --build -d

cd ../playwright
npm install
npx playwright install --with-deps chromium
npm test
```

## Continuous integration

`.github/workflows/ci.yml` runs on every push/PR to `main`: frontend lint + type-check + build, the full backend pytest suite with coverage (reported as a check, a job-summary percentage, and a downloadable HTML report) plus `ruff` lint against the real dev/test Docker Compose stack, and the full Playwright E2E suite against the running containers — all of it gating. A final job builds the production backend/frontend/mcp-server images once the two test jobs pass, tags each with a [GitVersion](https://gitversion.net/)-computed SemVer plus the commit SHA and `latest`, and pushes all three to `ghcr.io/<owner>/<repo>-{backend,frontend,mcp-server}` — except on pull request runs, which still build (proving the Dockerfiles work) but never push. See [deployment.md](deployment.md#obtaining-container-images) for how to point `docker-compose.yml` at a published image instead of building locally.

See the [README's Code Quality Rules](../README.md#code-quality-rules) for the conventions all of the above is expected to follow.
