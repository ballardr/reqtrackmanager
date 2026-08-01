#!/usr/bin/env bash
# Backs up the ReqTrackManager database (I-M-04). Run from the repo root
# against the production stack, with the `db` service already up
# (`docker compose up -d db`).
#
# Usage: ./scripts/backup.sh [output-directory]
#
# Note: this only covers the database. If STORAGE_BACKEND=local, also back
# up the STORAGE_LOCAL_DIR file tree separately; if STORAGE_BACKEND=s3 (the
# default, via MinIO), use MinIO's own backup/replication tooling for the
# reqtrack_minio_data volume instead.
set -euo pipefail

OUT_DIR="${1:-./backups}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT_DIR"

OUT_FILE="$OUT_DIR/reqtrack-${TIMESTAMP}.sql.gz"

docker compose exec -T db pg_dump -U reqtrack -d reqtrack | gzip > "$OUT_FILE"

echo "Backup written to $OUT_FILE"
