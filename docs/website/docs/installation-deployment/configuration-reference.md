---
sidebar_position: 4
---

# Configuration reference

Backend environment variables, set via `docker-compose.yml`, a `.env` file, or your process manager. The "Required in prod?" column reflects the root `docker-compose.yml`, which refuses to start without them — the dev/eval stack fills in dev-friendly defaults for all of these instead.

:::note
This table is ported from the project [README](https://github.com/ballardr/reqtrackmanager#configuration) and kept in sync with it — if you're reading a copy of this site that's fallen behind, the README is the fallback source of truth.
:::

| Variable | Default | Required in prod? | Purpose |
| --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql://reqtrack:reqtrack@localhost:5432/reqtrack` | — | SQLAlchemy connection string |
| `POSTGRES_PASSWORD` | `reqtrack` | Recommended | Postgres password, shared by the `db` service and the backend's `DATABASE_URL` |
| `JWT_SECRET` | `change-me-in-production` | **Yes** | Access token signing secret |
| `APP_SECRET_ENCRYPTION_KEY` | `change-me-in-production` | **Yes** | Encrypts SSO client secrets, per-org SMTP passwords, and TOTP secrets at rest (application-layer, distinct from `JWT_SECRET` so the two can be rotated independently) |
| `JWT_ALGORITHM` | `HS256` | — | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | — | Access token lifetime |
| `SERVER_ADMIN_ENABLED` | `true` | — | Whether to bootstrap the server-admin user |
| `SERVER_ADMIN_EMAIL` | `admin@example.com` | — | Bootstrap server-admin login |
| `SERVER_ADMIN_PASSWORD` | `ChangeMe123!` | **Yes** | Bootstrap server-admin password |
| `SERVER_ADMIN_CREATE_ORG` | `true` | — | Also create a default org with the admin as org admin |
| `MODULES_DEFAULT_AVAILABLE` | `true` | — | A fresh install starts with every module available to every organisation and on for new projects; an upgrade is never changed. Set `false` to keep each module's own opt-in default. Server administrators change the defaults under Server Management → Modules |
| `CORS_ORIGINS` | `http://localhost:3000` | Recommended | Comma-separated allowed frontend origins |
| `STORAGE_BACKEND` | `local` (Compose default: `s3`) | — | File storage backend: `local` (filesystem) or `s3` (S3-compatible) |
| `STORAGE_LOCAL_DIR` | `./data/files` | — | Filesystem directory used by the `local` storage backend |
| `STORAGE_S3_BUCKET` / `STORAGE_S3_ENDPOINT_URL` / `STORAGE_S3_ACCESS_KEY` | see `docker-compose.yml` | — | Connection details for the `s3` storage backend |
| `STORAGE_ACCESS_KEY` / `STORAGE_SECRET_KEY` | `minioadmin` / — | **Yes** | The one S3 identity of the bundled storage service, limited to the application bucket; the backend uses the same pair. Earlier `STORAGE_ROOT_USER` / `STORAGE_ROOT_PASSWORD` still work. See [Production deployment](./production-deployment.md#hardening-the-bundled-storage-further) |
| `SMTP_HOST` | — | **Yes** | Outgoing SMTP host — a real provider in production, MailHog in the dev/eval stack |
| `SMTP_PORT` / `SMTP_USE_TLS` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_ADDRESS` | see `docker-compose.yml` | Recommended | Remaining SMTP connection details |
| `DEPLOYMENT_NOTIFICATION_EMAIL` | unset | — | Address notified of deployment-level events such as low disk space |
| `DISK_USAGE_WARNING_THRESHOLD_PERCENT` | `90` | — | Disk usage monitor threshold for the `local` storage backend |
| `STORAGE_HEALTH_CHECK_ENABLED` / `STORAGE_HEALTH_CHECK_INTERVAL_SECONDS` | `true` / `300` | — | Periodic write probe of the file storage (alerts server admins when it stops accepting writes). Each probe is one write, read and delete, so set `false` (or raise the interval, minimum 60) to avoid request charges on a metered S3 provider |
| `WEBSOCKET_ENABLED` | `true` | — | Whether the optional live-update WebSocket interface is mounted at all |
| `BACKEND_WORKERS` | `4` | — | Backend worker processes per container (CPU cores the API can use). Workers coordinate via PostgreSQL; see the deployment guide's scaling section for connection/memory sizing |
| `GEOIP_LOOKUP_ENABLED` | `false` | — | Whether login events resolve an approximate location for the client IP via a third-party lookup. Off by default since it's an external network dependency; login is never blocked by it regardless |
| `GEOIP_LOOKUP_EXCLUDE_CIDRS` | private/loopback ranges | — | Comma-separated CIDR ranges never sent to the geolocation lookup, even when enabled |
| `PUBLIC_BACKEND_URL` | `http://localhost:8000` | Recommended if SSO is used | This backend's own externally-reachable base URL — must exactly match the redirect URI registered on any OIDC identity provider |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Recommended if SSO is used | The frontend's base URL, used to redirect back to the UI once an OIDC login completes |
| `OIDC_INTERNAL_BASE_URL_OVERRIDE` | unset | — | Dev/test-only escape hatch for a containerized identity provider whose public URL isn't reachable from inside the backend's own container. Leave unset in production. |
| `OIDC_ALLOW_PRIVATE_NETWORK_TARGETS` | `false` | — | Set `true` only if every organisation on this deployment runs its own trusted, internally-hosted identity provider with no public IP. Disables the SSRF guard that otherwise rejects an org's `oidc_issuer_url` resolving to a private/internal address. Leave `false` on any deployment serving mutually-untrusted organisations. |
| `SEARCH_RATE_LIMIT_BURST` / `SEARCH_RATE_LIMIT_PER_MINUTE` | `60` / `120` | — | How fast one person may search, counted in requests (each pause in typing in the live dropdown is one, so a query is several): a token bucket that starts full and refills at the per-minute rate, so the burst is not a time window; over it the search answers 429 and the UI asks them to wait. Each backend worker process keeps its own bucket, so a person's real ceiling is the limit times the number of workers. `0` for the burst turns the limit off |
| `USER_CREATE_RATE_LIMIT_BURST` / `USER_CREATE_RATE_LIMIT_PER_MINUTE` | `20` / `30` | — | How fast one server admin may add users from Server Management → Add user (accounts and invites together): a token bucket per administrator, kept per backend worker process. Over it the request answers 429. `0` for the burst turns the limit off |
| `HELP_ENABLED` / `HELP_URL` | `true` / the public docs site | — | The header Help link opens `HELP_URL` in a new tab; `HELP_ENABLED=false` removes the link (and `/help` shows "Help is not configured"). Point `HELP_URL` at an internally hosted copy for air-gapped installs — see [Hosting the documentation internally](./production-deployment.md#hosting-the-documentation-internally) |
| `IMAGE_TAG` / `GHCR_IMAGE_PREFIX` | `latest` / `ghcr.io/ballardr/reqtrackmanager` | — | Which published container image tag `docker-compose.yml` pulls (a SemVer, a commit SHA, or `latest`) and from where — see [Obtaining container images](./production-deployment.md#obtaining-container-images) |

## Frontend configuration

`VITE_API_BASE_URL` (build-time, via `frontend/.env`) or its container-runtime equivalent `PUBLIC_API_BASE_URL`, passed to `docker-compose.yml` and injected into a generated `env-config.js` at container startup — the same built frontend image can point at different backends without a rebuild.

Set `PUBLIC_API_BASE_URL` to an **empty** value (not left unset) to make the frontend call the API via relative paths against its own origin, instead of an absolute URL — this is the setting behind same-origin subpath deployment, see [TLS, reverse proxy, and same-origin deployment](./tls-and-reverse-proxy.md#one-hostname-routed-by-path-avoiding-cors) for the full recipe.
