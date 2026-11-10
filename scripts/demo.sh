#!/usr/bin/env bash
# Sets the local stack (tests/container) up as a demonstration: starts it, waits for it to be healthy, then seeds
# every demonstration project and posts the sign-in details message (backend/scripts/demo_setup.py).
#
#   scripts/demo.sh                      start, seed (a second run changes nothing)
#   scripts/demo.sh --reset              remove the demonstration organisation and seed again
#   scripts/demo.sh --teardown           remove the demonstration organisation and its messages
#   scripts/demo.sh --rotate-passwords   a new random password for every account (default: DemoDemo123!)
#   scripts/demo.sh --allow-uploads      keep file uploads enabled (default: the demonstration disables them)
#   scripts/demo.sh --clarity <id>       also load Microsoft Clarity (project id from your Clarity dashboard)
#   scripts/demo.sh --schedule           also start the daily reset (DEMO_RESET_AT, DEMO_RESET_TZ; default 00:00 UTC)
#   scripts/demo.sh --no-metrics         do not start the usage-metrics Prometheus (started by default)
#   scripts/demo.sh --export-metrics [path] [--since 7d] [--no-snapshot]
#                                        write a metrics bundle (.tar.gz) for a developer to review; starts nothing
#   scripts/demo.sh --view-metrics <bundle>   open a bundle in a throwaway Prometheus on 127.0.0.1:9091
#   scripts/demo.sh --purge-metrics      stop Prometheus and remove the collected metrics (a reset keeps them)
#   scripts/demo.sh --trust-local-ca     print how to trust the local certificate authority (localhost or an IP address)
#   scripts/demo.sh --purge-certificates stop the proxy and remove its certificates (a reset keeps them)
#   scripts/demo.sh --no-prune           with --pull: keep dangling images and old build cache (a host shared with other projects)
#   scripts/demo.sh --pull               first pull the published images and recreate the services whose image changed
#                                        (for the host timer: scripts/demo.sh --pull --reset; refused with --schedule)
#
# HTTPS: the Caddy proxy (tests/container/caddy) is the only published listener. DEMO_PUBLIC_HOST (default localhost)
# names the host: a DNS name gets a certificate from a public authority (ports 80 and 443 must be reachable; the MCP
# server is served on mcp.<host>, or on DEMO_MCP_HOST, or not at all when DEMO_MCP_HOST=off); localhost or an IP address
# uses Caddy's local authority. DEMO_ACME_EMAIL registers a contact address with the public authority.
#
# Images: --pull uses the images CI publishes (tests/container/docker-compose.demo-images.yml; IMAGE_TAG defaults to
# latest, a commit SHA or version pins one) instead of building the working tree. A failed pull keeps the images already
# present and the run carries on; an unhealthy new image stops the run (exit 1) with no automatic rollback, because
# migrations only go forward. The previous image of each updated service stays tagged :previous; after a healthy update
# dangling images and week-old build cache are pruned (--no-prune skips it). DEMO_RESET_AT and
# DEMO_RESET_TZ, when set, are passed to the reset so the sign-in details state the next reset time.
#
# Any other option is passed to demo_setup.py (for example --confirm-database reqtrack_test, --no-login-message).
# The command refuses a database that holds an organisation it did not create; see docs/development.md.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

# The metrics commands read or remove what the stack collected and never start or seed it. They run before the
# change of directory, so a relative bundle path means the caller's directory.
case "${1:-}" in
  --export-metrics) shift; exec python3 "$here/demo_metrics.py" export "$@" ;;
  --view-metrics) shift; exec python3 "$here/demo_metrics.py" view "$@" ;;
  --purge-metrics) exec python3 "$here/demo_metrics.py" purge ;;
esac

cd "$here/../tests/container"

# The demonstration generates its own secrets once and keeps them in an untracked file (mode 600): the stack's
# compose literals are for the local test stack only, and a demonstration can be served on a public name.
secrets_file="$PWD/.demo-secrets.env"
if [ ! -f "$secrets_file" ]; then
  ( umask 077
    python3 - "$secrets_file" <<'PY'
import secrets, sys
password = secrets.token_urlsafe(18) + "aA1!"
with open(sys.argv[1], "w") as handle:
    handle.write(f"JWT_SECRET={secrets.token_hex(32)}\nAPP_SECRET_ENCRYPTION_KEY={secrets.token_hex(32)}\nSERVER_ADMIN_PASSWORD={password}\n")
PY
  )
fi
set -a
# shellcheck disable=SC1090
. "$secrets_file"
set +a
export DEMO_ADMIN_PASSWORD="$SERVER_ADMIN_PASSWORD"

# The demonstration overlay adds the proxy and unpublishes the application ports; the developer stack never loads it.
export COMPOSE_FILE="docker-compose.yml:docker-compose.demo.yml"
host="${DEMO_PUBLIC_HOST:-localhost}"
case "$host" in
  *[!A-Za-z0-9.:-]*|"") echo "DEMO_PUBLIC_HOST must be a host name or an IP address." >&2; exit 2 ;;
esac
mcp_host="${DEMO_MCP_HOST-mcp.$host}"
if [[ "$host" == localhost || "$host" == *.localhost || "$host" =~ ^[0-9.]+$ || "$host" == *:* ]]; then
  export DEMO_TLS_MODE=internal
  # An IP address has no sub-domain to give the MCP server; localhost has mcp.localhost.
  if [[ "$host" != localhost && "$host" != *.localhost ]]; then mcp_host=off; fi
else
  export DEMO_TLS_MODE=public
fi
export DEMO_PUBLIC_HOST="$host" DEMO_PUBLIC_URL="https://$host"
if [[ -z "$mcp_host" || "$mcp_host" == off ]]; then
  export DEMO_MCP_MODE=off DEMO_MCP_HOST=off
else
  export DEMO_MCP_MODE=on DEMO_MCP_HOST="$mcp_host" DEMO_MCP_URL="https://$mcp_host"
fi
if [ -n "${DEMO_ACME_EMAIL:-}" ] && [ "$DEMO_TLS_MODE" = public ]; then export DEMO_ACME_MODE=email; fi

schedule=false
metrics=true
pull=false
prune=true
pass=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-metrics) metrics=false; shift ;;
    --clarity)
      [ $# -ge 2 ] || { echo "--clarity needs a project id" >&2; exit 2; }
      export DEMO_CLARITY_PROJECT_ID="$2"; shift 2 ;;
    --allow-uploads) export DEMO_ALLOW_UPLOADS=1; pass+=("$1"); shift ;;
    --schedule) schedule=true; shift ;;
    --pull) pull=true; shift ;;
    --no-prune) prune=false; shift ;;
    --trust-local-ca)
      cat <<'TEXT'
The proxy's local certificate authority signs the certificate for localhost and IP addresses. To trust it:
  docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-local-root.crt
  macOS:  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain caddy-local-root.crt
  Linux:  sudo cp caddy-local-root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates
Nothing is changed on this host by this command. Without it the browser shows a certificate warning.
TEXT
      exit 0 ;;
    --purge-certificates)
      docker compose rm -sf caddy
      project="$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
      for volume in reqtrack_demo_caddy_data reqtrack_demo_caddy_config; do
        docker volume ls -q --filter "label=com.docker.compose.volume=$volume" --filter "label=com.docker.compose.project=$project" \
          | while read -r name; do docker volume rm "$name"; done
      done
      exit 0 ;;
    *) pass+=("$1"); shift ;;
  esac
done

if [ "$pull" = true ] && [ "$schedule" = true ]; then
  echo "demo: --pull and --schedule cannot be combined: the in-container scheduler cannot replace its own image, and a host" >&2
  echo "      timer running --pull would reset a second time. Use the host timer alone (docs/demo.md, \"Daily reset\")." >&2
  exit 2
fi

profiles=()
if [ "$metrics" = true ]; then profiles+=(--profile demo-metrics); fi

# Environment the reset needs inside the container (the compose service does not receive the host's).
exec_env=(-e "DEMO_ADMIN_PASSWORD=$DEMO_ADMIN_PASSWORD")
if [ -n "${DEMO_RESET_AT:-}" ]; then exec_env+=(-e "DEMO_RESET_AT=$DEMO_RESET_AT" -e "DEMO_RESET_TZ=${DEMO_RESET_TZ:-UTC}"); fi

image_args=()
if [ "$pull" = true ]; then
  # Services built from this repository; docker-compose.demo-images.yml names exactly these (a test checks it).
  project_services=(backend converter frontend mcp-server docs)
  prefix="${GHCR_IMAGE_PREFIX:-ghcr.io/ballardr/reqtrackmanager}"
  tag="${IMAGE_TAG:-latest}"
  export COMPOSE_FILE="$COMPOSE_FILE:docker-compose.demo-images.yml"

  # One update at a time, on the host: a manual run cannot overlap the timer's. Exit 75 as the in-container lock does.
  state_dir="${DEMO_HOST_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/reqtrack-demo}"
  mkdir -p "$state_dir"
  lock="$state_dir/pull.lock"
  if ! mkdir "$lock" 2>/dev/null; then
    holder="$(cat "$lock/pid" 2>/dev/null || true)"
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
      echo "demo: another --pull run (process $holder) is in progress." >&2
      exit 75
    fi
    rm -rf "$lock"
    mkdir "$lock" 2>/dev/null || { echo "demo: another --pull run is in progress." >&2; exit 75; }
  fi
  echo $$ > "$lock/pid"
  trap 'rm -rf "$lock"' EXIT

  image_id() { docker image inspect --format '{{.Id}}' "$1" 2>/dev/null || echo none; }

  before=()
  for service in "${project_services[@]}"; do before+=("$(image_id "$prefix-$service:$tag")"); done

  outcome=unchanged
  # The pull is the one step allowed to fail: the demonstration must still reset, on the images it already has.
  if ! docker compose pull "${project_services[@]}"; then
    outcome=failed
    echo "demo: the image pull failed; continuing with the images already present." >&2
  fi

  report=""
  changed_services=()
  old_previous=()
  index=0
  for service in "${project_services[@]}"; do
    now="$(image_id "$prefix-$service:$tag")"
    is_changed=false
    if [ "$now" != "${before[$index]}" ]; then
      is_changed=true
      changed_services+=("$service")
      # Keep the image being replaced under :previous (for the pin in the message below); the one it displaces is
      # removed after the new stack is healthy.
      old_previous+=("$(image_id "$prefix-$service:previous")")
      if [ "${before[$index]}" != none ]; then docker tag "${before[$index]}" "$prefix-$service:previous"; fi
    fi
    report="${report:+$report,}\"$service\":{\"image_id\":\"$now\",\"changed\":$is_changed}"
    index=$((index + 1))
  done
  if [ "$outcome" != failed ] && [ ${#changed_services[@]} -gt 0 ]; then outcome=updated; fi
  [ ${#changed_services[@]} -eq 0 ] || echo "demo: updated: ${changed_services[*]}"

  # Recreates only the services whose image (or configuration) changed; the rest keep running.
  if ! docker compose ${profiles[@]+"${profiles[@]}"} up -d --no-build --wait; then
    echo "demo: the stack is not healthy after the image update. No rollback was attempted: the new backend may already" >&2
    echo "      have migrated the database. The previous images are tagged :previous. To run a published version instead:" >&2
    echo "      IMAGE_TAG=<version or commit SHA> scripts/demo.sh --pull" >&2
    index=0
    for service in "${project_services[@]}"; do echo "      $service was ${before[$index]}" >&2; index=$((index + 1)); done
    exit 1
  fi
  for old in ${old_previous[@]+"${old_previous[@]}"}; do
    # The project's own displaced :previous images; refused (and ignored) while anything still uses one.
    if [ "$old" != none ]; then docker image rm "$old" >/dev/null 2>&1 || true; fi
  done
  # Unattended, a demonstration host fills its disk with superseded layers. Dangling images (no tag, so never a
  # :previous or a running service) and build cache older than a week are removed; tagged images, containers and
  # volumes are never touched. This is host-wide, so a host shared with other Docker projects uses --no-prune.
  if [ "$prune" = true ]; then
    docker image prune -f >/dev/null 2>&1 || echo "demo: image prune failed (ignored)." >&2
    docker builder prune -f --filter until=168h >/dev/null 2>&1 || true
  fi
  image_args=(--image-update "$outcome" --image-report "{$report}")
else
  docker compose ${profiles[@]+"${profiles[@]}"} up -d --build --wait
fi
if [ "$schedule" = true ]; then
  docker compose --profile demo-schedule up -d --build demo-scheduler
fi
docker compose exec -T ${exec_env[@]+"${exec_env[@]}"} backend python scripts/demo_setup.py --demo ${image_args[@]+"${image_args[@]}"} ${pass[@]+"${pass[@]}"}
echo "Demonstration ready: $DEMO_PUBLIC_URL (sign-in details are on the login page)."
if [ "$pull" = true ]; then
  for service in "${project_services[@]}"; do
    echo "  $service: $(image_id "$prefix-$service:$tag" | cut -c1-19)"
  done
fi
if [ "$DEMO_TLS_MODE" = internal ]; then
  echo "The certificate comes from the local authority; run scripts/demo.sh --trust-local-ca to trust it."
fi
