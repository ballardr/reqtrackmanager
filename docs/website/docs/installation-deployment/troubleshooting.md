---
sidebar_position: 9
---

# Troubleshooting

**Every administrator is locked out (forgotten passwords, or a forced credential reset).** Print a single-use reset link for the server administrators from the host, with no application sign-in and even with email down: `docker compose exec backend python -m app.cli.credentials issue-link --server-admins`. See [Password resets and credential recovery](../workflows/password-reset-and-credential-recovery.md#command-line-when-nobody-can-sign-in).

**Backend logs are silently empty.** `docker compose logs backend` shows nothing beyond the startup banner — no per-request access logs, no error tracebacks. Root cause, now fixed: `backend/alembic/env.py` calls `logging.config.fileConfig(...)` on every app startup (migrations run automatically every boot), and `fileConfig()`'s default `disable_existing_loggers=True` disabled every logger not explicitly listed in `alembic.ini`, including uvicorn's own loggers. Fixed by passing `disable_existing_loggers=False`. If you're on a version predating this fix and logs look suspiciously empty, that's why.

**A `500` on every request, including login, with `/health` still reporting OK.** This was caused, once, by the test suite wiping the live database — a serious enough failure mode that it's worth knowing the shape of it even though it's now guarded against on both sides (`backend/tests/conftest.py` hard-fails if `DATABASE_URL` doesn't resolve to a `*_test` database, and the test suite runs against its own isolated stack, never by exec-ing into a running application container). If you ever see `relation "..." does not exist` errors on a live deployment, check whether something ran a migration or test tool against the wrong `DATABASE_URL`. Restarting the backend re-runs migrations and re-bootstraps the admin user, which restores functionality but **does not recover lost data** — restore from backup instead if this happens on a real deployment.

**`docker compose ps` shows a container `unhealthy` but the app works in the browser.** The health probe, not the app, is failing. On some hosts `localhost` inside a container resolves to `::1` (IPv6) first, and the service (nginx, for example) listens on IPv4 only, so a probe to `localhost` is refused for ever. The shipped probes use `127.0.0.1` and avoid this; if you see it on a custom image or an older version, run:

```bash
docker inspect --format '{{json .State.Health}}' <container>   # last probe outputs and errors
docker exec <container> getent hosts localhost                  # "::1 localhost" confirms the cause
docker exec <container> wget -qO- http://127.0.0.1:3000/health  # frontend; works when the probe address was the problem
```

The probes also have a start period (60 seconds; backend 120) so a slow first boot, which runs migrations, is not counted as failures. A monitor that probes `/health` through a reverse proxy needs that path exposed; see [TLS and reverse proxy](./tls-and-reverse-proxy.md).

## Verifying a deployment

After `docker compose up -d`, confirm:

1. `curl http://localhost:8000/health` (or your production hostname) returns HTTP 200 with `{"status": "ok", "database": "ok"}` (HTTP 503 if the database is unreachable).
2. `curl http://localhost:8000/metrics` returns Prometheus-format metrics.
3. The frontend loads and you can log in with the bootstrap admin credentials you configured.
4. If using email notifications, trigger one (e.g. change your password) and confirm it arrives at your configured SMTP provider (or MailHog's UI in non-production environments).
5. `curl http://localhost:8100/health` returns `ok` — see [AI assistants (MCP) → Overview](../api-integrations/ai-assistants-mcp/overview.md) if you intend to use the MCP server, including from a remote client.

## Still stuck?

- Re-check the [Configuration reference](./configuration-reference.md) — most deployment issues trace back to a missing or mismatched environment variable.
- [Overview](./overview.md) has the full production-stack component diagram and startup order, useful for narrowing down which container to look at first.
