---
sidebar_position: 1
---

# REST API overview

Everything the web UI does, it does by calling the same REST API documented here — there is no separate, more-capable internal API. A script, a CI job, or an AI assistant (see [AI assistants (MCP)](./ai-assistants-mcp/overview.md)) can call it directly, subject to the same authentication and per-organisation/per-project RBAC the UI itself is bound by.

This page explains the conventions the API follows. It is not a schema reference — for the exact, always-current shape of every endpoint, request body, and response model, use the live instance's own interactive documentation:

- **`/docs`** — Swagger UI, browsable and callable from the browser (see [Common API tasks](./common-api-tasks.md) for a worked example using it).
- **`/openapi.json`** — the raw OpenAPI 3 schema, for generating a client or feeding into other tooling.

A statically-written schema page on this site would drift out of date the moment an endpoint changed; the running instance's own `/docs` never can.

## Base URL and versioning

Every endpoint is mounted under `/api/v1/...`. Most routes are further scoped by the resource they belong to:

| Prefix | Covers |
| --- | --- |
| `/api/v1/auth` | Login, signup, password/2FA management, OIDC callback |
| `/api/v1/me/pats` | The caller's own Personal Access Tokens |
| `/api/v1/orgs/{organization_id}/...` | Organisation-scoped resources — users, groups, branding, SSO/SCIM configuration |
| `/api/v1/projects/{project_id}/...` | Project-scoped resources — requirements, change requests, reports, files, actions |
| `/api/v1/system/...` | Server-admin-only deployment-wide settings |

A module (e.g. the Compliance module) contributes its own endpoints under the same `/api/v1/orgs/{organization_id}/modules/<key>/...` and `/api/v1/projects/{project_id}/modules/<key>/...` shape — see below. There is only one API version today; a future breaking change would introduce `/api/v2/...` alongside `/api/v1/...` rather than break existing callers in place.

## Module-contributed endpoints and tools

A [module](../modules/overview.md) isn't limited to what ships in the core application: it can contribute its own REST endpoints (the URL shape above) and its own MCP tools, automatically prefixed with the module's key and registered alongside the hand-written ones (see [AI assistants → Overview](./ai-assistants-mcp/overview.md#module-contributed-tools)). The Compliance module, documented in [Modules → Compliance module](../modules/compliance-module/overview.md), is the working example of both. For the contract a module implements to do this — the `ModuleDefinition` shape, how a router gets mounted, how an MCP tool is declared and mechanically constrained — see [Modules → Building your own module](../modules/building-your-own-module.md).

## Request and response conventions

- **JSON in, JSON out.** Request bodies for `POST`/`PUT`/`PATCH` are JSON objects; every response body is JSON (except a file download, a generated PDF/CSV report, or a plain-text health check).
- **Field names are `snake_case`**, matching the Pydantic schemas the backend is built from — the same shape the frontend consumes.
- **IDs are UUIDs**, serialised as strings.
- **Timestamps are ISO 8601, UTC** (e.g. `"2026-09-15T03:42:37.401458Z"`).
- **Authentication** is a bearer token on every authenticated request — see [Authenticating](./authenticating.md).

## Pagination

List endpoints (e.g. `GET /api/v1/projects/{project_id}/requirements`, `GET /api/v1/projects/{project_id}/change-requests`) accept optional `limit`/`offset` query parameters:

- **Omitting both returns every matching row** — no implicit page size is ever imposed. This preserves the pre-pagination behaviour for any existing script or integration that doesn't ask for a page.
- **When `limit` is given**, the response is sliced to that page, and two response headers report counts computed *before* the slice:
  - **`X-Total-Count`** — how many rows match the current filters/search, in total (so a client can tell whether more pages remain).
  - **`X-Total-Unfiltered-Count`** — how many rows exist in the broader, unfiltered scope (the project, minus only the default archived-visibility rule), before any search/filter/status narrowing is applied — the number behind a "12 matching · 57 total" style UI.

```bash
curl -s -D - "http://localhost:8000/api/v1/projects/$PROJECT_ID/requirements?limit=2&offset=0" \
  -H "Authorization: Bearer $TOKEN" | grep -i x-total
# x-total-unfiltered-count: 11
# x-total-count: 11
```

This is the general convention across list endpoints, but not every one necessarily exposes it identically — check the specific endpoint's parameters in `/docs` before assuming a header is present.

## Error format

A rejected request follows FastAPI's default shapes:

- **A normal error** (404, 403, 401, 409, ...) — `{"detail": "<message>"}`:

  ```json
  {"detail": "Project not found."}
  ```

- **A 422 validation error** — `{"detail": [...]}`, an array of Pydantic error objects, each with `type`/`loc`/`msg`/`input`:

  ```json
  {"detail": [
    {"type": "missing", "loc": ["body", "password"], "msg": "Field required", "input": "***"}
  ]}
  ```

  Worth knowing if you're scripting against this: a 422 on a field named `password`, `new_password`, `totp_secret`, `code`, `smtp_password`, or `oidc_client_secret` has its echoed `input` redacted to `"***"` rather than reflecting back whatever value was submitted — a deliberate hardening measure (see `backend/app/main.py`'s `redact_sensitive_validation_errors`) so a failed-validation response body never leaks a submitted secret.

## Where this fits

- [Authenticating](./authenticating.md) — how to get a token to put in the `Authorization` header.
- [Common API tasks](./common-api-tasks.md) — worked `curl` examples using everything above.
- [AI assistants (MCP)](./ai-assistants-mcp/overview.md) — a higher-level way to reach the same API from an AI assistant.
