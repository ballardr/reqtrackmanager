---
sidebar_position: 3
---

# Production deployment

Production deployment uses the root `docker-compose.yml` and the same container images used for local development — the difference is entirely in configuration, and the compose file itself enforces the important parts of it: `docker compose up` fails immediately with a clear error naming the missing variable if any required secret isn't set, rather than silently starting with an insecure default.

## Minimum `.env`

Create a `.env` file next to `docker-compose.yml` (Docker Compose loads it automatically) and set at minimum:

```bash
# Secrets — generate strong random values, do not reuse the defaults
JWT_SECRET=<random 32+ byte secret>
APP_SECRET_ENCRYPTION_KEY=<random 32+ byte secret>  # distinct from JWT_SECRET — see Configuration reference
SERVER_ADMIN_PASSWORD=<strong password>
POSTGRES_PASSWORD=<strong password>
STORAGE_ROOT_PASSWORD=<strong password>        # if using the bundled storage service

# Networking
CORS_ORIGINS=https://your-domain.example
PUBLIC_API_BASE_URL=https://api.your-domain.example

# Outgoing email — point at a real SMTP provider instead of MailHog
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=<smtp username>
SMTP_PASSWORD=<smtp password>
SMTP_FROM_ADDRESS=noreply@your-domain.example

# Operational alerting
DEPLOYMENT_NOTIFICATION_EMAIL=ops@your-domain.example
```

```bash
docker compose up --build -d
```

The full list of backend environment variables — with defaults and which are actually required — is on the [Configuration reference](./configuration-reference.md) page.

## Beyond the two obvious containers

- **The bundled storage service** ([SeaweedFS](https://github.com/seaweedfs/seaweedfs)) is the default file-storage backend (`STORAGE_BACKEND=s3`) — an S3-compatible object store so file attachments and shared resources work out of the box. Point `STORAGE_S3_ENDPOINT_URL` at real AWS S3 (or another S3-compatible provider) instead if you'd rather not self-host it, or set `STORAGE_BACKEND=local` to use the backend container's own filesystem — see [Storage, database, and migrations](./storage-database-and-migrations.md).
- **OAuth/OIDC SSO** is per-organisation, not global: each organisation configures its own identity provider (issuer URL, client ID/secret) under its admin settings, so a single deployment can serve organisations with completely different IdPs — or none at all, staying on native email/password login. There's no bundled identity provider in the production stack; the dev/eval stack's Keycloak instance exists purely so SSO login can be tested end-to-end and should never be pointed at from a real deployment.
- **The MCP server** (`mcp-server`, port 8100) is optional but on by default — it holds no credentials of its own and does no authorization itself, only forwarding whatever access token the calling AI assistant already has. Leave it running (nothing reaches it without a valid token) or stop the container if you don't want to expose it at all.

```mermaid
flowchart TD
    DB[(db: PostgreSQL)] --> BE[backend]
    Storage[(storage: S3-compatible storage)] --> BE
    BE --> FE[frontend]
    BE --> MCP[mcp-server]
    SMTP[external SMTP provider] -.->|outgoing mail| BE
```

## Obtaining container images

CI builds the production `backend`, `frontend`, `mcp-server`, and `docs` images on every change and, once tests pass on a push to `main`, pushes all four to `ghcr.io/<owner>/<repo>-{backend,frontend,mcp-server,docs}`. Pull requests still build every image, proving the Dockerfiles work, but never push — only a merge to `main` publishes.

Each image is tagged three ways:

- **`latest`** — always the most recent build from `main`. What `IMAGE_TAG` defaults to.
- **`<git sha>`** — the exact commit it was built from, for pinning to a specific build without needing a release version.
- **a SemVer** (e.g. `1.4.0`) — computed automatically from the commit graph by [GitVersion](https://gitversion.net/): every merge to `main` is a release, so the version increments without anyone pushing a git tag by hand.

`docker-compose.yml` declares both `image:` (pointing at these published tags) and `build:` (a local Dockerfile build) for `backend`/`frontend`/`mcp-server`, so:

- **First run, or `docker compose up --build -d`**: builds locally — nothing requires ever touching `ghcr.io`.
- **To deploy an already-published image instead of building**: set `IMAGE_TAG` in your `.env` (a SemVer to pin a specific release, a commit SHA, or leave it unset/`latest` to track the newest `main` build), then `docker compose pull && docker compose up -d`. This is the faster path for upgrading an existing deployment — no build step, no source checkout needed on the host at all.

If your images live in a different registry/namespace (e.g. a private mirror), override `GHCR_IMAGE_PREFIX` in your `.env` instead of editing `docker-compose.yml`.

**Checking what's actually deployed.** The same SemVer/commit SHA used to tag an image is baked into it at build time, so a running instance can report its own build identity without shell access to the host: the signed-in nav rail shows both the frontend's and the backend's version, fetched from `GET /api/v1/system/version`. A local `docker compose build` with no build args (the default for both paths above) reports placeholder `dev`/`unknown` values instead of failing — only images built by CI carry a real version.

## Hosting the documentation internally

The header **Help** link opens the public documentation site by default. That shows the latest docs, not the version you run, and does not work without internet access. To host the docs yourself, run the `docs` image and point `HELP_URL` at it:

```mermaid
flowchart LR
    CI["CI build"] -->|"pushes"| IMG["…-docs image"]
    IMG -->|"docker compose --profile docs up -d"| DOCS["docs service :8200"]
    ENV["HELP_URL=http://docs.example:8200/"] --> BE["backend"]
    BE -->|"client-config"| UI["Help link in the app header"]
    UI -->|"opens"| DOCS
```

Read left to right: CI publishes a docs image tagged with the same version as the app, you run it, and the backend tells the UI where it is.

- The image is the same static site as the public one, served by unprivileged nginx on port 8080 (`docker-compose.yml` publishes it on 8200 under the `docs` profile). It is built for the root of its own host; to serve it under a sub-path such as `/docs/` behind your reverse proxy, set `DOCS_BASE_URL=/docs/` (and `DOCS_URL`) in your `.env` and build it with `docker compose --profile docs build docs`. The base path is baked in at build time, so a pulled image keeps its published `/`.
- `HELP_URL` must be reachable from users' browsers, not just from the backend.
- No internal mirror and no wish for an external link? Set `HELP_ENABLED=false` to remove the Help link.

## Storage credential scope (known gap)

By default `STORAGE_S3_ACCESS_KEY`/`STORAGE_S3_SECRET_KEY` are wired to `STORAGE_ROOT_USER`/`STORAGE_ROOT_PASSWORD`, so the backend authenticates to the bundled storage service as its single admin identity rather than a credential limited to its own bucket — a backend compromise (or a leaked environment variable) currently grants access to the whole storage service, not just this app's own files.

This used to be narrowable via MinIO's `mc admin user`/`mc admin policy` CLI, but the bundled storage service is now [SeaweedFS](https://github.com/seaweedfs/seaweedfs) (MinIO discontinued free/anonymous image distribution — see the decisions log), which scopes credentials differently, via a filer IAM identity config rather than an `mc`-style CLI, and that path hasn't been set up or verified against this stack yet. If you need scoped storage credentials for a production deployment today, either configure SeaweedFS's own IAM identity file yourself (see the [SeaweedFS S3 API docs](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API)) or point `STORAGE_S3_ENDPOINT_URL` at a real external S3-compatible provider with its own IAM instead of the bundled service.

## Next steps

- [Configuration reference](./configuration-reference.md) for the full environment-variable table.
- [TLS, reverse proxy, and same-origin deployment](./tls-and-reverse-proxy.md) — required reading before exposing this to real users, since ReqTrackManager does not terminate TLS itself.
- [Observability](./observability.md) to wire up metrics, logs, and traces.
