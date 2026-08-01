"""
Module: main

FastAPI application entrypoint. Wires together CORS, request metrics
middleware, router registration, and startup tasks (server-admin bootstrap,
capturing the event loop for the WebSocket pub/sub hub).

External dependencies: FastAPI, Starlette, Prometheus client.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import SessionLocal
from app.metrics import http_request_duration_seconds, http_requests_total
from app.migrations import run_migrations
from app.routers import (
    auth,
    change_requests,
    custom_fields,
    files,
    health,
    notifications,
    orgs,
    projects,
    reports,
    requirements,
    ws,
)
from app.services import pubsub
from app.services.bootstrap import run_bootstrap
from app.services.disk_monitor import run_disk_monitor_loop
from app.services.notifications import run_digest_loop

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Applies pending migrations, runs the server-admin bootstrap, captures
    the event loop for pub/sub, and starts the disk-usage monitor (I-M-11)
    — every process start self-heals the schema rather than requiring a
    manual migration step first."""
    run_migrations()
    pubsub.set_event_loop(asyncio.get_event_loop())
    db = SessionLocal()
    try:
        run_bootstrap(db)
    finally:
        db.close()
    disk_monitor_task = asyncio.create_task(run_disk_monitor_loop())
    digest_task = asyncio.create_task(run_digest_loop())
    yield
    disk_monitor_task.cancel()
    digest_task.cancel()


app = FastAPI(
    title="ReqTrackManager API",
    description="Formal engineering requirements management system API (Ossa v1).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_SENSITIVE_FIELD_NAMES = {"password", "current_password", "new_password", "totp_secret", "code"}


@app.exception_handler(RequestValidationError)
async def redact_sensitive_validation_errors(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Overrides FastAPI's default 422 handler to strip the submitted value
    out of validation errors on password/secret fields.

    Pydantic v2's `ValidationError.errors()` includes the raw `input` that
    failed validation (e.g. so a client can show "you typed X, expected Y").
    For most fields that's useful; for a password field it means a request
    that fails a constraint like `new_password`'s `min_length=8` would echo
    the attempted password back in the response body. FastAPI's default
    handler passes `exc.errors()` straight through, so this must be
    overridden rather than fixed at the schema level (Pydantic does not
    otherwise redact `input` for plain `str` fields).
    """
    errors = []
    for error in exc.errors():
        error = dict(error)
        loc = error.get("loc", ())
        if any(str(part) in _SENSITIVE_FIELD_NAMES for part in loc):
            error["input"] = "***"
        errors.append(error)
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": jsonable_encoder(errors)})


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Records request count and latency for every HTTP request (I-M metrics)."""
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    path = request.scope.get("route").path if request.scope.get("route") else request.url.path
    http_requests_total.labels(method=request.method, path=path, status_code=response.status_code).inc()
    http_request_duration_seconds.labels(method=request.method, path=path).observe(duration)
    return response


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(orgs.router)
app.include_router(projects.router)
app.include_router(requirements.router)
app.include_router(change_requests.router)
app.include_router(reports.router)
app.include_router(files.router)
app.include_router(custom_fields.router)
app.include_router(notifications.router)
app.include_router(ws.router)
