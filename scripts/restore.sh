#!/usr/bin/env bash
# Restores a backup produced by scripts/backup.sh into the running `db`
# (and, for a reqtrack-files-*.tar.gz, `backend`) service. This will
# overwrite existing data (I-M-04).
#
# Usage: ./scripts/restore.sh path/to/reqtrack-<timestamp>.sql.gz
#        ./scripts/restore.sh path/to/reqtrack-files-<timestamp>.tar.gz
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <backup-file.sql.gz|reqtrack-files-backup.tar.gz>" >&2
  exit 1
fi

case "$1" in
  *reqtrack-files-*.tar.gz)
    docker compose exec -T backend tar xzf - -C /app/data < "$1"
    echo "File storage restore complete."
    ;;
  *)
    gunzip -c "$1" | docker compose exec -T db psql -U reqtrack -d reqtrack
    echo "Database restore complete."
    ;;
esac
