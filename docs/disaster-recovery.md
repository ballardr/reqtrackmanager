# Disaster recovery: backup and restore

Whole-platform backup and restore for recovering a lost host, a corrupted volume or a bad deploy. The automated restore-test, scheduling and the full runbook are separate deliverables; this page covers taking a backup and restoring one.

## What a backup holds

| Component | Source | Stored as |
|-----------|--------|-----------|
| Database | `db` | `pg_dump` custom format, taken from one exported Postgres snapshot |
| Attachments | `storage` (S3 API) | Incremental mirror of the bucket; or a tar of `reqtrack_local_files` when `STORAGE_BACKEND=local` |
| Configuration | your `.env` | Only in `BACKUP_SECRETS_MODE=config`: encrypted with `age` to a public key you hold the private half of |
| Manifest | generated | `manifest.json`: app version, schema revision, Postgres version, component digests and the `dr_stats` counts a restore is verified against ([schema](schemas/backup-manifest.schema.json)) |

Everything is stored as one [restic](https://restic.net) snapshot per run (encrypted, deduplicated), copied to every destination you configure, then pruned to the retention policy and sampled for integrity (`restic check`).

```mermaid
sequenceDiagram
    participant T as backup tool
    participant DB as db
    participant S as storage
    participant R as restic repositories
    T->>DB: export snapshot, pg_dump --snapshot, counts in the same snapshot
    T->>S: sync new or changed objects into the mirror
    T->>T: write manifest and checksums
    T->>R: snapshot to the primary repository
    T->>R: copy to each destination, prune, check
    T->>T: write status.json and metrics
```

The dump is taken before the object sync, so every row in the dump finds its object. A deleted object stays in the mirror for one more run (the set taken then may still reference it) and is then dropped.

## Run it

```bash
export BACKUP_REPO_PASSWORD_FILE=/secure/location/restic-password   # outside the data it protects
export BACKUP_ENV_FILE=./.env                                       # config mode only
export BACKUP_CONFIG_AGE_RECIPIENT=age1...                          # config mode only: age-keygen's public key
./scripts/dr-backup.sh                                              # or: docker compose --profile backup run --rm backup
```

Exit status: `0` success, `1` failed (a failed destination counts), `75` another backup is running. `status.json` and a Prometheus textfile (`reqtrack-backup.prom`) are written to the `reqtrack_backup_status` volume after every run.

The primary repository defaults to a volume on the same host, which does not survive losing the host: set `BACKUP_DESTINATIONS` to at least one copy elsewhere.

## Configuration

All variables are read by the `backup` service (see `docker-compose.yml`).

| Variable | Default | Meaning |
|----------|---------|---------|
| `BACKUP_REPO_PASSWORD_FILE` | required | File holding the restic repository password (a Docker secret). Losing it loses every backup |
| `BACKUP_SECRETS_MODE` | `config` | `config` also stores the encrypted `.env`; `none` stores no key material (you supply keys at restore time) |
| `BACKUP_CONFIG_AGE_RECIPIENT` | | age public key the `.env` is encrypted to. Required in `config` mode |
| `BACKUP_ENV_FILE` | | Host path of the `.env` to snapshot. Required in `config` mode |
| `BACKUP_DESTINATIONS` | | Comma-separated restic repositories to copy each snapshot to: `/mnt/nfs/reqtrack`, `s3:https://host/bucket`, `sftp:user@host:/path`, `azure:container:/path` |
| `BACKUP_REPO_VOLUME` | `reqtrack_backup_repo` | Volume or host path of the primary repository |
| `BACKUP_KEEP_DAILY` / `_WEEKLY` / `_MONTHLY` | 7 / 4 / 12 | Retention. restic keeps the last set of each period, so a schedule more often than daily also needs `BACKUP_KEEP_HOURLY` |
| `BACKUP_CHECK_SUBSET` | `5%` | Share of repository data read by the integrity check (empty skips it) |
| `BACKUP_PROBE_ENCRYPTION_KEY` | the app key | Key used to check the dump's encrypted columns decrypt. Set it empty to keep the key out of the backup container |
| `BACKUP_AWS_*`, `BACKUP_AZURE_*` | | Credentials for S3-compatible and Azure destinations |
| `BACKUP_SSH_DIR` | | Host directory with `id_*` and `known_hosts` for SFTP destinations |
| `BACKUP_BUNDLE_AGE_RECIPIENT` | | age public key for `bundle` |

Only credentials and the repository password reach the tool through the environment or Docker secrets, never the command line, and anything restic prints is scrubbed of them before it is logged or stored.

To hand-copy the latest set (scp, a USB disk) as one file: `./scripts/dr-backup.sh bundle --output /path/reqtrack.tar.age`. Decrypt with `age -d -i identity.txt`.

## Restore

`./scripts/restore.sh` runs the restore tool in the `backup` image (the `restore` Compose profile). It never writes into the live database: the set is restored into a scratch database, checked against the manifest with the same `dr_stats` code the backup used, and only then renamed into place.

| Situation | Command |
|-----------|---------|
| See what is available | `./scripts/restore.sh list [--repository R]` |
| New host: recover the `.env` | `./scripts/restore.sh config --age-identity identity.txt --output .env [--repository R]` |
| New host: empty stack | `./scripts/restore.sh fresh [--set ID] [--repository R] [--start]` |
| Bad data or deploy: replace the live database | `./scripts/restore.sh in-place --yes [--set ID] [--start]` |
| Check without changing anything | add `--dry-run` to `fresh` or `in-place` |

```mermaid
flowchart TD
    A["restore.sh fresh or in-place"] --> B{"Guards pass?"}
    B -->|"No"| X["Nothing changed, reason printed"]
    B -->|"Yes"| C["Fetch set, verified against the repository and manifest checksums"]
    C --> D["Put objects back (only adds)"]
    D --> E["pg_restore into a scratch database, one transaction"]
    E --> F{"Statistics equal the manifest?"}
    F -->|"No"| Y["Scratch dropped, live database untouched"]
    F -->|"Yes"| G["Rename scratch into place"]
    G --> H["In place: old database kept as name_pre_restore_timestamp"]
```

**Guards (a refused restore changes nothing):** the target must be empty for `fresh`; `in-place` needs `--yes` and stops the application only after a dry run has passed; the image must be the one the set was taken with (the statistics are computed by that release's models, so another schema revision is refused with the tag to use, then upgrade afterwards: the newer image migrates on start); the PostgreSQL server must not be older than the dump's; `STORAGE_BACKEND` must match the set; the staging volume needs room for the fetched set.

**New host, step by step**

1. Install Docker and get this repository and the image tag the set names (`list` and `--dry-run` print it).
2. Recover the `.env` with `config` and your age identity. A set taken with `BACKUP_SECRETS_MODE=none` holds none: supply `APP_SECRET_ENCRYPTION_KEY` and `JWT_SECRET` from wherever you keep them.
3. `./scripts/restore.sh fresh --repository <off-site repository> --start` (credentials for the repository as for backups). Output ends with `verified against the manifest`.
4. After an incident that may have exposed the dump or the host, force credential resets before users sign in (not yet available; see the plan).

**Keys.** The restored application needs the original `APP_SECRET_ENCRYPTION_KEY`; the restore checks that every encrypted value decrypts with the key it is given and fails otherwise. If the original is lost, set a new key and add `--clear-unreadable-secrets`: those values are removed (users with 2FA re-enrol; organisation SMTP and SSO secrets are re-entered) and one audit event records the counts. Clearing is refused without a key to judge by.

**After an in-place restore** the replaced database stays on the server as `<name>_pre_restore_<UTC time>` (the name is printed and recorded in `restore-report.json`). Rolling back is stopping the application and renaming it back; when you no longer need it, `DROP DATABASE` it, since it still holds all the data the restore replaced.

`restore-report.json` (step names, counts and ids only, no row values or secrets) is written to the `reqtrack_backup_status` volume by every real restore, or to any file with `--report`. Objects the set does not contain are left in the store, never deleted. Exit status: `0` success, `1` failed or refused, `2` bad configuration, `75` a backup or restore is running.

Legacy files from `scripts/backup.sh` (`.sql.gz`, `reqtrack-files-*.tar.gz`) still restore with `./scripts/restore.sh FILE`, now in one transaction that stops at the first error, so only into an empty database.

## Security notes

- The `backup` service has no listener and no Docker socket, drops all capabilities, and reads the database and storage over the Compose network with the application's own credentials.
- The staging volume holds the object mirror and, during a run, an unencrypted dump: treat it as Confidential and keep it on an encrypted disk. The dump is removed when the run ends, successfully or not.
- A backup contains the same data as production, including password hashes and encrypted secrets. `none` mode keeps the keys out of it; `config` mode stores them only encrypted to your age key.
- The least-privilege read-only S3 identity for the backup is not in place yet; the tool currently uses the application's credentials, which already include list and read.
- The `restore` service additionally writes to the database server (it creates, renames and drops databases), the object store and the local file store; it is not started unless you run it, and shares the backup service's hardening (no listener, no Docker socket, all capabilities dropped).
