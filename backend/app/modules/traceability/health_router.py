"""
Module: modules.traceability.health_router

API of governance health, in two route groups the module's organisation and project routers include:
`org_routes` (the organisation's default way of keeping health) and `project_routes` (a project's health, its settings and
Refresh now).

Design decisions:
- Reading a project's health is open to every member of a project the `governance_health` part is on for; the figures are
  then reduced to the record types the caller may read (`health.restrict_to_viewer`). Changing settings and refreshing need
  `manage_project_governance` with no server-administrator bypass, because a refresh runs checks and writes a snapshot.
- Refresh now is refused (409) in `on_demand`, where nothing is stored, and while another refresh of the project runs.
- A read that serves `snapshot_on_change` may recompute the snapshot, so it commits.
- Organisation routes need `manage_org_governance`, as every organisation policy route of the module.

Dependencies: `modules.traceability.health`, `services.rbac` (gates), `services.client_date` (the caller's day).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.traceability import health
from app.modules.traceability._shared import (
    GOVERNANCE_HEALTH,
    MANAGE_ORG_GOVERNANCE,
    MANAGE_PROJECT_GOVERNANCE,
    TRACEABILITY_MODULE_KEY,
)
from app.modules.traceability.enums import HEALTH_INTERVAL_HOURS
from app.modules.traceability.schemas import (
    HealthCategoryOut,
    HealthCheckOut,
    HealthChecksOut,
    HealthCheckTypeOut,
    HealthDefaultIn,
    HealthDefaultOut,
    HealthOut,
    HealthReviewOut,
    HealthRunnerOut,
    HealthSettingsIn,
    HealthSettingsOut,
)
from app.services.client_date import effective_today
from app.services.lookups import project_or_404
from app.services.rbac import (
    get_effective_permissions,
    permission_satisfied,
    require_org_module_enabled,
    require_org_subcomponent_enabled,
    require_permission,
    require_project_subcomponent_enabled,
)

org_routes = APIRouter()
project_routes = APIRouter()

_org_module_on = require_org_module_enabled(TRACEABILITY_MODULE_KEY)
_org_manage = require_permission(MANAGE_ORG_GOVERNANCE, server_admin_bypass=False)
_org_guards = [Depends(_org_module_on), Depends(require_org_subcomponent_enabled(TRACEABILITY_MODULE_KEY, GOVERNANCE_HEALTH))]
_health_view = require_project_subcomponent_enabled(TRACEABILITY_MODULE_KEY, GOVERNANCE_HEALTH)
_manage = require_permission(MANAGE_PROJECT_GOVERNANCE, server_admin_bypass=False)


def _percent(done: int, total: int) -> int | None:
    """The share `done` of `total` as a whole percentage rounded down, `None` when there is nothing to count."""
    return None if total == 0 else done * 100 // total


def _runner_out(db: Session, user_id: UUID | None) -> HealthRunnerOut | None:
    """The person who runs, or ran, the baseline checks, by display name; `None` when there is none."""
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return None if user is None else HealthRunnerOut(id=user.id, name=user.display_name)


def _can_manage(db: Session, project: Project, user: User) -> bool:
    return permission_satisfied(get_effective_permissions(db, user.id, project_id=project.id), MANAGE_PROJECT_GOVERNANCE)


def _view_out(
    db: Session, project: Project, user: User, settings: health.EffectiveSettings, view: health.HealthView,
) -> HealthOut:
    """A health view as the API shape."""
    checks = view.checks
    return HealthOut(
        mode=settings.mode, source=view.source, computed_at=view.computed_at, stale=view.stale,
        can_refresh=settings.mode.is_snapshot and _can_manage(db, project, user),
        categories=[
            HealthCategoryOut(
                key=c.key, label=c.label, artefact_type=c.artefact_type, kind=c.kind, total=c.total, done=c.done,
                outstanding=c.outstanding, percent=c.percent,
            )
            for c in view.categories
        ],
        reviews=[HealthReviewOut(artefact_type=r.artefact_type, label=r.label, due=r.due) for r in view.reviews],
        checks=HealthChecksOut(
            status=checks.status,
            run_by=None if view.source == "live" else _runner_out(db, view.checks_run_by_id),
            run_at=view.checks_run_at,
            checks=[
                HealthCheckOut(
                    key=c.key, name=c.name,
                    types=[
                        HealthCheckTypeOut(
                            artefact_type=t.artefact_type, checked=t.checked, failing=t.failing,
                            percent_passing=_percent(t.checked - t.failing, t.checked),
                        )
                        for t in c.types
                    ],
                )
                for c in checks.checks
            ],
        ),
    )


def _settings_out(db: Session, project: Project, user: User) -> HealthSettingsOut:
    """A project's health settings as the API shape."""
    settings = health.effective_settings(db, project)
    org_mode, org_interval = health.organization_default(db, project.organization_id)
    return HealthSettingsOut(
        can_manage=_can_manage(db, project, user), mode=settings.mode, mode_source=settings.mode_source,
        interval_hours=settings.interval_hours, interval_source=settings.interval_source, own_mode=settings.own_mode,
        own_interval_hours=settings.own_interval_hours, organization_mode=org_mode, organization_interval_hours=org_interval,
        checks_runner=_runner_out(db, settings.checks_runner_id),
        runner_problem=health.runner_problem(db, project, settings.checks_runner_id),
        interval_options=list(HEALTH_INTERVAL_HOURS), on_demand_record_limit=health.ON_DEMAND_GUIDANCE_RECORDS,
        checks_enabled=health.checks_enabled(db, project),
    )


@project_routes.get("/health", response_model=HealthOut)
def get_project_health(
    project_id: UUID, current_user: User = Depends(_health_view), db: Session = Depends(get_db),
) -> HealthOut:
    """The project's governance health: live for the caller in `on_demand`, else the stored snapshot (refreshed first when
    `snapshot_on_change` finds it stale). Only the record types the caller may read are included."""
    project = project_or_404(db, project_id)
    settings = health.effective_settings(db, project)
    view = health.build_view(db, project, current_user, settings, today=effective_today())
    db.commit()
    return _view_out(db, project, current_user, settings, view)


@project_routes.post("/health/refresh", response_model=HealthOut, dependencies=[Depends(_health_view)])
def refresh_project_health(
    project_id: UUID, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> HealthOut:
    """Recomputes the stored snapshot now. The baseline checks run as the configured runner, else as the caller.

    Raises:
        HTTPException: 409 in `on_demand` (nothing is stored) or while another refresh of the project is running.
    """
    project = project_or_404(db, project_id)
    settings = health.effective_settings(db, project)
    if not settings.mode.is_snapshot:
        raise HTTPException(status.HTTP_409_CONFLICT, "Governance health is computed on demand for this project; there is no snapshot to refresh.")
    if health.refresh_snapshot(db, project, actor=current_user) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A refresh of this project's governance health is already running.")
    health.record_manual_refresh(db, project, current_user)
    db.commit()
    view = health.build_view(db, project, current_user, settings, today=effective_today())
    return _view_out(db, project, current_user, settings, view)


@project_routes.get("/health/settings", response_model=HealthSettingsOut)
def get_project_health_settings(
    project_id: UUID, current_user: User = Depends(_health_view), db: Session = Depends(get_db),
) -> HealthSettingsOut:
    """How the project's health is kept (mode, interval and baseline check runner) and where each value comes from."""
    return _settings_out(db, project_or_404(db, project_id), current_user)


@project_routes.put("/health/settings", response_model=HealthSettingsOut, dependencies=[Depends(_health_view)])
def set_project_health_settings(
    project_id: UUID, payload: HealthSettingsIn, current_user: User = Depends(_manage), db: Session = Depends(get_db),
) -> HealthSettingsOut:
    """Sets the project's own mode, interval and baseline check runner (`null` follows the organisation's default)."""
    project = project_or_404(db, project_id)
    health.set_project_settings(
        db, project=project, mode=payload.mode, interval_hours=payload.interval_hours,
        checks_runner_id=payload.checks_runner_id, actor_id=current_user.id,
    )
    db.commit()
    return _settings_out(db, project, current_user)


def _org_or_404(db: Session, organization_id: UUID) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return org


def _default_out(db: Session, organization_id: UUID) -> HealthDefaultOut:
    mode, interval = health.organization_default(db, organization_id)
    return HealthDefaultOut(mode=mode, interval_hours=interval, interval_options=list(HEALTH_INTERVAL_HOURS))


@org_routes.get("/health-defaults", response_model=HealthDefaultOut, dependencies=_org_guards)
def get_health_default(
    organization_id: UUID, current_user: User = Depends(_org_manage), db: Session = Depends(get_db),
) -> HealthDefaultOut:
    """The organisation's default way of keeping governance health (on demand and daily when none is set)."""
    _org_or_404(db, organization_id)
    return _default_out(db, organization_id)


@org_routes.put("/health-defaults", response_model=HealthDefaultOut, dependencies=_org_guards)
def set_health_default(
    organization_id: UUID, payload: HealthDefaultIn, current_user: User = Depends(_org_manage), db: Session = Depends(get_db),
) -> HealthDefaultOut:
    """Sets the default mode and snapshot interval of every project that sets none of its own."""
    health.set_organization_default(
        db, organization=_org_or_404(db, organization_id), mode=payload.mode, interval_hours=payload.interval_hours,
        actor_id=current_user.id,
    )
    db.commit()
    return _default_out(db, organization_id)

