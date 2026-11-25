"""
Module: modules.seams

Contracts for the registration points a module uses to take part in core behaviour it does not own: a permission atom
it contributes, the sub-type of a record, a review schedule, a pre-baseline check, a policy for one of the core
engine seams (lifecycle move, approval check, review, baseline check) and a table of policy rows a governance profile
can own.

Responsibilities:
- Define the frozen dataclasses `ModuleDefinition` carries (`administrative_permissions`, `record_subtypes`,
  `review_adapters`, `baseline_check_providers`, `policy_resolvers`, `profile_contributors`); `registry.py` merges them
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.enums import OrgRole, ProjectRole

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
    (`services.lifecycles.check_move`, the approval check, the review engine, the baseline check)."""

    LIFECYCLE = "lifecycle"
    APPROVAL = "approval"
    REVIEW = "review"
    BASELINE = "baseline"


@dataclass(frozen=True)
class PolicyResolver:
    """A module's answer to "which policy applies" for one core seam.

    Attributes:
        seam: The seam it answers for.
        resolve: `resolve(db, project_id, artefact_type)` returns the seam's policy object for the type in the project,
            or `None` when the module has no policy there, in which case the next resolver or the type's built-in default
            applies. It reads only and never commits. The policy object's shape belongs to the seam.
        sub_component: The sub-component of the registering module that must be effective in the project for the resolver
            to be asked; `None` means the whole module being on is enough.
    """

    seam: GovernanceSeam
    resolve: Callable[[Session, uuid.UUID, str], Any | None]
    sub_component: str | None = None


@dataclass(frozen=True)
class DueReview:
    """One record whose review falls due.

    Attributes:
        artefact_id: The record's id.
        due_on: The calendar date the review is due.
    """

    artefact_id: uuid.UUID
    due_on: date


@dataclass(frozen=True)
class ReviewAdapter:
    """How the review engine reads one artefact type's review schedule.

    Attributes:
        schedule: `review_record` when a review is a separate row and the record leaves the due list because a review
            dated on or after the due date exists (requirements); `next_review_date` when completing a review writes
            the record's next review date (risks). The engine supports both.
        due_reviews: `due_reviews(db, project_id, as_of)` returns the project's records whose review is due on or before
            `as_of`, oldest first. It reads only.
    """

    schedule: Literal["review_record", "next_review_date"]
    due_reviews: Callable[[Session, uuid.UUID, date], Sequence[DueReview]]


@dataclass(frozen=True)
class BaselineCheckContext:
    """What a baseline check is told about the baseline being written.

    Attributes:
        project_id: The project being baselined.
        kind: `stage` (a stage entering a locked phase, which is itself the approval act for drafts) or `manual`.
        actor_id: The person who triggered the baseline.
    """

    project_id: uuid.UUID
    kind: Literal["stage", "manual"]
    actor_id: uuid.UUID | None


@dataclass(frozen=True)
class BaselineCheckFailure:
    """One reason a baseline is refused.

    Attributes:
        artefact_type: The failing record's registered type.
        artefact_id: The failing record's id.
        check_key: The `BaselineCheckProvider.key` that failed.
        message: Formal sentence naming what is missing; carries no personal data.
    """

    artefact_type: str
    artefact_id: uuid.UUID
    check_key: str
    message: str


@dataclass(frozen=True)
class BaselineCheckProvider:
    """A check run before a baseline is taken. One failing check refuses the whole baseline, listing every failure.

    Attributes:
        key: Stable identifier, unique within its module; the registry namespaces it as `<module_key>:<key>`.
        name: Formal display name shown where a failure is listed.
        artefact_types: The registered types the check inspects, so a baseline that holds none of them skips it.
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


RecordSubtypeResolver = Callable[[Session, uuid.UUID, Sequence[uuid.UUID]], dict[uuid.UUID, str]]
"""`resolver(db, project_id, record_ids)` returns each record's sub-type key (a Decision Type name, an action type name),
for the records that have one. A record without a sub-type is absent. It reads in bulk, never per record."""
