"""
Module: modules.compliance.models

The Compliance Module's data model (docs/Compliance_Module_Requirements.md
§2, §5, §6, §25, §31; docs/compliance-module-plan.md Phase 5) — organisation-
level, reusable compliance standard definitions. Project-specific assessment
state (§7-§16) is deliberately **not** part of this file: per §31's "A
Compliance Requirement must not contain the compliance state of a project,"
that belongs to `ProjectCompliance`/`ProjectComplianceRequirement`, built in
Phase 7 on top of these tables, not alongside them.

Shape, per §25's conceptual data model:

    ComplianceStandard (org-level identity row)
        `-- ComplianceStandardVersion (versioned content, §4)
                `-- ComplianceRequirement (hierarchical, self-referential, §5)
                        `-- ComplianceRequiredAction (§6)

    ComplianceActionTypeDefinition (org-level, extensible vocabulary, §6)

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

External dependencies: none beyond this project's own ORM/config modules.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.modules.compliance.enums import ComplianceStandardVersionStatus


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
