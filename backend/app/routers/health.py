"""
Module: routers.health

Liveness/readiness endpoint used by container health checks (I-M-01) and the
Prometheus metrics endpoint (solution-architecture.md, I-M requirements).
"""

import os

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess
from sqlalchemy import text

from app.database import engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Returns service and database health status.

    Returns:
        A dict with overall status and a database connectivity check.
    """
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "unreachable"}


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
