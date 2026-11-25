#!/usr/bin/env bash
# Takes a disaster-recovery backup of the whole platform: the database, the object store (or local file
# store), and, in BACKUP_SECRETS_MODE=config, the operator's .env encrypted to an age recipient. The set is
# stored as an encrypted restic snapshot, copied to every BACKUP_DESTINATIONS repository, pruned to the
# retention policy and sampled for integrity.
#
# Usage (the stack's .env is in deployments/full; run from any directory; cron-safe: no TTY needed):
#   ./scripts/dr-backup.sh              # one backup (same as `run`)
#   ./scripts/dr-backup.sh bundle --output FILE   # latest set as one age-encrypted tar, for scp or a USB disk
#
# Exit status: 0 success, 1 failed (see status.json in the `reqtrack_backup_status` volume), 75 another
# backup is already running. `db` and `storage` are started on demand; nothing else needs to be up.
#
# Sets written here are restic snapshots; scripts/restore.sh restores only the files scripts/backup.sh writes.
set -euo pipefail

# The Compose project lives in deployments/full, with its .env beside it.
cd "$(dirname "$0")/../deployments/full"

if [ $# -eq 0 ]; then
  set -- run
fi
case "$1" in
  run|bundle) ;;
  *)
    echo "Usage: $0 [run | bundle --output FILE]" >&2
    exit 2
    ;;
esac

exec docker compose --profile backup run --rm -T backup "$@"
