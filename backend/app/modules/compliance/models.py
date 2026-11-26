"""
Module: modules.compliance.models

The Compliance Module's data model: the organisation-level, reusable standard definitions (§2, §5, §6, §25, §31) and, on
top of them, the project assessment layer (§7-§11, §16, §20, §25, §26). Per §31 ("A Compliance Requirement must not
contain the compliance state of a project") project state lives only in the project-level models.

    ComplianceStandard (organisation-level identity row)
        `-- ComplianceStandardVersion (versioned content, §4)
                `-- ComplianceRequirement (hierarchical, self-referential, §5)
                        `-- ComplianceRequiredAction (§6)
    ComplianceActionTypeDefinition (organisation-level, extensible vocabulary, §6)

    Project
        `-- ProjectCompliance (assignment to one standard version, §7)
                `-- ProjectComplianceRequirement (per-requirement assessment, §8-§10)
                        `-- ComplianceRequiredActionAssessment (per-required-action assessment, §6/§25)

Design decisions, standard definitions:
- `ComplianceStandard` / `ComplianceStandardVersion` are an identity row plus versioned child rows but without
  `valid_from` / `valid_to`: every version stays live and addressable, because projects may stay pinned to different past
  versions (§4). Versions are ordered and made immutable by `version_number` and `status` (draft, published, retired).
- `ComplianceRequirement.parent_requirement_id` is a plain foreign key with no ORM `relationship()` (as
  `Project.parent_project_id`): tree traversal is a service concern.
- A `ComplianceRequiredAction` belongs to exactly one requirement (§25 has no mapping table). Its status, assignee, due
  date, completion and evidence (§6) belong to `ComplianceRequiredActionAssessment` (§31 one level down).
- "Review schedule" (§2, §7) is the `ComplianceReview` entity (§17), not a column. Audit and history (§2) come from
  `TimestampMixin` and `services.audit.log_event`. A standard's status is the `is_archived` soft delete, independent of
  its versions' lifecycle.
- `ComplianceActionTypeDefinition` is an extensible vocabulary (§6) scoped to the organisation, as the standard that
  draws on it is (§2); the table ships empty and seeding is separate.

Design decisions, project assessment:
- `ProjectCompliance.standard_version_id` is only ever a `PUBLISHED` version (API layer, `router.create_project_compliance`)
  and never moves to another row, whatever the version's later lifecycle (§4, §27).
- "Compliance Officer(s)" (§7) is not a column: `UserModuleRole` rows for `(compliance, compliance_officer, project_id)`
  already answer it, and a second field would be a second source of truth.
- `explicit_applicability` is nullable: `None` is "never decided", distinct from an explicit `APPLICABLE` although both
  resolve alike (`service.resolve_applicability`).
- One `justification` column serves §9's Not Applicable justification and §16's Non-Compliant rationale (§8 lists one
  field). The API requires it exactly when `explicit_applicability` becomes `NOT_APPLICABLE` or `compliance_status`
  becomes `NON_COMPLIANT`; it is never a NOT NULL constraint.
- `approval_state` (default `NOT_ASSESSED`) is changed only by the approval workflow. `approval_decided_at`,
  `approval_decided_by` and `decision_note` serve both approval and rejection (`approval_state` says which); the
  assessment timestamps reuse `assessed_at` / `assessed_by` (§12). There is no submission timestamp and no approval
  history table: `services.audit.log_event` rows (`project_router.get_requirement_history`) carry both. The transitions
  (§12) are business logic in `service.py` and the approval endpoints.
- Every requirement of an assigned version, section and leaf rows alike, gets a `ProjectComplianceRequirement` (and every
  required action a `ComplianceRequiredActionAssessment`) materialised in full when the `ProjectCompliance` is created
  (`router.create_project_compliance`), not lazily. The tree matters only for applicability inheritance (§9) and totals
  (§20); a published version is immutable, so the set never needs reconciling.
- `ComplianceRequiredActionAssessment` has the `is_completed` / `completed_at` / `completed_by` completion overlay of
  `Requirement`, not `ComplianceStatus`: a required action is a task.

Design decisions, cross-standard mapping:
- `ComplianceRequirement.cloned_from_requirement_id` (nullable, self-referential, `ondelete="SET NULL"`) records the
  source requirement when `router._clone_requirement_tree` creates a version from another. §27's added, removed,
  modified, replaced and re-mapped classification needs a durable lineage: names alone cannot tell a renamed and edited
  requirement from a removal plus an unrelated addition. `SET NULL`, not `CASCADE` as for `parent_requirement_id`,
  because a cloned requirement is an independent row of a published version that must survive deletion of its draft
  source; a missing lineage is treated as `added` (`service.diff_standard_versions`, which also walks multi-hop lineage).
- `ComplianceMappingRelationshipTypeDefinition` is an organisation-scoped, extensible vocabulary (§19), shaped like
  `ComplianceActionTypeDefinition`, with no seed rows. Its table is `compliance_mapping_relationship_types` because the
  longer auto-generated `organization_id` index name exceeds Postgres's 63-byte identifier limit.
- `ComplianceRequirementMapping` records one directed relationship between two `ComplianceRequirement` rows (§19). It
  is not restricted to different standards: §27's `replaced` category reuses it for a same-standard, cross-version link.
  It is directed because relationship types such as "Derived From" are; a symmetric type is stored in a stable order.
  `organization_id` is stored directly so cross-organisation isolation (404, not 403) is one indexed column. A `CHECK`
  forbids `from_requirement_id = to_requirement_id`; `is_archived` / `archived_at` / `archived_by` keep a mapping
  auditable (§19); `UNIQUE (from, to, relationship_type_id)` allows several types between one pair.
- Per §19 a mapping never implies that satisfying one requirement satisfies another: no code reads a mapping to write
  an assessment value except one narrow path. Carrying an assessment forward across a `replaced` mapping requires two
  gates: the relationship type's `implies_equivalence` is `True` (an organisation decision, default `False`, no fixed
  list of type names), and the compliance officer lists that requirement's id in
  `ProjectComplianceMigrationRequest.confirmed_replacement_requirement_ids` for that migration. A carried `replaced`
  row always has `requires_reassessment` true, because the wording changed (`service.migrate_project_compliance`).

Design decisions, evidence:
- `ComplianceEvidence` is project-scoped (`project_id`): it is supplied for one project's assessment but may support
  several of that project's requirements and required actions (§13). That many-to-many is `ArtefactLink` rows with
  `source_type=COMPLIANCE_EVIDENCE` and `target_type` `PROJECT_COMPLIANCE_REQUIREMENT` or
  `COMPLIANCE_REQUIRED_ACTION_ASSESSMENT`: the assessment rows, not the reusable definitions (§31).
- `expiry_date` is the current expiry, updated in place by a revalidation (§15). `ComplianceEvidenceRevalidation` is
  append-only so each revalidation's previous expiry stays visible.
- `ComplianceEvidenceFile` has the shape of `app.models.file.RequirementFile` but lives here because it is
  Compliance-owned; §13 reuses the file mechanism (`services.files.upload_file`), not core's owner-specific tables.
- `is_archived` / `archived_at` / `archived_by` answer "Whether it remains applicable" (§13); a hard delete would sever
  `ArtefactLink` rows the assessments' audit trail (§16) depends on.

Design decisions, reviews:
- `ComplianceReview` has exactly one of `standard_id` / `project_compliance_id` (`CheckConstraint`): §17 names two owners.
- `frequency_label` (free text) plus nullable `recurrence_days` (`None` is one-off) replace a calendar enum, because
  §17 includes event-triggered reviews ("before product release").
- Review history (§17) is the retained rows: a completed row stays (`status` `COMPLETED`) and a recurring review gets a
  new `SCHEDULED` row for the next cycle (`service.complete_review`), so no history table exists.
- `ComplianceReviewEvidenceLink` is a dedicated many-to-many (not `ArtefactLink`, which covers evidence to requirement
  and required action assessment). The API, not the database, requires the evidence and review to share a project, so a
  standard-level review cannot link project evidence.
- Reminder bookkeeping (`*_reminder_sent_at`, `*_notified_at` on `ComplianceEvidence`,
  `ComplianceRequiredActionAssessment`, `ProjectCompliance`) lives on the owning row, as
  `RequirementVersion.review_reminder_sent_at` does, so sweeps do not re-notify.

Design decisions, applicability defaults:
- `ComplianceStandard.applicability_default` is a column on the standard (§3, §26): one setting, no history.
- `ComplianceStandardDefaultExclusion` joins `(standard_id, project_id)` with a mandatory `reason` (API-validated) and
  cascades on both keys.
- Reconciliation never creates a second `ProjectCompliance` for a project that already tracks the standard through any
  version (that would break the `(project_id, standard_version_id)` uniqueness or create a confusing concurrent
  assignment); it fills only the gap, targets the standard's current latest `PUBLISHED` version when it runs, and
  reconciles nothing for a standard with no published version (`service.reconcile_standard_applicability`, which reuses
  an exclusion-archived row on un-exclusion).
- Switching back to `OPT_IN` never archives rows an earlier reconciliation created: a real row carries a real
  assessment and audit trail (§8, §16). The default governs future reconciliation only.

Design decisions, post-publish clarification:
- `ComplianceStandardVersion.summary` and `ComplianceRequirement`'s four clarification columns are a narrow exception to
  immutability of a published version (`router._require_draft_version`): a manager-gated, mandatory-note edit
  (`router.clarify_requirement`) is not a silent change to assessed wording (§4, §31).
- `summary` is editable at any `status`; the schema shape (`ComplianceStandardVersionUpdate` carries only this field)
  makes it exempt from the draft gate, not only a runtime check.
- The clarification fields sit on the reusable `ComplianceRequirement` because they describe the requirement's own text,
  identical for every project, like `name` and `description`; they are not project state (§31).
- There is no substantive-versus-clarification flag: a text diff cannot be classified reliably, so the distinction is
  procedural (the dedicated `PATCH .../clarify` endpoint) and the mandatory `clarification_note` makes each use
  accountable.

External dependencies: this project's ORM and configuration modules only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column
from app.modules.compliance.enums import (
    ComplianceApplicability,
    ComplianceApprovalState,
    ComplianceReviewOutcome,
    ComplianceReviewStatus,
    ComplianceStandardApplicabilityDefault,
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
        owner_type / owner_id: The principal accountable for this standard
            (§2's "Owner") — a user or an organisation group
            (`models.principal`); mandatory. Distinct from `creator_id` —
            mirrors `RequirementVersion.owner_id` being distinct from
            `created_by`, since ownership may be reassigned after creation
            while authorship never changes. No foreign key;
            `services.principals.validate_principal` checks it on write and
            `module.py`'s `principal_references` guard group deletion.
        creator_id: The user who created this standard (audit fact, never
            reassigned).
        is_archived / archived_at / archived_by: Soft-delete / lifecycle
            state, mirroring `Requirement.is_archived`'s convention exactly
            — this satisfies §2's "Status" attribute; see this module's own
            docstring for why a separate status enum wasn't introduced.
        applicability_default: Whether this
            standard's default project-assignment mode is the ordinary
            per-project opt-in (`OPT_IN`, every standard's original behaviour) or an org-wide "applies to all projects
            by default, except..." mandate (`APPLIES_TO_ALL_PROJECTS`) —
            see `ComplianceStandardApplicabilityDefault`'s own docstring
            and the applicability defaults design decisions below
            for the reconciliation mechanism this drives.
        versions: This standard's versions, ordered by `version_number` —
            mirrors `Requirement.versions`'s identical shape (the precedent
            this model explicitly follows), unlike `ComplianceRequirement`'s
            self-referential hierarchy below, which deliberately has no
            ORM `relationship()` (see this module's own docstring).
    """

    __tablename__ = "compliance_standards"
    __table_args__ = (UniqueConstraint("organization_id", "reference"), principal_check_constraint("owner"))

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    reference: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    issuing_organisation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_type: Mapped[str] = principal_type_column()
    owner_id: Mapped[uuid.UUID] = principal_id_column()
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    applicability_default: Mapped[ComplianceStandardApplicabilityDefault] = mapped_column(
        str_enum(ComplianceStandardApplicabilityDefault, 30), default=ComplianceStandardApplicabilityDefault.OPT_IN
    )

    versions: Mapped[list[ComplianceStandardVersion]] = relationship(
        back_populates="standard", order_by="ComplianceStandardVersion.version_number"
    )


class ComplianceStandardVersion(UUIDPKMixin, TimestampMixin, Base):
    """A single version of a `ComplianceStandard` (§4) — e.g. "v1.1." Every
    version, published or retired, remains independently addressable
    indefinitely (see this module's own docstring for why this isn't a
    valid_from/valid_to temporal model): a `ProjectCompliance` assignment
 references one specific version and must keep doing so even
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
            requirements become immutable (enforced at the API layer);
            this table only records the state, not the
            enforcement.
        effective_date: When this version takes effect, where applicable
            (§2).
        change_note: Free-text summary of what changed relative to the
            previous version — supports §27's "users should be able to see
            what changed between standard versions" (full structured
            diffing is a separate diff endpoint; this is the author's own summary,
            mirroring `RequirementVersion.change_note`).
        summary: The version's *current* standing
            (distinct from `change_note`, which describes what changed
            *relative to the previous version*, not this version's own
            present state, e.g. noting an already-retired version is
            deprecated). Editable at any lifecycle stage — DRAFT/PUBLISHED/
            RETIRED alike — unlike every other field on this row, which is
            frozen once the version leaves DRAFT (`router.py::
            _require_draft_version`). See the post-publish clarification
            design decisions above.
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
    summary: Mapped[str] = mapped_column(Text, default="")
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
        cloned_from_requirement_id: The requirement (in an earlier version
            of the same standard) this row was cloned from, if any — set by
            `router.py::_clone_requirement_tree` when a new draft version
            is created from an existing one; `None` for a requirement
            authored directly (never cloned) or whose lineage record has
            since been detached (see the cross-standard mapping design decisions).
            `ondelete="SET NULL"`, deliberately *not* `CASCADE` (unlike
            `parent_requirement_id` above) — see the cross-standard mapping
            design decisions for the full reasoning. Consumed by `service.py::
            diff_standard_versions` (§27) to distinguish an unchanged/
            modified requirement (has lineage) from an added one (doesn't).
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
        clarification_count / last_clarified_at / last_clarified_by /
            last_clarification_note: A non-
            substantive wording correction/elaboration made to this
            requirement *after* its owning version was published (§4/§31's
            "must not silently alter... compliance assessment" is satisfied
            by this always being human-asserted via a mandatory note, never
            a mechanically-detected distinction — see `router.py::
            clarify_requirement`'s own docstring). `last_clarification_note`
            mirrors `ProjectComplianceRequirement.decision_note`'s already-
            established "last decision's own note lives on the row itself;
            the full history is the audit trail" precedent (see the approval workflow design
            decisions) rather than a new table —
            every clarification, including this one, is also logged via
            `services.audit.log_event` (action `"clarified"`), so nothing
            here is the sole record of a past clarification, only the most
            recent one, surfaced as a badge without a second round trip.
            `clarification_count` lets the badge say "clarified 3 times"
            without a `COUNT(*)` over the audit log on every requirement-
            tree render.
    """

    __tablename__ = "compliance_requirements"

    standard_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standard_versions.id", ondelete="CASCADE"), index=True
    )
    parent_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="CASCADE"), nullable=True, index=True
    )
    cloned_from_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    clarification_count: Mapped[int] = mapped_column(Integer, default=0)
    last_clarified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_clarified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    last_clarification_note: Mapped[str] = mapped_column(Text, default="")


class ComplianceRequiredAction(UUIDPKMixin, TimestampMixin, Base):
    """A required action definition needed to demonstrate a compliance
    requirement is met (§6) — e.g. "Perform IPX9 water ingress test."
    "Required Action" rather than "Test," since demonstrating compliance may
    involve activities other than testing (§6).

    Purely definitional, like `ComplianceRequirement` — the per-project
    assessment of a required action (status, assignee, due date, completion
    information, evidence) is the "Required Action Assessment" (§25),
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
    # Deferred so deleting an organisation (which cascades to both the org-level action types and,
    # through the standards, these rows) is not rejected by whichever cascade branch runs first;
    # an in-use type is still refused, at commit.
    action_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("compliance_action_type_definitions.id", deferrable=True, initially="DEFERRED"),
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


# --- project-specific compliance assessment ----------------------------


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
            version is a distinct, explicit, user-triggered action,
            never an implicit effect of this row's own lifecycle.
        assigned_at / assigned_by: When/who made this assignment (§7's
            "Date assigned").
        target_compliance_date: Optional target date for the project to
            reach full compliance (§7) — distinct from any individual
            required action's own due date.
        target_date_reminder_sent_at / target_date_overdue_notified_at:
            Sweep bookkeeping (§18/§28) — stamped the first time
            the "target date approaching"/"target date exceeded"
            notification has been sent for the *current*
            `target_compliance_date`, so the daily sweep
            (`scheduler.py::send_target_date_notifications`) never repeats
            either notification. Mirrors `RequirementVersion.review_
            reminder_sent_at`'s own single-stamp convention, split into two
            columns since "approaching" and "exceeded" are two independent
            notifications here (§18 lists them separately), not one.
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
    target_date_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_date_overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ComplianceStandardDefaultExclusion(UUIDPKMixin, TimestampMixin, Base):
    """Records that a specific project is excepted out of a standard's
    `APPLIES_TO_ALL_PROJECTS` default — the "...except" half of
    "applies to all projects by default, except...". A project on this list
    is never touched by `service.py::reconcile_standard_applicability`
    while the exclusion row exists; removing it (not deleting a
    `ComplianceStandard`/`Project` row) restores the project to the
    standard's default reconciliation the next time it runs, per this
    module's own `on_project_created`-style "reconciled at the moment of
    the triggering event" convention.

    Attributes:
        standard_id: The `ComplianceStandard` this exclusion applies to.
        project_id: The excluded project — must belong to the same
            organisation as `standard_id` (enforced at the API layer, this
            table carries no cross-table `CHECK`).
        excluded_by: The user (a Compliance Manager, or org/server admin)
            who added this exclusion.
        excluded_at: When the exclusion was added.
        reason: Mandatory justification (§16's established convention,
            mirroring the Not-Applicable/Non-Compliant/Rejection
            mandatory-rationale rule already enforced elsewhere in this
            module) — enforced at the API layer, not a DB constraint, same
            as every other mandatory-justification field in this module.
    """

    __tablename__ = "compliance_standard_default_exclusions"
    __table_args__ = (UniqueConstraint("standard_id", "project_id"),)

    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standards.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    excluded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    excluded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, default="")


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
        approval_state: The row's current position in §12's approval/
            sign-off state machine — see the approval workflow design decisions
            and `service.py` for the transition rules.
        approval_decided_at / approval_decided_by: When/who last decided
            this row's `approval_state` at the `approve`/`reject` step
            (§12's "Date/time of approval"/"Who approved/signed off") —
            `None` until the first such decision. Not set by `submit-for-
            approval` (that's a request, not a decision) or by the
            automatic transitions in `service.py` (those are system-
            derived, not a human decision).
        decision_note: Free-text rationale attached to the last `approve`/
            `reject` decision — mandatory (enforced at the API layer) for
            a rejection, optional for an approval. Independent of
            `justification`/`notes` (the assessment/applicability
            fields), which this column never overwrites or reads from.
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
    approval_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decision_note: Mapped[str] = mapped_column(Text, default="")
    # The person approval must be separate from (`approval.record_context`): the lifecycle engine reads a gated type's
    # creator through this name.
    creator_id = synonym("assessed_by")


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
        assignee_type / assignee_id: The principal (a user, an organisation
            group or a project group — `models.principal`) responsible for
            this required action, both `None` if unassigned (§6's
            "Assignee"). No foreign key; see `ComplianceStandard.owner_id`.
        due_date: Optional due date (§6).
        due_reminder_sent_at / overdue_notified_at: Sweep (§18/§28)
            bookkeeping — stamped the first time the "approaching due
            date"/"overdue" notification has been sent for the *current*
            `due_date`, so `scheduler.py::send_required_action_due_
            notifications`'s daily sweep never repeats either notification.
            Reset to `None` (by the same PATCH that changes `due_date`) so a
            rescheduled due date gets its own fresh reminder cycle rather
            than silently inheriting the old date's "already reminded"
            state.
        is_completed / completed_at / completed_by: Completion overlay,
            mirroring `Requirement.completed_at`'s own shape — see this
            module's own docstring for why this shape rather than reusing
            `ComplianceStatus`.
        notes: Free-text notes.
    """

    __tablename__ = "compliance_required_action_assessments"
    __table_args__ = (
        UniqueConstraint("project_compliance_requirement_id", "required_action_id"),
        principal_check_constraint("assignee", nullable=True),
        # Explicit short index name: the generated `ix_compliance_required_action_assessments_project_compliance_
        # requirement_id` is 75 characters, over Postgres's 63-byte limit, so Postgres truncates it at DDL time and it
        # never matches SQLAlchemy's computed name (`test_schema_migrations_match_models.py`).
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
    assignee_type: Mapped[str | None] = principal_type_column(nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


# --- Evidence -----------------------------------------------------------


class ComplianceEvidence(UUIDPKMixin, TimestampMixin, Base):
    """A piece of supporting evidence for one or more of a project's
    compliance assessments (§13) — e.g. "IPX9 Test Certificate." Project-
    scoped, not standard/requirement-scoped: see this module's own
    docstring for why.

    Attributes:
        project_id: The owning project.
        unique_code: Project-scoped identifier (e.g. `"EVD-003"`), from
            `services.sequences.generate_unique_code`; never reused.
        title: Short display name (§13's own worked example: "IPX9 Test
            Certificate").
        description: Free-text elaboration.
        issuing_organisation: The external body/person that issued this
            evidence, where applicable (§14) — e.g. a test lab's name.
        issued_date: When this evidence was issued (§13/§14's "Issue
            date"), distinct from `provided_at` (when it was uploaded into
            this system).
        expiry_date: This evidence's *current* effective expiry (§14),
            nullable — not every piece of evidence expires. Updated in
            place by a revalidation; see this module's own docstring for
            why the *previous* value is never lost.
        provided_by / provided_at: Who supplied this evidence and when
            (§13) — set automatically at creation, never caller-supplied,
            mirroring `ProjectCompliance.assigned_at`/`assigned_by`'s own
            convention.
        notes: Free-text notes, independent of `description`.
        expiry_reminder_sent_at / expiry_notified_at: Sweep (§18/§28)
            bookkeeping — mirrors `ComplianceRequiredActionAssessment.
            due_reminder_sent_at`/`overdue_notified_at`'s own shape,
            stamped by `scheduler.py::send_evidence_expiry_notifications`
            so its daily sweep never repeats the "approaching expiry"/
            "expired" notification for the same `expiry_date`. Reset to
            `None` by `revalidate_evidence` (the only endpoint that changes
            `expiry_date`), so a revalidated expiry gets its own fresh
            reminder cycle.
        is_archived / archived_at / archived_by: Whether this evidence
            "remains applicable" (§13) — see this module's own docstring
            for why this is a soft-delete, not a hard one.
    """

    __tablename__ = "compliance_evidence"
    __table_args__ = (UniqueConstraint("project_id", "unique_code", name="uq_compliance_evidence_project_unique_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    unique_code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    issuing_organisation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    provided_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    provided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")
    expiry_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ComplianceEvidenceRevalidation(UUIDPKMixin, Base):
    """One revalidation event for a `ComplianceEvidence` row (§15) —
    append-only, never updated: mirrors `app.models.file.RequirementFile`'s
    own "no `updated_at`, insert-only" shape (a plain `created_at` column
    rather than `TimestampMixin`), for the same reason — this row is never
    mutated after creation.

    Attributes:
        evidence_id: The `ComplianceEvidence` this revalidation applies to.
        revalidated_by / revalidated_at: Who revalidated and when (§15).
        previous_expiry_date: `ComplianceEvidence.expiry_date`'s value
            immediately before this revalidation (`None` if it had none) —
            this is what makes the history genuinely retained rather than
            reconstructible only from timestamps.
        new_expiry_date: The new validity/expiry date this revalidation
            sets (§15) — mirrors `ComplianceEvidence.expiry_date`'s value
            immediately after this event is applied.
        justification: Optional free-text justification (§15).
    """

    __tablename__ = "compliance_evidence_revalidations"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_evidence.id", ondelete="CASCADE"), index=True
    )
    revalidated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    revalidated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    justification: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ComplianceEvidenceFile(UUIDPKMixin, Base):
    """Links a file (direct upload, or an organisation shared resource) to
    a `ComplianceEvidence` row — the exact shape of `app.models.file.
    RequirementFile`; see this module's own docstring for why this lives
    here rather than reusing that table directly. No `index=True` on
    either foreign key, mirroring `RequirementFile`'s own
    unindexed-beyond-primary-key convention for this exact join-table
    shape."""

    __tablename__ = "compliance_evidence_files"
    __table_args__ = (UniqueConstraint("evidence_id", "file_id"),)

    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_evidence.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Evidence links to a `ProjectComplianceRequirement` or `ComplianceRequiredActionAssessment` are
# `app.models.relationship.ArtefactLink` rows (see the module docstring and `app.services.relationships`).
#
# This module's registered artefact-type values (`module.MODULE_DEFINITION.artefact_types`) are the constants every call
# site (`service.py`, `reports.py`, `export.py`, `project_router`) imports. `module.py` repeats them as local literals to
# avoid an import cycle.
ARTEFACT_TYPE_COMPLIANCE_REQUIREMENT = "compliance_requirement"
ARTEFACT_TYPE_EVIDENCE = "compliance_evidence"
EVIDENCE_CODE_PREFIX = "EVD"
ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT = "project_compliance_requirement"
ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT = "compliance_required_action_assessment"


# --- Scheduled reviews --------------------------------------------------


class ComplianceReview(UUIDPKMixin, TimestampMixin, Base):
    """A scheduled compliance review (§17) — either of a `ComplianceStandard`
    itself, or of one project's compliance assignment (`ProjectCompliance`).
    Exactly one of `standard_id`/`project_compliance_id` is set; see this
    module's own docstring for why these are separate owners rather than a
    shared "reviewable" abstraction.

    Attributes:
        standard_id: The `ComplianceStandard` this review is scheduled
            against, or `None` if this is a project-level review.
        project_compliance_id: The `ProjectCompliance` assignment this
            review is scheduled against, or `None` if this is a
            standard-level review.
        frequency_label: Free-text display of the review's cadence (§17's
            "Review frequency"), e.g. "Annual," "Six-monthly," "Before
            product release" — display metadata, not itself the scheduling
            mechanism (`recurrence_days` is).
        recurrence_days: Days between cycles, or `None` for a one-off
            review that doesn't automatically recur once completed (see
            `service.py::complete_review`).
        next_due_date: This cycle's due date (§17's "Next review date").
            Never itself computed as "upcoming/due/overdue" — see
            `service.py::compute_review_schedule_state`.
        owner_type / owner_id: The principal responsible for performing this
            review (§17's "Review owner"), both `None` if not yet assigned.
            A standard-level review is organisation-scoped (a user or an
            organisation group); a project-level one may also name a group
            of its project (`models.principal`). No foreign key; see
            `ComplianceStandard.owner_id`.
        status: `SCHEDULED` or `COMPLETED` — see `ComplianceReviewStatus`'s
            own docstring for why there's no separate overdue/cancelled
            member.
        notes: Free-text notes (§17), independent of the evidence linkage
            below.
        outcome: Set only on completion (§17's "Review outcome") — `None`
            while `SCHEDULED`.
        completed_at / completed_by: When/who completed this review — set
            automatically by `service.py::complete_review`, `None` while
            `SCHEDULED`.
        created_by: The user who scheduled this review.
        due_reminder_sent_at / overdue_notified_at: Sweep bookkeeping,
            mirroring `ComplianceRequiredActionAssessment`'s own pair —
            see `scheduler.py::send_review_due_notifications`.
    """

    __tablename__ = "compliance_reviews"
    __table_args__ = (
        CheckConstraint(
            "(standard_id IS NOT NULL) != (project_compliance_id IS NOT NULL)",
            name="ck_compliance_reviews_exactly_one_owner",
        ),
        principal_check_constraint("owner", nullable=True),
    )

    standard_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_standards.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_compliance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_compliances.id", ondelete="CASCADE"), nullable=True, index=True
    )
    frequency_label: Mapped[str] = mapped_column(String(100))
    recurrence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_due_date: Mapped[date] = mapped_column(Date)
    owner_type: Mapped[str | None] = principal_type_column(nullable=True)
    owner_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    status: Mapped[ComplianceReviewStatus] = mapped_column(
        str_enum(ComplianceReviewStatus, 20), default=ComplianceReviewStatus.SCHEDULED
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[ComplianceReviewOutcome | None] = mapped_column(str_enum(ComplianceReviewOutcome, 20), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    due_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplianceReviewEvidenceLink(UUIDPKMixin, Base):
    """Links one `ComplianceEvidence` row to one `ComplianceReview` (§17's
    "Notes/evidence associated with the review") — an untyped many-to-many
    join table, the same shape the evidence-requirement/
    evidence-action links used before those two were folded into the
    generic `ArtefactLink` table (this table was not, so it remains
    dedicated). No
    `index=True` on either foreign key, avoiding this exact table/column
    combination's auto-generated index name exceeding Postgres's 63-byte
    identifier limit, the same class of problem
    `ComplianceRequiredActionAssessment`'s own comment documents for a
    different table. Only ever created for a project-scoped review
    (`ComplianceReview.project_compliance_id` set) — enforced at the API
    layer, since evidence is inherently project-scoped and a
    standard-level review has no project to share with it."""

    __tablename__ = "compliance_review_evidence_links"
    __table_args__ = (UniqueConstraint("evidence_id", "review_id"),)

    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_evidence.id", ondelete="CASCADE"))
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_reviews.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Cross-standard mapping + version impact -----------------------------


class ComplianceMappingRelationshipTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """An organisation-defined cross-standard-mapping relationship type
    (e.g. "Equivalent," "Satisfies," "Derived From," "Related To,"
    "Overlaps," "Conflicts With") — mirrors `ComplianceActionTypeDefinition`'s
    existing extensible-vocabulary pattern (§19: "exact relationship types
    should be configurable or extensible where practical"); see the cross-standard mapping design decisions for why this uses a *shorter* table name
    than its column names would otherwise suggest.

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique within the organisation.
        sort_order: Display/picker order among the organisation's
            relationship types.
        implies_equivalence: Whether this relationship type is strong
            enough that a `replaced` version-diff pair linked by it (§27)
            may have its project-specific assessment carried forward during
            migration (`service.py::migrate_project_compliance`), subject
            to the compliance officer's own explicit, per-requirement
            confirmation at migration time — never automatic. Defaults
            `False`: an org must deliberately mark a type (e.g. "Equivalent")
            as strong enough for this before it can ever be offered, so a
            weaker type (e.g. "Related To," "Overlaps") can never be used
            this way by default. See the cross-standard mapping design decisions
            (below) for the full reasoning and why this doesn't reopen
            §19's "must not imply... satisfying" guarantee.
    """

    __tablename__ = "compliance_mapping_relationship_types"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    implies_equivalence: Mapped[bool] = mapped_column(Boolean, default=False)


class ComplianceRequirementMapping(UUIDPKMixin, TimestampMixin, Base):
    """A directed relationship between two `ComplianceRequirement` rows
    (§19's cross-standard mapping) — e.g. "ISO 27001 A.5.15 Equivalent
    Corporate Security Standard 3.0 SEC-12." See the cross-standard mapping
    design decisions for why this single table also serves §27's "replaced"/
    "re-mapped" version-diff categories (a same-standard, cross-*version*
    link), why the relationship is directed, and why the org scope is
    denormalised onto this row directly.

    Attributes:
        organization_id: The organisation both mapped requirements belong
            to (denormalised from their own standards) — the scoping
            anchor for this module's usual "404, not 403" cross-org
            isolation check.
        from_requirement_id / to_requirement_id: The two mapped
            `ComplianceRequirement` rows. `CheckConstraint` below rules out
            `from_requirement_id == to_requirement_id`. `ondelete="CASCADE"`
            on both — a mapping referencing a requirement that no longer
            exists (only possible for a still-`DRAFT` version's
            requirements, since a published version's requirements are
            immutable and never deleted) has nothing left to mean.
        relationship_type_id: Which `ComplianceMappingRelationshipTypeDefinition`
            this mapping is. No `ondelete` (implicit RESTRICT), mirroring
            `ComplianceRequiredAction.action_type_id` — an in-use
            relationship type must not be deletable out from under it.
        notes: Free-text notes (§19 names no specific field list beyond the
            relationship type itself, but every other definitional entity
            in this module carries a notes/description field for the same
            "why this link exists" context).
        created_by: The user who created this mapping (§19: "must be...
            auditable" — this plus `TimestampMixin.created_at`/
            `services.audit.log_event` on the creating endpoint satisfy
            that, mirroring every other entity in this module rather than
            a bespoke mapping-history mechanism).
        is_archived / archived_at / archived_by: Soft-delete, mirroring
            every other entity in this module — a mapping is retained
            audit history once created, not hard-deleted.
    """

    __tablename__ = "compliance_requirement_mappings"
    __table_args__ = (
        UniqueConstraint("from_requirement_id", "to_requirement_id", "relationship_type_id"),
        CheckConstraint(
            "from_requirement_id != to_requirement_id", name="ck_compliance_requirement_mappings_no_self_link"
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    from_requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="CASCADE"), index=True
    )
    to_requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_requirements.id", ondelete="CASCADE"), index=True
    )
    # Deferred for the same reason as `ComplianceRequiredAction.action_type_id`.
    relationship_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("compliance_mapping_relationship_types.id", deferrable=True, initially="DEFERRED"),
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


# --- standard-scoped RBAC (standards_manager/standards_contributor) ----


class ComplianceOrgSettings(UUIDPKMixin, TimestampMixin, Base):
    """One organisation's own Compliance-module-owned settings —
    started for a single field, the org's designated **default compliance-
    managers group** (§3's "a standard must always have a
    standards_manager, defaulting to a group of all compliance managers
    where roles are SSO-managed"): every current member of this `OrgGroup`
    counts as an effective `standards_manager` for any standard in this
    organisation that has no explicit per-standard grant of its own,
    resolved live at floor-check/effective-access time (see `service.py::
    get_effective_standard_managers`/`standard_manager_floor_covered_by_
    fallback`) — never a stored/materialised per-standard row.

    Deliberately **not** a new column on the core `Organization` model —
    this is Compliance-module-owned configuration, and the Modular Feature
    System Boundary (`CLAUDE.md`) requires a module's own settings to live
    in the module's own table, not bolted onto a core one, the same reason
    `organization_module_entitlements`/`organization_modules` are their own tables rather than `Organization` columns.

    One row per organisation that has ever set this (created lazily, on
    first write — see `router.py::update_compliance_org_settings`), not
    pre-seeded for every org on creation, mirroring `OrgAdvancedSettings`-
    style "absent means not configured yet, not zero" semantics elsewhere
    in this codebase.

    Attributes:
        organization_id: The owning organisation. Unique — one settings
            row per org.
        default_standards_manager_group_id: The designated fallback
            `OrgGroup`, or `NULL` if none is configured yet (the "no
            fallback" state — see this class's own module docstring
            reference above). `ON DELETE SET NULL`: deleting the
            designated group must not leave a dangling reference, and
            silently reverting to "no fallback configured" is the correct,
            safe behaviour (matching this class's own "absent means not
            configured" semantics) rather than a delete failing/cascading
            unexpectedly.
    """

    __tablename__ = "compliance_org_settings"
    __table_args__ = (UniqueConstraint("organization_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    default_standards_manager_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_groups.id", ondelete="SET NULL"), nullable=True
    )
