#!/usr/bin/env bash
# Proves the latest backup set restores into a working platform, on a throwaway Compose project that cannot
# touch or reach the real deployment, and that its statistics match the source. Safe to run on the production
# host (read-only access to the repository, no published ports, email disabled) and from cron or CI.
#
# Usage (from the repo root):
#   BACKUP_REPO_PASSWORD_FILE=/path/to/repo-password \
#     ./scripts/restore-test.sh --repository-volume reqtrack_backup_repo --source-env /path/to/.env
#   ./scripts/restore-test.sh --repository sftp:backup@host:/srv/reqtrack ...    # test the off-site copy
#   ./scripts/restore-test.sh --key-mode wrong --clear-unreadable-secrets ...    # recovery without the original key
#   ./scripts/restore-test.sh --inject delete-row ...                            # self-test: passes only if the fault is caught
#
# Options (see `--help`): --repository-volume, --repository, --password-file, --set, --source-env, --key-mode,
# --clear-unreadable-secrets, --image-tag, --output, --status-dir, --keep, --inject, --login-email,
# --login-password-file, --check-subset, --timeout.
#
# Exit status: 0 passed, 1 a check failed, 2 usage or missing input, 75 a backup or restore is running.
# The report is written to ./restore-test-reports/<project>/report.{json,md}.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1; then
  echo "restore-test needs python3 (3.9 or newer) on the host to drive Docker Compose" >&2
  exit 2
fi
exec python3 scripts/restore_test.py "$@"
