#!/bin/sh
# Entrypoint of the `profile` image target (never the production image).
#
# Starts the backend as docker-entrypoint.sh does, or, with PROFILE_MEMRAY=1, as ONE worker under memray so its heap is
# attributed to source lines (memray cannot follow uvicorn's spawned workers). The capture is finalised on SIGTERM, so stop
# it with `docker compose stop` and allow time. app.serve is the single-process entry the production entrypoint uses.
set -e
if [ "${PROFILE_MEMRAY:-}" != "1" ]; then
    exec ./docker-entrypoint.sh "$@"
fi
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus-multiproc}"
rm -rf "$PROMETHEUS_MULTIPROC_DIR"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR" "${PROFILE_OUTPUT_DIR:-/profile}"
exec memray run --force -o "${PROFILE_OUTPUT_DIR:-/profile}/heap.bin" -m app.serve
