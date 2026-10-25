#!/usr/bin/env bash
# Restores a backup set taken by scripts/dr-backup.sh (an encrypted restic snapshot), or a legacy file written
# by scripts/backup.sh. Runs the restore tool in the `backup` image through the `restore` Compose profile; it
# restores into a scratch database, checks it against the set's manifest and only then swaps it in.
#
# Usage (from the repo root, with the stack's .env in place; BACKUP_REPO_PASSWORD_FILE set as for backups):
#   ./scripts/restore.sh list [--repository R]
#   ./scripts/restore.sh config --age-identity FILE --output PATH [--set ID] [--repository R]
#       Decrypts the set's .env snapshot to PATH (mode 0600; refuses to overwrite). Needs only Docker, so it
#       works on a new host before any .env exists. Set BACKUP_REPO_VOLUME to a host path, or pass --repository.
#   ./scripts/restore.sh fresh [--set latest|ID] [--repository R] [--dry-run] [--start] [--clear-unreadable-secrets] [--force-reset [all|server_admins]] [--reset-2fa]
#       Into an empty database (a new host). Refuses a database that holds data.
#   ./scripts/restore.sh in-place --yes [same options]
#       Replaces the live database; the application is stopped first and the old database is kept under a new
#       name. Without --yes it prints the plan and refuses. A dry run happens first, so a refused restore leaves the
#       application running.
#   ./scripts/restore.sh FILE.sql.gz | reqtrack-files-*.tar.gz     (legacy files from scripts/backup.sh)
#
# --start brings the application up after a verified restore. Exit status: 0 success, 1 failed or refused,
# 2 usage, 75 a backup or restore is already running.
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//' >&2
}

restore_tool() {
  docker compose --profile restore run --rm -T restore "$@"
}

# Decrypts the .env snapshot to a file without needing a Compose project (which would itself need the .env).
config_command() {
  local identity="" output="" repository="" set_selector="latest"
  while [ $# -gt 0 ]; do
    case "$1" in
      --age-identity) identity="${2:?--age-identity needs a file}"; shift 2 ;;
      --output) output="${2:?--output needs a path}"; shift 2 ;;
      --repository) repository="${2:?--repository needs a value}"; shift 2 ;;
      --set) set_selector="${2:?--set needs a value}"; shift 2 ;;
      *) usage; exit 2 ;;
    esac
  done
  if [ -z "$identity" ] || [ -z "$output" ] || [ -z "${BACKUP_REPO_PASSWORD_FILE:-}" ]; then
    echo "config needs --age-identity, --output and BACKUP_REPO_PASSWORD_FILE" >&2
    exit 2
  fi
  if [ -z "$repository" ] && [ -z "${BACKUP_REPO_VOLUME:-}" ]; then
    echo "config needs --repository (an off-site copy) or BACKUP_REPO_VOLUME (a host path holding the repository)" >&2
    exit 2
  fi
  if [ -e "$output" ]; then
    echo "$output already exists; remove it first (an existing .env is never overwritten)" >&2
    exit 1
  fi
  local image="${GHCR_IMAGE_PREFIX:-ghcr.io/ballardr/reqtrackmanager}-backup:${IMAGE_TAG:-latest}"
  local args=(--rm -i --user "$(id -u):$(id -g)" -e HOME=/tmp
    -e BACKUP_PASSWORD_FILE=/run/secrets/backup_repo_password
    -v "$BACKUP_REPO_PASSWORD_FILE:/run/secrets/backup_repo_password:ro"
    -v "$(cd "$(dirname "$identity")" && pwd)/$(basename "$identity"):/run/restore/identity:ro"
    -e "AWS_ACCESS_KEY_ID=${BACKUP_AWS_ACCESS_KEY_ID:-}" -e "AWS_SECRET_ACCESS_KEY=${BACKUP_AWS_SECRET_ACCESS_KEY:-}"
    -e "AWS_DEFAULT_REGION=${BACKUP_AWS_DEFAULT_REGION:-}"
    -e "AZURE_ACCOUNT_NAME=${BACKUP_AZURE_ACCOUNT_NAME:-}" -e "AZURE_ACCOUNT_KEY=${BACKUP_AZURE_ACCOUNT_KEY:-}")
  [ -n "${BACKUP_REPO_VOLUME:-}" ] && args+=(-v "$BACKUP_REPO_VOLUME:/backup/repo")
  [ -n "${BACKUP_SSH_DIR:-}" ] && args+=(-v "$BACKUP_SSH_DIR:/home/app/.ssh:ro")
  local tool_args=(config --age-identity /run/restore/identity --set "$set_selector")
  [ -n "$repository" ] && tool_args+=(--repository "$repository")

  # Created 0600; noclobber stops a file that appears after the check above from being overwritten. The file is
  # removed again only if this run created it and the tool failed.
  (
    umask 077
    set -o noclobber
    : > "$output"
    set +o noclobber
    if ! docker run "${args[@]}" --entrypoint python "$image" scripts/dr_restore.py "${tool_args[@]}" > "$output"; then
      rm -f "$output"
      exit 1
    fi
  )
  echo "configuration written to $output (mode 0600); keep it out of version control" >&2
}

# fresh / in-place: plan first, stop the application only when the plan is accepted, then restore.
mode_command() {
  local mode="$1"; shift
  local start=0 dry_run=0 yes=0
  local pass=()  # expanded as ${pass[@]+...}: an empty array is an unbound variable under `set -u` in bash 3.2 (macOS)
  for arg in "$@"; do
    case "$arg" in
      --start) start=1 ;;
      --dry-run) dry_run=1; pass+=("$arg") ;;
      --yes) yes=1; pass+=("$arg") ;;
      *) pass+=("$arg") ;;
    esac
  done

  if [ "$mode" = "in-place" ] && [ "$dry_run" = 0 ] && [ "$yes" = 1 ]; then
    restore_tool restore "$mode" --dry-run ${pass[@]+"${pass[@]}"}
    docker compose stop backend mcp-server
  fi

  local status=0
  restore_tool restore "$mode" ${pass[@]+"${pass[@]}"} || status=$?

  if [ "$status" = 0 ] && [ "$dry_run" = 0 ] && [ "$start" = 1 ]; then
    docker compose up -d
  elif [ "$mode" = "in-place" ] && [ "$dry_run" = 0 ] && [ "$yes" = 1 ]; then
    echo "The application is stopped. Start it with: docker compose up -d" >&2
  fi
  return "$status"
}

# Legacy files from scripts/backup.sh. A plain SQL dump restores only into an empty database, in one
# transaction, and stops at the first error instead of carrying on into a half-restored database.
legacy_restore() {
  case "$1" in
    *reqtrack-files-*.tar.gz)
      docker compose exec -T backend tar xzf - -C /app/data < "$1"
      echo "File storage restore complete."
      ;;
    *)
      gunzip -c "$1" | docker compose exec -T db psql -U reqtrack -d reqtrack -v ON_ERROR_STOP=1 --single-transaction
      echo "Database restore complete."
      ;;
  esac
}

case "${1:-}" in
  list) shift; restore_tool list "$@" ;;
  config) shift; config_command "$@" ;;
  fresh|in-place) mode_command "$@" ;;
  *.sql.gz|*reqtrack-files-*.tar.gz) [ $# -eq 1 ] || { usage; exit 2; }; legacy_restore "$1" ;;
  *) usage; exit 2 ;;
esac
