"""
Module: modules.traceability.health

Governance health: how far a project has got against its own configured policy, as figures per record category, reviews
due and the results of the baseline checks the project enables. Served live for each viewer (on demand) or from a stored
snapshot that is refreshed at an interval or after the project's records change.

Responsibilities:
- Settings: the organisation's default mode and a project's own mode, interval and baseline-check runner, resolved to one
  effective answer that names where each value comes from (`effective_settings`).
- Figures (`compute_figures`): one `HealthMeasure` per registered `HealthProvider` in effect (share complete or count
  outstanding), and the reviews due or overdue per type with a review schedule.
- Checks (`compute_checks`): the project's enabled baseline checks run as one person over the records as they stand
  (`services.baseline.evaluate_checks`), reduced to records checked and records failing per check and type. Counts only.
- Snapshots (`refresh_snapshot`, `served_snapshot`, `refresh_due_projects`): one stored row per project, recomputed
  lazily after a change (`snapshot_on_change`) or by the hourly sweep once the interval has elapsed (`snapshot_interval`).
- The viewer's view (`build_view`): the stored or live figures reduced to the types the viewer may read.

Design decisions:
- Counts only. A snapshot holds numbers and keys, never a record's code, title or content, so one stored row serves every
  viewer; each viewer then sees only the categories, review rows and check types they hold `view` on (`readable_provider`),
  so a figure never reveals records they cannot open. The failing records themselves come from the baseline check preview,
  which needs `manage_project_governance`.
- Baseline checks read records as a person (each check lists a type through the person's own view), so they never run as
  nobody. In `on_demand` they run as the viewer. In a snapshot they run as the project's configured runner, or, with no
  runner, only when a person presses Refresh now; any other refresh carries the last results forward and labels them with
  who ran them and when. A runner who has left the project or been deactivated is not used, and the results say so.
- Staleness is read from the audit trail: a snapshot is stale once the project has an audit event of a governed type (or a
  governance policy change) after the instant the snapshot began reading. That needs no hook in any record's write path, and
  the instant is taken before reading so a change made while it was computing is never missed.
- Reviews due are compared with the UTC date when a snapshot is stored (no caller supplies a day) and with the caller's day
  when computed live.
- A refresh takes a transaction-scoped advisory lock per project and a reader that cannot take it serves the stored snapshot
  flagged stale, so a burst of readers after a change recomputes once.
- A refresh the system makes writes no audit event (it is derived data); a person pressing Refresh now and every change of a
  setting do.

Dependencies: `modules.seams`/`modules.registry` (providers), `services.baseline` (checks), `services.review_engine` (due
reviews), `services.record_counts` (the viewer's rights), `services.governance_seams`, `services.audit`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules import registry
from app.modules.seams import HealthMeasure
from app.modules.traceability._shared import GOVERNANCE_HEALTH, TRACEABILITY_MODULE_KEY
from app.modules.traceability.enums import DEFAULT_HEALTH_INTERVAL_HOURS, HEALTH_INTERVAL_HOURS, HealthMode
from app.modules.traceability.models import GovernanceHealthDefault, GovernanceHealthSettings, GovernanceHealthSnapshot
from app.services import baseline as core_baseline
from app.services import governance_seams
from app.services.audit import log_event
from app.services.rbac import get_effective_permissions, get_effective_project_roles
from app.services.record_counts import readable_provider
from app.services.review_engine import due_reviews

logger = logging.getLogger(__name__)

SETTINGS_AUDIT_ENTITY_TYPE = "governance_health_settings"
DEFAULT_AUDIT_ENTITY_TYPE = "governance_health_default"
REFRESH_AUDIT_ENTITY_TYPE = "governance_health"

#: Records in a project (all governed types) above which on-demand health is advised against while baseline checks are
#: enabled: the checks capture every record of every baseline type, about 3 ms a record, which leaves the 1 s list budget at
#: about 300 records. The figures alone (without checks) stay under 0.5 s at 50,000 records. Measured in process at T2 to T4
#: and re-measured by `perf/loadgen/scenarios.py`'s `governance_health` scenario (`docs/decisions.md`).
ON_DEMAND_GUIDANCE_RECORDS = 300

#: Audit entity types besides the governed record types that change what the figures say.
_POLICY_EVENT_TYPES = (
    "governance_profile", "governance_approval_policy", "governance_review_policy", "governance_baseline_policy",
)
#: Events that change what a baseline check finds without changing a governed record: links and traceability rules.
_CHECK_INPUT_EVENT_TYPES = ("artefact_link", "requirement_link", "requirement_action_link", "governance_traceability_rule")
_LOCK_NAMESPACE = 7304
#: The hourly sweep runs a few minutes past the hour, so a snapshot refreshed on the previous sweep is due again.
_SWEEP_TOLERANCE = timedelta(minutes=10)

ChecksStatus = Literal["not_enabled", "current", "carried_forward", "not_run", "runner_unavailable"]
Source = Literal["project", "organization", "default"]


# --- settings --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectiveSettings:
    """The way a project's health is kept, with where each value comes from.

    Attributes:
        mode: The mode in force.
        mode_source: `project` (its own choice), `organization` (the default) or `default` (nothing is set).
        interval_hours: The snapshot interval in force (used by `snapshot_interval`).
        interval_source: Where the interval comes from.
        checks_runner_id: The person the baseline checks of a snapshot run as, or `None`.
        own_mode, own_interval_hours: The project's own values, `None` where it follows the default.
    """

    mode: HealthMode
    mode_source: Source
    interval_hours: int
    interval_source: Source
    checks_runner_id: uuid.UUID | None
    own_mode: HealthMode | None = None
    own_interval_hours: int | None = None


def org_default_row(db: Session, organization_id: uuid.UUID) -> GovernanceHealthDefault | None:
    """The organisation's stored default, or `None` when it has set none."""
    return db.scalar(select(GovernanceHealthDefault).where(GovernanceHealthDefault.organization_id == organization_id))


def project_settings_row(db: Session, project_id: uuid.UUID) -> GovernanceHealthSettings | None:
    """The project's stored settings, or `None` when it has set none."""
    return db.scalar(select(GovernanceHealthSettings).where(GovernanceHealthSettings.project_id == project_id))


def validated_interval(hours: int) -> int:
    """`hours` when it is one of the offered snapshot intervals.

    Raises:
        HTTPException: 422 for any other value.
    """
    if hours not in HEALTH_INTERVAL_HOURS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The snapshot interval must be one of {', '.join(str(h) for h in HEALTH_INTERVAL_HOURS)} hours.",
        )
    return hours


def organization_default(db: Session, organization_id: uuid.UUID) -> tuple[HealthMode, int]:
    """The organisation's default mode and snapshot interval; on demand and daily when it has set none."""
    row = org_default_row(db, organization_id)
    if row is None:
        return HealthMode.ON_DEMAND, DEFAULT_HEALTH_INTERVAL_HOURS
    return HealthMode(row.mode), row.interval_hours


def set_organization_default(
    db: Session, *, organization: Organization, mode: HealthMode, interval_hours: int, actor_id: uuid.UUID,
) -> None:
    """Sets the organisation's default health mode and snapshot interval.

    Args:
        db: Active session (not committed).
        organization: The organisation.
        mode: The default mode.
        interval_hours: The default interval, one of `HEALTH_INTERVAL_HOURS`.
        actor_id: The acting user.

    Raises:
        HTTPException: 422 for an interval that is not offered.
    """
    validated_interval(interval_hours)
    row = org_default_row(db, organization.id)
    if row is None:
        db.add(GovernanceHealthDefault(organization_id=organization.id, mode=mode.value, interval_hours=interval_hours))
    else:
        row.mode = mode.value
        row.interval_hours = interval_hours
    log_event(
        db, entity_type=DEFAULT_AUDIT_ENTITY_TYPE, entity_id=organization.id, action="updated", actor_id=actor_id,
        organization_id=organization.id, detail={"mode": mode.value, "interval_hours": interval_hours},
    )
    db.flush()


def effective_settings(db: Session, project: Project) -> EffectiveSettings:
    """The project's health mode and interval: its own choice, else the organisation's default, else on demand and daily."""
    own = project_settings_row(db, project.id)
    default = org_default_row(db, project.organization_id)
    mode, interval = HealthMode.ON_DEMAND, DEFAULT_HEALTH_INTERVAL_HOURS
    mode_source: Source = "default"
    interval_source: Source = "default"
    if default is not None:
        mode, mode_source = HealthMode(default.mode), "organization"
        interval, interval_source = default.interval_hours, "organization"
    if own is not None and own.mode is not None:
        mode, mode_source = HealthMode(own.mode), "project"
    if own is not None and own.interval_hours is not None:
        interval, interval_source = own.interval_hours, "project"
    return EffectiveSettings(
        mode=mode, mode_source=mode_source, interval_hours=interval, interval_source=interval_source,
        checks_runner_id=None if own is None else own.checks_runner_id,
        own_mode=None if own is None or own.mode is None else HealthMode(own.mode),
        own_interval_hours=None if own is None else own.interval_hours,
    )


def runner_problem(db: Session, project: Project, user_id: uuid.UUID | None) -> str | None:
    """Why `user_id` cannot run the project's baseline checks, or `None` when they can.

    A runner must be an active user who holds a role in the project, because the checks read each type through that
    person's own view.
    """
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return "The person is not an active user."
    if not get_effective_project_roles(db, user.id, project.id):
        return "The person holds no role in the project."
    return None


def set_project_settings(
    db: Session, *, project: Project, mode: HealthMode | None, interval_hours: int | None, checks_runner_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> None:
    """Sets a project's own health settings; a `None` value follows the organisation's default (no runner for the runner).

    Args:
        db: Active session (not committed).
        project: The project.
        mode: The project's own mode, or `None` to follow the default.
        interval_hours: The project's own interval, or `None` to follow the default.
        checks_runner_id: The person the baseline checks of a snapshot run as, or `None` for person-run only.
        actor_id: The acting user.

    Raises:
        HTTPException: 422 for an interval that is not offered or a runner who cannot run the checks.
    """
    if interval_hours is not None:
        validated_interval(interval_hours)
    problem = runner_problem(db, project, checks_runner_id)
    if problem is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"The baseline check runner is not valid. {problem}")
    row = project_settings_row(db, project.id)
    if row is None:
        row = GovernanceHealthSettings(project_id=project.id)
        db.add(row)
    row.mode = None if mode is None else mode.value
    row.interval_hours = interval_hours
    row.checks_runner_id = checks_runner_id
    log_event(
        db, entity_type=SETTINGS_AUDIT_ENTITY_TYPE, entity_id=project.id, action="updated", actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id,
        detail={
            "mode": None if mode is None else mode.value, "interval_hours": interval_hours,
            "runner_set": checks_runner_id is not None,
        },
    )
    db.flush()


# --- figures ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CategoryFigure:
    """One record category's progress.

    Attributes:
        key: The provider's namespaced key (`risk_management:risk`, or `requirement` for a core type).
        label: Plural display name.
        artefact_type: The registered type the figure describes.
        kind: `completion` or `outstanding` (what the category headlines).
        total: Records that count.
        done: Records that have reached the settled outcome.
        open_to_members: Every member of the project sees the figure (`HealthProvider.open_to_members`), not only a person
            who may read `artefact_type`.
    """

    key: str
    label: str
    artefact_type: str
    kind: Literal["completion", "outstanding"]
    total: int
    done: int
    open_to_members: bool = False

    @property
    def outstanding(self) -> int:
        """Records that have not reached the settled outcome."""
        return self.total - self.done

    @property
    def percent(self) -> int | None:
        """The share done as a whole percentage rounded down (never 100 until all are done); `None` with no records."""
        return None if self.total == 0 else self.done * 100 // self.total


@dataclass(frozen=True)
class ReviewFigure:
    """Reviews due or overdue for one record type.

    Attributes:
        artefact_type: The registered type with a review schedule.
        label: Plural display name.
        due: Records whose review date is on or before the day compared.
    """

    artefact_type: str
    label: str
    due: int


@dataclass(frozen=True)
class CheckTypeFigure:
    """One baseline check's result for one record type.

    Attributes:
        artefact_type: The registered type.
        checked: Records the check covered.
        failing: Records that fail the check (each counted once).
    """

    artefact_type: str
    checked: int
    failing: int


@dataclass(frozen=True)
class CheckFigure:
    """One enabled baseline check's results.

    Attributes:
        key: The namespaced check key.
        name: The check's display name.
        types: Its result per record type it covered.
    """

    key: str
    name: str
    types: tuple[CheckTypeFigure, ...]


@dataclass(frozen=True)
class ChecksFigure:
    """The baseline check section of the health figures.

    Attributes:
        status: `not_enabled` (the policy enables no check), `current` (run now), `carried_forward` (the last results, older
            than the snapshot), `not_run` (no results yet: a snapshot without a runner waits for a person to refresh) or
            `runner_unavailable` (the configured runner cannot run them and there are no earlier results).
        checks: The results, empty unless `current` or `carried_forward`.
    """

    status: ChecksStatus
    checks: tuple[CheckFigure, ...] = ()


@dataclass(frozen=True)
class Figures:
    """Everything a health view shows before the viewer's rights are applied.

    Attributes:
        categories: Progress per category.
        reviews: Reviews due per type.
        checks: The baseline check section.
    """

    categories: tuple[CategoryFigure, ...] = ()
    reviews: tuple[ReviewFigure, ...] = ()
    checks: ChecksFigure = field(default_factory=lambda: ChecksFigure("not_enabled"))


def compute_categories(db: Session, project: Project) -> list[CategoryFigure]:
    """The progress of each record category in effect for the project, in provider order.

    Args:
        db: Active session (read only).
        project: The project.

    Returns:
        One figure per `HealthProvider` whose module and sub-component are in effect, whose type is enabled and whose
        `measure` reports a figure for the project.
    """
    figures: list[CategoryFigure] = []
    for module_key, provider in registry.get_health_providers():
        if not governance_seams.registration_active(db, project.id, module_key, provider.sub_component):
            continue
        if not registry.artefact_type_enabled_for_project(db, provider.artefact_type, project.id):
            continue
        measure: HealthMeasure | None = provider.measure(db, project.id)
        if measure is None:
            continue
        figures.append(CategoryFigure(
            key=f"{module_key}:{provider.key}" if module_key else provider.key, label=provider.label,
            artefact_type=provider.artefact_type, kind=provider.kind, total=measure.total, done=measure.done,
            open_to_members=provider.open_to_members,
        ))
    return figures


def compute_reviews(db: Session, project: Project, today: date) -> list[ReviewFigure]:
    """The reviews due on or before `today` for each record type with a review schedule in effect for the project.

    Args:
        db: Active session (read only).
        project: The project.
        today: The calendar day compared with (the caller's day live, the UTC day for a stored snapshot).

    Returns:
        One figure per record type with a schedule in effect, in type-name order, including types with nothing due. A
        schedule that is not a record type's (a stage's phases, a standard's review) is not a figure: no viewer may read it.
    """
    providers = registry.get_record_table_providers()
    counts: dict[str, int] = {}
    for artefact_type, _ in due_reviews(db, project.id, today, providers.keys()):
        counts[artefact_type] = counts.get(artefact_type, 0) + 1
    return [
        ReviewFigure(artefact_type=t, label=providers[t].label, due=counts.get(t, 0))
        for t in sorted(registry.get_review_adapters())
        if t in providers and governance_seams.review_adapter_for_project(db, project.id, t) is not None
    ]


def checks_enabled(db: Session, project: Project) -> bool:
    """Whether the project's baseline policy enables any check for either kind of baseline."""
    return bool(
        core_baseline.active_checks(db, project, "stage", automated=True)
        or core_baseline.active_checks(db, project, "manual")
        or core_baseline.active_checks(db, project, "approval")
    )


def compute_checks(db: Session, project: Project, runner: User) -> ChecksFigure:
    """Runs the project's enabled baseline checks as `runner` and reduces them to counts.

    Args:
        db: Active session (read only).
        project: The project.
        runner: The person whose view of each type's records the checks read.

    Returns:
        A `current` section with one entry per check and type; `not_enabled` when the policy enables none.
    """
    evaluation = core_baseline.evaluate_checks(db, project, runner)
    if not evaluation.checks:
        return ChecksFigure("not_enabled")
    failing: dict[tuple[str, str], set[uuid.UUID]] = {}
    for failure in evaluation.failures:
        failing.setdefault((failure.check_key, failure.artefact_type), set()).add(failure.artefact_id)
    checks: list[CheckFigure] = []
    for key, provider in evaluation.checks:
        types = provider.artefact_types or tuple(sorted(evaluation.records))
        checks.append(CheckFigure(
            key=key, name=provider.name,
            types=tuple(
                CheckTypeFigure(t, evaluation.records[t], len(failing.get((key, t), ())))
                for t in sorted(types) if evaluation.records.get(t)
            ),
        ))
    return ChecksFigure("current", tuple(checks))


def figures_to_json(figures: Figures) -> dict[str, Any]:
    """The JSON stored in a snapshot (counts and keys only)."""
    return {
        "categories": [
            {"key": c.key, "label": c.label, "artefact_type": c.artefact_type, "kind": c.kind, "total": c.total, "done": c.done,
             "open_to_members": c.open_to_members}
            for c in figures.categories
        ],
        "reviews": [{"artefact_type": r.artefact_type, "label": r.label, "due": r.due} for r in figures.reviews],
        "checks": {
            "status": figures.checks.status,
            "checks": [
                {
                    "key": c.key, "name": c.name,
                    "types": [{"artefact_type": t.artefact_type, "checked": t.checked, "failing": t.failing} for t in c.types],
                }
                for c in figures.checks.checks
            ],
        },
    }


def figures_from_json(data: dict[str, Any]) -> Figures:
    """The figures a snapshot's JSON holds."""
    checks = data.get("checks") or {}
    return Figures(
        categories=tuple(CategoryFigure(**c) for c in data.get("categories", [])),
        reviews=tuple(ReviewFigure(**r) for r in data.get("reviews", [])),
        checks=ChecksFigure(
            status=checks.get("status", "not_enabled"),
            checks=tuple(
                CheckFigure(key=c["key"], name=c["name"], types=tuple(CheckTypeFigure(**t) for t in c["types"]))
                for c in checks.get("checks", [])
            ),
        ),
    )


# --- snapshots -------------------------------------------------------------------------------------


def _snapshot(db: Session, project_id: uuid.UUID) -> GovernanceHealthSnapshot | None:
    return db.scalar(select(GovernanceHealthSnapshot).where(GovernanceHealthSnapshot.project_id == project_id))


def _governed_event_types() -> list[str]:
    """The audit entity types whose events change the figures or the check results."""
    providers = {p.artefact_type for _, p in registry.get_health_providers()}
    return sorted(providers | set(_POLICY_EVENT_TYPES) | set(_CHECK_INPUT_EVENT_TYPES))


def is_stale(db: Session, project: Project, snapshot: GovernanceHealthSnapshot) -> bool:
    """Whether the project's governed records or the governance policy that reaches it changed after the snapshot began reading.

    Args:
        db: Active session (read only).
        project: The project.
        snapshot: Its stored snapshot.

    Returns:
        `True` when an audit event of a governed type, a link or a traceability rule in the project, or a governance profile
        or profile rule event of its organisation, is newer than `snapshot.computed_at`.
    """
    in_project = exists().where(
        AuditEvent.project_id == project.id, AuditEvent.entity_type.in_(_governed_event_types()),
        AuditEvent.created_at > snapshot.computed_at,
    )
    in_organization = exists().where(
        or_(
            AuditEvent.entity_type == "governance_profile",
            and_(AuditEvent.entity_type == "governance_traceability_rule", AuditEvent.project_id.is_(None)),
        ),
        AuditEvent.organization_id == project.organization_id, AuditEvent.created_at > snapshot.computed_at,
    )
    return bool(db.scalar(select(in_project | in_organization)))


def refresh_lock_key(project_id: uuid.UUID) -> tuple[int, int]:
    """The two-part advisory lock key that serialises refreshes of one project's snapshot."""
    return _LOCK_NAMESPACE, int.from_bytes(project_id.bytes[:4], "big", signed=True)


def _try_lock(db: Session, project_id: uuid.UUID) -> bool:
    """Takes the project's health refresh lock for the transaction; `False` when another refresh holds it."""
    return bool(db.scalar(select(func.pg_try_advisory_xact_lock(*refresh_lock_key(project_id)))))


def refresh_snapshot(db: Session, project: Project, *, actor: User | None) -> GovernanceHealthSnapshot | None:
    """Recomputes and stores the project's snapshot.

    Args:
        db: Active session (the snapshot is flushed, never committed).
        project: The project.
        actor: The person pressing Refresh now, or `None` for a refresh the system makes. With no configured runner the
            baseline checks run as `actor` when there is one; otherwise they are carried forward.

    Returns:
        The stored snapshot, or `None` when another refresh of the project is already running.
    """
    if not _try_lock(db, project.id):
        return None
    started = datetime.now(UTC)
    settings = effective_settings(db, project)
    previous = _snapshot(db, project.id)
    checks_by: User | None = None
    problem: str | None = None
    if settings.checks_runner_id is not None:
        problem = runner_problem(db, project, settings.checks_runner_id)
        checks_by = None if problem else db.get(User, settings.checks_runner_id)
    elif actor is not None:
        checks_by = actor
    figures = Figures(categories=tuple(compute_categories(db, project)), reviews=tuple(compute_reviews(db, project, started.date())))
    run_by_id: uuid.UUID | None = None
    run_at: datetime | None = None
    if not checks_enabled(db, project):
        checks = ChecksFigure("not_enabled")
    elif checks_by is not None:
        checks = compute_checks(db, project, checks_by)
        run_by_id, run_at = checks_by.id, started
    else:
        earlier = figures_from_json(previous.payload).checks if previous is not None else ChecksFigure("not_run")
        if earlier.status in ("current", "carried_forward"):
            checks = ChecksFigure("carried_forward", earlier.checks)
            run_by_id = previous.checks_run_by_id if previous is not None else None
            run_at = previous.checks_run_at if previous is not None else None
        else:
            checks = ChecksFigure("runner_unavailable" if problem else "not_run")
    payload = figures_to_json(Figures(figures.categories, figures.reviews, checks))
    if previous is None:
        previous = GovernanceHealthSnapshot(project_id=project.id)
        db.add(previous)
    previous.computed_at = started
    previous.payload = payload
    previous.refreshed_by_id = None if actor is None else actor.id
    previous.checks_run_by_id = run_by_id
    previous.checks_run_at = run_at
    db.flush()
    return previous


def served_snapshot(db: Session, project: Project, mode: HealthMode) -> tuple[GovernanceHealthSnapshot | None, bool]:
    """The snapshot to serve for a snapshot mode, refreshing it first when `snapshot_on_change` finds it stale or missing.

    Args:
        db: Active session (a refresh is flushed; the caller commits).
        project: The project.
        mode: A snapshot mode.

    Returns:
        `(snapshot, stale)`. `stale` is true when a change is not yet reflected because another refresh is running. The
        snapshot is `None` only when none exists and another refresh is running. `snapshot_interval` computes a first
        snapshot when none exists and otherwise leaves refreshing to the hourly sweep.
    """
    snapshot = _snapshot(db, project.id)
    if snapshot is None:
        return refresh_snapshot(db, project, actor=None), False
    if mode is HealthMode.SNAPSHOT_ON_CHANGE and is_stale(db, project, snapshot):
        refreshed = refresh_snapshot(db, project, actor=None)
        if refreshed is None:
            return snapshot, True
        return refreshed, False
    return snapshot, False


def refresh_due_projects(db: Session, *, now: datetime | None = None) -> int:
    """The hourly sweep: refreshes the snapshot of every project that keeps interval snapshots and is due.

    A project is due when it has no snapshot or its snapshot is older than its interval (less a tolerance, because the sweep
    runs hourly). Each project refreshes in its own transaction, so one failing project never stops the rest.

    Args:
        db: A session with no open work; each project's refresh is committed (or rolled back) here.
        now: The instant to compare with (tests); the current UTC time by default.

    Returns:
        The number of snapshots refreshed.
    """
    now = now or datetime.now(UTC)
    org_ids = set(db.scalars(select(GovernanceHealthDefault.organization_id).where(
        GovernanceHealthDefault.mode == HealthMode.SNAPSHOT_INTERVAL.value
    )))
    candidates = select(Project.id).where(
        Project.id.in_(select(GovernanceHealthSettings.project_id).where(
            GovernanceHealthSettings.mode == HealthMode.SNAPSHOT_INTERVAL.value
        )) | Project.organization_id.in_(org_ids)
    )
    refreshed = 0
    for project_id in list(db.scalars(candidates)):
        try:
            project = db.get(Project, project_id)
            if project is None or not registry.is_module_subcomponent_enabled(db, project.id, TRACEABILITY_MODULE_KEY, GOVERNANCE_HEALTH):
                continue
            settings = effective_settings(db, project)
            if settings.mode is not HealthMode.SNAPSHOT_INTERVAL:
                continue
            snapshot = _snapshot(db, project.id)
            if snapshot is not None and snapshot.computed_at + timedelta(hours=settings.interval_hours) - _SWEEP_TOLERANCE > now:
                continue
            if refresh_snapshot(db, project, actor=None) is not None:
                refreshed += 1
            db.commit()
        except Exception:  # noqa: BLE001 - one project's failure must not stop the sweep
            logger.exception("Governance health refresh failed for project %s", project_id)
            db.rollback()
    return refreshed


def run_scheduled_refresh(db: Session) -> None:
    """`ModuleScheduledJob.run`: the hourly sweep over projects that keep interval snapshots."""
    refresh_due_projects(db)


def record_manual_refresh(db: Session, project: Project, actor: User) -> None:
    """Audits a person's Refresh now (keys only)."""
    log_event(
        db, entity_type=REFRESH_AUDIT_ENTITY_TYPE, entity_id=project.id, action="refreshed", actor_id=actor.id,
        organization_id=project.organization_id, project_id=project.id,
    )


# --- the viewer's view -----------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthView:
    """What one viewer sees.

    Attributes:
        source: `live` (computed for this request) or `snapshot`.
        computed_at: When the figures were read.
        stale: A change is not yet reflected (a refresh is already running).
        categories, reviews, checks: The figures reduced to the types the viewer may read.
        checks_run_by_id, checks_run_at: Who ran the check results and when (a snapshot's carried-forward results are older
            than `computed_at`); `None` for live results, which are the viewer's own.
    """

    source: Literal["live", "snapshot"]
    computed_at: datetime
    stale: bool
    categories: tuple[CategoryFigure, ...]
    reviews: tuple[ReviewFigure, ...]
    checks: ChecksFigure
    checks_run_by_id: uuid.UUID | None = None
    checks_run_at: datetime | None = None


def restrict_to_viewer(db: Session, project: Project, viewer: User, figures: Figures) -> Figures:
    """Removes every figure about a type the viewer may not read.

    A category, review row or check result for a type is dropped, never shown as zero, so a number never reveals records the
    viewer cannot open. A check left with no type is dropped.

    Args:
        db: Active session (read only).
        project: The project.
        viewer: The person looking.
        figures: The unrestricted figures.

    Returns:
        The figures the viewer may see.
    """
    held = get_effective_permissions(db, viewer.id, project_id=project.id)
    allowed: dict[str, bool] = {}

    def readable(artefact_type: str) -> bool:
        if artefact_type not in allowed:
            allowed[artefact_type] = readable_provider(db, viewer, project, artefact_type, held) is not None
        return allowed[artefact_type]

    checks = tuple(
        CheckFigure(c.key, c.name, kept)
        for c in figures.checks.checks
        if (kept := tuple(t for t in c.types if readable(t.artefact_type)))
    )
    return Figures(
        categories=tuple(c for c in figures.categories if c.open_to_members or readable(c.artefact_type)),
        reviews=tuple(r for r in figures.reviews if readable(r.artefact_type)),
        checks=ChecksFigure(figures.checks.status, checks),
    )


def build_view(
    db: Session, project: Project, viewer: User, settings: EffectiveSettings, *, today: date,
) -> HealthView:
    """The project's health for one viewer, live or from the snapshot as the mode says.

    Args:
        db: Active session (a lazy refresh is flushed; the caller commits).
        project: The project.
        viewer: The person looking.
        settings: The effective settings.
        today: The viewer's calendar day, used for live reviews due.

    Returns:
        The view; empty figures when a first snapshot cannot be made because another refresh is running.
    """
    if settings.mode is HealthMode.ON_DEMAND:
        started = datetime.now(UTC)
        checks = compute_checks(db, project, viewer) if checks_enabled(db, project) else ChecksFigure("not_enabled")
        figures = restrict_to_viewer(db, project, viewer, Figures(
            tuple(compute_categories(db, project)), tuple(compute_reviews(db, project, today)), checks,
        ))
        return HealthView("live", started, False, figures.categories, figures.reviews, figures.checks)
    snapshot, stale = served_snapshot(db, project, settings.mode)
    if snapshot is None:
        return HealthView("snapshot", datetime.now(UTC), True, (), (), ChecksFigure("not_run"))
    figures = restrict_to_viewer(db, project, viewer, figures_from_json(snapshot.payload))
    return HealthView(
        "snapshot", snapshot.computed_at, stale, figures.categories, figures.reviews, figures.checks,
        snapshot.checks_run_by_id, snapshot.checks_run_at,
    )
