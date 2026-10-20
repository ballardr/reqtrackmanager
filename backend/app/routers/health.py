"""
Module: routers.health

Liveness/readiness endpoint used by container health checks (I-M-01) and the
Prometheus metrics endpoint (solution-architecture.md, I-M requirements).

`/health` answers HTTP 503 (same JSON body) when the database cannot be
reached, because container probes (`curl -f`) and load balancers only look at
the status code. The database probe is time-bounded so a hung database fails
the check instead of hanging it.
"""

import os

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess
from sqlalchemy import text

from app.database import engine

router = APIRouter(tags=["health"])

# Upper bound for the database probe's query; connecting is bounded separately
# by the engine's `connect_timeout`.
HEALTH_DB_TIMEOUT_MS = 3000


@router.get("/health")
def health() -> JSONResponse:
    """Returns service and database health status.

    Returns:
        HTTP 200 with `{"status": "ok", "database": "ok"}` when the database
        answers within `HEALTH_DB_TIMEOUT_MS`; otherwise HTTP 503 with
        `{"status": "degraded", "database": "unreachable"}`.
    """
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = {HEALTH_DB_TIMEOUT_MS}"))
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "unreachable"},
    )


@router.get("/metrics")
def metrics() -> Response:
    """Exposes Prometheus-formatted metrics for scraping (I-M requirements).

    With several worker processes (`BACKEND_WORKERS`) each worker counts
    separately, so when `PROMETHEUS_MULTIPROC_DIR` is set (the container
    entrypoint sets it) the response aggregates every worker's files —
    `prometheus_client`'s documented multi-process mode. Without it (single
    process, tests) the default registry is used as before.
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
