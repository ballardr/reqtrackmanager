#!/usr/bin/env bash
# Runs one scheduled disaster-recovery job from cron or a systemd timer, so the schedule entry is one short line
# and the settings live in one file.
#
# Usage:  scripts/dr-scheduled.sh backup | restore-test
#
# Settings come from the environment and, if present, from $REQTRACK_DR_ENV (default /etc/reqtrack/dr.env): plain
# KEY=value lines, `#` comments, no shell syntax (the file is read, never executed). Keep it readable only by the
# user the job runs as; it names where the secrets are, not the secrets.
#
#   BACKUP_REPO_PASSWORD_FILE   required: the restic repository password file
#   BACKUP_STATUS_VOLUME        restore-test: required, an absolute host directory; the same one the backup writes
#                               to (set it for the backup too), so one directory holds every status file Alloy reads
#   BACKUP_REPO_VOLUME          restore-test: the repository volume or host path (default reqtrack_backup_repo)
#   RESTORE_TEST_SOURCE_ENV     restore-test: required, a .env holding the original APP_SECRET_ENCRYPTION_KEY
#   RESTORE_TEST_OUTPUT         restore-test: report directory (default /var/log/reqtrack/restore-test-reports)
#   RESTORE_TEST_ARGS           restore-test: extra options, e.g. `--repository sftp:backup@host:/srv/reqtrack`
#                               to test the off-site copy (word-split, so no spaces inside a value)
#   RESTORE_TEST_EXPECTED_INTERVAL_HOURS   how often it runs (default 168, weekly); the staleness alert follows it
#   BACKUP_* / the rest of docker-compose.yml's backup settings, as for ./scripts/dr-backup.sh
#
# Exit status: that of the job (0 ok, 1 failed, 75 another backup or restore is running), 2 for a missing setting.
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
  echo "Usage: $0 backup | restore-test" >&2
  exit 2
}

# Exports KEY=value lines without executing them. Values are taken literally; one pair of surrounding quotes is removed.
load_env() {
  local file="$1" line key value
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    value="${line#*=}"
    [ "$key" != "$line" ] || { echo "$file: ignoring a line without '='" >&2; continue; }
    case "$key" in
      *[!A-Za-z0-9_]*|[0-9]*|'') echo "$file: ignoring an invalid name" >&2; continue ;;
    esac
    case "$value" in
      \"*\") value="${value#\"}"; value="${value%\"}" ;;
      \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    export "$key=$value"
  done < "$file"
}

require() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "$name is not set (environment or ${REQTRACK_DR_ENV:-/etc/reqtrack/dr.env})" >&2
    exit 2
  fi
}

[ $# -eq 1 ] || usage
load_env "${REQTRACK_DR_ENV:-/etc/reqtrack/dr.env}"
require BACKUP_REPO_PASSWORD_FILE

case "$1" in
  backup)
    exec ./scripts/dr-backup.sh run
    ;;
  restore-test)
    require RESTORE_TEST_SOURCE_ENV
    require BACKUP_STATUS_VOLUME
    case "$BACKUP_STATUS_VOLUME" in
      /*) ;;
      *) echo "BACKUP_STATUS_VOLUME must be an absolute host directory for the restore-test to write its metrics there" >&2; exit 2 ;;
    esac
    # RESTORE_TEST_ARGS is deliberately word-split into options.
    # shellcheck disable=SC2086
    exec ./scripts/restore-test.sh \
      --repository-volume "${BACKUP_REPO_VOLUME:-reqtrack_backup_repo}" \
      --password-file "$BACKUP_REPO_PASSWORD_FILE" \
      --source-env "$RESTORE_TEST_SOURCE_ENV" \
      --status-dir "$BACKUP_STATUS_VOLUME" \
      --output "${RESTORE_TEST_OUTPUT:-/var/log/reqtrack/restore-test-reports}" \
      ${RESTORE_TEST_ARGS:-}
    ;;
  *)
    usage
    ;;
esac
