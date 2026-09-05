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
from app.modules.registry import get_module_registry, sync_module_role_definitions
from app.routers import (
    action_types,
    actions,
    auth,
    auth_oidc,
    change_requests,
    custom_fields,
    files,
    health,
    notifications,
    orgs,
    pats,
    projects,
    reports,
    requirements,
    reviews,
    scim,
    system,
    ws,
)
from app.services import pubsub
from app.services.bootstrap import run_bootstrap
from app.services.disk_monitor import run_disk_monitor_loop
from app.services.notifications import run_digest_loop
from app.services.scheduler import start_scheduler, stop_scheduler
from app.version import APP_VERSION

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Applies pending migrations, runs the server-admin bootstrap, syncs
    the module-contributed RBAC role registry mirror (module system
    Phase 2), captures the event loop for pub/sub, and starts the
    disk-usage monitor (I-M-11) — every process start self-heals the
    schema rather than requiring a manual migration step first."""
    run_migrations()
    pubsub.set_event_loop(asyncio.get_event_loop())
    db = SessionLocal()
    try:
        run_bootstrap(db)
        # Module system Phase 2: keeps `module_role_definitions` caught up
        # with whatever the live registry currently declares, the same
        # "self-heal at every process start" pattern `run_bootstrap` itself
        # follows. See `sync_module_role_definitions`'s own docstring for
        # why this never deletes a row for a module/role no longer
        # registered.
        sync_module_role_definitions(db)
    finally:
        db.close()
    disk_monitor_task = asyncio.create_task(run_disk_monitor_loop())
    digest_task = asyncio.create_task(run_digest_loop())
    start_scheduler()
    yield
    disk_monitor_task.cancel()
    digest_task.cancel()
    stop_scheduler()


app = FastAPI(
    title="ReqTrackManager API",
    description="Formal engineering requirements management system API (Ossa v1).",
    # Was hardcoded to a permanently-stale "1.0.0" (2026-08 UX audit
    # roadmap, "Fix the hardcoded FastAPI(version=...) OpenAPI metadata
    # constant") — now reads the same build-time version `app.version`
    # already exposes live at `GET /api/v1/system/version`, so
    # `/openapi.json`/`/docs` metadata tracks real releases instead of
    # being frozen at the value set when the app was first scaffolded.
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # X-Total-Count (U-P-06 pagination) and X-Total-Unfiltered-Count
    # (2026-08 UX audit roadmap: persistent "showing X of Y" result count,
    # `ResultCount`) are custom response headers, so they need to be
    # explicitly exposed — browsers hide non-safelisted response headers
    # from JS by default even with allow_headers="*" (that setting only
    # governs allowed *request* headers). Missing this for the new header
    # was caught only by a live Playwright run against a real browser
    # (`fetch().headers.get()` silently returning null) — curl and pytest's
    # TestClient both bypass CORS entirely, so neither could have caught it.
    expose_headers=["X-Total-Count", "X-Total-Unfiltered-Count"],
)


_SENSITIVE_FIELD_NAMES = {
    "password", "current_password", "new_password", "totp_secret", "code",
    "smtp_password", "oidc_client_secret",
}


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
async def security_headers_middleware(request: Request, call_next):
    """Adds baseline security response headers to every request (hardening
    review finding: none were set anywhere, and it wasn't a documented,
    deliberate deferral to a reverse-proxy layer either).

    Deliberately conservative: `X-Frame-Options`/`frame-ancestors` close
    clickjacking-style UI-redress against an authenticated session without
    touching what scripts/styles/fonts the app is allowed to load — a full
    `Content-Security-Policy` restricting *those* would need to be tuned
    against this specific SPA's actual script/style sources to avoid
    silently breaking it, so it's left as a documented follow-up
    (docs/deployment.md) rather than shipped unverified here.

    `frame-src` is the exception, added for the modular feature system's
    Tier B remote modules (compliance-module-plan.md Phase 3): unlike
    `frame-ancestors` (who may frame *this app* — always `'none'`), `frame-
    src` governs what *this app* may embed in its own `<ModuleFrame>`
    iframe, so it is built from `Settings.module_frame_allowed_origins`
    every request (cheap — `get_settings()` is `lru_cache`d) rather than
    hardcoded, and defaults to `'none'` (no origin allowlisted) exactly
    like every other module-system opt-in in this codebase (`ALLOW_
    EXTERNAL_MODULES`, `MCP_WRITES_ENABLED`).
    """
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    frame_src_origins = get_settings().module_frame_allowed_origin_list
    frame_src = " ".join(frame_src_origins) if frame_src_origins else "'none'"
    response.headers["Content-Security-Policy"] = f"frame-ancestors 'none'; frame-src {frame_src}"
    return response


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Records request count and latency for every HTTP request (I-M metrics).

    Labels with the matched route's *template* (`/api/v1/projects/{project_id}`),
    never the resolved request path — a request that matches no route (a
    genuine 404, or a CORS preflight `OPTIONS`, which `CORSMiddleware`
    short-circuits before FastAPI's router ever sets `request.scope["route"]`,
    even for a path that would otherwise have matched) has no template to
    label with and is bucketed under the fixed `path="unmatched"` instead of
    falling back to the raw path. Falling back to the raw path previously
    leaked real path parameters — project/org/requirement ids — as literal,
    unbounded-cardinality label values into the unauthenticated `/metrics`
    output on every preflight (one per non-simple cross-origin request the
    SPA makes), not just on genuine 404s.
    """
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    route = request.scope.get("route")
    path = route.path if route else "unmatched"
    http_requests_total.labels(method=request.method, path=path, status_code=response.status_code).inc()
    http_request_duration_seconds.labels(method=request.method, path=path).observe(duration)
    return response


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(auth_oidc.router)
app.include_router(orgs.router)
app.include_router(projects.router)
app.include_router(requirements.router)
app.include_router(change_requests.router)
app.include_router(reports.router)
app.include_router(files.router)
app.include_router(custom_fields.router)
app.include_router(action_types.router)
app.include_router(actions.router)
app.include_router(notifications.router)
app.include_router(reviews.router)
app.include_router(pats.router)
app.include_router(system.router)
app.include_router(scim.router)
if settings.websocket_enabled:
    # I-A-04: the WebSocket interface is optional — deployments that can't
    # or don't want persistent socket connections can disable it entirely
    # via WEBSOCKET_ENABLED=false rather than it always being mounted.
    app.include_router(ws.router)

# --- Module system (compliance-module-plan.md Phase 1) ---------------------
# Mounts every registered module's own router(s), if it has any. Building the
# registry here (via `get_module_registry`, which internally caches) is
# also what produces this run's "every loaded module logged at startup"
# operational record (see `app.modules.registry`'s module docstring) — no
# separate lifespan-hook logging is needed for that. A module contributes up
# to two routers — `get_router()` (org-scoped, `/api/v1/orgs/
# {organization_id}/modules/<key>/...`) and, since Phase 7, an optional
# `get_project_router()` (project-scoped, `/api/v1/projects/{project_id}/
# modules/<key>/...`) — both mounted the same way here. A module's own
# router(s) apply their own `require_org_module_enabled`/`require_project_
# module_enabled`/`require_module_role` gating internally; there is no
# second gate applied at this mount-loop level.
for _module_definition in get_module_registry().values():
    for _module_router in (
        _module_definition.get_router(),
        _module_definition.get_project_router() if _module_definition.get_project_router is not None else None,
    ):
        if _module_router is not None:
            app.include_router(_module_router)
