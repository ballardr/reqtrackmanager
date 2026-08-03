# System Operations, Monitoring, and Logging Policy

| | |
| --- | --- |
| Policy Owner | **[Name / Title]** |
| Approved By | **[Name / Title]** |
| Effective Date | **[YYYY-MM-DD]** |
| Review Cadence | Annually |
| Applies To | Operations, Engineering |

## Purpose

Satisfies CC7.1 and CC7.2: detecting configuration/vulnerability risk and monitoring system components for anomalies. See [trust-services-criteria-mapping.md](../trust-services-criteria-mapping.md) §CC7.

## Scope

Covers logging, monitoring, alerting, and backup operations for the ReqTrackManager application and its infrastructure.

## Policy

### Logging

1. Every action that mutates organizational or project structure is written to a structured audit trail (`audit_events`) recording who did it, when, and what changed — not reconstructed after the fact from application logs. This extends to account-level security state changes (password changes, 2FA enable/disable) — a hardening review found these had been missed, since the user-facing notification a password change also sends isn't itself an admin-visible audit record.
2. Every authentication attempt (success and failure) is recorded as a `login_events` row, including the source IP.
3. Sensitive field values (passwords, TOTP secrets, verification codes) are explicitly redacted from error responses and must never appear in application logs.
4. Logs are aggregated centrally when the observability stack is enabled (see Implementation below), rather than relying on reading individual container logs.

### Monitoring

1. Every service exposes a health check; container orchestration must not route traffic to, or consider healthy, a service failing its check.
2. The backend exposes a Prometheus-compatible `/metrics` endpoint; a production deployment must scrape it.
3. Disk usage for local file storage is monitored continuously and triggers an operator email alert when it crosses a configured threshold, rather than being discovered only when storage is already exhausted.
4. **[Company must define alerting thresholds, on-call rotation, and escalation paths on top of the raw metrics/logs the application produces — the application generates the signal, but routing that signal to a person is an operational process the Company owns.]**

### Backup and recovery operations

1. Database and (for local file storage) file backups must be taken on a defined recurring schedule. **[Company must configure and document the actual schedule — the application ships the tooling, not a cron entry.]**
2. Backups must be tested by performing an actual restore at a defined interval (recommended: quarterly at minimum) — an untested backup is not considered a valid control.
3. Backup artifacts must be stored separately from the primary database (a different volume/region/account than production), so a single infrastructure failure cannot destroy both.

## Implementation in ReqTrackManager

- **Audit/login logging**: `backend/app/services/audit.py` (`log_event`), `backend/app/models/audit.py` (`AuditEvent`, `LoginEvent`).
- **Sensitive-field redaction**: `backend/app/main.py`'s `redact_sensitive_validation_errors` exception handler strips password/secret values out of validation error responses before they can be logged or returned.
- **Health checks**: every container in `docker-compose.yml` defines a health check; `backend`/`frontend` startup ordering depends on upstream health.
- **Metrics**: `GET /metrics` (Prometheus format).
- **Disk monitoring**: the disk-usage monitor (I-M-11) emails `DEPLOYMENT_NOTIFICATION_EMAIL` when usage crosses `DISK_USAGE_WARNING_THRESHOLD_PERCENT`.
- **Log aggregation / tracing**: optional Loki (logs), Tempo (traces), and Grafana Alloy (shipping/correlation) stack, enabled via `docker compose --profile observability up -d` — see [deployment.md](../deployment.md) §Observability. Distributed tracing is wired but the backend does not yet emit OpenTelemetry spans itself (see Known Gaps).
- **Backup tooling**: `scripts/backup.sh` (Postgres `pg_dump`, gzip'd, plus a tarball of local file storage when `STORAGE_BACKEND=local`) and `scripts/restore.sh`.

## Roles and Responsibilities

| Role | Responsibility |
| --- | --- |
| Operations | Schedules backups, configures alerting/on-call, monitors dashboards |
| Engineering | Maintains the metrics/logging/audit instrumentation |

## Known Gaps / Exceptions

1. **Backups are not scheduled by the application** — `scripts/backup.sh` must be invoked by an operator-configured cron job/scheduler; nothing runs it automatically today.
2. **No automated alerting rules exist on top of the raw metrics** — Prometheus/Grafana are wired for scraping and dashboards, but alert rules and an escalation path are a Company configuration task.
3. **No distributed tracing is emitted yet** — the Tempo/Alloy pipeline is deployed and ready to receive traces, but the backend does not instrument requests with OpenTelemetry spans.
4. **Grafana's bundled configuration enables anonymous viewer access**, appropriate only for local development — a production deployment of the observability stack must put Grafana behind the same authentication/reverse-proxy layer as the rest of the system (documented in [deployment.md](../deployment.md), but worth restating here as a control requirement, not just a deployment tip).

## Related Documents

[incident-response-plan.md](incident-response-plan.md), `docs/deployment.md` §Observability and §Database, `docs/solution-architecture.md` §Observability and Operations.
