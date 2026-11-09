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
#
# Any other option is passed to demo_setup.py (for example --confirm-database reqtrack_test, --no-login-message).
# The command refuses a database that holds an organisation it did not create; see docs/development.md.
set -euo pipefail

cd "$(dirname "$0")/../tests/container"

schedule=false
pass=()
while [ $# -gt 0 ]; do
  case "$1" in
    --clarity)
      [ $# -ge 2 ] || { echo "--clarity needs a project id" >&2; exit 2; }
      export DEMO_CLARITY_PROJECT_ID="$2"; shift 2 ;;
    --schedule) schedule=true; shift ;;
    *) pass+=("$1"); shift ;;
  esac
done

docker compose up -d --build --wait
if [ "$schedule" = true ]; then
  docker compose --profile demo-schedule up -d --build demo-scheduler
fi
docker compose exec -T backend python scripts/demo_setup.py --demo ${pass[@]+"${pass[@]}"}
echo "Demonstration ready: http://localhost:3000 (sign-in details are on the login page)."
