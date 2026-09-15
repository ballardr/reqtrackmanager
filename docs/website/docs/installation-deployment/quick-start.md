---
sidebar_position: 2
---

# Quick start (local / evaluation)

This is the fastest way to see ReqTrackManager running, whether you're evaluating the product or setting up to hack on this repo. It uses the dedicated dev/eval stack, **not** the production `docker-compose.yml` — see [Overview](./overview.md) for why the two are kept separate.

```bash
git clone <this-repo>
cd reqtrackmanager/tests/container
docker compose up --build -d
```

This starts Postgres (its own `reqtrack_test` database), MinIO (S3-compatible file storage), MailHog (SMTP catcher), Keycloak (a real OIDC provider, for testing per-organisation SSO end-to-end), the backend, and the frontend. On first boot the backend automatically runs database migrations and creates a bootstrap **server admin** user and default organisation.

Once every container reports healthy:

| Service | URL |
| --- | --- |
| Frontend UI | http://localhost:3000 |
| Backend API / Swagger UI | http://localhost:8000/docs |
| Backend OpenAPI schema (JSON) | http://localhost:8000/openapi.json |
| Health check | http://localhost:8000/health |
| Prometheus metrics | http://localhost:8000/metrics |
| MCP server (see [AI assistants (MCP)](../api-integrations/index.md)) | http://localhost:8100/mcp |
| MailHog UI (view sent notification emails) | http://localhost:8025 |
| MinIO console (view uploaded files) | http://localhost:9001 |

Default bootstrap admin login: `admin@example.com` / `ChangeMe123!`.

| Login screen |
| --- |
| The bootstrap admin account created automatically on first boot |
| ![ReqTrackManager login screen](../../static/img/screenshots/login-page.png) |

**Never point this stack at the internet, and never confuse it with the production stack** — see [Overview](./overview.md#two-compose-stacks-two-purposes) for why they're kept deliberately separate.

## Demo data

A bootstrap admin with an otherwise empty instance isn't much to look at. To populate the running stack with a realistic, presentable dataset — a fictional drone-inspection company, two projects at different lifecycle stages, requirements at varied statuses, an approved and a pending change request, discussion threads, custom fields, and a branded report template:

```bash
cd tests/container && docker compose exec backend python scripts/seed_demo_data.py
```

This is idempotent (it skips if already seeded) and API-driven — the same approach used for the separate, test-oriented E2E persona dataset (`scripts/seed_e2e_dataset.py`), just with different, screenshot-friendly content. Log in as `demo.admin@example.com` / `DemoDemo123!` afterward; see the script's own docstring for the other seeded personas and their roles. This is also the exact dataset used for the screenshots throughout this site and the project README.

There's no organisation-deletion endpoint, so the script only skips rather than resets existing demo data. To get back to a clean slate: `docker compose down -v && docker compose up -d --build`, then re-run the seed script.

## Next steps

- [Use cases](../introduction/use-cases.md) for the kinds of teams this was built for.
- [Workflows](../workflows/signing-in.md) for a guided tour of each screen, step by step.
- [Production deployment](./production-deployment.md) once you're ready to run this for real users.
