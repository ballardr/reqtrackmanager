# ReqTrackManager

[![CI](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml/badge.svg)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)
[![Backend tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ballardr/reqtrackmanager/badges/backend-tests-badge.json)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)
[![Backend coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ballardr/reqtrackmanager/badges/backend-coverage-badge.json)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)
[![Storybook tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ballardr/reqtrackmanager/badges/storybook-tests-badge.json)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)
[![Frontend coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/ballardr/reqtrackmanager/badges/frontend-coverage-badge.json)](https://github.com/ballardr/reqtrackmanager/actions/workflows/ci.yml)

ReqTrackManager is an open-source engineering requirements management system (ERMS) — a formal, collaborative alternative to expensive legacy enterprise requirements tools for product teams that can't justify that cost, without falling back to a static requirements spreadsheet that nobody trusts by the second review cycle. Requirements get a real identity, a full version history, and a paper trail from first draft to shipped and verified; changes to already-approved requirements go through an actual review workflow instead of a silent edit. It's built to sit at the center of how a hardware, firmware, or regulated-software team actually works day to day — not bolted on as an afterthought.

See [docs/requirements.md](docs/requirements.md) for the full product requirements and [docs/solution-architecture.md](docs/solution-architecture.md) for the architecture; [docs/decisions.md](docs/decisions.md) records the scoping and implementation decisions made along the way, [docs/ux-style-guide.md](docs/ux-style-guide.md) is the normative frontend UX style guide (navigation/settings hierarchy, create flows, confirmation, tokens) and [docs/plans/completed/ux-audit-2026-08.md](docs/plans/completed/ux-audit-2026-08.md) is the audit and roadmap that produced it, [docs/enterprise-integration.md](docs/enterprise-integration.md) covers the SSO design, SCIM provisioning, and the separate-port provisioning API blueprint, [docs/mcp-server.md](docs/mcp-server.md) covers AI-assistant access to requirements, [docs/deployment.md](docs/deployment.md) covers deploying to production, [docs/development.md](docs/development.md) covers running it locally and the contributor workflow, and [docs/user-guide.md](docs/user-guide.md) is a full walkthrough of using the app.

A public documentation website is live at **[ballardr.github.io/reqtrackmanager](https://ballardr.github.io/reqtrackmanager/)** (Docusaurus, built from [docs/website/](docs/website/) and deployed via GitHub Pages — see [docs/plans/completed/docs-website-plan.md](docs/plans/completed/docs-website-plan.md) for how it was built). It is also published as a container image (`ghcr.io/ballardr/reqtrackmanager-docs`) for [hosting the docs inside your own deployment](docs/deployment.md#hosting-the-documentation-internally).

## The requirements workflow

A requirement is authored, reviewed, and approved — not just typed into a cell. Every edit is versioned, with a full change log per requirement; once a project stage is approved, its requirements are **baselined** and locked, so "what did we actually commit to" stays answerable months later. Formal **change requests** are the only way to modify a baselined requirement: they carry their own reasoning field, an approve/reject decision by a project manager, optional tasks to track follow-up work, proposed links to other records that the approver merges all, some or none of in a dialog (each re-checked at approval), and advisory stakeholder voting that surfaces disagreement without silently overriding the decision-maker. Every requirement and change request has a threaded discussion, so the "why" behind a decision lives next to the thing it's about instead of in a separate chat history nobody can find later. On top of that: a two-level component/category tree per project for real organisational structure, scheduled requirement reviews with due-date notifications (and an assumed-approval path for stage deadlines that pass without action), completion tracking at both the requirement and stage level, and a full-fidelity CSV export/import (every field, including custom field values and target stage, via a column-mapping wizard) for round-tripping requirements to and from a spreadsheet without hand-retyping anything. Every record list of every module offers the same: a **List actions** menu exports the list as filtered on screen (CSV, PDF or Word) and imports the same file back with a preview, where a row's code updates that record and a blank code creates one (personal-data columns stay out unless the organisation's policy and the person's permission allow them). Requirements can also be linked to each other with a typed, bidirectional relationship (e.g. "Derives from" / "Is the source of" — org-extensible beyond the 12 seeded defaults) for real traceability, and any two records of a project (a requirement, a decision, a pain point, ...) can be linked from either end through a Links panel beside every record's page, with admins able to restrict which kinds of record each link type may join and which link types each kind of record may use, project admins able to add link types of their own (inherited by nested projects) and hide the organisation's, an organisation able to switch that off for one shared set, and each link type able to allow, forbid or direct (upstream end in the parent only) links between a project and its parent or child projects, and can require actions (reviews, tests, etc.) that carry their own project-scoped identity, outcome, discussion, and attachments, so one action can satisfy several requirements at once. Any record of any kind can also carry **tags** (a theme, a release, a regulation): a governed vocabulary per project (free or limited to a list its administrators keep, inherited by nested projects), chips in every record's header, a tag filter in every list, and admin tools to rename, merge, reclassify and delete tags with usage tables per kind of record. A **global search** box in the top bar finds any record by its code, title and tags (and more fields on request) across one project, everything the person can open, or a unit such as a Compliance standard, with a live dropdown, a shareable results page and the same rules as every other read: nothing the person could not open is ever returned or counted. Projects themselves carry an org-definable status (Proposed/Active/Abandoned/Completed by default), configured alongside link types in each organisation's admin page.

## Built for how teams actually work

Organisations contain projects; projects have role- and group-based access control, so who can author, review, approve, or just view is enforced server-side, not by convention. Custom fields and per-project terminology let a team's own vocabulary and tracked attributes show up in the UI without a fork. Project templates carry that setup — fields, terminology, categories — into every new project instead of rebuilding it by hand each time. File attachments live on requirements and change requests, plus organisation-wide shared resources for anything that isn't specific to one item. In-app and email notifications (with per-type preferences and a daily digest, so nobody has to choose between "know everything immediately" and "silence") keep people aware of what changed without forcing them to poll the app for it. Outgoing email is a branded, self-contained HTML template (light/dark theme aware, with a plain-text fallback and an embedded — not externally hosted — logo) that resolves an organisation's own branding, falling back to the platform default; every email includes a one-click, no-login unsubscribe link that updates the same preference the logged-in Preferences page controls, logged to the audit trail either way. Reporting turns all of this into a real deliverable: filtered PDF or CSV export, with selectable organisation branding templates and a Markdown-or-WYSIWYG intro/chapters/appendices written separately for each report type, which a project can inherit from its parent projects and its organisation's defaults rather than authoring from scratch. A project or an entire organisation can be exported as a self-contained, versioned zip bundle (full structure and history — change requests, baselines, review outcomes, attachments included) and re-imported to stand up a brand-new project or organisation, for backup, offboarding, or migrating between organisations or deployments; Restricted secrets (SMTP/OIDC credentials, password hashes) are deliberately never included, so they're re-entered by hand after a restore.

## Optional modules

Beyond requirements and change requests, ReqTrackManager is a modular platform: each capability area is a module that a server administrator makes available to organisations and an organisation turns on per project (a fresh install has every module available; see Server Management → Modules). First-party modules: **Compliance** (standards, clauses, assessments), **Context & Strategy** (strategy, future states, guiding principles, pain points with configurable scoring, open questions), **Decision Management** (decisions with approval and supersession), **Risk Management** (risks, scoring matrices, reports) and **Stakeholders & Personas** (people, needs, engagements, research findings). Every record of every module shares the same machinery: a project-scoped human-readable code (`REQ-001`, `DEC-003`, qualified by the project code outside its own project), tags, links and traceability, an Activity timeline beside the record, global search, reports and bundle export. Create forms mark required fields with `*`, explain non-obvious fields with a `(?)` help tooltip, keep Save in a pinned header above the scrolling fields, and can link and tag the new record in the same step. Lists keep their scroll position after opening a record, filter panels collapse, and Pain Points can be scored in a bulk edit grid; the project overview shows a total-records chart split by type. Where projects are nested, any list can widen to parent and child projects. A module is added by registration, not by editing core code — see [docs/modules.md](docs/modules.md) and the website's "Building your own module".

## Enterprise-ready

- **Access & identity**: native email/password auth alongside per-organisation OIDC/SSO (tested end-to-end against a real Keycloak instance), optional org-wide-enforceable TOTP two-factor auth, password reset by a single-use emailed link (a person's own, or sent by an organisation or server admin) plus a forced credential reset and a command-line tool for when no administrator can sign in, personal access tokens individually scopable down to specific organisations and projects, and public self-signup with server-admin-controlled modes (invite-only, open, or org-level email-domain auto-accept). An organisation can also invite a new user by email, either org-wide or onto a single project, with its own provisioning path for SSO-only organisations.
- **Directory-driven provisioning**: inbound SCIM 2.0 provisioning (a pragmatic, documented subset of RFC 7643/7644) lets an identity provider push user and group changes in directly, so deprovisioning doesn't depend on someone logging in — a per-organisation bearer token, managed from an org's admin page. See [docs/enterprise-integration.md](docs/enterprise-integration.md).
- **Data protection**: application-layer encryption (distinct key from the JWT signing secret, independently rotatable) for every genuinely sensitive stored value — OIDC client secrets, per-organisation SMTP passwords, TOTP secrets — so a database-only compromise doesn't expose them in plaintext.
- **AI-assistant access**: a read-only [Model Context Protocol](https://modelcontextprotocol.io) server (`mcp-server/`) exposes requirements/projects/organisations as tools an AI assistant can call directly — Claude Code, VS Code Copilot Chat, and Microsoft Copilot Studio are all documented — authenticated by forwarding the caller's own access token, never a shared service account. A downloadable agent skill (workflow guidance plus a generated tool reference, with per-module usage guides) helps AI clients use it well. See [docs/mcp-server.md](docs/mcp-server.md) and its "Agent skill" section.
- **Operability**: Prometheus metrics, container health checks, an optional WebSocket live-update stream, and a documented Loki/Tempo/Grafana Alloy observability stack — see [Optional observability stack](#optional-observability-stack) below.
- **Compliance posture**: an adopted SOC 2 policy set and a Security + Confidentiality Trust Services Criteria control matrix live in [docs/soc2/](docs/soc2/), including a candid list of known gaps (e.g. no login rate limiting yet) rather than a claim of a finished audit — useful groundwork if a real SOC 2 engagement is ever in scope, not a substitute for one.
- **Extensibility blueprint**: a standalone separate-port provisioning API is scoped as an implementable design in [docs/enterprise-integration.md](docs/enterprise-integration.md) rather than built — effectively its own project — for a deployment that needs machine-to-machine provisioning beyond what SCIM and SSO login already cover.

## Screenshots

Captured from the seeded demo dataset (see [docs/development.md](docs/development.md#demo-data)) — a fictional drone-inspection company with two projects at different lifecycle stages.

|  |  |
| --- | --- |
| **Project dashboard** — favourites, role/stage filters, tile or list view | **Project overview** — status breakdown, change-request funnel, stage progress, activity feed |
| ![Projects dashboard](docs/screenshots/projects-page.png) | ![Project overview](docs/screenshots/project-overview.png) |
| **Requirements list** — status, target version, category filters | **Requirement detail** — version history, change log, links, discussion thread |
| ![Requirements list](docs/screenshots/requirements-list.png) | ![Requirement detail](docs/screenshots/requirement-detail.png) |
| **Change request** — tasks, advisory stakeholder votes, discussion, approve/reject | **Organisation admin** — members, roles, 2FA status, access-review filters |
| ![Change request detail](docs/screenshots/change-request-detail.png) | ![Organisation admin](docs/screenshots/org-admin.png) |
| **Reports** — filtered PDF/Word/CSV export with selectable org branding | **Reviews due** — requirements with a scheduled review date now overdue |
| ![Reports](docs/screenshots/reports-page.png) | ![Reviews due](docs/screenshots/reviews-due.png) |

<details>
<summary>Login page</summary>

![Login page](docs/screenshots/login-page.png)
</details>

Want to click through it yourself instead? [docs/development.md](docs/development.md#quick-start--local-development--evaluation) has a one-command local stack with this exact demo dataset.

## Production deployment

Production runs from the root [`docker-compose.yml`](docker-compose.yml): Postgres, the backend, the frontend, a bundled S3-compatible storage service, and the MCP server, plus an optional observability profile. It's deliberately strict rather than convenient — no MailHog, no baked-in secret defaults — and refuses to start (`docker compose up` fails fast with a clear error naming the missing variable) until you provide real values via a `.env` file next to the compose file. At minimum:

```bash
JWT_SECRET=<random 32+ byte secret>              # access token signing
APP_SECRET_ENCRYPTION_KEY=<random 32+ byte secret>  # encrypts stored secrets at rest — distinct from JWT_SECRET
SERVER_ADMIN_PASSWORD=<strong password>           # bootstrap admin account
POSTGRES_PASSWORD=<strong password>
STORAGE_SECRET_KEY=<strong password>              # S3 secret for the bundled storage (STORAGE_ACCESS_KEY optional)
CORS_ORIGINS=https://your-domain.example
SMTP_HOST=smtp.your-provider.example              # a real provider — MailHog is dev/test-only
```

Then:

```bash
docker compose up --build -d
```

The full list of variables, defaults, and which are actually required is in [Configuration](#configuration) below; the complete deployment guide — including a `.env` walkthrough, backups, migrations, and troubleshooting — is [docs/deployment.md](docs/deployment.md).

**Beyond the two obvious containers**, a full deployment brings a few more pieces together:

- **The bundled storage service** ([SeaweedFS](https://github.com/seaweedfs/seaweedfs); see `docker-compose.yml`'s `storage` service) is the default file-storage backend (`STORAGE_BACKEND=s3`) — an S3-compatible object store so file attachments and shared resources work out of the box. Point `STORAGE_S3_ENDPOINT_URL` at real AWS S3 (or another S3-compatible provider) instead if you'd rather not self-host it, or set `STORAGE_BACKEND=local` to use the backend container's own filesystem (see [Storage backend](docs/deployment.md#storage-backend)).
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

### Sizing

Memory follows the backend's worker count and the size of the largest project, not the number of users: a worker keeps the memory of the heaviest request it has served. Every always-on service has a memory limit in `docker-compose.yml` (overridable from `.env`); the backend's is roughly 0.1 GiB + `BACKEND_WORKERS` × 1.2 GiB for projects up to 1,000 requirements.

| Largest project | Backend, 4 workers | Database | Host RAM to plan for |
|-----------------|--------------------|----------|----------------------|
| Up to ~1,000 requirements | 4.4-4.6 GiB once heavy requests have run (1.8-2.4 GiB while only reading) | 0.4-0.8 GiB | 8 GiB |
| ~5,000 requirements | 8.3 GiB | 0.9-2.7 GiB | 16 GiB, or fewer workers |
| 20,000 requirements | 11.4 GiB | 1-3 GiB | 16 GiB or more |

Throughput is CPU-bound: on a 16-core Linux server with six cores for the API a one-worker stack serves about 60 requests a second and six workers about 190 (usable) to 230 (peak), roughly 300-1,900 active people; a Raspberry Pi 5 serves about 8 requests a second with one worker. Figures, method and how to repeat it (`perf/run_baseline.sh`) are in [docs/performance.md](docs/performance.md) and [docs/deployment.md](docs/deployment.md#sizing-and-memory-limits).

### Optional observability stack

```bash
docker compose --profile observability up -d
```

Adds Prometheus (http://localhost:9090), Loki, Tempo, Grafana Alloy, cAdvisor (per-container CPU and memory), and Grafana (http://localhost:3300, anonymous viewer access enabled for local use — put it behind auth in production). Prometheus is pre-configured to scrape the backend's `/metrics` endpoint (including `http_requests_total` and `db_statements_total`; PromQL for requests/min and DB reads/writes per 15 min is in [deployment.md](docs/deployment.md#observability)); Grafana comes with Prometheus and a **Resource usage** dashboard (per-container and per-worker memory, CPU, pool connections, restarts, OOM kills) provisioned; Alloy ships container logs to Loki and exposes an OTLP receiver on `4317` ready to forward traces to Tempo once the backend is instrumented with OpenTelemetry (not yet done — see decisions log).

### Backup and disaster recovery

```bash
./scripts/dr-backup.sh          # database + attachments + manifest, encrypted restic snapshot, copied off-site
./scripts/restore.sh fresh      # restore on a new host (or: in-place, list, config)
./scripts/restore-test.sh ...   # prove the latest backup restores into a working platform
```

A backup is one encrypted, deduplicated snapshot of the database, the stored files (SeaweedFS or local) and, optionally, the encrypted `.env`, with a manifest of table and record counts. A restore is checked against those counts before it replaces anything, and the restore test does the same on a throwaway stack every week. Scheduling (systemd, cron or a Compose service), Prometheus alerts, key custody and the step-by-step runbook are in [docs/disaster-recovery.md](docs/disaster-recovery.md).

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
| `MODULES_DEFAULT_AVAILABLE` | `true` | — | A fresh install starts with every module available to every organisation and on for new projects; an upgrade is never changed. Set `false` to keep each module's own opt-in default. Server administrators change the defaults under Server Management → Modules |
| `CORS_ORIGINS` | `http://localhost:3000` | Recommended | Comma-separated allowed frontend origins |
| `STORAGE_BACKEND` | `local` (Compose default: `s3`) | — | File storage backend: `local` (filesystem) or `s3` (S3-compatible), I-M-10 |
| `STORAGE_LOCAL_DIR` | `./data/files` | — | Filesystem directory used by the `local` storage backend |
| `STORAGE_S3_BUCKET` / `STORAGE_S3_ENDPOINT_URL` / `STORAGE_S3_ACCESS_KEY` | see `docker-compose.yml` | — | Connection details for the `s3` storage backend |
| `STORAGE_ACCESS_KEY` / `STORAGE_SECRET_KEY` | `minioadmin` / — | **Yes** | The one S3 identity of the bundled storage service, limited to the application bucket; the backend uses the same pair. Earlier `STORAGE_ROOT_USER` / `STORAGE_ROOT_PASSWORD` still work. Hardening: [docs/deployment.md](docs/deployment.md#hardening-the-bundled-storage-further) |
| `SMTP_HOST` | — | **Yes** | Outgoing SMTP host (C-N-03) — a real provider in production, MailHog in the dev/test stack |
| `CREDENTIAL_RESET_TOKEN_MINUTES` | `60` | — | How long an emailed password-reset link works (5 to 1440 minutes) |
| `EMAIL_DELIVERY` | `smtp` | — | `smtp` sends mail through the SMTP settings; `disabled` sends none at all (every send is refused before a connection is made), for a copy that must never reach real recipients, such as the disaster-recovery restore test |
| `SMTP_PORT` / `SMTP_USE_TLS` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_ADDRESS` | see `docker-compose.yml` | Recommended | Remaining SMTP connection details |
| `DEPLOYMENT_NOTIFICATION_EMAIL` | unset | — | Address notified of deployment-level events such as low disk space (I-M-09, I-M-11) |
| `DISK_USAGE_WARNING_THRESHOLD_PERCENT` | `90` | — | Disk usage monitor threshold for the `local` storage backend (I-M-11) |
| `STORAGE_HEALTH_CHECK_ENABLED` / `STORAGE_HEALTH_CHECK_INTERVAL_SECONDS` | `true` / `300` | — | Periodic write probe of the file storage (alerts server admins when it stops accepting writes). Each probe is one write, read and delete, so set `false` (or raise the interval, minimum 60) to avoid request charges on a metered S3 provider |
| `WEBSOCKET_ENABLED` | `true` | — | Whether the optional live-update WebSocket interface is mounted at all (I-A-04) |
| `BACKEND_WORKERS` | `4` | — | Backend worker processes per container (CPU cores the API can use). Workers coordinate via PostgreSQL; see the deployment guide's scaling section for connection/memory sizing |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `10` | — | Database connections each backend worker keeps / may add under load. A worker holds at most `DB_POOL_SIZE + DB_MAX_OVERFLOW` plus two dedicated connections (17 by default), so `BACKEND_WORKERS × replicas × 17` must stay under PostgreSQL's `max_connections` (100 by default, 3 reserved) |
| `MAX_CONCURRENT_REQUESTS` / `REQUEST_QUEUE_TIMEOUT_SECONDS` | `0` / `30` | — | Requests one backend worker serves at once (`0` = the database pool's capacity, `DB_POOL_SIZE + DB_MAX_OVERFLOW`), and how many seconds an extra request waits for a slot before a `503` with `Retry-After`. The limit keeps requests from holding every connection while waiting for a thread; raise it only together with the pool. `/health` and `/metrics` are never held |
| `BACKEND_MEM_LIMIT` / `DB_MEM_LIMIT` / `STORAGE_MEM_LIMIT` / `FRONTEND_MEM_LIMIT` / `MCP_MEM_LIMIT` | `5g` / `2g` / `1g` / `128m` / `256m` | — | Memory limit of each always-on Compose service (`0` removes it). Defaults come from measured peaks; raise the backend's with the worker count and project size, see the [sizing guide](docs/deployment.md#sizing-and-memory-limits) |
| `GEOIP_LOOKUP_ENABLED` | `false` | — | Whether login events resolve an approximate location for the client IP via a third-party lookup (C-A-07). Off by default since it's an external network dependency; login is never blocked by it regardless |
| `GEOIP_LOOKUP_EXCLUDE_CIDRS` | private/loopback ranges | — | Comma-separated CIDR ranges never sent to the geolocation lookup, even when enabled |
| `PUBLIC_BACKEND_URL` | `http://localhost:8000` | Recommended if SSO is used | This backend's own externally-reachable base URL — must exactly match the redirect URI registered on any OIDC identity provider (E-U-01) |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Recommended if SSO is used | The frontend's base URL, used to redirect back to the UI once an OIDC login completes (E-U-01) |
| `OIDC_INTERNAL_BASE_URL_OVERRIDE` | unset | — | Dev/test-only escape hatch for a containerized identity provider whose public URL isn't reachable from inside the backend's own container — see [docs/enterprise-integration.md](docs/enterprise-integration.md). Leave unset in production. |
| `OIDC_ALLOW_PRIVATE_NETWORK_TARGETS` | `false` | — | Set `true` only if every organisation on this deployment runs its own trusted, internally-hosted identity provider with no public IP (e.g. an on-prem Keycloak/Authentik on a corporate LAN or VPC). Disables the SSRF guard that otherwise rejects an org's `oidc_issuer_url` resolving to a private/internal address — see [docs/enterprise-integration.md](docs/enterprise-integration.md). Leave `false` on any deployment serving mutually-untrusted organisations. |
| `ORG_SMTP_ALLOW_PRIVATE_NETWORK_TARGETS` | `false` | — | Set `true` only if every organisation on this deployment uses an internal mail relay with no public address. By default an organisation's own SMTP host (used by its "send test email" action) must resolve to a public address, so an organisation administrator cannot aim the server at its own network |
| `REQUIRE_STRONG_SECRETS` | `false` (Compose default: `true`) | Recommended | Refuse to start while `JWT_SECRET` is a placeholder or under 32 characters, `APP_SECRET_ENCRYPTION_KEY` is the placeholder, or the S3 secret is the bundled store's default. A weak value is logged as a warning either way |
| `MAX_UPLOAD_BYTES` / `MAX_REQUEST_BODY_BYTES` | `52428800` / `54525952` | — | Largest single uploaded file (413 beyond it) and largest request body of any other endpoint; bundle and spreadsheet imports have their own 200 MB ceiling. Set a reverse proxy's `client_max_body_size` to the same order of magnitude |
| `HELP_ENABLED` / `HELP_URL` | `true` / the public docs site | — | The header Help link opens `HELP_URL` in a new tab; `HELP_ENABLED=false` removes the link (and `/help` shows "Help is not configured"). Point `HELP_URL` at an internally hosted copy for air-gapped installs — see [Hosting the documentation internally](docs/deployment.md#hosting-the-documentation-internally) |
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
    API --> FS[(File Storage: local or S3-compatible)]
    API --> Mail[Email: MailHog or SMTP]
    API -. metrics .-> Prom[Prometheus]
    API -. optional .-> WS[WebSocket clients]
```

The frontend is a single-page app talking to a REST/JSON API (I-A-01, I-A-02), documented via OpenAPI (I-A-03). The backend enforces the full permission and workflow model server-side — the frontend has no independent business logic. See [docs/solution-architecture.md](docs/solution-architecture.md) for the full domain model, ER diagrams, and deployment topology, and [docs/decisions.md](docs/decisions.md) for why specific implementation choices were made.

## Known limitations

Published container images are multi-arch (`linux/amd64` and `linux/arm64`, including a 64-bit Raspberry Pi); the `arm64` images are smoke tested in CI but the full test suites run on `amd64` only, and a Raspberry Pi 5 (8 GiB) ran one worker up to 20,000 requirements in 1.4 GiB of backend memory but serves only about 8 requests a second, and smaller boards and the default four workers are unmeasured (see [Supported platforms](docs/deployment.md#obtaining-container-images) and [Sizing](#sizing)).

Backups give a recovery point equal to the backup interval (nightly by default); there is no point-in-time recovery between backups, and the recovery time on a clean machine has not yet been measured (see [docs/disaster-recovery.md](docs/disaster-recovery.md)). Deferred to a follow-up session or later, per `docs/requirements.md`: the standalone separate-port provisioning API (E-P-02) — scoped as an implementable blueprint rather than built, since it's effectively its own project (see [docs/enterprise-integration.md](docs/enterprise-integration.md)) — plus Murchison (v4)'s AI-assisted authoring and legacy-tool import/export (E-C-01). (SCIM provisioning, E-U-02, was subsequently built — see the Enterprise-ready section above.) A small number of Ossa/Pelion/Massif-tagged items were implemented with a deliberately scoped-down approach (documented in [docs/decisions.md](docs/decisions.md)): login IP is logged but not geolocated, requirement/component/category ordering is move-up/move-down rather than drag-and-drop, the backend does not yet emit OpenTelemetry traces (the Alloy/Tempo pipeline is wired and ready for it), permission-revocation does not currently send a notification (only grant does), and notification email/digest delivery plus the disk-usage monitor and the review/stage-deadline scheduler run as in-process background tasks rather than a separate worker service. Project/organisation bundle export deliberately excludes Restricted secrets and project-level group *membership* (only group structure is recreated, to avoid a cross-tenant privilege-escalation path on import) — see [decisions.md](docs/decisions.md)'s "Bundle export/import" entry for the full reasoning and what a re-imported project/org needs re-populated by hand. See [docs/soc2/](docs/soc2/) for the fuller, ongoing catalogue of known gaps against a SOC 2 Security + Confidentiality control set (e.g. no login rate limiting, no branch protection enforcing CI) and their remediation status. On the frontend UX side: [docs/plans/completed/ux-audit-2026-08.md](docs/plans/completed/ux-audit-2026-08.md) catalogues navigation/settings-hierarchy inconsistency, inconsistent destructive-action confirmation, custom terminology overrides only actually taking effect on a small fraction of the surface they claim to, and two list views (project change-history, the server-admin user directory) with no pagination — tracked in that document's roadmap against [docs/ux-style-guide.md](docs/ux-style-guide.md)'s rules, not yet all implemented.

## Development workflow

Running it locally, the backend/frontend dev setup, the test suites (backend pytest, Playwright E2E, Storybook), linting, and CI are all covered in [docs/development.md](docs/development.md) — including the exact commands to reproduce everything CI runs.

Briefly, what CI enforces on every push/PR to `main`: frontend lint + type-check + build, the full backend pytest suite with coverage (~95% statement coverage, failing the build below 93.2% — auth, RBAC boundaries, full resource lifecycles, requirement locking, change-request workflow, notifications, 2FA, SSO-only enforcement, and more) plus `ruff` lint, a Playwright E2E suite of 150+ spec files in a real browser, and vulnerability scanning of the Python and npm dependencies (`pip-audit`, `npm audit`) and of every production image (Trivy) before it is published — all gating, all against the same dev/test Docker Compose stack developers run locally. See [docs/development.md#continuous-integration](docs/development.md#continuous-integration) for the full breakdown, including how production images get built, version-tagged, and published.

## Code Quality Rules

- Prefer clear, maintainable code over clever solutions.
- Do not introduce undocumented behaviour.
- Do not remove existing documentation unless it is incorrect.
- Update documentation when changing functionality.
- Add tests for new functionality.
