#!/bin/sh
# Entrypoint of the `profile` image target (never the production image).
#
# Starts the backend exactly as docker-entrypoint.sh does, or, with PROFILE_MEMRAY=1, as ONE worker under memray so
# its heap can be attributed to source lines. memray cannot follow uvicorn's spawned workers, and one in-process
# worker is what answers "what does a worker hold"; the capture is finalised when the container is stopped
# (SIGTERM, which uvicorn handles); app.serve is the single-process entry the production entrypoint uses for one worker, so stop it with `docker compose stop` and give it time.
set -e
if [ "${PROFILE_MEMRAY:-}" != "1" ]; then
    exec ./docker-entrypoint.sh "$@"
fi
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus-multiproc}"
rm -rf "$PROMETHEUS_MULTIPROC_DIR"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR" "${PROFILE_OUTPUT_DIR:-/profile}"
exec memray run --force -o "${PROFILE_OUTPUT_DIR:-/profile}/heap.bin" -m app.serve
