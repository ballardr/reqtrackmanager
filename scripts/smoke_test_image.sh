#!/bin/sh
# Smoke test for one production container image: does it start, report healthy
# and answer a real request on the CPU architecture it is run on?
#
# Usage: scripts/smoke_test_image.sh <backend|backup|frontend|mcp-server|docs> <image> [expected-arch]
#
# Why: CI builds an arm64 image for Raspberry Pi and other arm hosts, and an
# image that builds but does not start (a missing aarch64 wheel, a broken
# binary) is a failure users meet first. The full test suites run on amd64
# only, so this is the one check arm images get before they are published.
#
# What each kind proves:
#   backend    - starts against a throwaway PostgreSQL (migrations run), becomes
#                healthy, then logs in as the bootstrap server admin and lists
#                projects and organisations (exercises bcrypt, psycopg2 and
#                cryptography natively).
#   backup     - the disaster-recovery tools (pg_dump, restic, age, ssh) run.
#   frontend   - nginx serves `/`, a built static asset and the runtime config.
#   mcp-server - becomes healthy.
#   docs       - becomes healthy and serves `/`.
#
# Safety: everything it creates (one network, its containers) carries a
# per-run name and is removed on exit, including on failure and Ctrl-C; it never
# removes anything else and never prunes. Credentials are random per run, nothing
# is published on a host port, and mail delivery is disabled. Needs only Docker.
#
# Environment: SMOKE_TIMEOUT (seconds to wait for health; default 300, raise it
# on a slow board).
set -eu

KIND="${1:?usage: smoke_test_image.sh <kind> <image> [expected-arch]}"
IMAGE="${2:?usage: smoke_test_image.sh <kind> <image> [expected-arch]}"
EXPECT_ARCH="${3:-}"
TIMEOUT="${SMOKE_TIMEOUT:-300}"

RUN_ID="$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
PREFIX="reqtrack-smoke-${RUN_ID}"
NETWORK="${PREFIX}"
CREATED=""

log() { printf '[smoke %s] %s\n' "$KIND" "$*"; }
fail() { printf '[smoke %s] FAIL: %s\n' "$KIND" "$*" >&2; exit 1; }
random_hex() { od -An -N24 -tx1 /dev/urandom | tr -d ' \n'; }

# Removes only the containers and network created by this run.
cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        for name in $CREATED; do
            printf '[smoke %s] ---- logs: %s ----\n' "$KIND" "$name" >&2
            docker logs --tail 80 "$name" >&2 2>&1 || true
        done
    fi
    for name in $CREATED; do
        docker rm -f -v "$name" >/dev/null 2>&1 || true
    done
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Starts a detached container on the run's network and records it for cleanup.
start() {
    name="$1"; shift
    CREATED="$CREATED ${PREFIX}-${name}"
    docker run -d --name "${PREFIX}-${name}" --network "$NETWORK" \
        --label "reqtrack.smoke=${RUN_ID}" "$@" >/dev/null
}

# Waits until the container's own HEALTHCHECK reports healthy.
wait_healthy() {
    name="${PREFIX}-$1"
    elapsed=0
    while [ "$elapsed" -lt "$TIMEOUT" ]; do
        state="$(docker inspect -f '{{.State.Status}}' "$name")"
        [ "$state" = "running" ] || fail "$1 is $state, expected running"
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name")"
        [ "$health" != "healthy" ] || { log "$1 healthy after ${elapsed}s"; return 0; }
        sleep 3
        elapsed=$((elapsed + 3))
    done
    fail "$1 not healthy after ${TIMEOUT}s"
}

# Runs a command inside a started container.
in_container() {
    name="${PREFIX}-$1"; shift
    docker exec "$name" "$@"
}

docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "image $IMAGE not found locally"
ARCH="$(docker image inspect -f '{{.Architecture}}' "$IMAGE")"
log "image architecture: $ARCH"
if [ -n "$EXPECT_ARCH" ] && [ "$ARCH" != "$EXPECT_ARCH" ]; then
    fail "image is $ARCH, expected $EXPECT_ARCH (would run emulated)"
fi

docker network create --label "reqtrack.smoke=${RUN_ID}" "$NETWORK" >/dev/null

case "$KIND" in
backend)
    DB_PASSWORD="$(random_hex)"
    ADMIN_EMAIL="smoke-admin@example.com"
    ADMIN_PASSWORD="Smoke-$(random_hex)"
    start db -e POSTGRES_DB=reqtrack -e POSTGRES_USER=reqtrack -e "POSTGRES_PASSWORD=${DB_PASSWORD}" \
        postgres:16-alpine
    elapsed=0
    until in_container db pg_isready -q -U reqtrack -d reqtrack; do
        [ "$elapsed" -lt "$TIMEOUT" ] || fail "postgres not ready after ${TIMEOUT}s"
        sleep 2
        elapsed=$((elapsed + 2))
    done
    start backend \
        -e BACKEND_WORKERS=2 \
        -e "DATABASE_URL=postgresql://reqtrack:${DB_PASSWORD}@${PREFIX}-db:5432/reqtrack" \
        -e "JWT_SECRET=$(random_hex)" -e "APP_SECRET_ENCRYPTION_KEY=$(random_hex)" \
        -e SERVER_ADMIN_ENABLED=true -e "SERVER_ADMIN_EMAIL=${ADMIN_EMAIL}" \
        -e "SERVER_ADMIN_PASSWORD=${ADMIN_PASSWORD}" -e SERVER_ADMIN_CREATE_ORG=true \
        -e STORAGE_BACKEND=local -e EMAIL_DELIVERY=disabled \
        "$IMAGE"
    wait_healthy backend
    # Login (bcrypt) then two authenticated list calls (ORM, psycopg2, JWT), from inside the container
    # so no host port is needed. Credentials come from the container's own environment.
    in_container backend python -c '
import json, os, urllib.request as r
base = "http://127.0.0.1:8000"
login = r.Request(base + "/api/v1/auth/login",
                  json.dumps({"email": os.environ["SERVER_ADMIN_EMAIL"], "password": os.environ["SERVER_ADMIN_PASSWORD"]}).encode(),
                  {"Content-Type": "application/json"})
token = json.load(r.urlopen(login, timeout=120))["access_token"]
for path in ("/api/v1/projects", "/api/v1/orgs"):
    resp = r.urlopen(r.Request(base + path, headers={"Authorization": "Bearer " + token}), timeout=60)
    assert resp.status == 200 and isinstance(json.load(resp), list), path
print("login and list calls ok")
' || fail "authenticated API calls failed"
    ;;
backup)
    docker run --rm --name "${PREFIX}-backup" --label "reqtrack.smoke=${RUN_ID}" --entrypoint sh "$IMAGE" -c '
set -e
"$BACKUP_PG_DUMP" --version
restic version
age --version
ssh -V
python -c "import app"
' || fail "backup tools did not run"
    ;;
frontend)
    start frontend "$IMAGE"
    wait_healthy frontend
    in_container frontend wget -qO /dev/null http://127.0.0.1:3000/ || fail "/ not served"
    ASSET="$(in_container frontend sh -c "wget -qO- http://127.0.0.1:3000/ | grep -o '/assets/[^\"]*\.js' | head -n 1")"
    [ -n "$ASSET" ] || fail "no built asset referenced by index.html"
    in_container frontend wget -qO /dev/null "http://127.0.0.1:3000${ASSET}" || fail "asset $ASSET not served"
    in_container frontend wget -qO /dev/null http://127.0.0.1:3000/env-config.js || fail "env-config.js not served"
    ;;
mcp-server)
    start mcp-server "$IMAGE"
    wait_healthy mcp-server
    ;;
docs)
    start docs "$IMAGE"
    wait_healthy docs
    in_container docs wget -qO /dev/null http://127.0.0.1:8080/ || fail "/ not served"
    ;;
*)
    fail "unknown kind '$KIND' (backend, backup, frontend, mcp-server, docs)"
    ;;
esac

log "OK"
