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
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${BACKEND_WORKERS:-4}" "$@"
