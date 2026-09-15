---
sidebar_position: 9
---

# Troubleshooting

**Backend logs are silently empty.** `docker compose logs backend` shows nothing beyond the startup banner — no per-request access logs, no error tracebacks. Root cause, now fixed: `backend/alembic/env.py` calls `logging.config.fileConfig(...)` on every app startup (migrations run automatically every boot), and `fileConfig()`'s default `disable_existing_loggers=True` disabled every logger not explicitly listed in `alembic.ini`, including uvicorn's own loggers. Fixed by passing `disable_existing_loggers=False`. If you're on a version predating this fix and logs look suspiciously empty, that's why.

**A `500` on every request, including login, with `/health` still reporting OK.** This was caused, once, by the test suite wiping the live database — a serious enough failure mode that it's worth knowing the shape of it even though it's now guarded against on both sides (`backend/tests/conftest.py` hard-fails if `DATABASE_URL` doesn't resolve to a `*_test` database, and the test suite runs against its own isolated stack, never by exec-ing into a running application container). If you ever see `relation "..." does not exist` errors on a live deployment, check whether something ran a migration or test tool against the wrong `DATABASE_URL`. Restarting the backend re-runs migrations and re-bootstraps the admin user, which restores functionality but **does not recover lost data** — restore from backup instead if this happens on a real deployment.

## Verifying a deployment

After `docker compose up -d`, confirm:

1. `curl http://localhost:8000/health` (or your production hostname) returns `{"status": "ok", "database": "ok"}`.
2. `curl http://localhost:8000/metrics` returns Prometheus-format metrics.
3. The frontend loads and you can log in with the bootstrap admin credentials you configured.
4. If using email notifications, trigger one (e.g. change your password) and confirm it arrives at your configured SMTP provider (or MailHog's UI in non-production environments).
5. `curl http://localhost:8100/health` returns `ok` — see [AI assistants (MCP)](../api-integrations/index.md) if you intend to use the MCP server, including from a remote client.

## Still stuck?

- Re-check the [Configuration reference](./configuration-reference.md) — most deployment issues trace back to a missing or mismatched environment variable.
- [Overview](./overview.md) has the full production-stack component diagram and startup order, useful for narrowing down which container to look at first.
