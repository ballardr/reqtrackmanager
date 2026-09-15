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
| `CORS_ORIGINS` | `http://localhost:3000` | Recommended | Comma-separated allowed frontend origins |
| `STORAGE_BACKEND` | `local` (Compose default: `s3`) | — | File storage backend: `local` (filesystem) or `s3` (MinIO/S3-compatible) |
| `STORAGE_LOCAL_DIR` | `./data/files` | — | Filesystem directory used by the `local` storage backend |
| `STORAGE_S3_BUCKET` / `STORAGE_S3_ENDPOINT_URL` / `STORAGE_S3_ACCESS_KEY` | see `docker-compose.yml` | — | Connection details for the `s3` storage backend |
| `MINIO_ROOT_PASSWORD` / `STORAGE_S3_SECRET_KEY` | `minioadmin` | **Yes** | MinIO admin password, shared with the backend's S3 secret key |
| `SMTP_HOST` | — | **Yes** | Outgoing SMTP host — a real provider in production, MailHog in the dev/eval stack |
| `SMTP_PORT` / `SMTP_USE_TLS` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_ADDRESS` | see `docker-compose.yml` | Recommended | Remaining SMTP connection details |
| `DEPLOYMENT_NOTIFICATION_EMAIL` | unset | — | Address notified of deployment-level events such as low disk space |
| `DISK_USAGE_WARNING_THRESHOLD_PERCENT` | `90` | — | Disk usage monitor threshold for the `local` storage backend |
| `WEBSOCKET_ENABLED` | `true` | — | Whether the optional live-update WebSocket interface is mounted at all |
| `GEOIP_LOOKUP_ENABLED` | `false` | — | Whether login events resolve an approximate location for the client IP via a third-party lookup. Off by default since it's an external network dependency; login is never blocked by it regardless |
| `GEOIP_LOOKUP_EXCLUDE_CIDRS` | private/loopback ranges | — | Comma-separated CIDR ranges never sent to the geolocation lookup, even when enabled |
| `PUBLIC_BACKEND_URL` | `http://localhost:8000` | Recommended if SSO is used | This backend's own externally-reachable base URL — must exactly match the redirect URI registered on any OIDC identity provider |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Recommended if SSO is used | The frontend's base URL, used to redirect back to the UI once an OIDC login completes |
| `OIDC_INTERNAL_BASE_URL_OVERRIDE` | unset | — | Dev/test-only escape hatch for a containerized identity provider whose public URL isn't reachable from inside the backend's own container. Leave unset in production. |
| `OIDC_ALLOW_PRIVATE_NETWORK_TARGETS` | `false` | — | Set `true` only if every organisation on this deployment runs its own trusted, internally-hosted identity provider with no public IP. Disables the SSRF guard that otherwise rejects an org's `oidc_issuer_url` resolving to a private/internal address. Leave `false` on any deployment serving mutually-untrusted organisations. |
| `IMAGE_TAG` / `GHCR_IMAGE_PREFIX` | `latest` / `ghcr.io/ballardr/reqtrackmanager` | — | Which published container image tag `docker-compose.yml` pulls (a SemVer, a commit SHA, or `latest`) and from where — see [Obtaining container images](./production-deployment.md#obtaining-container-images) |

## Frontend configuration

`VITE_API_BASE_URL` (build-time, via `frontend/.env`) or its container-runtime equivalent `PUBLIC_API_BASE_URL`, passed to `docker-compose.yml` and injected into a generated `env-config.js` at container startup — the same built frontend image can point at different backends without a rebuild.

Set `PUBLIC_API_BASE_URL` to an **empty** value (not left unset) to make the frontend call the API via relative paths against its own origin, instead of an absolute URL — this is the setting behind same-origin subpath deployment, see [TLS, reverse proxy, and same-origin deployment](./tls-and-reverse-proxy.md#one-hostname-routed-by-path-avoiding-cors) for the full recipe.
