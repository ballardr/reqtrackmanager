#!/usr/bin/env bash
# Backs up the ReqTrackManager database and, if applicable, local file
# storage (I-M-04). Run from the repo root against the production stack,
# with the `db` (and `backend`, for the file-storage step) service already
# up (`docker compose up -d db backend`).
#
# Usage: ./scripts/backup.sh [output-directory]
#
# If STORAGE_BACKEND=s3 (the default, via MinIO), file data lives in the
# `reqtrack_minio_data` volume — use MinIO's own backup/replication tooling
# for that instead, since it isn't a plain file tree this script can tar up.
set -euo pipefail

OUT_DIR="${1:-./backups}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT_DIR"

DB_FILE="$OUT_DIR/reqtrack-${TIMESTAMP}.sql.gz"
docker compose exec -T db pg_dump -U reqtrack -d reqtrack | gzip > "$DB_FILE"
echo "Database backup written to $DB_FILE"

# Only the local storage backend has a plain file tree this script can
# archive directly; skip entirely for s3/MinIO (see note above).
STORAGE_BACKEND="$(docker compose exec -T backend printenv STORAGE_BACKEND 2>/dev/null | tr -d '\r' || true)"
if [ "$STORAGE_BACKEND" = "local" ]; then
    FILES_ARCHIVE="$OUT_DIR/reqtrack-files-${TIMESTAMP}.tar.gz"
    docker compose exec -T backend tar czf - -C /app/data files > "$FILES_ARCHIVE"
    echo "File storage backup written to $FILES_ARCHIVE"
fi
