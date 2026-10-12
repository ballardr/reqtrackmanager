---
sidebar_position: 5
---

# Storage, database, and migrations

## Storage backend

- **`STORAGE_BACKEND=local`** (default outside Compose) stores files on the backend container's own filesystem, at `STORAGE_LOCAL_DIR`. The root `docker-compose.yml` mounts this as the named volume `reqtrack_local_files` so files survive container recreation; if you run the backend outside this Compose file, mount an equivalent persistent volume yourself. The built-in disk-usage monitor only runs for this backend, emailing `DEPLOYMENT_NOTIFICATION_EMAIL` when usage crosses `DISK_USAGE_WARNING_THRESHOLD_PERCENT`.
- **`STORAGE_BACKEND=s3`** (the Compose default) stores files in any S3-compatible bucket — the bundled SeaweedFS service, a self-hosted SeaweedFS/MinIO cluster, or real AWS S3. Set `STORAGE_S3_ENDPOINT_URL` to your provider (omit it, or point it at AWS's endpoint, for real S3), and set `STORAGE_S3_BUCKET`/`STORAGE_S3_ACCESS_KEY`/`STORAGE_S3_SECRET_KEY`/`STORAGE_S3_REGION` accordingly. This is the recommended choice for any deployment with more than one backend replica, since local disk storage doesn't get shared across replicas.
- **Storage health.** Every `STORAGE_HEALTH_CHECK_INTERVAL_SECONDS` (default 300) the elected leader writes, reads back and deletes a tiny probe object through the configured backend (any backend, including S3-compatible ones whose free space the app cannot read). A failing probe is logged at ERROR on every check, sets the Prometheus gauge `storage_write_healthy` to `0` (alert on it), and notifies every server admin in-app (and by email per their preferences, plus the `DEPLOYMENT_NOTIFICATION_EMAIL` address if set) once per outage, with a second notification on recovery. For local storage the disk-percentage warning (`DISK_USAGE_WARNING_THRESHOLD_PERCENT`) also notifies server admins. Each probe is one write, one read and one delete, which a metered S3 provider bills; set `STORAGE_HEALTH_CHECK_ENABLED=false` to turn the periodic probe off, or raise the interval. A server admin can still probe on demand with `GET /api/v1/system/storage-health`.

## Database

PostgreSQL is not started with automatic backups. Use the provided scripts on a schedule — cron, a systemd timer, or your orchestrator's job scheduler:

```bash
./scripts/backup.sh [output-dir]     # pg_dump (gzip'd) + local file storage (tar.gz, if STORAGE_BACKEND=local), timestamped
./scripts/restore.sh <backup-file>   # restores a .sql.gz into db, or a reqtrack-files-*.tar.gz into backend
```

```mermaid
flowchart LR
    Backup[backup.sh] -->|"pg_dump, gzip'd"| SQL[".sql.gz"]
    Backup -->|"if STORAGE_BACKEND=local"| Files["reqtrack-files-*.tar.gz"]
    SQL --> Restore["restore.sh"]
    Files --> Restore
    Restore -->|"into db"| DB[(PostgreSQL)]
    Restore -->|"into backend"| FS["Local file storage"]
```

`backup.sh` covers everything in one run for the common case: it always dumps the database, and additionally archives `reqtrack_local_files` when the running deployment has `STORAGE_BACKEND=local`. If you use `STORAGE_BACKEND=s3` (the Compose default, via the bundled SeaweedFS service), back up the `reqtrack_storage_data` volume with SeaweedFS's own backup/replication tooling instead — it isn't a plain file tree this script can tar up.

Test restores periodically — a backup that has never been restored is not a verified backup.

## Migrations

The backend runs `alembic upgrade head` automatically on every startup. Upgrading to a new ReqTrackManager version is therefore just: pull the new image, `docker compose up -d backend` — no manual migration step is required. Because the migration runs immediately and automatically on container start, **always take a database backup before upgrading**.

## Next steps

- [TLS, reverse proxy, and same-origin deployment](./tls-and-reverse-proxy.md)
- [Scaling and adding modules](./scaling-and-modules.md)
