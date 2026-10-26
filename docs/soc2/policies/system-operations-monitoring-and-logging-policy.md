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
   Exporting a record list and applying an import are each audited as one event (`records_exported`, `records_imported`) carrying the record type, counts, the names of the filters and the sensitivity tags that were left out or included, never a cell value; a change to the personal-data policy is one event (`record_policy.server_default_updated`, `record_policy.organization_override_updated`) with the tag and its old and new value; an import's rows are additionally audited by the record type's own create and update events, and a database error for a row is logged without its values.
   The text of a global search is treated the same way: a person may paste anything into the search box, so the query is sent in a POST body, is never written to application logs, audit events or traces (the search log line carries the scope, field keys, match mode, result count and duration only), and the frontend web server's access log records the request path and the referrer's path but never a query string, since the search page keeps its text in its address.
   A run of a custom report layout is recorded as one `generated_reports` row (layout and version, caller, UTC time, engine version, format, projects covered, record counts and a digest of the records read), written only after the report was produced; it holds identifiers, counts and keys, never layout text or a cell value. A background run's failures are logged by run id and exception type only (never the message or traceback, which can quote record content) and stored as a fixed sentence the requester can read. Reading a report is not an `audit_events` entry, as for the module reports whose every field the same caller already reads through the module's own endpoints.
4. Logs are aggregated centrally when the observability stack is enabled (see Implementation below), rather than relying on reading individual container logs.

### Monitoring

1. Every service exposes a health check; container orchestration must not route traffic to, or consider healthy, a service failing its check.
2. The backend exposes a Prometheus-compatible `/metrics` endpoint; a production deployment must scrape it.
3. Disk usage for local file storage is monitored continuously and triggers an operator email alert when it crosses a configured threshold, rather than being discovered only when storage is already exhausted.
4. **[Company must define alerting thresholds, on-call rotation, and escalation paths on top of the raw metrics/logs the application produces — the application generates the signal, but routing that signal to a person is an operational process the Company owns.]**

### Backup and recovery operations

1. The database, the stored files (object store or local) and, where the Company chooses, the encrypted configuration must be backed up on a defined recurring schedule. **[Company must configure the schedule and record it — the application ships the schedulers, not a decision about when.]** The recovery point objective is the backup interval (24 hours with the shipped nightly defaults).
2. Backups must be tested by performing an actual restore at a defined interval — an untested backup is not considered a valid control. The shipped default is a weekly automated restore test that compares the restored copy with the backup's manifest; a game-day restore on a clean machine from the off-site copy and documented key custody alone should be exercised at least annually.
3. Backup artifacts must be stored separately from the primary database (a different volume/region/account than production), so a single infrastructure failure cannot destroy both. The default repository is on the same host and does not meet this on its own: at least one off-site destination must be configured.
4. A failed, stale or silent backup or restore test must raise an alert to a person (see Known Gaps for the routing the Company owns). The backup, its staging volume and the restore-test scratch stack hold Confidential data and are handled as such: encrypted repository, scratch credentials generated per run and removed afterwards, no published ports, email disabled.
5. Credentials that read the backup source (repository password, destination credentials, the age key for the configuration snapshot) are held outside the backed-up host with at least two people able to reach them; losing the repository password makes every backup unreadable.

## Implementation in ReqTrackManager

- **Audit/login logging**: `backend/app/services/audit.py` (`log_event`), `backend/app/models/audit.py` (`AuditEvent`, `LoginEvent`).
- **Search query text**: `backend/app/services/search.py` logs scope, field keys, match mode, counts and duration only (pinned by `backend/tests/test_search.py`); `frontend/nginx.conf`'s `path_only` log format uses `$uri` and the referrer's path, never `$request` or `$args` (also pinned by a test). A reverse proxy in front of the product logs its own request lines and is outside this control.
- **Sensitive-field redaction**: `backend/app/main.py`'s `redact_sensitive_validation_errors` exception handler strips password/secret values out of validation error responses before they can be logged or returned.
- **Health checks**: every container in `docker-compose.yml` defines a health check; `backend`/`frontend` startup ordering depends on upstream health.
- **Metrics**: `GET /metrics` (Prometheus format), including request counts (`http_requests_total`) and database statement counts by operation (`db_statements_total`). Metric labels are bounded and carry no ids, table names or SQL, so the unauthenticated endpoint exposes no Restricted data.
- **Disk monitoring**: the disk-usage monitor (I-M-11) emails `DEPLOYMENT_NOTIFICATION_EMAIL` when usage crosses `DISK_USAGE_WARNING_THRESHOLD_PERCENT`.
- **Log aggregation / tracing**: optional Loki (logs), Tempo (traces), and Grafana Alloy (shipping/correlation) stack, enabled via `docker compose --profile observability up -d` — see [deployment.md](../../deployment.md) §Observability. Distributed tracing is wired but the backend does not yet emit OpenTelemetry spans itself (see Known Gaps).
- **Backup tooling**: `scripts/dr-backup.sh` (`backend/app/services/dr_backup.py`): a consistent `pg_dump`, an incremental mirror of the object store (or a tar of the local files), an optional age-encrypted `.env` snapshot, and a manifest with exact table counts, as one encrypted restic snapshot copied to every configured destination, with retention (default 7 daily, 4 weekly, 12 monthly), a sampled integrity check, a lock against concurrent runs and a non-zero exit on any failure. `BACKUP_SECRETS_MODE=none` keeps key material out of the backup. `scripts/backup.sh` (plain dump) remains for one-off use only.
- **Restore**: `scripts/restore.sh` (`dr_restore.py`) restores into a scratch database, verifies it against the manifest, then swaps it in; guards refuse a non-empty target, a different schema revision and a missing `--yes`. `--force-reset` applies a credential reset to the restored copy.
- **Restore test**: `scripts/restore-test.sh` (`restore_test.py`, `dr_verify.py`) restores the latest set into an isolated Compose project and checks migrations, every table count, every stored file, encrypted-column decryption, email suppression and an API walk-through; `--inject` faults prove each check can fail, and CI runs the whole chain as the `restore-test` job.
- **Scheduling and alerting**: the `backup-scheduler` Compose service, systemd timers and cron examples (`scripts/schedule/`); Prometheus textfile metrics and the alert rules in `observability/alerts/` (failed, stale, destination down, scheduler down, restore test failed or stale, metrics missing), unit-tested with `promtool` in CI. See [disaster-recovery.md](../../disaster-recovery.md).

## Roles and Responsibilities

| Role | Responsibility |
| --- | --- |
| Operations | Schedules backups, configures alerting/on-call, monitors dashboards |
| Engineering | Maintains the metrics/logging/audit instrumentation |

## Known Gaps / Exceptions

1. **Backups run only when the operator turns a scheduler on** — the schedulers and a weekly restore test ship, but none is enabled by default (a deployment that enables none is flagged by the `ReqTrackBackupMetricsMissing` alert only if the observability stack is also running). The Company must enable one, set an off-site destination and record the schedule. A restore on a clean machine from the off-site copy alone (a game day) has not yet been exercised, so the recovery time is unmeasured.
2. **Alert rules exist for backups only, and nothing routes them to a person** — the backup and restore-test alerts ship, but the bundled Prometheus has no Alertmanager, and there are no rules on the application's own metrics. Grafana ships unprovisioned (no data sources or dashboards). Alert routing and an escalation path are a Company configuration task.
3. **No distributed tracing is emitted yet** — the Tempo/Alloy pipeline is deployed and ready to receive traces, but the backend does not instrument requests with OpenTelemetry spans.
4. **Grafana's bundled configuration enables anonymous viewer access**, appropriate only for local development — a production deployment of the observability stack must put Grafana behind the same authentication/reverse-proxy layer as the rest of the system (documented in [deployment.md](../../deployment.md), but worth restating here as a control requirement, not just a deployment tip).

## Related Documents

[incident-response-plan.md](incident-response-plan.md), `docs/deployment.md` §Observability and §Database, `docs/solution-architecture.md` §Observability and Operations.
