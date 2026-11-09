#!/usr/bin/env bash
# Sets the local stack (tests/container) up as a demonstration: starts it, waits for it to be healthy, then seeds
# every demonstration project and posts the sign-in details message (backend/scripts/demo_setup.py).
#
#   scripts/demo.sh                      start, seed (a second run changes nothing)
#   scripts/demo.sh --reset              remove the demonstration organisation and seed again
#   scripts/demo.sh --teardown           remove the demonstration organisation and its messages
#   scripts/demo.sh --rotate-passwords   a new random password for every account (default: DemoDemo123!)
#   scripts/demo.sh --clarity <id>       also load Microsoft Clarity (project id from your Clarity dashboard)
#   scripts/demo.sh --schedule           also start the daily reset (DEMO_RESET_AT, DEMO_RESET_TZ; default 00:00 UTC)
#   scripts/demo.sh --no-metrics         do not start the usage-metrics Prometheus (started by default)
#   scripts/demo.sh --export-metrics [path] [--since 7d] [--no-snapshot]
#                                        write a metrics bundle (.tar.gz) for a developer to review; starts nothing
#   scripts/demo.sh --view-metrics <bundle>   open a bundle in a throwaway Prometheus on 127.0.0.1:9091
#   scripts/demo.sh --purge-metrics      stop Prometheus and remove the collected metrics (a reset keeps them)
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

schedule=false
metrics=true
pass=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-metrics) metrics=false; shift ;;
    --clarity)
      [ $# -ge 2 ] || { echo "--clarity needs a project id" >&2; exit 2; }
      export DEMO_CLARITY_PROJECT_ID="$2"; shift 2 ;;
    --schedule) schedule=true; shift ;;
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
echo "Demonstration ready: http://localhost:3000 (sign-in details are on the login page)."
