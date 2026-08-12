# ReqTrackManager

[![CI](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml/badge.svg)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)
[![Backend tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ballardr/reqtrackmanager/badges/backend-tests-badge.json)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)
[![Backend coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ballardr/reqtrackmanager/badges/backend-coverage-badge.json)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)
[![Frontend tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ballardr/reqtrackmanager/badges/frontend-tests-badge.json)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)
[![Frontend coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ballardr/reqtrackmanager/badges/frontend-coverage-badge.json)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)

ReqTrackManager is an open-source engineering requirements management system (ERMS) — a formal, collaborative alternative to IBM DOORS-style tools for product teams that can't justify that cost, without falling back to a static requirements spreadsheet that nobody trusts by the second review cycle. Requirements get a real identity, a full version history, and a paper trail from first draft to shipped and verified; changes to already-approved requirements go through an actual review workflow instead of a silent edit. It's built to sit at the center of how a hardware, firmware, or regulated-software team actually works day to day — not bolted on as an afterthought.

See [docs/requirements.md](docs/requirements.md) for the full product requirements and [docs/solution-architecture.md](docs/solution-architecture.md) for the architecture; [docs/decisions.md](docs/decisions.md) records the scoping and implementation decisions made along the way, [docs/enterprise-integration.md](docs/enterprise-integration.md) covers the SSO design and the SCIM/provisioning blueprint, [docs/mcp-server.md](docs/mcp-server.md) covers AI-assistant access to requirements, [docs/deployment.md](docs/deployment.md) covers deploying to production, [docs/development.md](docs/development.md) covers running it locally and the contributor workflow, and [docs/user-guide.md](docs/user-guide.md) is a full walkthrough of using the app.

## The requirements workflow

A requirement is authored, reviewed, and approved — not just typed into a cell. Every edit is versioned, with a full change log per requirement; once a project stage is approved, its requirements are **baselined** and locked, so "what did we actually commit to" stays answerable months later. Formal **change requests** are the only way to modify a baselined requirement: they carry their own reasoning field, an approve/reject decision by a project manager, optional tasks to track follow-up work, and advisory stakeholder voting that surfaces disagreement without silently overriding the decision-maker. Every requirement and change request has a threaded discussion, so the "why" behind a decision lives next to the thing it's about instead of in a separate chat history nobody can find later. On top of that: a two-level component/category tree per project for real organisational structure, scheduled requirement reviews with due-date notifications (and an assumed-approval path for stage deadlines that pass without action), completion tracking at both the requirement and stage level, and a full-fidelity CSV export/import (every field, including custom field values and target stage, via a column-mapping wizard) for round-tripping requirements to and from a spreadsheet without hand-retyping anything.

## Built for how teams actually work

Organisations contain projects; projects have role- and group-based access control, so who can author, review, approve, or just view is enforced server-side, not by convention. Custom fields and per-project terminology let a team's own vocabulary and tracked attributes show up in the UI without a fork. Project templates carry that setup — fields, terminology, categories — into every new project instead of rebuilding it by hand each time. File attachments live on requirements and change requests, plus organisation-wide shared resources for anything that isn't specific to one item. In-app and email notifications (with per-type preferences and a daily digest, so nobody has to choose between "know everything immediately" and "silence") keep people aware of what changed without forcing them to poll the app for it. Reporting turns all of this into a real deliverable: filtered PDF or CSV export, with selectable organisation branding templates and a Markdown-or-WYSIWYG report intro/chapters/appendices a project can inherit from its organisation's default rather than authoring from scratch. A project or an entire organisation can be exported as a self-contained, versioned zip bundle (full structure and history — change requests, baselines, review outcomes, attachments included) and re-imported to stand up a brand-new project or organisation, for backup, offboarding, or migrating between organisations or deployments; Restricted secrets (SMTP/OIDC credentials, password hashes) are deliberately never included, so they're re-entered by hand after a restore.

## Enterprise-ready

- **Access & identity**: native email/password auth alongside per-organisation OIDC/SSO (tested end-to-end against a real Keycloak instance), optional org-wide-enforceable TOTP two-factor auth, personal access tokens individually scopable down to specific organisations and projects, and public self-signup with server-admin-controlled modes (invite-only, open, or org-level email-domain auto-accept). An organisation can also invite an external user onto a single project by email, with its own provisioning path for SSO-only organisations.
- **Data protection**: application-layer encryption (distinct key from the JWT signing secret, independently rotatable) for every genuinely sensitive stored value — OIDC client secrets, per-organisation SMTP passwords, TOTP secrets — so a database-only compromise doesn't expose them in plaintext.
- **AI-assistant access**: a read-only [Model Context Protocol](https://modelcontextprotocol.io) server (`mcp-server/`) exposes requirements/projects/organisations as tools an AI assistant can call directly — Claude Code, VS Code Copilot Chat, and Microsoft Copilot Studio are all documented — authenticated by forwarding the caller's own access token, never a shared service account. See [docs/mcp-server.md](docs/mcp-server.md).
- **Operability**: Prometheus metrics, container health checks, an optional WebSocket live-update stream, and a documented Loki/Tempo/Grafana Alloy observability stack — see [Optional observability stack](#optional-observability-stack) below.
- **Compliance posture**: an adopted SOC 2 policy set and a Security + Confidentiality Trust Services Criteria control matrix live in [docs/soc2/](docs/soc2/), including a candid list of known gaps (e.g. no login rate limiting yet) rather than a claim of a finished audit — useful groundwork if a real SOC 2 engagement is ever in scope, not a substitute for one.
- **Extensibility blueprint**: SCIM provisioning and a standalone separate-port provisioning API are scoped as implementable designs in [docs/enterprise-integration.md](docs/enterprise-integration.md) rather than built — each is effectively its own project — for a deployment that needs directory-driven user lifecycle management beyond what SSO login alone provides.

## Screenshots

Captured from the seeded demo dataset (see [docs/development.md](docs/development.md#demo-data)) — a fictional drone-inspection company with two projects at different lifecycle stages.

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

Want to click through it yourself instead? [docs/development.md](docs/development.md#quick-start--local-development--evaluation) has a one-command local stack with this exact demo dataset.

## Production deployment

Production runs from the root [`docker-compose.yml`](docker-compose.yml): Postgres, the backend, the frontend, MinIO, and the MCP server, plus an optional observability profile. It's deliberately strict rather than convenient — no MailHog, no baked-in secret defaults — and refuses to start (`docker compose up` fails fast with a clear error naming the missing variable) until you provide real values via a `.env` file next to the compose file. At minimum:

```bash
JWT_SECRET=<random 32+ byte secret>              # access token signing
APP_SECRET_ENCRYPTION_KEY=<random 32+ byte secret>  # encrypts stored secrets at rest — distinct from JWT_SECRET
SERVER_ADMIN_PASSWORD=<strong password>           # bootstrap admin account
POSTGRES_PASSWORD=<strong password>
MINIO_ROOT_PASSWORD=<strong password>             # if using the bundled MinIO
CORS_ORIGINS=https://your-domain.example
SMTP_HOST=smtp.your-provider.example              # a real provider — MailHog is dev/test-only
```

Then:

```bash
docker compose up --build -d
```

The full list of variables, defaults, and which are actually required is in [Configuration](#configuration) below; the complete deployment guide — including a `.env` walkthrough, a MinIO credential-scoping hardening step, backups, migrations, and troubleshooting — is [docs/deployment.md](docs/deployment.md).

**Beyond the two obvious containers**, a full deployment brings a few more pieces together:

- **MinIO** is the default file-storage backend (`STORAGE_BACKEND=s3`) — an S3-compatible object store bundled in the compose file so file attachments and shared resources work out of the box. Point `STORAGE_S3_ENDPOINT_URL` at real AWS S3 (or another S3-compatible provider) instead if you'd rather not self-host it, or set `STORAGE_BACKEND=local` to use the backend container's own filesystem (see [Storage backend](docs/deployment.md#storage-backend)).
- **OAuth/OIDC SSO** is per-organisation, not global: each organisation configures its own identity provider (issuer URL, client ID/secret) under its admin settings, so a single deployment can serve organisations with completely different IdPs — or none, staying on native email/password login. There's no bundled identity provider in the production stack; `tests/container/docker-compose.yml`'s Keycloak instance exists purely so SSO login can be tested end-to-end in dev/CI, and should never be pointed at from a real deployment.
- **The MCP server** (`mcp-server`, port 8100) is optional but on by default in the compose file — it holds no credentials of its own and does no authorization itself, only forwarding whatever access token the calling AI assistant already has. Leave it running (nothing reaches it without a valid token) or stop the container if you don't want to expose it at all. See [docs/mcp-server.md](docs/mcp-server.md).

**Hosting behind nginx as a reverse proxy**: ReqTrackManager's containers serve plain HTTP internally — TLS termination and a public hostname are the reverse proxy's job, not something the app does itself. Two supported patterns, both documented in full (including the security-header/CSP notes) in [docs/deployment.md](docs/deployment.md#tls-and-reverse-proxy):

1. **Two hostnames** (`app.example.com` for the UI, `api.example.com` for the backend) — simplest to reason about, needs `CORS_ORIGINS` set correctly since the browser treats them as different origins.
2. **One hostname, routed by path** (`my.website.com/` for the UI, `my.website.com/api/` for the backend) — avoids CORS entirely instead of configuring around it. This needs no backend routing changes, because every route the frontend calls already lives under `/api/v1/...`:

   ```nginx
   location /api/ {
       proxy_pass http://backend:8000;   # no path here — forwards the URI unchanged, so
       proxy_set_header Host $host;      # /api/v1/... in stays /api/v1/... out, matching the backend's own routes
   }

   location / {
       proxy_pass http://frontend:3000;
       proxy_set_header Host $host;
   }
   ```

   This exact config was verified against the real running stack (proxied and direct responses byte-identical). The one thing that **will** break it: `PUBLIC_API_BASE_URL` must be left **empty**, not set to `/api` or a full URL containing it. The frontend already prepends `/api/v1/...` to whatever `PUBLIC_API_BASE_URL` is — setting it to `/api` produces requests to `/api/api/v1/...`, which 404s. Leaving it empty makes the frontend call the API via relative paths against its own origin instead, which is the entire point of routing by path in the first place. See [docs/deployment.md](docs/deployment.md#same-origin-subpath-deployment-avoiding-cors) for the full recipe, including the extra one-to-one blocks needed if you also want `/docs`/`/metrics`/`/health` reachable through the public subpath.

### Optional observability stack

```bash
docker compose --profile observability up -d
```

Adds Prometheus (http://localhost:9090), Loki, Tempo, Grafana Alloy, and Grafana (http://localhost:3300, anonymous viewer access enabled for local use — put it behind auth in production). Prometheus is pre-configured to scrape the backend's `/metrics` endpoint; Alloy ships container logs to Loki and exposes an OTLP receiver on `4317` ready to forward traces to Tempo once the backend is instrumented with OpenTelemetry (not yet done — see decisions log).

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
| `IMAGE_TAG` / `GHCR_IMAGE_PREFIX` | `latest` / `ghcr.io/ballardr/reqtrackmanager` | — | Which published container image tag `docker-compose.yml` pulls (a SemVer, a commit SHA, or `latest`) and from where — see [Obtaining container images](docs/deployment.md#obtaining-container-images) |

Frontend: `VITE_API_BASE_URL` (build-time, via `frontend/.env`) or the container-runtime equivalent `PUBLIC_API_BASE_URL` passed to `docker-compose.yml`, which is injected into a generated `env-config.js` at container startup — the same built frontend image can point at different backends without a rebuild. Set it to an **empty** value (not left unset) to make the frontend call the API via relative paths against its own origin, instead of an absolute URL — the setting behind same-origin subpath deployment described above; see [docs/deployment.md](docs/deployment.md#same-origin-subpath-deployment-avoiding-cors) for the full reverse-proxy recipe.

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

Deferred to a follow-up session or later, per `docs/requirements.md`: SCIM provisioning (E-U-02) and the standalone separate-port provisioning API (E-P-02) — each scoped as an implementable blueprint rather than built, since each is effectively its own project (see [docs/enterprise-integration.md](docs/enterprise-integration.md)) — plus Murchison (v4)'s AI-assisted authoring and IBM DOORS import/export. A small number of Ossa/Pelion/Massif-tagged items were implemented with a deliberately scoped-down approach (documented in [docs/decisions.md](docs/decisions.md)): login IP is logged but not geolocated, requirement/component/category ordering is move-up/move-down rather than drag-and-drop, the backend does not yet emit OpenTelemetry traces (the Alloy/Tempo pipeline is wired and ready for it), permission-revocation does not currently send a notification (only grant does), and notification email/digest delivery plus the disk-usage monitor and the review/stage-deadline scheduler run as in-process background tasks rather than a separate worker service. Project/organisation bundle export deliberately excludes Restricted secrets and project-level group *membership* (only group structure is recreated, to avoid a cross-tenant privilege-escalation path on import) — see [decisions.md](docs/decisions.md)'s "Bundle export/import" entry for the full reasoning and what a re-imported project/org needs re-populated by hand. See [docs/soc2/](docs/soc2/) for the fuller, ongoing catalogue of known gaps against a SOC 2 Security + Confidentiality control set (e.g. no login rate limiting, no branch protection enforcing CI) and their remediation status.

## Development workflow

Running it locally, the backend/frontend dev setup, the test suites (backend pytest, Playwright E2E, Storybook), linting, and CI are all covered in [docs/development.md](docs/development.md) — including the exact commands to reproduce everything CI runs.

Briefly, what CI enforces on every push/PR to `main`: frontend lint + type-check + build, the full backend pytest suite with coverage (~90%+ statement coverage — auth, RBAC boundaries, full resource lifecycles, requirement locking, change-request workflow, notifications, 2FA, SSO-only enforcement, and more) plus `ruff` lint, and a 33-spec-file Playwright E2E suite in a real browser — all gating, all against the same dev/test Docker Compose stack developers run locally. See [docs/development.md#continuous-integration](docs/development.md#continuous-integration) for the full breakdown, including how production images get built, version-tagged, and published.

## Code Quality Rules

- Prefer clear, maintainable code over clever solutions.
- Do not introduce undocumented behaviour.
- Do not remove existing documentation unless it is incorrect.
- Update documentation when changing functionality.
- Add tests for new functionality.
