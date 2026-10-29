#!/bin/sh
# Backend container entrypoint.
#
# Runs uvicorn with BACKEND_WORKERS worker processes (default 4) so the API
# can use more than one CPU core; process-wide work is coordinated between
# workers by app/services/process_coordination.py (startup lock + leader
# election) and app/services/pubsub.py (Postgres LISTEN/NOTIFY).
#
# Prometheus multi-process mode: each worker writes its metrics to
# PROMETHEUS_MULTIPROC_DIR and /metrics aggregates them. The directory must
# be emptied on every container start, before any worker imports
# prometheus_client, or stale counts from a previous run would be summed in.
set -e
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus-multiproc}"
rm -rf "$PROMETHEUS_MULTIPROC_DIR"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
# Warn when the container's memory limit (cgroup v2, else v1) cannot hold the workers: about 1.2 GiB each (the heaviest request a worker has served stays in it) plus the
# parent (docs/deployment.md, "Sizing and memory limits"). The kernel would OOM-kill the backend under load, not at start.
workers="${BACKEND_WORKERS:-4}"
limit=""
for file in "${MEMORY_LIMIT_FILE:-/sys/fs/cgroup/memory.max}" /sys/fs/cgroup/memory/memory.limit_in_bytes; do
    [ -r "$file" ] && { limit=$(cat "$file"); break; }
done
case "$limit" in
    ''|*[!0-9]*) ;;  # no limit ("max") or unreadable
    *)
        needed=$(( workers * 1200 + 100 ))
        if [ $(( limit / 1048576 )) -lt "$needed" ]; then
            echo "WARNING: the memory limit is $(( limit / 1048576 )) MiB but $workers workers need about $needed MiB; lower BACKEND_WORKERS or raise BACKEND_MEM_LIMIT" >&2
        fi
        ;;
esac
# An empty value must mean "not set" (compose passes an empty string when an override is blank).
[ -n "${MALLOC_ARENA_MAX:-}" ] || unset MALLOC_ARENA_MAX
[ -n "${UVICORN_LIMIT_MAX_REQUESTS:-}" ] || unset UVICORN_LIMIT_MAX_REQUESTS
# `::` is dual-stack on Linux (accepts IPv4 and IPv6); 0.0.0.0 would be IPv4 only.
# One worker is served in-process, where uvicorn's `--host ::` ends up IPv6 only (asyncio sets IPV6_V6ONLY), so that
# case binds its own dual-stack socket (app/serve.py). Extra uvicorn arguments apply to the multi-worker path only.
if [ "${BACKEND_WORKERS:-4}" -le 1 ]; then
    exec python -m app.serve
fi
exec uvicorn app.main:app --host :: --port 8000 --workers "${BACKEND_WORKERS:-4}" "$@"
