#!/usr/bin/env bash
# End-to-end proof of the disaster-recovery chain, on throwaway Docker Compose projects (CI job `restore-test`,
# or by hand): builds a SOURCE stack, seeds the Playwright dataset, takes a real backup, then runs the
# restore-test (scripts/restore-test.sh) against it:
#   1. the positive case: the set restores into a working platform whose statistics equal the source
#      (including a real sign-in as the seeded administrator);
#   2. the same with a replacement encryption key and --clear-unreadable-secrets (recovery without the key);
#   3. a forced credential reset (--force-reset all --reset-2fa): every local account must choose a new password and
#      a locked-out server administrator is let back in with a single-use link printed by the command line;
#   4. five injected faults (a deleted row, a deleted object, a wrong key, a damaged repository, an account whose
#      reset marker was cleared), each of which the restore-test must catch: a check that cannot fail is not a check;
#   5. nothing left behind (no scratch containers or volumes).
# The source stack and every scratch project are removed at the end, pass or fail, unless DRCHECK_KEEP=1.
#
# Usage (from the repo root; needs Docker with the Compose plugin and python3; takes 15 to 30 minutes):
#   ./scripts/restore-test-selfcheck.sh
# DRCHECK_CASES="positive nokey reset faults" (any subset) runs only those cases.
# Environment: DRCHECK_OUTPUT (report directory, default ./restore-test-reports),
# DRCHECK_IMAGE_PREFIX / DRCHECK_IMAGE_TAG (the images built and used, default reqtrack-drcheck / selfcheck, so a
# real deployment's images are never replaced), DRCHECK_KEEP=1 (leave the source stack for inspection).
#
# Exit status: 0 every case behaved as required, 1 at least one did not, 2 a prerequisite is missing.
set -euo pipefail

cd "$(dirname "$0")/.."

for tool in docker python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "restore-test-selfcheck needs $tool" >&2; exit 2; }
done

STAMP="$(date -u +%Y%m%dt%H%M%Sz | tr 'A-Z' 'a-z')"
SOURCE="reqtrack-drsrc-${STAMP}"
OUTPUT="${DRCHECK_OUTPUT:-restore-test-reports}"
export GHCR_IMAGE_PREFIX="${DRCHECK_IMAGE_PREFIX:-reqtrack-drcheck}"
export IMAGE_TAG="${DRCHECK_IMAGE_TAG:-selfcheck}"
ADMIN_EMAIL="admin@example.com"   # the account scripts/seed_e2e_dataset.py signs in with
ADMIN_PASSWORD="ChangeMe123!"
ORG_ADMIN_EMAIL="e2e-orgadmin-ab@example.com"   # an organisation administrator of the seeded Alpha organisation
ORG_ADMIN_PASSWORD="E2ePass123!"

WORK="$(mktemp -d)"
chmod 700 "$WORK"
FAILURES=0

random() { python3 -c 'import secrets; print(secrets.token_urlsafe(24))'; }

source_compose() {
  docker compose -p "$SOURCE" --env-file "$WORK/source.env" -f docker-compose.yml -f docker-compose.restore-test.yml --profile backup "$@"
}

cleanup() {
  local status=$?
  if [ "${DRCHECK_KEEP:-0}" = 1 ]; then
    echo "DRCHECK_KEEP=1: source project $SOURCE left running; its credentials are in $WORK/source.env"
    exit "$status"
  fi
  source_compose down --volumes --remove-orphans --timeout 30 >/dev/null 2>&1 || true
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

step() { printf '\n== %s\n' "$*"; }

# --- source stack ----------------------------------------------------------------------------------------

step "Building the images (cached after the first run)"
printf '%s' "$(random)" > "$WORK/repo-password"
printf '%s' "$ADMIN_PASSWORD" > "$WORK/admin-password"
# Both names carry the one secret: older Compose releases (the CI runner has 2.38) evaluate the legacy
# STORAGE_ROOT_PASSWORD fallback eagerly and refuse to start without it.
STORAGE_SECRET="$(random)"
# REQUIRE_STRONG_SECRETS=false: the seeded end-to-end dataset signs in as the built-in administrator
# (ChangeMe123!), which the strong-secret start-up check refuses. Every other secret below is random.
cat > "$WORK/source.env" <<ENV
REQUIRE_STRONG_SECRETS=false
POSTGRES_PASSWORD=$(random)
JWT_SECRET=$(random)
APP_SECRET_ENCRYPTION_KEY=$(random)
SERVER_ADMIN_EMAIL=$ADMIN_EMAIL
SERVER_ADMIN_PASSWORD=$ADMIN_PASSWORD
STORAGE_ACCESS_KEY=drsrc
STORAGE_SECRET_KEY=$STORAGE_SECRET
STORAGE_ROOT_PASSWORD=$STORAGE_SECRET
SMTP_HOST=mail-sink.invalid
RESTORE_TEST_SERVER_ADMIN_ENABLED=true
BACKUP_REPO_PASSWORD_FILE=$WORK/repo-password
BACKUP_ENV_FILE=$WORK/source.env
BACKUP_SECRETS_MODE=config
GHCR_IMAGE_PREFIX=$GHCR_IMAGE_PREFIX
IMAGE_TAG=$IMAGE_TAG
ENV
# Readable by the backup container's own user (not the runner's uid), which mounts it read-only; the file is
# throwaway and sits in a 0700 directory.
chmod 644 "$WORK/source.env"

source_compose build backend backup

# The config snapshot is encrypted to an age public key; the identity stays here, as it would in a vault.
IMAGE="$GHCR_IMAGE_PREFIX-backup:$IMAGE_TAG"
docker run --rm --entrypoint age-keygen "$IMAGE" > "$WORK/age-identity.txt" 2>/dev/null
RECIPIENT="$(sed -n 's/^# public key: //p' "$WORK/age-identity.txt")"
[ -n "$RECIPIENT" ] || { echo "could not generate an age key" >&2; exit 2; }
echo "BACKUP_CONFIG_AGE_RECIPIENT=$RECIPIENT" >> "$WORK/source.env"

step "Starting the source stack ($SOURCE) and seeding the end-to-end dataset"
source_compose up -d --wait --wait-timeout 600 db storage backend
source_compose exec -T backend python scripts/seed_e2e_dataset.py

# The seeded data holds no encrypted value, and a wrong-key test needs some: give an organisation an SSO client
# secret (encrypted at rest) so the encrypted-column probe has something to read. Only an organisation
# administrator may set it (a server administrator has no role inside an organisation).
step "Adding an encrypted value (an organisation SSO client secret)"
source_compose exec -T backend python - <<PY
import httpx
base = "http://localhost:8000/api/v1"
token = httpx.post(f"{base}/auth/login", json={"email": "$ORG_ADMIN_EMAIL", "password": "$ORG_ADMIN_PASSWORD"}, timeout=60).json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
orgs = httpx.get(f"{base}/orgs?mine=true", headers=headers, timeout=60).json()
org = next(o for o in orgs if o["name"] == "E2E Alpha Robotics")
r = httpx.put(f"{base}/orgs/{org['id']}/sso-config", headers=headers, timeout=60,
              json={"slug": "drcheck", "sso_enabled": False, "oidc_client_secret": "drcheck-secret-value"})
r.raise_for_status()
PY

step "Taking a backup (config mode, real restic repository)"
source_compose run --rm -T backup run
REPO_VOLUME="${SOURCE}_reqtrack_backup_repo"

# --- the cases -------------------------------------------------------------------------------------------

run_case() {
  local label="$1"; shift
  step "$label"
  if python3 scripts/restore_test.py \
      --repository-volume "$REPO_VOLUME" --password-file "$WORK/repo-password" --source-env "$WORK/source.env" \
      --output "$OUTPUT" --check-subset 100% "$@"; then
    echo ">> $label: as required"
  else
    echo ">> $label: NOT as required" >&2
    FAILURES=$((FAILURES + 1))
  fi
}

selected() { case " ${DRCHECK_CASES:-positive nokey reset faults} " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

if selected positive; then
  run_case "Positive: restore, start, verify, sign in" \
    --login-email "$ADMIN_EMAIL" --login-password-file "$WORK/admin-password"
fi
if selected nokey; then
  run_case "Recovery without the original key (--key-mode wrong, secrets cleared)" \
    --key-mode wrong --clear-unreadable-secrets
fi
if selected reset; then
  run_case "Forced credential reset: every local account locked, a locked-out administrator let back in from the command line" \
    --force-reset all --reset-2fa
fi
if selected faults; then
  for fault in delete-row delete-object wrong-key corrupt-dump unmarked-account; do
    run_case "Self-test: the harness must catch '$fault'" --inject "$fault"
  done
fi

step "Nothing left behind"
if docker volume ls -q | grep -q '^reqtrack-drtest-'; then
  echo "scratch volumes were left behind:" >&2
  docker volume ls -q | grep '^reqtrack-drtest-' >&2
  FAILURES=$((FAILURES + 1))
fi
if docker ps -a --format '{{.Names}}' | grep -q '^reqtrack-drtest-'; then
  echo "scratch containers were left behind" >&2
  FAILURES=$((FAILURES + 1))
fi

if [ "$FAILURES" -ne 0 ]; then
  echo "restore-test self-check: $FAILURES case(s) did not behave as required (reports in $OUTPUT)" >&2
  exit 1
fi
echo "restore-test self-check passed"
