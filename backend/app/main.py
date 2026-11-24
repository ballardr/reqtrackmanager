"""
Module: main

FastAPI application entrypoint. Wires together CORS, request metrics
middleware, router registration, and startup tasks (server-admin bootstrap,
capturing the event loop for the WebSocket pub/sub hub).

External dependencies: FastAPI, Starlette, Prometheus client.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import profiling
from app.body_limit import BodySizeLimitMiddleware
from app.concurrency_limit import ConcurrencyLimitMiddleware
from app.config import get_settings
from app.database import SessionLocal, engine
from app.deps import INVALID_TOKEN_CODE, InvalidTokenError
from app.metrics import http_request_duration_seconds, http_requests_total, run_worker_gauge_loop
from app.migrations import run_migrations
from app.modules.registry import get_module_registry, sync_module_role_definitions
from app.routers import (
    action_types,
    actions,
    announcements,
    artefact_links,
    auth,
    auth_oidc,
    change_requests,
    code_prefixes,
    custom_fields,
    custom_reports,
    external_references,
    external_systems,
    files,
    health,
    lifecycles,
    nav_labels,
    notifications,
    org_dashboards,
    org_record_tables,
    orgs,
    overview_widgets,
    pats,
    placements,
    policies,
    project_link_types,
    projects,
    record_comments,
    record_list_report,
    record_tables,
    report_catalogue,
    report_copy,
    report_duplicate,
    report_exchange,
    report_file_names,
    report_folders,
    report_images,
    report_layouts,
    report_packs,
    report_placements,
    report_snippets,
    reports,
    requirement_aliases,
    requirements,
    reviews,
    scim,
    search,
    stage_workflows,
    system,
    tags,
    ws,
)
from app.services import markdown_fields, pubsub, report_font_catalogue, secret_keys
from app.services.bootstrap import run_bootstrap
from app.services.client_date import reset_client_date, set_client_date
from app.services.disk_monitor import run_disk_monitor_loop
from app.services.module_defaults import seed_fresh_install_defaults
from app.services.notifications import run_digest_loop
from app.services.process_coordination import run_leadership_loop, startup_lock
from app.services.report_run_jobs import run_job_loop
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.scoring import sync_scoring_levels
from app.services.storage_health import run_storage_health_loop
from app.services.template_guard import enforce_template_read_only
from app.version import APP_VERSION

settings = get_settings()
logger = logging.getLogger(__name__)


def _check_secrets() -> None:
    """Warns about placeholder/weak secrets at start, and refuses to start when `REQUIRE_STRONG_SECRETS` is on.

    Raises:
        RuntimeError: If `Settings.require_strong_secrets` is set and any secret is still a placeholder or
            too short (the message names the setting, never its value).
    """
    problems = settings.weak_secret_problems()
    if not problems:
        return
    if settings.require_strong_secrets:
        raise RuntimeError("Refusing to start with weak secrets: " + "; ".join(problems) + ".")
    logger.warning("Weak or placeholder secrets in use (acceptable only for local development): %s.", "; ".join(problems))


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Per worker process: applies pending migrations, runs the server-admin
    bootstrap and the registry syncs (serialised across workers by
    `startup_lock`), captures the event loop and starts the cross-process
    pub/sub listener, then joins leader election — only the elected leader
    runs the singleton background work (scheduled jobs, digest emails, the
    disk-usage monitor, I-M-11), so several workers (`BACKEND_WORKERS`) never
    duplicate it. Every process start self-heals the schema rather than
    requiring a manual migration step first."""
    _check_secrets()
    with startup_lock():
        run_migrations()
        db = SessionLocal()
        try:
            # Before the bootstrap: a database with no server settings yet is a fresh install,
            # and gets every module available (`seed_fresh_install_defaults`).
            seed_fresh_install_defaults(db)
            run_bootstrap(db)
            # Keeps `module_role_definitions` in step with the live registry at every start; it never
            # deletes a row for a module or role no longer registered (see `sync_module_role_definitions`).
            sync_module_role_definitions(db)
            # Seeds every org's missing scoring-axis levels
            # from the registry, so a module installed after orgs exist still
            # gets its levels (see `sync_scoring_levels`).
            sync_scoring_levels(db)
            # Logs an unreadable stored secret at start, so a wrong or lost encryption key shows before it locks users out.
            secret_keys.warn_if_unreadable(db)
        finally:
            db.close()
    pubsub.set_event_loop(asyncio.get_event_loop())
    if settings.websocket_enabled:
        pubsub.start_listener()

    singleton_tasks: list[asyncio.Task] = []

    def start_singletons() -> None:
        singleton_tasks.extend([
            asyncio.create_task(run_disk_monitor_loop()),
            asyncio.create_task(run_storage_health_loop()),
            asyncio.create_task(run_digest_loop()),
            asyncio.create_task(run_job_loop()),
        ])
        start_scheduler()

    def stop_singletons() -> None:
        for task in singleton_tasks:
            task.cancel()
        singleton_tasks.clear()
        stop_scheduler()

    try:  # a bad font directory must never stop the server: the scan itself skips what it cannot read
        report_font_catalogue.rescan()
    except Exception:  # noqa: BLE001
        logger.exception("report font scan failed")
    leadership_task = asyncio.create_task(run_leadership_loop(start_singletons, stop_singletons))
    # Per worker (not leader-only): each process reports its own memory and pool usage.
    worker_gauge_task = asyncio.create_task(run_worker_gauge_loop(engine))
    profile_task = None
    if settings.profile_mode:
        logger.warning("profile mode is on: per-route database statistics are written to %s", settings.profile_output_dir)
        profile_task = asyncio.create_task(profiling.run_profile_loop(
            Path(settings.profile_output_dir), tracemalloc_enabled=settings.profile_tracemalloc, baseline_seconds=settings.profile_baseline_seconds,
        ))
    yield
    if profile_task is not None:
        profile_task.cancel()
    worker_gauge_task.cancel()
    leadership_task.cancel()
    stop_singletons()
    pubsub.stop_listener()


markdown_fields.install()

app = FastAPI(
    title="ReqTrackManager API",
    description="Formal engineering requirements management system API (Ossa v1).",
    # The build-time version `app.version` exposes at `GET /api/v1/system/version`, so `/openapi.json`
    # and `/docs` track real releases.
    version=APP_VERSION,
    lifespan=lifespan,
    dependencies=[Depends(enforce_template_read_only)],
)

# Added before CORS so it ends up inside it (middleware added last runs first): a 413 still carries the CORS
# headers the browser needs to read it. The concurrency limit is innermost, so a refused (503) request still
# carries them too and only requests that pass the body check wait for a slot.
app.add_middleware(ConcurrencyLimitMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Browsers hide non-safelisted response headers from JS unless exposed (`allow_headers` governs only
    # request headers); only a real browser shows a missing one, as curl and TestClient bypass CORS.
    # X-Total-Count (U-P-06 pagination) and X-Total-Unfiltered-Count carry list totals.
    # `Content-Disposition` carries the server's file name for a generated file (a pack's zip name template).
    # `WWW-Authenticate` lets the client tell a dead session (invalid or expired token) from a business 401
    # such as a wrong current password. `X-Projects-Truncated` marks a project list that was cut short.
    expose_headers=[
        "X-Total-Count",
        "X-Total-Unfiltered-Count",
        "X-Can-Include-Unjoined",
        "X-Projects-Truncated",
        "Content-Disposition",
        "WWW-Authenticate",
    ],
)


_SENSITIVE_FIELD_NAMES = {
    "password", "current_password", "new_password", "totp_secret", "code",
    "smtp_password", "oidc_client_secret",
}


@app.exception_handler(RequestValidationError)
async def redact_sensitive_validation_errors(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Replaces FastAPI's 422 handler to strip the submitted value from validation errors on
    password/secret fields.

    Pydantic's `errors()` includes the raw `input`, so a failed `new_password` constraint would echo the
    attempted password in the response; Pydantic does not redact plain `str` fields, so this is handled
    here. Also stringifies a non-finite float `input`, which would otherwise crash JSON encoding.
    """
    errors = []
    for error in exc.errors():
        error = dict(error)
        loc = error.get("loc", ())
        if any(str(part) in _SENSITIVE_FIELD_NAMES for part in loc):
            error["input"] = "***"
        elif isinstance(error.get("input"), float) and not math.isfinite(error["input"]):
            # `inf`/`nan` cannot be JSON-encoded; echoing one would turn a rejected value into a 500.
            error["input"] = str(error["input"])
        errors.append(error)
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": jsonable_encoder(errors)})


@app.exception_handler(InvalidTokenError)
async def invalid_token_response(request: Request, exc: InvalidTokenError) -> JSONResponse:
    """Answers a dead-token 401 with the usual `detail` text plus the stable `code` the client reads as "session over".

    Args:
        request: The refused request (unused; every cause answers identically).
        exc: The shared invalid-token exception from `app.deps`.

    Returns:
        A 401 response with `WWW-Authenticate: Bearer` and the body `{"detail": ..., "code": "invalid_token"}`.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": INVALID_TOKEN_CODE},
        headers=exc.headers,
    )


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Adds baseline security response headers to every request.

    Conservative: `X-Frame-Options`/`frame-ancestors` prevent clickjacking against an authenticated
    session without restricting the scripts, styles and fonts the app loads. A full
    `Content-Security-Policy` for those would need tuning against this SPA's actual sources, so it is a
    documented follow-up (docs/deployment.md).

    `frame-src` is the exception, for Tier B remote modules: it governs what this app may embed in its
    `<ModuleFrame>` iframe (unlike `frame-ancestors`, which is always `'none'`). It is built per request
    from `Settings.module_frame_allowed_origins` (`get_settings()` is `lru_cache`d) and defaults to
    `'none'`, like every module-system opt-in (`ALLOW_EXTERNAL_MODULES`, `MCP_WRITES_ENABLED`).

    A route that serves user-supplied markup (a symbol's SVG) sets its own, stricter
    `Content-Security-Policy`, which is kept; it must carry `frame-ancestors 'none'` itself.
    """
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    frame_src_origins = get_settings().module_frame_allowed_origin_list
    frame_src = " ".join(frame_src_origins) if frame_src_origins else "'none'"
    if "content-security-policy" not in response.headers:
        response.headers["Content-Security-Policy"] = f"frame-ancestors 'none'; frame-src {frame_src}"
    # An answer for a signed-in person is not kept by a shared cache or the browser's disk cache. Only JSON, and only
    # when the route set no policy of its own: file downloads and health probes choose theirs.
    if "cache-control" not in response.headers and response.headers.get("content-type", "").startswith("application/json"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def client_date_middleware(request: Request, call_next):
    """Records the caller's calendar day (`X-Client-Date`) for rules about whether a date has happened yet.

    See `services.client_date`: the value is validated for plausibility and only affects derived,
    display-level dates, so an absent or bad header just means the UTC day is used.
    """
    token = set_client_date(request.headers.get("x-client-date"))
    try:
        return await call_next(request)
    finally:
        reset_client_date(token)


#: The HTTP methods the metrics label by name; any other request method is recorded as `OTHER`.
_METRIC_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Records request count and latency for every HTTP request (I-M metrics).

    Labels with the matched route's template (`/api/v1/projects/{project_id}`), never the resolved
    path. A request that matches no route (a 404, or a CORS preflight `OPTIONS`, which `CORSMiddleware`
    short-circuits before the router sets `request.scope["route"]`) is bucketed under `path="unmatched"`;
    the raw path would expose real ids as unbounded-cardinality labels on the unauthenticated `/metrics`.
    """
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    route = request.scope.get("route")
    path = route.path if route else "unmatched"
    # The method is client-supplied and HTTP lets it be any token, so an unrecognised one is bucketed:
    # otherwise anyone could mint a new time series per request on the unauthenticated /metrics output.
    method = request.method if request.method in _METRIC_METHODS else "OTHER"
    http_requests_total.labels(method=method, path=path, status_code=response.status_code).inc()
    http_request_duration_seconds.labels(method=method, path=path).observe(duration)
    return response


if settings.profile_mode:
    # Developer profiling only (app.profiling): outermost, so it sees every request. Never set by the production Compose file.
    app.middleware("http")(profiling.profile_middleware)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(auth_oidc.router)
app.include_router(orgs.router)
app.include_router(projects.router)
app.include_router(requirements.router)
app.include_router(change_requests.router)
app.include_router(reports.router)
app.include_router(report_catalogue.router)
app.include_router(report_images.org_router)
app.include_router(report_images.project_router)
app.include_router(report_layouts.org_router)
app.include_router(report_layouts.project_router)
app.include_router(report_packs.org_router)
app.include_router(report_packs.project_router)
app.include_router(report_snippets.org_router)
app.include_router(report_snippets.project_router)
app.include_router(report_file_names.router)
app.include_router(report_copy.router)
app.include_router(report_duplicate.project_router)
app.include_router(report_duplicate.org_router)
app.include_router(report_exchange.project_router)
app.include_router(report_exchange.org_router)
app.include_router(report_folders.org_router)
app.include_router(report_folders.project_router)
app.include_router(report_placements.org_router)
app.include_router(report_placements.project_router)
app.include_router(custom_reports.org_router)
app.include_router(custom_reports.project_router)
app.include_router(custom_reports.runs_router)
app.include_router(search.router)
app.include_router(record_tables.router)
app.include_router(record_comments.router)
app.include_router(org_record_tables.router)
app.include_router(record_list_report.router)
app.include_router(files.router)
app.include_router(custom_fields.router)
app.include_router(action_types.router)
app.include_router(actions.router)
app.include_router(artefact_links.router)
app.include_router(placements.router)
app.include_router(lifecycles.org_router)
app.include_router(lifecycles.project_router)
app.include_router(requirement_aliases.org_router)
app.include_router(requirement_aliases.project_router)
app.include_router(code_prefixes.org_router)
app.include_router(code_prefixes.project_router)
app.include_router(external_systems.org_router)
app.include_router(external_systems.project_router)
app.include_router(external_references.router)
app.include_router(external_references.project_router)
app.include_router(stage_workflows.org_router)
app.include_router(stage_workflows.project_router)
app.include_router(announcements.system_router)
app.include_router(announcements.org_router)
app.include_router(announcements.reader_router)
app.include_router(policies.system_router)
app.include_router(policies.org_router)
app.include_router(policies.member_router)
app.include_router(policies.public_router)
app.include_router(nav_labels.router)
app.include_router(nav_labels.org_router)
app.include_router(org_dashboards.router)
app.include_router(overview_widgets.router)
app.include_router(overview_widgets.org_router)
app.include_router(tags.router)
app.include_router(tags.org_router)
app.include_router(project_link_types.router)
app.include_router(notifications.router)
app.include_router(reviews.router)
app.include_router(pats.router)
app.include_router(system.router)
app.include_router(scim.router)
if settings.websocket_enabled:
    # I-A-04: the WebSocket interface is optional; WEBSOCKET_ENABLED=false disables it entirely.
    app.include_router(ws.router)

# --- Module system ---------------------
# Mounts every registered module's router(s). Building the registry (`get_module_registry`, cached) also
# logs every loaded module at startup (see `app.modules.registry`). A module contributes up to three routers:
# `get_router()` (org-scoped, `/api/v1/orgs/{organization_id}/modules/<key>/...`), an optional
# `get_project_router()` (`/api/v1/projects/{project_id}/modules/<key>/...`) and an optional
# `get_global_router()` (`/api/v1/<key>/...`, for an endpoint that aggregates across the caller's orgs or
# resolves its own org from another id, such as compliance's `nav-visibility` or `standards/{standard_id}`).
# Each router applies its own `require_org_module_enabled`/`require_project_module_enabled`/
# `require_module_role`/`require_org_access_and_module_enabled` gating; the mount loop adds no second gate.
for _module_definition in get_module_registry().values():
    for _module_router in (
        _module_definition.get_router(),
        _module_definition.get_project_router() if _module_definition.get_project_router is not None else None,
        _module_definition.get_global_router() if _module_definition.get_global_router is not None else None,
    ):
        if _module_router is not None:
            app.include_router(_module_router)
