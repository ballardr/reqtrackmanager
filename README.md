# ReqTrackManager

[![CI](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml/badge.svg)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)

ReqTrackManager is an open-source engineering requirements management system (ERMS) for product development teams — a formal alternative to IBM DOORS-style tools for teams that can't justify the cost, without falling back to a static requirements document. See [docs/requirements.md](docs/requirements.md) for the full product requirements and [docs/solution-architecture.md](docs/solution-architecture.md) for the architecture.

This build implements the **Ossa (v1)**, **Pelion (v2)**, and most of **Massif (v3)** milestones: a complete requirements management workflow (organisations/projects, role-based access, requirement authoring with full version history, stage approval and baselining, formal change requests, discussion threads, PDF/CSV reporting with images), Pelion v2's customisation, notification, and file-management layer (custom fields, per-project terminology, project templates, file attachments and shared resources, in-app/email notifications, 2FA, project favourites/filters), and Massif v3's enterprise layer (requirement review scheduling with due-date notifications, change-request tasks and advisory stakeholder voting, project-stage review deadlines with assumed-approval, requirement/stage completion tracking, an access-review user directory, selectable report branding, and SSO/OIDC login tested end-to-end against a real Keycloak instance) — plus, beyond the requirements doc, public self-signup (server-admin-controlled mode, org-level email-domain auto-accept), inviting an external user onto a project by email (with a dedicated provisioning path for SSO-only organisations), and real backend enforcement of an organisation's SSO-only setting. See [docs/decisions.md](docs/decisions.md) for the scoping and implementation decisions made along the way, [docs/enterprise-integration.md](docs/enterprise-integration.md) for the SSO design and the SCIM/separate-port-provisioning blueprint, [docs/mcp-server.md](docs/mcp-server.md) for giving an AI assistant read-only access to requirements, [docs/deployment.md](docs/deployment.md) for deploying to production, and [docs/user-guide.md](docs/user-guide.md) for a walkthrough of using the app.

## What's included

- **Backend**: Python/FastAPI, PostgreSQL via SQLAlchemy 2.0 + Alembic, JWT auth with a pluggable auth-backend interface (native + per-organisation OIDC/SSO) and optional TOTP 2FA (an organisation can require it org-wide), RBAC (org + project roles and groups), full requirement version history and stage-approval baselining, a two-level component/category tree per project, change-request workflow with tasks and advisory stakeholder voting, custom requirement/change-request attributes and per-project terminology, project templates, file attachments and organisation shared resources (pluggable local/S3-compatible storage), in-app and email notifications with per-type preferences and daily digest, personal access tokens scopable down to specific organisations and projects, CSV bulk-import of requirements, PDF (ReportLab, with selectable org branding templates and a Markdown-or-WYSIWYG report intro/chapters/appendices that a project can leave to its organisation's default) and CSV reporting with filters, application-layer encryption for stored secrets (OIDC client secrets, per-org SMTP passwords, TOTP secrets), Prometheus metrics, health checks, optional WebSocket live-update stream, OpenAPI/Swagger docs.
- **Frontend**: React + TypeScript (Vite), light/dark theming via CSS variables, responsive layout, project list (with favourites/role/stage filters, organisation and requirement-count shown per project)/overview/requirements/change-requests/history/admin/reports/preferences pages, click-to-filter status badges, a full notification history page alongside the header's notification bell, an in-app help page (Markdown-driven, with Mermaid workflow diagrams) linked from the header, and a CSV import wizard that maps the file's own column headers onto the required fields with a live preview before anything is uploaded.
- **MCP server**: a read-only [Model Context Protocol](https://modelcontextprotocol.io) server (`mcp-server/`) exposing requirements/projects/organisations as tools an AI assistant can call directly — Claude Code, VS Code Copilot Chat, and Microsoft Copilot Studio are all documented — authenticated by forwarding the caller's own ReqTrackManager access token, never a shared service account. See [docs/mcp-server.md](docs/mcp-server.md).
- **Infrastructure**: two separate Docker Compose stacks — the root `docker-compose.yml` (production-oriented: Postgres + backend + frontend + MinIO + the MCP server, requiring real secrets/SMTP config, plus an optional observability profile) and `tests/container/docker-compose.yml` (local development and automated testing: the same stack plus MailHog and a real Keycloak instance for SSO testing, with dev-friendly defaults and its own isolated test database). See "Quick start" and [docs/deployment.md](docs/deployment.md).
- **Tests**: backend pytest suite (~90%+ statement coverage — auth, RBAC boundaries and a systematic permission matrix, full resource create/read/remove lifecycles, requirement lifecycle/locking, the component/category tree, change-request workflow, files, notifications/digest, custom fields, templates, 2FA (including org-wide enforcement), favourites/filters, report generation and embedded images, self-signup, SSO-only enforcement, and external-user/invite provisioning) and a Playwright end-to-end suite (16 spec files covering the golden path, the full Pelion v2 and Massif v3 feature sets, click-to-filter badges, multi-org/RBAC-boundary workflows, SSO login tested against a real Keycloak container, self-signup across all three modes, an external-user invite completed through a real MailHog email, and a report-image round trip) in a real browser — both run against `tests/container/docker-compose.yml`, never against a production stack, and both run automatically in CI (see "Continuous integration" below). The frontend has a Storybook component explorer with light/dark theme coverage, run as automated tests via Vitest + Playwright (`npm run test-storybook`).

## Screenshots

Captured from the seeded demo dataset (see "Demo data" below) — a fictional drone-inspection company with two projects at different lifecycle stages.

|  |  |
| --- | --- |
| **Project dashboard** — favourites, role/stage filters, tile or list view | **Project overview** — status breakdown, change-request funnel, stage progress, activity feed |
| ![Projects dashboard](docs/screenshots/projects-page.png) | ![Project overview](docs/screenshots/project-overview.png) |
| **Requirements list** — status, target version, category filters | **Requirement detail** — version history, change log, discussion thread |
| ![Requirements list](docs/screenshots/requirements-list.png) | ![Requirement detail](docs/screenshots/requirement-detail.png) |
| **Change request** — tasks, advisory stakeholder votes, discussion, approve/reject | **Organisation admin** — members, roles, 2FA status, access-review filters |
| ![Change request detail](docs/screenshots/change-request-detail.png) | ![Organisation admin](docs/screenshots/org-admin.png) |
| **Reports** — filtered PDF/CSV export with selectable org branding | **Reviews due** — requirements with a scheduled review date now overdue |
| ![Reports](docs/screenshots/reports-page.png) | ![Reviews due](docs/screenshots/reviews-due.png) |

<details>
<summary>Login page</summary>

![Login page](docs/screenshots/login-page.png)
</details>

## Quick start — local development / evaluation

Use the dedicated dev/test stack, **not** the root `docker-compose.yml` (that one is production-oriented and requires real secrets — see below):

```bash
cd tests/container
docker compose up --build
```

This starts Postgres (its own `reqtrack_test` database, isolated from any production instance), MinIO (S3-compatible file storage), MailHog (SMTP catcher), the backend, and the frontend. On first boot the backend automatically runs database migrations and creates a bootstrap **server admin** user and default organisation.

Once healthy:

- **Frontend UI**: http://localhost:3000
- **Backend API / Swagger UI**: http://localhost:8000/docs
- **Backend OpenAPI schema (JSON)**: http://localhost:8000/openapi.json
- **Health check**: http://localhost:8000/health
- **Prometheus metrics**: http://localhost:8000/metrics
- **MCP server** (AI-assistant access to requirements — see [docs/mcp-server.md](docs/mcp-server.md)): http://localhost:8100/mcp
- **MailHog UI** (view sent notification emails): http://localhost:8025
- **MinIO console** (view uploaded files): http://localhost:9001

Default bootstrap admin login: `admin@example.com` / `ChangeMe123!`.

### Demo data

To populate the running stack with a realistic, presentable dataset (the one used for the screenshots above — a fictional drone-inspection company, two projects at different lifecycle stages, requirements at varied statuses, an approved and a pending change request, discussion threads, custom fields, and a branded report template):

```bash
cd tests/container && docker compose exec backend python scripts/seed_demo_data.py
```

Idempotent (skips if already seeded) and API-driven, same as the E2E persona dataset (`scripts/seed_e2e_dataset.py`) — this is a separate script with separate, screenshot-friendly content, not a variant of the E2E fixtures. Login as `demo.admin@example.com` / `DemoDemo123!` afterward; see the script's own docstring for the other seeded personas and their roles.

There's no organisation-deletion endpoint (see [docs/soc2/policies/data-retention-and-disposal-policy.md](docs/soc2/policies/data-retention-and-disposal-policy.md)), so this script only skips rather than resets existing demo data. A future public demo instance that resets nightly would do the reset at the database level instead — `docker compose down -v && docker compose up -d --build` against a dedicated demo compose stack, then re-run the seed script — the same pattern already used throughout local development to get back to a clean slate (see [docs/deployment.md](docs/deployment.md)'s troubleshooting section).

## Production deployment

The root `docker-compose.yml` is the production-oriented stack: no MailHog, no baked-in secret defaults (it refuses to start until you provide `JWT_SECRET`, `APP_SECRET_ENCRYPTION_KEY`, `SERVER_ADMIN_PASSWORD`, `MINIO_ROOT_PASSWORD`, and `SMTP_HOST` via environment or a `.env` file), and Postgres isn't exposed to the host. See [docs/deployment.md](docs/deployment.md) for the full guide, including required configuration and a security checklist.

```bash
docker compose up --build -d
```

### Optional observability stack

```bash
docker compose --profile observability up -d
```

Adds Prometheus (http://localhost:9090), Loki, Tempo, Grafana Alloy, and Grafana (http://localhost:3300, anonymous viewer access enabled for local use). Prometheus is pre-configured to scrape the backend's `/metrics` endpoint; Alloy ships container logs to Loki and exposes an OTLP receiver on `4317` ready to forward traces to Tempo once the backend is instrumented with OpenTelemetry (not yet done — see decisions log).

## Configuration

Backend environment variables (set via `docker-compose.yml`, a `.env` file, or your process manager). The "Required in prod?" column reflects the root `docker-compose.yml`, which refuses to start without them (`tests/container/docker-compose.yml` fills in dev-friendly defaults for all of these):

| Variable | Default | Required in prod? | Purpose |
| --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql://reqtrack:reqtrack@localhost:5432/reqtrack` | — | SQLAlchemy connection string |
| `POSTGRES_PASSWORD` | `reqtrack` | Recommended | Postgres password, shared by the `db` service and the backend's `DATABASE_URL` |
| `JWT_SECRET` | `change-me-in-production` | **Yes** | Access token signing secret |
| `APP_SECRET_ENCRYPTION_KEY` | `change-me-in-production` | **Yes** | Encrypts SSO client secrets, per-org SMTP passwords, and TOTP secrets at rest (application-layer, distinct from `JWT_SECRET` so the two can be rotated independently) |
| `JWT_ALGORITHM` | `HS256` | — | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | — | Access token lifetime |
| `SERVER_ADMIN_ENABLED` | `true` | — | Whether to bootstrap the server-admin user (I-M-06) |
| `SERVER_ADMIN_EMAIL` | `admin@example.com` | — | Bootstrap server-admin login |
| `SERVER_ADMIN_PASSWORD` | `ChangeMe123!` | **Yes** | Bootstrap server-admin password |
| `SERVER_ADMIN_CREATE_ORG` | `true` | — | Also create a default org with the admin as org admin (I-M-08) |
| `CORS_ORIGINS` | `http://localhost:3000` | Recommended | Comma-separated allowed frontend origins |
| `STORAGE_BACKEND` | `local` (Compose default: `s3`) | — | File storage backend: `local` (filesystem) or `s3` (MinIO/S3-compatible), I-M-10 |
| `STORAGE_LOCAL_DIR` | `./data/files` | — | Filesystem directory used by the `local` storage backend |
| `STORAGE_S3_BUCKET` / `STORAGE_S3_ENDPOINT_URL` / `STORAGE_S3_ACCESS_KEY` | see `docker-compose.yml` | — | Connection details for the `s3` storage backend |
| `MINIO_ROOT_PASSWORD` / `STORAGE_S3_SECRET_KEY` | `minioadmin` | **Yes** | MinIO admin password, shared with the backend's S3 secret key |
| `SMTP_HOST` | — | **Yes** | Outgoing SMTP host (C-N-03) — a real provider in production, MailHog in the dev/test stack |
| `SMTP_PORT` / `SMTP_USE_TLS` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_ADDRESS` | see `docker-compose.yml` | Recommended | Remaining SMTP connection details |
| `DEPLOYMENT_NOTIFICATION_EMAIL` | unset | — | Address notified of deployment-level events such as low disk space (I-M-09, I-M-11) |
| `DISK_USAGE_WARNING_THRESHOLD_PERCENT` | `90` | — | Disk usage monitor threshold for the `local` storage backend (I-M-11) |
| `WEBSOCKET_ENABLED` | `true` | — | Whether the optional live-update WebSocket interface is mounted at all (I-A-04) |
| `GEOIP_LOOKUP_ENABLED` | `false` | — | Whether login events resolve an approximate location for the client IP via a third-party lookup (C-A-07). Off by default since it's an external network dependency; login is never blocked by it regardless |
| `GEOIP_LOOKUP_EXCLUDE_CIDRS` | private/loopback ranges | — | Comma-separated CIDR ranges never sent to the geolocation lookup, even when enabled |
| `PUBLIC_BACKEND_URL` | `http://localhost:8000` | Recommended if SSO is used | This backend's own externally-reachable base URL — must exactly match the redirect URI registered on any OIDC identity provider (E-U-01) |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Recommended if SSO is used | The frontend's base URL, used to redirect back to the UI once an OIDC login completes (E-U-01) |
| `OIDC_INTERNAL_BASE_URL_OVERRIDE` | unset | — | Dev/test-only escape hatch for a containerized identity provider whose public URL isn't reachable from inside the backend's own container — see [docs/enterprise-integration.md](docs/enterprise-integration.md). Leave unset in production. |
| `OIDC_ALLOW_PRIVATE_NETWORK_TARGETS` | `false` | — | Set `true` only if every organisation on this deployment runs its own trusted, internally-hosted identity provider with no public IP (e.g. an on-prem Keycloak/Authentik on a corporate LAN or VPC). Disables the SSRF guard that otherwise rejects an org's `oidc_issuer_url` resolving to a private/internal address — see [docs/enterprise-integration.md](docs/enterprise-integration.md). Leave `false` on any deployment serving mutually-untrusted organisations. |

Frontend: `VITE_API_BASE_URL` (build-time, via `frontend/.env`) or the container-runtime equivalent `PUBLIC_API_BASE_URL` passed to `docker-compose.yml`, which is injected into a generated `env-config.js` at container startup — the same built frontend image can point at different backends without a rebuild. Set it to an **empty** value (not left unset) to make the frontend call the API via relative paths against its own origin, instead of an absolute URL — the setting behind same-origin subpath deployment (UI at `my.website.com/`, API at `my.website.com/api/`, avoiding CORS entirely instead of configuring around it); see [docs/deployment.md](docs/deployment.md#same-origin-subpath-deployment-avoiding-cors) for the full reverse-proxy recipe.

## Development workflow

### Backend

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

### Frontend

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

### End-to-end tests

Requires the dev/test stack running:

```bash
cd tests/container && docker compose up --build -d

cd ../playwright
npm install
npx playwright install --with-deps chromium
npm test
```

### Continuous integration

`.github/workflows/ci.yml` runs on every push/PR to `main`: frontend lint + type-check + build, the full backend pytest suite with coverage (reported as a check, a job-summary percentage, and a downloadable HTML report) plus `ruff` lint against the real dev/test Docker Compose stack, and the full Playwright E2E suite against the running containers — all of it gating. A final job builds the production backend/frontend images (proving both Dockerfiles still build) once the two test jobs pass; it does not publish them yet — see the comments at the top of that job for exactly what to uncomment when ready.

### Backups

Backups target the production stack's `db` service (run from the repo root, with the root stack up):

```bash
./scripts/backup.sh [output-dir]     # pg_dump, gzip'd, timestamped
./scripts/restore.sh <backup-file>   # restores into the running db service
```

If `STORAGE_BACKEND=local`, also back up the storage directory (`STORAGE_LOCAL_DIR`) separately — `scripts/backup.sh` only covers the database. If using the `s3` backend (the default, via MinIO), use MinIO's own backup/replication tooling for the `reqtrack_minio_data` volume.

## Architecture overview

The diagram below shows the system's runtime components and how requests flow between them. The React frontend is the only thing an end user's browser talks to; it calls the FastAPI backend over REST/JSON, which in turn is the only component that talks to PostgreSQL, file storage, and outgoing email. An AI assistant follows the same rule from a different direction: the MCP server is a second, independent caller of the same REST API, holding no credentials of its own and authenticating as whoever configured it — see [docs/mcp-server.md](docs/mcp-server.md). Reading it left to right traces a typical request: a user action in the browser (or an AI assistant's tool call) becomes an API call, which the backend serves by reading/writing the database and, where relevant, storing a file or sending a notification email. This matters because it shows the backend as the sole enforcement point for permissions and business rules (neither the frontend nor the MCP server has independent logic to bypass it), and it shows exactly which two backing services (storage and email) are pluggable per environment — local disk/MailHog for development, S3-compatible storage/a real SMTP provider for production.

```mermaid
flowchart LR
    User[User] --> UI[React Web Frontend]
    AI[AI assistant] --> MCP[MCP server]
    UI --> API[Python/FastAPI Backend]
    MCP -->|forwards the caller's own token| API
    API --> DB[(PostgreSQL)]
    API --> FS[(File Storage: local or MinIO/S3)]
    API --> Mail[Email: MailHog or SMTP]
    API -. metrics .-> Prom[Prometheus]
    API -. optional .-> WS[WebSocket clients]
```

The frontend is a single-page app talking to a REST/JSON API (I-A-01, I-A-02), documented via OpenAPI (I-A-03). The backend enforces the full permission and workflow model server-side — the frontend has no independent business logic. See [docs/solution-architecture.md](docs/solution-architecture.md) for the full domain model, ER diagrams, and deployment topology, and [docs/decisions.md](docs/decisions.md) for why specific implementation choices were made.

## Known limitations

Deferred to a follow-up session or later, per `docs/requirements.md`: SCIM provisioning (E-U-02) and the standalone separate-port provisioning API (E-P-02) — each scoped as an implementable blueprint rather than built, since each is effectively its own project (see [docs/enterprise-integration.md](docs/enterprise-integration.md)) — plus Murchison (v4)'s AI-assisted authoring and IBM DOORS import/export. A small number of Ossa/Pelion/Massif-tagged items were implemented with a deliberately scoped-down approach (documented in [docs/decisions.md](docs/decisions.md)): login IP is logged but not geolocated, requirement/component/category ordering is move-up/move-down rather than drag-and-drop, the backend does not yet emit OpenTelemetry traces (the Alloy/Tempo pipeline is wired and ready for it), permission-revocation does not currently send a notification (only grant does), and notification email/digest delivery plus the disk-usage monitor and the review/stage-deadline scheduler run as in-process background tasks rather than a separate worker service. See [docs/soc2/](docs/soc2/) for the fuller, ongoing catalogue of known gaps against a SOC 2 Security + Confidentiality control set (e.g. no login rate limiting, no branch protection enforcing CI) and their remediation status.

## Code Quality Rules

- Prefer clear, maintainable code over clever solutions.
- Do not introduce undocumented behaviour.
- Do not remove existing documentation unless it is incorrect.
- Update documentation when changing functionality.
- Add tests for new functionality.
