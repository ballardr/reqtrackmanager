"""
Module: routers.health

Liveness/readiness endpoint used by container health checks (I-M-01) and the
Prometheus metrics endpoint (solution-architecture.md, I-M requirements).
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
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
    """Exposes Prometheus-formatted metrics for scraping (I-M requirements)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
