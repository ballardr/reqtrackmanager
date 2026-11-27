"""
Module: modules.seams

Contracts for the registration points a module uses to take part in core behaviour it does not own: a permission atom
it contributes, the sub-type of a record, a review schedule, a pre-baseline check, a policy for one of the core
engine seams (lifecycle move, approval check, review, baseline check) and a table of policy rows a governance profile
can own.

Responsibilities:
- Define the frozen dataclasses `ModuleDefinition` carries (`administrative_permissions`, `record_subtypes`,
  `review_adapters`, `baseline_check_providers`, `policy_resolvers`, `profile_contributors`, `health_providers`,
  `rule_condition_fields`);
  `registry.py` merges them
  and `services.governance_seams` resolves them for a project.

Design decisions:
- Each seam lives in core `services/` with the type's own behaviour as the built-in default; a module only registers what
  applies on top, so a project whose module is off behaves exactly as before and core never imports a module.
- A registration may name a `sub_component` of its own module: it applies to a project only while that sub-component is
  effective (`registry.is_module_subcomponent_enabled`), so switching a part off removes its contribution.
- A contract holds only what every registrant needs now; a seam's phase extends it when it builds the seam.
- This file imports no registry code (the registry imports it), so it cannot create an import cycle.

Dependencies: SQLAlchemy `Session` for the callable signatures and `app.models.enums` for the role vocabulary.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.enums import OrgRole, ProjectRole
from app.schemas.principal import PrincipalRef

_ATOM_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class ModuleAdministrativePermission:
    """One administrative permission atom a module contributes (a bare key such as `manage_project_governance`, with no
    artefact type or level), added to the vocabulary `services.permissions.get_all_permissions` offers and resolved by
    `services.rbac.get_effective_permissions`.

    Attributes:
        key: The atom's stable bare key: lower-case words joined by underscores, unique across every module and distinct
            from the core `ADMINISTRATIVE_PERMISSIONS`. It is stored in custom role grants, so it never changes.
        label: Formal display name for the permission picker.
        org_roles: Organisation roles that hold the atom in their organisation (organisation administrators by default,
            as for the core atoms). It applies in every project of the organisation.
        project_roles: Project roles that hold the atom in their own project.

    Raises:
        ValueError: If `key` is not a bare lower-case key.
    """

    key: str
    label: str
    org_roles: tuple[OrgRole, ...] = (OrgRole.ORG_ADMIN,)
    project_roles: tuple[ProjectRole, ...] = ()

    def __post_init__(self) -> None:
        if not _ATOM_KEY.match(self.key):
            raise ValueError(f"Administrative permission key {self.key!r} must be lower-case words joined by underscores.")


class GovernanceSeam(str, Enum):
    """The core engine seams a module's policy can take part in. The set is closed because each seam is core code
    (`services.lifecycles.check_move`, the approval check, the review engine, the baseline check, the stage workflow choice)."""

    LIFECYCLE = "lifecycle"
    APPROVAL = "approval"
    REVIEW = "review"
    BASELINE = "baseline"
    STAGE_WORKFLOW = "stage_workflow"


@dataclass(frozen=True)
class LifecyclePolicy:
    """What governance policy adds to a project's lifecycles: the answer of `GovernanceSeam.LIFECYCLE`
    (`services.lifecycles` reads it for every type and for the rule on skipping steps).

    Attributes:
        required: `{artefact type: {state: names of the profiles that require it}}`. A required state binds the project
            like an organisation's requirement: it cannot be turned off. Policies of several profiles are merged by
            union, so one profile never relaxes another.
        skip_forbidden_by: Names of the profiles that forbid skipping steps; any one forbids it for the project.
    """

    required: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)
    skip_forbidden_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageWorkflowPolicy:
    """What governance policy asks of the stage workflows a project may use: the answer of `GovernanceSeam.STAGE_WORKFLOW`
    (`services.stage_workflows` reads it when it lists the project's workflows and picks the one a new stage starts in).

    Attributes:
        default_workflow_id: The organisation workflow new stages start in when none is chosen: the first source in
            precedence order that names one. Existing stages are never moved.
        required: `{workflow id: names of the profiles requiring it}`. A required workflow is always one the project may
            use and cannot be hidden. Policies of several profiles are merged by union, so one never removes another's.
        restricted_by: Names of the profiles that limit the project to the required workflows; any one limits it, so the
            project may then create stages and change workflow only within them.
    """

    default_workflow_id: uuid.UUID | None = None
    required: Mapping[uuid.UUID, tuple[str, ...]] = field(default_factory=dict)
    restricted_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApproverRole:
    """A role a policy names as one more way to satisfy a record type's approval check.

    Attributes:
        kind: `project` (a fixed project role such as `project_manager`), `module` (a role a module contributes, with the
            key written `<module key>:<role key>`) or `custom` (an organisation's custom role, with the key its id).
        key: The role within its kind.
    """

    kind: Literal["project", "module", "custom"]
    key: str


@dataclass(frozen=True)
class ApprovalPolicy:
    """What governance policy adds to the approval check of one record type in one project: the answer of
    `GovernanceSeam.APPROVAL` (`services.approval_policy` reads it at every approval path).

    Attributes:
        roles: Roles whose holders may also approve the type, beside whoever the type's own check already admits. A
            policy only adds ways to satisfy the check: it never removes the type's default approvers, and the approval
            separation rule still applies to everyone it admits. The roles of several sources are merged by union.
    """

    roles: tuple[ApproverRole, ...] = ()


@dataclass(frozen=True)
class PolicyResolver:
    """A module's answer to "which policy applies" for one core seam.

    Attributes:
        seam: The seam it answers for.
        resolve: `resolve(db, project_id, artefact_type)` returns the seam's policy object for the type in the project,
            or `None` when the module has no policy there, in which case the next resolver or the type's built-in default
            applies. It reads only and never commits. The policy object's shape belongs to the seam. Used by a seam that
            asks one type at a time (approval, review).
        sub_component: The sub-component of the registering module that must be effective in the project for the resolver
            to be asked; `None` means the whole module being on is enough.
        resolve_project: `resolve_project(db, project_id)` returns the seam's policy for the whole project (every type at
            once), or `None`. Used by a seam that reads all types in one pass (lifecycle), so the answer costs a fixed
            number of statements however many types are registered.

    Raises:
        ValueError: If neither or both of `resolve` and `resolve_project` are given.
    """

    seam: GovernanceSeam
    resolve: Callable[[Session, uuid.UUID, str], Any | None] | None = None
    sub_component: str | None = None
    resolve_project: Callable[[Session, uuid.UUID], Any | None] | None = None

    def __post_init__(self) -> None:
        if (self.resolve is None) == (self.resolve_project is None):
            raise ValueError("A policy resolver gives exactly one of resolve and resolve_project.")


@dataclass(frozen=True)
class ApprovalGateDefinition:
    """A record type that has an approval gate but no lifecycle with a gated state (`ModuleDefinition.approval_gates`).

    Attributes:
        label: The type's singular display name.
        record_context: `record_context(db, record_id)` returns `(creator id, project id, organisation id)` of the record
            (the organisation id only for a record the organisation owns), or `None` when the record does not exist or
            has no creator to separate the approver from. It reads only.
    """

    label: str
    record_context: Callable[[Session, uuid.UUID], tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None] | None]


@dataclass(frozen=True)
class ReviewPolicy:
    """What governance policy adds to the review of one record type in one project: the answer of
    `GovernanceSeam.REVIEW` (`services.review_engine` reads it).

    Attributes:
        interval_days: The longest gap between two reviews, in days. A record's next review falls due no later than this
            many days after the last one (`review_engine.next_due_date`, `check_next_review_date`). `None` sets no
            interval, so each type keeps the schedule it has.
        lead_days: Days before the due date that the reminder is sent, for a record that sets no lead of its own. `None`
            leaves the project's default lead.
        default_owner: Who is reminded, and may record the review, for a record that has no reviewer of its own: a user or a
            group. `None` leaves the project managers as the fallback.
    """

    interval_days: int | None = None
    lead_days: int | None = None
    default_owner: PrincipalRef | None = None


@dataclass(frozen=True)
class DueReview:
    """One record whose review falls due.

    Attributes:
        artefact_id: The record's id.
        due_on: The calendar date the review is due.
        owner: The record's own reviewer, or `None` when it has none.
    """

    artefact_id: uuid.UUID
    due_on: date
    owner: PrincipalRef | None = None


@dataclass(frozen=True)
class ReviewReminder:
    """One record whose review reminder may still have to be sent for its current due date.

    Attributes:
        artefact_id: The record's id.
        project_id: The project that holds the record, `None` for a record the organisation owns (then `organization_id`
            is set, no review policy applies and no project default lead is read).
        due_on: The calendar date the review is due.
        title: The record's name, shown in the notification title.
        code: The record's code as it reads outside its project (qualified), shown in the notification body.
        owner: The record's own reviewer, or `None` when it has none.
        lead_days: The record's own reminder lead in days, or `None` to follow the policy and the project.
        organization_id: The organisation of a record with no project.
        entity: The `(entity type, entity id)` a notification opens, when it is not the record itself (a review of a
            standard opens the standard).
        reminded_for: The due date the "due" reminder was last sent for, or `None`. The engine sends no second "due"
            reminder for the same date.
        overdue_reminded_for: The due date the "overdue" reminder was last sent for, or `None`. Used only by a type that
            sets `ReviewAdapter.overdue_notification_type`.
        kind: `"due"` or `"overdue"` when the adapter itself says which reminder this is, `None` to let the engine infer it
            from `due_on` (a date that has passed is overdue, for a type with an overdue notification). A row with two
            dates yields two reminders, each with its own `due_on` and `kind`; an `"overdue"` one is sent only once its date
            has passed and has no lead window.
        detail: Text the adapter's own `message` shows (a schedule range); the engine's wording ignores it.
    """

    artefact_id: uuid.UUID
    project_id: uuid.UUID | None
    due_on: date
    title: str
    code: str
    owner: PrincipalRef | None = None
    lead_days: int | None = None
    organization_id: uuid.UUID | None = None
    entity: tuple[str, str] | None = None
    reminded_for: date | None = None
    overdue_reminded_for: date | None = None
    kind: Literal["due", "overdue"] | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.project_id is None and self.organization_id is None:
            raise ValueError("A reminder of a record with no project names its organisation.")


@dataclass(frozen=True)
class ReminderMark:
    """One reminder the engine has sent, for the adapter to record.

    Attributes:
        artefact_id: The record's id.
        due_on: The due date the reminder was sent for.
        overdue: `True` for the "overdue" reminder, `False` for the "due" one.
    """

    artefact_id: uuid.UUID
    due_on: date
    overdue: bool = False


@dataclass(frozen=True)
class ReviewAdapter:
    """How the review engine reads one artefact type's review schedule.

    Attributes:
        schedule: `review_record` when a review is a separate row and the record leaves the due list because a review
            dated on or after the due date exists (requirements); `next_review_date` when completing a review writes
            the record's next review date (risks). The engine supports both.
        due_reviews: `due_reviews(db, project_id, as_of)` returns the project's records whose review is due on or before
            `as_of`, oldest first. It reads only.
        pending_reminders: `pending_reminders(db)` returns, across every project, the records whose reminder may still
            have to be sent for their current due date and that are open to review (not archived or closed). It reads
            only. `None` leaves the type's own sweep in charge of its reminders.
        mark_reminded: `mark_reminded(db, marks, when)` records each reminder the engine sent. It flushes and never
            commits.
        notification_type: The registered notification type of the "due" reminder; required with `pending_reminders`.
        overdue_notification_type: The registered notification type of a separate "overdue" reminder, sent once per due
            date once the date has passed. `None` sends the "due" reminder throughout (requirements).
        message: `message(reminder, overdue)` returns the notification `(title, body)` of a reminder. `None` uses the
            engine's wording.
        fallback_recipients: `fallback_recipients(db, reminder)` returns who is reminded when the record has no reviewer
            and the policy names no default owner. `None` falls back to the project managers.
        also_notify: `also_notify(db, reminder)` returns people told of every reminder in addition to the reviewer, the
            default owner or the fallback (Compliance: its officers). `None` adds nobody.
        default_lead_days: The type's own reminder lead, used in place of the project's default lead when neither the
            record nor the policy sets one. `None` follows the project's default.
        project_lead_days: `project_lead_days(db, project_id)` returns the project's lead for this type (a schedule's own
            setting), used in place of the project's default review lead; the policy's lead still overrides it. Cannot be
            combined with `default_lead_days`.
        reminder_day: `reminder_day(now, kind)` returns the calendar day a reminder of that kind is compared with, given the
            sweep's instant. `None` compares with the UTC date. A type whose dates are in the planner's own day uses it to
            judge "due" against the latest day anywhere and "overdue" against the earliest.
        sub_component: The sub-component of the registering module that must also be effective in a project for the
            adapter to apply; `None` means the module being on is enough.
    """

    schedule: Literal["review_record", "next_review_date"]
    due_reviews: Callable[[Session, uuid.UUID, date], Sequence[DueReview]]
    pending_reminders: Callable[[Session], Sequence[ReviewReminder]] | None = None
    mark_reminded: Callable[[Session, Sequence[ReminderMark], datetime], None] | None = None
    notification_type: str | None = None
    overdue_notification_type: str | None = None
    message: Callable[[ReviewReminder, bool], tuple[str, str]] | None = None
    fallback_recipients: Callable[[Session, ReviewReminder], set[uuid.UUID]] | None = None
    also_notify: Callable[[Session, ReviewReminder], set[uuid.UUID]] | None = None
    default_lead_days: int | None = None
    project_lead_days: Callable[[Session, uuid.UUID], int | None] | None = None
    reminder_day: Callable[[datetime, Literal["due", "overdue"]], date] | None = None
    sub_component: str | None = None

    def __post_init__(self) -> None:
        reminding = (self.pending_reminders, self.mark_reminded, self.notification_type)
        if any(x is None for x in reminding) and any(x is not None for x in reminding):
            raise ValueError("A review adapter gives pending_reminders, mark_reminded and notification_type together.")
        if self.pending_reminders is None and any(
            x is not None
            for x in (
                self.overdue_notification_type, self.message, self.fallback_recipients, self.also_notify,
                self.default_lead_days, self.project_lead_days, self.reminder_day,
            )
        ):
            raise ValueError("A review adapter that sends no reminders cannot set reminder options.")
        if self.default_lead_days is not None and self.project_lead_days is not None:
            raise ValueError("A review adapter sets default_lead_days or project_lead_days, not both.")


@dataclass(frozen=True)
class BaselinePolicy:
    """What governance policy asks of a project's baselines and approvals: the answer of `GovernanceSeam.BASELINE`
    (`services.baseline` reads it before a baseline is written or a record is approved).

    Attributes:
        stage_checks: Namespaced keys (`<module key>:<check key>`) of the checks that run before a stage baseline, the one
            written when a stage enters a locked phase, whether a person or the review deadline moved it.
        manual_checks: The keys of the checks that run before a manual baseline.
        manual_approval_checks: The keys of the checks that run when a person approves one record.
        automated_approval_checks: The keys of the checks that run, beside `stage_checks`, when the product approves a
            stage itself because its review deadline passed.
        notify_managers: Whether the project's managers are told when the automatic approval of a stage is refused by a
            check (the review-deadline sweep, which retries daily).
        A check key names a registered `BaselineCheckProvider`; one that is not registered or not in effect for the project
        is skipped. The checks of several sources are merged by union, so no source relaxes another.
    """

    stage_checks: tuple[str, ...] = ()
    manual_checks: tuple[str, ...] = ()
    manual_approval_checks: tuple[str, ...] = ()
    automated_approval_checks: tuple[str, ...] = ()
    notify_managers: bool = True

    def checks_for(self, kind: Literal["stage", "manual", "approval"], *, automated: bool = False) -> tuple[str, ...]:
        """The check keys that run before a baseline of `kind`, or before a person's approval of a record (`approval`).
        `automated` marks a stage baseline taken by the review deadline, which also runs the automated approval checks."""
        if kind == "approval":
            return self.manual_approval_checks
        if kind == "manual":
            return self.manual_checks
        if automated:
            return tuple(sorted({*self.stage_checks, *self.automated_approval_checks}))
        return self.stage_checks


@dataclass(frozen=True)
class BaselineCheckContext:
    """What a baseline check is told about the baseline being written or the approval being made.

    Attributes:
        project_id: The project.
        kind: `stage` (a stage entering a locked phase, which is itself the approval act for drafts), `manual`, or
            `approval` (one person approving one record; no baseline is written).
        actor_id: The person who triggered it (a project manager standing in for the product when `automated`).
        automated: The product is approving a stage because its review deadline passed.
    """

    project_id: uuid.UUID
    kind: Literal["stage", "manual", "approval"]
    actor_id: uuid.UUID | None
    automated: bool = False


@dataclass(frozen=True)
class BaselineCheckFailure:
    """One reason a baseline is refused.

    Attributes:
        artefact_type: The failing record's registered type.
        artefact_id: The failing record's id.
        check_key: The `BaselineCheckProvider.key` that failed.
        message: Formal sentence naming what is missing; carries no personal data and does not repeat the code.
        code: The record's own code (`REQ-001`), shown beside the message; empty for a record with none.
    """

    artefact_type: str
    artefact_id: uuid.UUID
    check_key: str
    message: str
    code: str = ""


@dataclass(frozen=True)
class BaselineCheckProvider:
    """A check run before a baseline is taken. One failing check refuses the whole baseline, listing every failure.

    Attributes:
        key: Stable identifier, unique within its module; the registry namespaces it as `<module_key>:<key>`.
        name: Formal display name shown where a failure is listed.
        artefact_types: The registered types the check inspects, so a baseline that holds none of them skips it. Empty
            means every type the baseline holds (a check that reads each type through its own record table).
        check: `check(db, context, record_ids)` takes the baseline's records of `artefact_types` keyed by type and returns
            every failure. It reads only and never commits.
        sub_component: As `PolicyResolver.sub_component`.
    """

    key: str
    name: str
    artefact_types: tuple[str, ...]
    check: Callable[[Session, BaselineCheckContext, dict[str, Sequence[uuid.UUID]]], Sequence[BaselineCheckFailure]]
    sub_component: str | None = None


@dataclass(frozen=True)
class ProfileContributor:
    """A table of policy rows a governance profile can own, so the profile screens, counts and bundles need no per-table
    code.

    The table carries a `profile_id` column (a foreign key to `governance_profiles.id` with `ON DELETE CASCADE`, so
    deleting a profile removes its rows) beside its own columns; a row with no profile belongs to a project.

    Attributes:
        key: Stable identifier, unique within its module; the registry namespaces it as `<module_key>:<key>`.
        name: Formal display name of the kind of policy shown beside a profile (for example "Approval policies").
        count_rows: `count_rows(db, profile_ids)` returns the number of rows each profile holds, keyed by profile id
            (a profile with none may be absent). It reads in bulk.
        export_rows: `export_rows(db, profile_id)` returns the profile's rows as JSON-serialisable bundle entries,
            ordered stably, referring to other records by portable key.
        import_rows: `import_rows(db, profile_id, rows, warn)` writes bundle entries into the profile, reporting an
            entry it cannot apply through `warn` and never failing the import for one. It flushes and never commits.
        sub_component: The sub-component of the registering module the rows belong to. The profile screens list the
            kind only while it is in effect for the organisation; the data is kept and still travels in bundles when
            it is off.
    """

    key: str
    name: str
    count_rows: Callable[[Session, Sequence[uuid.UUID]], dict[uuid.UUID, int]]
    export_rows: Callable[[Session, uuid.UUID], list[dict[str, Any]]]
    import_rows: Callable[[Session, uuid.UUID, Sequence[dict[str, Any]], Callable[[str], None]], None]
    sub_component: str | None = None


@dataclass(frozen=True)
class HealthMeasure:
    """How far one record type has got in one project, as two counts.

    Attributes:
        total: The records that count (live records: archived and terminally set-aside ones are left out by the provider).
        done: How many of them have reached the provider's settled outcome. Never above `total`.
    """

    total: int
    done: int

    @property
    def outstanding(self) -> int:
        """The records that have not reached the settled outcome."""
        return self.total - self.done


@dataclass(frozen=True)
class HealthProvider:
    """How a record type reports its progress to the governance health view (a share complete, or a count outstanding).

    Attributes:
        key: Stable identifier, unique within its module; the registry namespaces it as `<module_key>:<key>`.
        label: Formal plural display name of the category (`"Requirements"`).
        artefact_type: The registered type the figures describe. The view shows the category only to a person who may
            read the type (`view`) in the project, so a figure never reveals records they cannot open.
        kind: `completion` headlines the share that is done; `outstanding` headlines the count that is not (a question
            still open).
        measure: `measure(db, project_id)` returns the project's own records of the type (never a related project's) as a
            `HealthMeasure`, or `None` when the project reports no figure for the category (a switch that governs it is
            off). It reads in bulk, never commits and never lists records one at a time.
        sub_component: As `PolicyResolver.sub_component`.
        open_to_members: The figure describes something every member of the project may see (the project's stages), not
            records a `view` permission on `artefact_type` governs, so the view shows it to every member. `artefact_type`
            then names the audit entity type whose events change the figure.
    """

    key: str
    label: str
    artefact_type: str
    kind: Literal["completion", "outstanding"]
    measure: Callable[[Session, uuid.UUID], HealthMeasure | None]
    sub_component: str | None = None
    open_to_members: bool = False


@dataclass(frozen=True)
class RuleConditionField:
    """One property of a record that a traceability rule's "applies when" condition may test.

    Attributes:
        key: The stable field key stored in rules (`"requirement_type_rank"`); unique across every module.
        label: Formal display name for the rule editor.
        value_kind: `"text"` (compared as text, ignoring case) or `"number"` (compared as whole numbers).
        values: `(db, project_id, artefact_type, record_ids) -> {record id: values}`, read in bulk for the records of one
            project; a record with no value is absent (or maps to an empty list). A record may hold several values (a tag
            set), and a condition holds when any of them satisfies it.
        options: Optional `(db, project_id, artefact_type) -> value choices` the editor offers; `None` when any value may
            be typed.
        artefact_types: The record types the field applies to; empty means every registered type.
        sub_component: A sub-component of the registering module that must be in effect for the field to apply.
    """

    key: str
    label: str
    value_kind: Literal["text", "number"]
    values: Callable[[Session, uuid.UUID, str, Sequence[uuid.UUID]], Mapping[uuid.UUID, Sequence[str | int]]]
    options: Callable[[Session, uuid.UUID, str], Sequence[str]] | None = None
    artefact_types: tuple[str, ...] = ()
    sub_component: str | None = None


RecordSubtypeResolver = Callable[[Session, uuid.UUID, Sequence[uuid.UUID]], dict[uuid.UUID, str]]
"""`resolver(db, project_id, record_ids)` returns each record's sub-type key (a Decision Type name, an action type name),
for the records that have one. A record without a sub-type is absent. It reads in bulk, never per record."""
