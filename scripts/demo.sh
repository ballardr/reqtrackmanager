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
#
# HTTPS: the Caddy proxy (tests/container/caddy) is the only published listener. DEMO_PUBLIC_HOST (default localhost)
# names the host: a DNS name gets a certificate from a public authority (ports 80 and 443 must be reachable; the MCP
# server is served on mcp.<host>, or on DEMO_MCP_HOST, or not at all when DEMO_MCP_HOST=off); localhost or an IP address
# uses Caddy's local authority. DEMO_ACME_EMAIL registers a contact address with the public authority.
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
pass=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-metrics) metrics=false; shift ;;
    --clarity)
      [ $# -ge 2 ] || { echo "--clarity needs a project id" >&2; exit 2; }
      export DEMO_CLARITY_PROJECT_ID="$2"; shift 2 ;;
    --allow-uploads) export DEMO_ALLOW_UPLOADS=1; pass+=("$1"); shift ;;
    --schedule) schedule=true; shift ;;
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

profiles=()
if [ "$metrics" = true ]; then profiles+=(--profile demo-metrics); fi
docker compose ${profiles[@]+"${profiles[@]}"} up -d --build --wait
if [ "$schedule" = true ]; then
  docker compose --profile demo-schedule up -d --build demo-scheduler
fi
docker compose exec -T backend python scripts/demo_setup.py --demo ${pass[@]+"${pass[@]}"}
echo "Demonstration ready: $DEMO_PUBLIC_URL (sign-in details are on the login page)."
if [ "$DEMO_TLS_MODE" = internal ]; then
  echo "The certificate comes from the local authority; run scripts/demo.sh --trust-local-ca to trust it."
fi
