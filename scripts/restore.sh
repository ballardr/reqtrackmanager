#!/usr/bin/env bash
# Restores a backup produced by scripts/backup.sh into the running `db`
# service. This will overwrite existing data (I-M-04).
#
# Usage: ./scripts/restore.sh path/to/reqtrack-<timestamp>.sql.gz
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <backup-file.sql.gz>" >&2
  exit 1
fi

gunzip -c "$1" | docker compose exec -T db psql -U reqtrack -d reqtrack

echo "Restore complete."
