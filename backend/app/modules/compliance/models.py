"""
Module: modules.compliance.models

The Compliance Module's data model. Phase 5 (docs/Compliance_Module_
Requirements.md §2, §5, §6, §25, §31) built the organisation-level, reusable
compliance standard definitions. Phase 7 (§7-§11, §16, §20, §25, §26) adds
the project-specific assessment layer on top of them: per §31's "A
Compliance Requirement must not contain the compliance state of a project,"
that state was deliberately kept off `ComplianceRequirement`/
`ComplianceRequiredAction` and lives in the three models at the bottom of
this file instead.

Shape, per §25's conceptual data model:

    ComplianceStandard (org-level identity row)
        `-- ComplianceStandardVersion (versioned content, §4)
                `-- ComplianceRequirement (hierarchical, self-referential, §5)
                        `-- ComplianceRequiredAction (§6)

    ComplianceActionTypeDefinition (org-level, extensible vocabulary, §6)

    Project
        `-- ProjectCompliance (a project's assignment to one standard version, §7)
                `-- ProjectComplianceRequirement (per-requirement assessment, §8-§10)
                        `-- ComplianceRequiredActionAssessment (per-required-action assessment, §6/§25)

Design decisions:
- `ComplianceStandard`/`ComplianceStandardVersion` follow the `Requirement`/
  `RequirementVersion` identity-row + versioned-child-row shape the plan's
  Phase 5 spec calls for, but *not* that pair's valid_from/valid_to temporal
  semantics: a `RequirementVersion` superseded by a newer one is history,
  while every `ComplianceStandardVersion` remains independently live and
  addressable indefinitely, since different projects may deliberately stay
  pinned to different past versions forever (§4's worked example — Project A
  on v1.1, Project B on v1.0). Versions are instead ordered and made
  immutable by `version_number` + `status` (draft -> published -> retired),
  not superseded by a newer row.
- `ComplianceRequirement`'s self-referential `parent_requirement_id` is a
  plain foreign key with no ORM `relationship()`, matching `Project.
  parent_project_id`'s own precedent (hierarchy traversal is a service-layer
  concern, not something the ORM needs to model directly) rather than
  `Requirement`/`RequirementVersion`'s `relationship()`-backed pattern, which
  exists there to walk a *single* linear version history rather than an
  arbitrary-depth tree.
- `ComplianceRequiredAction` belongs to exactly one `ComplianceRequirement`
  (a plain one-to-many foreign key), unlike `RequirementAction`, which is
  many-to-many with requirements via `RequirementActionLink`. §25's data
  model diagram places "Required Actions" as a direct child of "Compliance
  Requirements" with no separate mapping table, and nothing in §6 asks for
  one required action to be reused verbatim across multiple compliance
  requirements the way a `RequirementAction` can be reused across
  requirements within a project.
- §6 also lists "Status," "Assignee," "Due date," "Completion information,"
  and "Evidence" as things a Required Action "should support" — those are
  the *project-specific assessment* of a required action (§25's "Required
  Action Assessments," nested under "Project Compliance Requirements," not
  under "Required Actions"), and so belong to Phase 7's per-project
  assessment model, not to this reusable definition — the same §31
  principle that keeps compliance state off `ComplianceRequirement` applies
  identically one level down.
- "Review schedule" (§2, one of a standard's listed attributes) is
  satisfied by Phase 10's dedicated `ComplianceReview` entity (§17: "
  Compliance Standards and Project Compliance records must support
  scheduled reviews"), not a scalar field here — §25's diagram places
  "Compliance Reviews" as its own entity, not a column.
- "Appropriate audit/history information" (§2) is satisfied by
  `TimestampMixin`'s `created_at`/`updated_at` plus Phase 6's
  `services.audit.log_event` integration on every mutating endpoint, not a
  bespoke history column here.
- `ComplianceStandard`'s "Status" attribute (§2) is satisfied by the
  existing `is_archived`/`archived_at`/`archived_by` soft-delete convention
  already used by `Requirement`/`RequirementAction`, not a separate status
  enum — a standard's own active/archived lifecycle is independent of its
  versions' draft/published/retired lifecycle (`ComplianceStandardVersion.
  status`), which is what actually needs a dedicated enum (§4).
- `ComplianceActionTypeDefinition` mirrors `ActionTypeDefinition`'s existing
  extensible-vocabulary pattern (§6: "Action types should preferably be
  configurable/extensible rather than hard-coded"), but is organisation-
  scoped rather than project-scoped: a required action's type is chosen
  within a Compliance Standard, which is itself an organisation-level,
  cross-project resource (§2's "must be capable of being assigned to
  multiple projects"), so the vocabulary it draws from is scoped the same
  way. No rows are seeded by this phase — Phase 5 is data model only; seed
  data (including §6's "potential initial action types") lands in Phase 15,
  per this plan's own precedent of shipping empty, extensible tables ahead
  of any seed step (see module system Phase 1's notes on
  `organization_module_entitlements`/`organization_modules`).

Phase 7 design decisions:
- `ProjectCompliance.standard_version_id` may only ever be set to a
  `PUBLISHED` version (enforced at the API layer, `router.py::
  create_project_compliance`) — a `DRAFT` version's requirements aren't
  fixed yet, and `ComplianceStandardVersionStatus.RETIRED`'s own docstring
  already states a retired version is "no longer assignable to **new**
  projects." An existing assignment stays on its version regardless of
  that version's later lifecycle changes (§4, §27) — nothing here ever
  moves `standard_version_id` to a different row.
- "Compliance Officer(s)" (§7's own field list for `ProjectCompliance`) is
  **not** a column on this model — it's already fully answered by
  `UserModuleRole` rows for `(module_key="compliance", role_key=
  "compliance_officer", project_id=...)` (module system Phase 2), which
  the existing `GET/POST /projects/{project_id}/members/{user_id}/
  module-roles` endpoints already expose. Duplicating that as a second
  field here would create two sources of truth for the same fact.
- "Review schedule" (§7's field list) is, like §2's identical field on
  `ComplianceStandard`, satisfied by Phase 10's dedicated `ComplianceReview`
  entity, not a column here — see this file's Phase 5 notes above for the
  identical reasoning applied to the standard-level case.
- `ProjectComplianceRequirement.explicit_applicability` is nullable —
  `None` means "never explicitly decided," distinct from an explicit
  `APPLICABLE` decision, even though both currently *resolve* to the same
  effective value absent an ancestor override. This is what lets
  `service.py::resolve_applicability` distinguish "the ordinary, untouched
  default" from "a user actively confirmed this is applicable" if a future
  phase ever needs to (today both render as the same `EXPLICIT` source —
  see `ComplianceApplicabilitySource`'s own docstring).
- A single `justification` column serves both §9's "Not Applicable
  justification" and §16's "rationale... required for Non-Compliant
  decisions" — §8 itself lists this as one field ("Justification/
  rationale"), and the two are never needed simultaneously in practice (a
  row is either Not Applicable *or* Applicable-and-assessed, never both at
  once). Enforced as mandatory, at the API layer, exactly when
  `explicit_applicability` is being set to `NOT_APPLICABLE` or
  `compliance_status` is being set to `NON_COMPLIANT` — never a NOT NULL
  constraint, since it is conditionally required depending on which other
  field is changing.
- `ProjectComplianceRequirement.approval_state` exists now (default
  `NOT_ASSESSED`) but no endpoint in this phase changes it — see this
  file's enums module docstring for why the column can't wait for Phase 9
  without splitting one coherent piece of the data model across two
  phases, mirroring the same reasoning Phase 5's own notes already recorded
  for `ComplianceStandardVersionStatus`.
- Every `ComplianceRequirement` in an assigned version — section/parent
  rows and leaf rows alike — gets its own `ProjectComplianceRequirement`
  row, materialised once, in full, at `ProjectCompliance` creation time
  (`router.py::create_project_compliance`), not lazily on first access.
  This deliberately does not special-case "does this requirement have
  children" — the tree structure only matters for applicability
  inheritance (§9) and requirement-count totals (§20), not for which rows
  exist. Same materialisation for `ComplianceRequiredActionAssessment` —
  one row per `ComplianceRequiredAction` under the version, created at the
  same time. A version's requirement/required-action set is immutable
  once published (Phase 6's own enforcement), so there is nothing to
  reconcile later: the set materialised at assignment time is permanently
  complete for that assignment.
- `ComplianceRequiredActionAssessment` mirrors `Requirement`'s own
  "completion overlay" shape (`is_completed`/`completed_at`/`completed_by`,
  see `Requirement.completed_at`'s own docstring) rather than reusing the
  `ComplianceStatus` enum — a required action is closer to a task than to
  something needing degrees of compliance, and §6's own field list
  ("Status, Assignee, Due date, Completion information") reads as a task's
  fields, not a re-assessment's.
- Evidence linkage is deliberately absent from every model in this file —
  Phase 8 owns it, following `services/files.py::upload_file`'s existing
  join-table-per-owner-type convention; adding a placeholder column now
  would just need reconciling away later, the same call Phase 5 already
  made about its own standard-level fields.

External dependencies: none beyond this project's own ORM/config modules.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.modules.compliance.enums import (
    ComplianceApplicability,
    ComplianceApprovalState,
    ComplianceStandardVersionStatus,
    ComplianceStatus,
)


class ComplianceStandard(UUIDPKMixin, TimestampMixin, Base):
    """An organisation-level, reusable compliance standard (§2) — e.g.
    "Corporate Security Standard." Not a project: per §31, "A Compliance
    Standard is not a Project" and "Compliance Standards are organisation-
    level reusable definitions."

    Attributes:
        organization_id: The owning organisation. A standard is defined
            once and assignable to any number of that organisation's
            projects (§2, §7) — never duplicated per project (§2's "A
            project must not need to duplicate the underlying compliance
            requirements simply because multiple projects use the same
            standard").
        reference: Human-readable identifier/reference code (§2), e.g.
            "ISO-27001", unique within the organisation.
        name: Display name, e.g. "Corporate Security Standard."
        description: Free-text description.
        issuing_organisation: The external body that issues/owns this
            standard, where applicable (§2) — e.g. "ISO." `None` for an
            internally-authored standard.
        owner_id: The user accountable for this standard (§2's "Owner"),
            distinct from `creator_id` — mirrors `RequirementVersion.
            owner_id` being distinct from `created_by`, since ownership may
            be reassigned after creation while authorship never changes.
        creator_id: The user who created this standard (audit fact, never
            reassigned).
        is_archived / archived_at / archived_by: Soft-delete / lifecycle
            state, mirroring `Requirement.is_archived`'s convention exactly
            — this satisfies §2's "Status" attribute; see this module's own
            docstring for why a separate status enum wasn't introduced.
        versions: This standard's versions, ordered by `version_number` —
            mirrors `Requirement.versions`'s identical shape (the precedent
            this model explicitly follows), unlike `ComplianceRequirement`'s
            self-referential hierarchy below, which deliberately has no
            ORM `relationship()` (see this module's own docstring).
    """

    __tablename__ = "compliance_standards"
    __table_args__ = (UniqueConstraint("organization_id", "reference"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    reference: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    issuing_organisation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    versions: Mapped[list[ComplianceStandardVersion]] = relationship(
        back_populates="standard", order_by="ComplianceStandardVersion.version_number"
    )


class ComplianceStandardVersion(UUIDPKMixin, TimestampMixin, Base):
    """A single version of a `ComplianceStandard` (§4) — e.g. "v1.1." Every
    version, published or retired, remains independently addressable
    indefinitely (see this module's own docstring for why this isn't a
    valid_from/valid_to temporal model): a `ProjectCompliance` assignment
    (Phase 7) references one specific version and must keep doing so even
    after newer versions are published (§4, §27, §31).

    Attributes:
        standard_id: The owning `ComplianceStandard`.
        version_number: Sequential ordering among this standard's versions
            (1, 2, 3, ...), used for `versions` ordering and to detect "is
            this the latest version" without string-parsing `version_label`.
        version_label: The human-facing version string (§4's examples:
            "1.0", "1.1", "2.0") — independent of `version_number` since a
            standard's own versioning scheme (semantic, date-based, ...) is
            display metadata, not this table's ordering key.
        status: Draft/published/retired lifecycle (§4) — see
            `ComplianceStandardVersionStatus`. A published version's
            requirements become immutable (enforced at the API layer,
            Phase 6); this table only records the state, not the
            enforcement.
        effective_date: When this version takes effect, where applicable
            (§2).
        change_note: Free-text summary of what changed relative to the
            previous version — supports §27's "users should be able to see
            what changed between standard versions" (full structured
            diffing is Phase 11; this is the author's own summary,
            mirroring `RequirementVersion.change_note`).
        created_by: The user who created this version.
        published_at / published_by / retired_at / retired_by: Lifecycle
            transition stamps, mirroring `Requirement.archived_at/
            archived_by`'s convention of a timestamp+actor pair per
            transition rather than overloading `updated_at`.
    """

    __tablename__ = "compliance_standard_versions"
    __table_args__ = (UniqueConstraint("standard_id", "version_number"),)

    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standards.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    version_label: Mapped[str] = mapped_column(String(50))
    status: Mapped[ComplianceStandardVersionStatus] = mapped_column(
        str_enum(ComplianceStandardVersionStatus, 20), default=ComplianceStandardVersionStatus.DRAFT
    )
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    standard: Mapped[ComplianceStandard] = relationship(back_populates="versions")


class ComplianceRequirement(UUIDPKMixin, TimestampMixin, Base):
    """A single compliance requirement within a standard version (§5) — e.g.
    "Equipment shall meet IPX9 water ingress requirements." Purely
    definitional: per §31, "A Compliance Requirement must not contain the
    compliance state of a project."

    Attributes:
        standard_version_id: The owning `ComplianceStandardVersion`.
        parent_requirement_id: Optional parent for section/subsection
            hierarchy (§5's "support hierarchy/parent-child relationships
            so that standards can be structured into sections and
            subsections"). A plain foreign key with no ORM `relationship()`
            — see this module's own docstring for why this mirrors
            `Project.parent_project_id` rather than `RequirementVersion`'s
            pattern. `ondelete="CASCADE"`: deleting a section requirement
            removes its subsections with it, unlike `Project`'s `SET NULL`
            (a compliance requirement has no "stand alone once detached"
            concept the way a project does).
        reference: Optional section/clause numbering (e.g. "3.2.1"),
            distinct from the row's own UUID `id`.
        name: The requirement's own text/title.
        description: Free-text elaboration.
        reasoning: Why this requirement exists — mirrors `RequirementVersion.
            reasoning` (§5's "should support the information and metadata
            appropriate to existing ReqTrackManager requirements where
            practical").
        sort_order: Display/ordering position among sibling requirements.
        created_by: The user who created this requirement.
    """

    __tablename__ = "compliance_requirements"

    standard_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standard_versions.id", ondelete="CASCADE"), index=True
    )
    parent_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="CASCADE"), nullable=True, index=True
    )
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ComplianceRequiredAction(UUIDPKMixin, TimestampMixin, Base):
    """A required action definition needed to demonstrate a compliance
    requirement is met (§6) — e.g. "Perform IPX9 water ingress test."
    "Required Action" rather than "Test," since demonstrating compliance may
    involve activities other than testing (§6).

    Purely definitional, like `ComplianceRequirement` — the per-project
    assessment of a required action (status, assignee, due date, completion
    information, evidence) is Phase 7's "Required Action Assessment" (§25),
    not this row; see this module's own docstring.

    Attributes:
        requirement_id: The owning `ComplianceRequirement`. A plain
            one-to-many foreign key, not a many-to-many link table — see
            this module's own docstring for why this differs from
            `RequirementAction`/`RequirementActionLink`.
        action_type_id: Which `ComplianceActionTypeDefinition` this action
            is. No `ondelete` (implicit RESTRICT), mirroring
            `RequirementAction.action_type_id` exactly — an in-use action
            type must not be deletable out from under it.
        name: The action's own name/description (§6).
        description: Free-text elaboration.
        is_mandatory: Whether this action is mandatory for the requirement
            to be considered met (§6).
        sort_order: Display/ordering position among sibling required
            actions.
        created_by: The user who created this required action.
    """

    __tablename__ = "compliance_required_actions"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="CASCADE"), index=True
    )
    action_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_action_type_definitions.id")
    )
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ComplianceActionTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """An organisation-defined required-action type (e.g. "Test,"
    "Inspection," "Document Review") — mirrors `ActionTypeDefinition`'s
    existing extensible-vocabulary pattern (§6), but organisation-scoped
    rather than project-scoped; see this module's own docstring for why.

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique within the organisation.
        sort_order: Display/picker order among the organisation's action
            types.
    """

    __tablename__ = "compliance_action_type_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# --- Phase 7: project-specific compliance assessment ----------------------------


class ProjectCompliance(UUIDPKMixin, TimestampMixin, Base):
    """A project's assignment to one specific `ComplianceStandardVersion`
    (§7) — e.g. "Project A is assigned to Corporate Security Standard
    v3.1." The same standard may be assigned to many projects, and the
    same project may be assigned many standards (§7's own worked example);
    each `(project_id, standard_version_id)` pair is exactly one row.

    Attributes:
        project_id: The assigned project.
        standard_version_id: The specific standard version assigned — must
            be `PUBLISHED` at assignment time (enforced at the API layer,
            never a `DRAFT` or already-`RETIRED` version — see this
            module's own docstring). Stays pointed at this exact version
            row forever, even after that version is later retired or a
            newer version is published (§4, §27) — migrating to a newer
            version is a distinct, explicit, user-triggered action (Phase
            11), never an implicit effect of this row's own lifecycle.
        assigned_at / assigned_by: When/who made this assignment (§7's
            "Date assigned").
        target_compliance_date: Optional target date for the project to
            reach full compliance (§7) — distinct from any individual
            required action's own due date.
        is_archived / archived_at / archived_by: Soft-delete, mirroring
            `ComplianceStandard`'s own convention — used when a project no
            longer needs to track compliance against this standard.
            Deliberately never a hard delete: the `ProjectComplianceRequirement`
            rows underneath carry real assessment/audit history (§16) that
            must survive a project deciding to stop tracking a standard.
    """

    __tablename__ = "project_compliances"
    __table_args__ = (UniqueConstraint("project_id", "standard_version_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    standard_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standard_versions.id"), index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    target_compliance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ProjectComplianceRequirement(UUIDPKMixin, TimestampMixin, Base):
    """One project's assessment of one `ComplianceRequirement` (§8) —
    "Requirement 1 -> Compliant" in §8's own worked example. Deliberately
    separate from `ComplianceRequirement` itself: the same requirement has
    a different `ProjectComplianceRequirement` row per project that's
    assigned the standard it belongs to (§8: "This allows the same
    requirement to have different compliance states for different
    projects").

    One row exists per `(project_compliance_id, requirement_id)` pair,
    materialised in full when the owning `ProjectCompliance` is created —
    see this module's own docstring.

    Attributes:
        project_compliance_id: The owning `ProjectCompliance` assignment.
        requirement_id: The `ComplianceRequirement` this row assesses.
        explicit_applicability: This row's own, directly-set applicability
            decision, or `None` if never explicitly set (§9). See this
            module's own docstring for why `None` is distinct from an
            explicit `APPLICABLE`. The *effective* applicability (after
            hierarchical inheritance, §9's "Hierarchical Applicability") is
            never stored — it's computed by `service.py::
            resolve_applicability`.
        justification: Mandatory (enforced at the API layer, not a NOT NULL
            constraint) when `explicit_applicability` is being set to
            `NOT_APPLICABLE` (§9) or `compliance_status` is being set to
            `NON_COMPLIANT` (§16) — see this module's own docstring for why
            one field serves both.
        notes: Free-text notes (§8), independent of `justification`.
        compliance_status: This project's assessed compliance state
            against this requirement (§10), independent of applicability
            (§10: "Applicability should remain separate from compliance
            status").
        assessed_at / assessed_by: When/who last changed `compliance_status`
            (§8's "Assessment date"/"Assessed by") — set automatically by
            the assessment endpoint, never caller-supplied.
        applicability_set_at / applicability_set_by: When/who last changed
            `explicit_applicability` — set automatically by the
            applicability endpoint, never caller-supplied. `None` until
            `explicit_applicability` is set for the first time.
        approval_state: Reserved for Phase 9's approval/sign-off workflow
            (§12) — see this module's own docstring and the enums module's
            docstring for why this column exists a phase ahead of the
            workflow that transitions it.
    """

    __tablename__ = "project_compliance_requirements"
    __table_args__ = (UniqueConstraint("project_compliance_id", "requirement_id"),)

    project_compliance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_compliances.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id"), index=True
    )
    explicit_applicability: Mapped[ComplianceApplicability | None] = mapped_column(
        str_enum(ComplianceApplicability, 20), nullable=True
    )
    justification: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    compliance_status: Mapped[ComplianceStatus] = mapped_column(
        str_enum(ComplianceStatus, 20), default=ComplianceStatus.NOT_STARTED
    )
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assessed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    applicability_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applicability_set_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approval_state: Mapped[ComplianceApprovalState] = mapped_column(
        str_enum(ComplianceApprovalState, 24), default=ComplianceApprovalState.NOT_ASSESSED
    )


class ComplianceRequiredActionAssessment(UUIDPKMixin, TimestampMixin, Base):
    """One project's assessment of one `ComplianceRequiredAction` (§6's
    "Status, Assignee, Due date, Completion information," §25's "Required
    Action Assessments" nested under "Project Compliance Requirements").

    One row exists per `(project_compliance_requirement_id,
    required_action_id)` pair, materialised in full alongside its owning
    `ProjectComplianceRequirement` — see this module's own docstring.

    Attributes:
        project_compliance_requirement_id: The owning per-project
            requirement assessment.
        required_action_id: The `ComplianceRequiredAction` this row
            assesses.
        assignee_id: Who is responsible for this required action, or
            `None` if unassigned (§6's "Assignee").
        due_date: Optional due date (§6).
        is_completed / completed_at / completed_by: Completion overlay,
            mirroring `Requirement.completed_at`'s own shape — see this
            module's own docstring for why this shape rather than reusing
            `ComplianceStatus`.
        notes: Free-text notes.
    """

    __tablename__ = "compliance_required_action_assessments"
    __table_args__ = (
        UniqueConstraint("project_compliance_requirement_id", "required_action_id"),
        # Explicit, shortened index name: `index=True`'s auto-generated
        # `ix_compliance_required_action_assessments_project_compliance_
        # requirement_id` is 75 characters, over Postgres's 63-byte
        # identifier limit — Postgres silently truncates it at DDL time,
        # which then never matches SQLAlchemy's own (untruncated) computed
        # name and permanently fails `test_schema_migrations_match_models.py`
        # regardless of what the migration itself names it. No other
        # table/column combination in this codebase is long enough to hit
        # this limit (confirmed by inspecting every table's own indexes).
        Index(
            "ix_required_action_assessments_pcr_id", "project_compliance_requirement_id"
        ),
    )

    project_compliance_requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_compliance_requirements.id", ondelete="CASCADE")
    )
    required_action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_required_actions.id"), index=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
