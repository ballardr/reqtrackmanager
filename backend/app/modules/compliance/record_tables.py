"""
Module: modules.compliance.record_tables

The `RecordTableProvider`s of Compliance's four record types, so each of their lists exports to CSV, PDF and Word:
Evidence (authored, and imported from the same CSV), and the Standard Requirement, the project's assessment of one
(Project Compliance Requirement) and the assessment of one of its Required Actions, which are export-only.

Responsibilities:
- Declare the columns of each list, and the list queries (the assignments of a project, the requirements of a
  standard's versions) the pages and the files share.
- Share Evidence's create and edit logic with the endpoints (`evidence_edits`), so the code, the audit event and
  the revalidation-only expiry rule are the ones the screen applies.

Design decisions:
- **Three types have no `PREFIX-nnn` code** (the compliance requirement and its two project-level children: a
  recorded gap). Their `Code` column holds the requirement's clause reference where it has one (`3.2.1`) and is
  blank otherwise; the `standard`, `version` and `requirement` columns identify the row. Because they cannot be
  matched by a code they cannot be updated by a file either, and each gives its reason in `not_importable`.
- Evidence is the one importable type. Its expiry date can be written when a row is created only: changing it is
  a revalidation that keeps the previous date, so a file that changes it on an existing row is refused for that row.
- A project's assessments and required-action assessments are materialised when a standard is assigned and then
  moved by the assessment, justification and approval workflow; a file would bypass the justification rules and
  the invalidation of an approval, so those lists are read-only tables. The standard's requirements are authored in
  a draft version's tree (parents, order, mappings) and are immutable once published.
- The Standard Requirement is organisation-owned (a standard belongs to the organisation): its organisation tier
  lists every standard's requirements, narrowed by `standard` and `version`; its project tier lists those of the
  versions the project is assigned. The module declares no sub-components, so the module being enabled is the gate.
- The rows are small wrappers carrying the record and what its columns read (standard, version, requirement,
  resolved applicability), so a column does not query and `code_of` can read a requirement's reference.

Dependencies: `service` (assignment cache, applicability), `evidence_edits`, `models`, `labels`,
`services.record_tables_core`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.compliance import evidence_edits
from app.modules.compliance.enums import ComplianceApplicability, ComplianceApprovalState, ComplianceEvidenceValidityState, ComplianceStatus
from app.modules.compliance.labels import (
    COMPLIANCE_APPLICABILITY_LABEL,
    COMPLIANCE_APPLICABILITY_SOURCE_LABEL,
    COMPLIANCE_APPROVAL_STATE_LABEL,
    COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL,
    COMPLIANCE_EVIDENCE_VALIDITY_STATE_TONE,
    COMPLIANCE_STANDARD_VERSION_STATUS_LABEL,
    COMPLIANCE_STATUS_LABEL,
)
from app.modules.compliance.models import (
    ARTEFACT_TYPE_COMPLIANCE_REQUIREMENT,
    ARTEFACT_TYPE_EVIDENCE,
    ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT,
    ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT,
    ComplianceEvidence,
    ComplianceRequiredAction,
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
)
from app.modules.compliance.service import (
    COMPLIANCE_EVIDENCE_MANAGE_PERMISSION,
    ComplianceVersionCache,
    compute_evidence_validity_state,
    load_pcrs_and_applicability,
)
from app.modules.registry import (
    OrganizationRecordTable,
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
)
from app.services import tags as tag_service
from app.services.client_date import effective_today
from app.services.principals import principal_ref
from app.services.rbac import get_effective_permissions, permission_satisfied, user_satisfies_module_role
from app.services.record_tables import PrincipalCells
from app.services.record_tables_core import (
    bool_cell,
    count_rows,
    date_parser,
    enum_filter,
    instant_cell,
    list_cell,
    text_parser,
)

COMPLIANCE_MODULE_KEY = "compliance"

#: Why each export-only type is not importable (`ModuleDefinition.not_importable`).
NOT_IMPORTABLE = {
    ARTEFACT_TYPE_COMPLIANCE_REQUIREMENT: (
        "A standard's requirements are authored in a draft version's tree (parents, order, mappings) and are immutable "
        "once the version is published; import the standard itself instead."
    ),
    ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT: (
        "A project's assessment of a requirement moves through the justification and approval workflow, which a file "
        "would bypass; assess the requirement on its page."
    ),
    ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT: (
        "A required-action assessment is produced when a standard is assigned and completed through the workflow; "
        "it has no code a file could match."
    ),
}

#: The filters of the assessment-side lists, by the names their exports take. `assignment` is a project compliance
#: (one standard version assigned to the project); `standard` and `version` narrow to a standard or one of its
#: versions, and `section` to one top-level requirement and everything beneath it (the outstanding panel's filters).
ASSESSMENT_FILTERS = frozenset({"assignment", "standard", "version", "section", "search"})


def _may_manage_evidence(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """The evidence endpoints' gate: the Compliance Officer role, or a `(compliance_evidence, manage)` grant."""
    project = db.get(Project, project_id)
    if user_satisfies_module_role(
        db, user, COMPLIANCE_MODULE_KEY, "compliance_officer", organization_id=project.organization_id, project_id=project.id,
    ):
        return True
    held = get_effective_permissions(db, user.id, organization_id=project.organization_id, project_id=project.id)
    return permission_satisfied(held, COMPLIANCE_EVIDENCE_MANAGE_PERMISSION)


def _hit(filters: RecordFilters, *parts: str) -> bool:
    """Whether the page's search box (`search`) matches any of `parts`, ignoring case."""
    needle = filters.one("search")
    return needle is None or needle.casefold() in " ".join(parts).casefold()


def _uuid_filter(filters: RecordFilters, key: str) -> uuid.UUID | None:
    raw = filters.one(key)
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(422, f"{key} is not a valid id.") from None


# --- Evidence ----------------------------------------------------------------------------------------------------


def _list_evidence(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[ComplianceEvidence]:
    validity = enum_filter(filters, "validity", ComplianceEvidenceValidityState)
    query = select(ComplianceEvidence).where(ComplianceEvidence.project_id == project_id)
    if not filters.flag("include_archived"):
        query = query.where(ComplianceEvidence.is_archived.is_(False))
    rows = db.scalars(query.order_by(ComplianceEvidence.created_at, ComplianceEvidence.unique_code)).all()
    today = effective_today()
    return [
        e for e in rows
        if (validity is None or compute_evidence_validity_state(e, today=today) == validity)
        and _hit(filters, e.unique_code, e.title)
    ]


class _EvidencePrepared:
    """The tags and the validity of each row being written."""

    def __init__(self, db: Session, records: list[ComplianceEvidence]) -> None:
        self.tags = tag_service.tag_names_for_records(db, ARTEFACT_TYPE_EVIDENCE, [r.id for r in records]) if records else {}
        today = effective_today()
        self.validity = {r.id: compute_evidence_validity_state(r, today=today) for r in records}


def _date_cell(value: date | None) -> str:
    return value.isoformat() if value else ""


def _evidence_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        RecordColumn("title", "Title", lambda t, r: r.title, text_parser, editable=True, required=True),
        RecordColumn("description", "Description", lambda t, r: r.description or "", text_parser, editable=True),
        RecordColumn(
            "issuing_organisation", "Issuing organisation", lambda t, r: r.issuing_organisation or "", text_parser, editable=True,
        ),
        RecordColumn(
            "issued_date", "Issued date", lambda t, r: _date_cell(r.issued_date), date_parser("Issued date"), kind="date", editable=True,
        ),
        RecordColumn("expiry_date", "Expiry date", lambda t, r: _date_cell(r.expiry_date), date_parser("Expiry date"), kind="date"),
        RecordColumn("notes", "Notes", lambda t, r: r.notes or "", text_parser, editable=True),
        RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list"),
        RecordColumn(
            "validity", "Validity", lambda t, r: COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[t.validity[r.id].value], kind="enum",
            tones={
                COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[value]: tone for value, tone in COMPLIANCE_EVIDENCE_VALIDITY_STATE_TONE.items()
            },
        ),
        RecordColumn("status", "Status", lambda t, r: "Archived" if r.is_archived else "Active", kind="enum"),
        RecordColumn("provided_at", "Provided at", lambda t, r: instant_cell(r.provided_at), kind="instant"),
    ]


def _create_evidence(ctx: RecordImportContext, values: Mapping[str, Any]) -> ComplianceEvidence:
    return evidence_edits.stage_evidence(
        ctx.db, ctx.project, ctx.user, title=values["title"], description=values.get("description") or "",
        issuing_organisation=values.get("issuing_organisation") or None, issued_date=values.get("issued_date"),
        expiry_date=values.get("expiry_date"), notes=values.get("notes") or "",
    )


def _update_evidence(ctx: RecordImportContext, evidence: ComplianceEvidence, values: Mapping[str, Any]) -> None:
    if "expiry_date" in values:
        raise RecordCellError("The expiry date is changed by revalidating the evidence, which keeps the previous date.")
    changes = dict(values)
    if "issuing_organisation" in changes:
        changes["issuing_organisation"] = changes["issuing_organisation"] or None
    evidence_edits.stage_evidence_update(ctx.db, evidence, ctx.user, changes)


def _find_evidence(db: Session, project: Project, code: str) -> ComplianceEvidence | None:
    return db.scalar(select(ComplianceEvidence).where(
        ComplianceEvidence.project_id == project.id, ComplianceEvidence.unique_code == code.upper(),
    ))


EVIDENCE_TABLE = RecordTableProvider(
    label="Evidence",
    columns=_evidence_columns,
    list_records=_list_evidence,
    find=_find_evidence,
    prepare=lambda db, project, records: _EvidencePrepared(db, records),
    create=_create_evidence,
    update=_update_evidence,
    filter_params=frozenset({"include_archived", "validity", "search"}),
    gate=(COMPLIANCE_MODULE_KEY, None),
    can_create=_may_manage_evidence,
    can_update=_may_manage_evidence,
    count=lambda db, user, project_id: count_rows(db, ComplianceEvidence, project_id, live_only=True),
)


# --- Rows that carry what their columns read ---------------------------------------------------------------------


class _Row:
    """A record plus what its columns read, so a column does not query. `unique_code` is the requirement's clause
    reference (the recorded gap: these types have no `PREFIX-nnn` code) and `project_id` the owning project."""

    def __init__(
        self, record: Any, project_id: uuid.UUID | None, requirement: ComplianceRequirement, version: ComplianceStandardVersion,
        standard: ComplianceStandard,
    ) -> None:
        self.record, self.id, self.project_id = record, record.id, project_id
        self.requirement, self.version, self.standard = requirement, version, standard
        self.unique_code = requirement.reference or ""


class _AssessedRow(_Row):
    """A row of a project's assessment: adds the resolved applicability and the assignment's project."""

    def __init__(self, record: Any, project_id: uuid.UUID, requirement: Any, version: Any, standard: Any, applicability: Any) -> None:
        super().__init__(record, project_id, requirement, version, standard)
        self.effective, self.source = applicability


def _assigned(db: Session, project_id: uuid.UUID, filters: RecordFilters) -> list[tuple[ProjectCompliance, Any]]:
    """The project's active assignments with their cache, narrowed by the `assignment` filter."""
    cache = ComplianceVersionCache(db)
    wanted, standard_id, version_id = (_uuid_filter(filters, key) for key in ("assignment", "standard", "version"))
    kept = []
    for pc in cache.assignments(project_id):
        if (wanted is not None and pc.id != wanted) or (version_id is not None and pc.standard_version_id != version_id):
            continue
        if standard_id is not None and cache.version(pc.standard_version_id).standard_id != standard_id:
            continue
        kept.append((pc, cache))
    return kept


def _in_section(filters: RecordFilters, requirement: ComplianceRequirement, by_id: Mapping[uuid.UUID, ComplianceRequirement]) -> bool:
    """Whether `requirement` sits under the top-level requirement the `section` filter names (always when absent)."""
    section = _uuid_filter(filters, "section")
    if section is None:
        return True
    current = requirement
    for _ in range(len(by_id)):  # bounded, so a cycle in bad data cannot loop
        parent = by_id.get(current.parent_requirement_id) if current.parent_requirement_id else None
        if parent is None:
            break
        current = parent
    return current.id == section


def _identifying(row: _Row) -> list[str]:
    return [row.standard.reference, row.version.version_label, row.requirement.reference or "", row.requirement.name]


def _list_assessments(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[_AssessedRow]:
    rows: list[_AssessedRow] = []
    for pc, cache in _assigned(db, project_id, filters):
        version = cache.version(pc.standard_version_id)
        standard = cache.standard(version.standard_id)
        requirements = cache.requirements(version.id)
        pcrs, applicability = load_pcrs_and_applicability(
            db, project_compliance_id=pc.id, standard_version_id=version.id, requirements=requirements, pcrs=cache.pcrs(pc.id),
        )
        by_id = {r.id: r for r in requirements}
        for pcr in pcrs:
            row = _AssessedRow(pcr, project_id, by_id[pcr.requirement_id], version, standard, applicability[pcr.requirement_id])
            if (
                _in_section(filters, row.requirement, by_id)
                and _enum_matches(filters, "status", ComplianceStatus, pcr.compliance_status)
                and _enum_matches(filters, "approval", ComplianceApprovalState, pcr.approval_state)
                and _enum_matches(filters, "applicability", ComplianceApplicability, row.effective)
                and _hit(filters, *_identifying(row))
            ):
                rows.append(row)
    return rows


def _enum_matches(filters: RecordFilters, key: str, enum_class: Any, held: Any) -> bool:
    wanted = enum_filter(filters, key, enum_class)
    return wanted is None or held == wanted


class _TaggedPrepared:
    """Tags (and, for an assessment of an action, the assignees) of the rows being written."""

    def __init__(self, db: Session, records: list[Any], artefact_type: str, *, assignees: bool = False) -> None:
        ids = [r.id for r in records]
        self.tags = tag_service.tag_names_for_records(db, artefact_type, ids) if ids else {}
        self.people = PrincipalCells.load(
            db, [principal_ref(r.record.assignee_type, r.record.assignee_id) for r in records] if assignees else [],
        )


def _clause_columns() -> list[RecordColumn]:
    return [
        RecordColumn("standard", "Standard", lambda t, r: r.standard.reference, kind="text"),
        RecordColumn("version", "Version", lambda t, r: r.version.version_label, kind="text"),
        RecordColumn("requirement", "Requirement", lambda t, r: r.requirement.name, kind="text"),
    ]


def _assessment_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        *_clause_columns(),
        RecordColumn("applicability", "Applicability", lambda t, r: COMPLIANCE_APPLICABILITY_LABEL[r.effective.value], kind="enum"),
        RecordColumn(
            "applicability_source", "Applicability source", lambda t, r: COMPLIANCE_APPLICABILITY_SOURCE_LABEL[r.source.value],
            kind="enum",
        ),
        RecordColumn(
            "compliance_status", "Compliance status", lambda t, r: COMPLIANCE_STATUS_LABEL[r.record.compliance_status.value], kind="enum",
        ),
        RecordColumn(
            "approval_state", "Approval", lambda t, r: COMPLIANCE_APPROVAL_STATE_LABEL[r.record.approval_state.value], kind="enum",
        ),
        RecordColumn("justification", "Justification", lambda t, r: r.record.justification or "", kind="text"),
        RecordColumn("notes", "Notes", lambda t, r: r.record.notes or "", kind="text"),
        RecordColumn("assessed_at", "Assessed at", lambda t, r: instant_cell(r.record.assessed_at), kind="instant"),
        RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list"),
    ]


def _never_found(db: Session, project: Project, code: str) -> None:
    """These types have no code a row could be matched by."""
    return None


ASSESSMENT_TABLE = RecordTableProvider(
    label="Compliance assessments",
    columns=_assessment_columns,
    list_records=_list_assessments,
    find=_never_found,
    prepare=lambda db, project, records: _TaggedPrepared(db, records, ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT),
    filter_params=ASSESSMENT_FILTERS | {"status", "approval", "applicability"},
    gate=(COMPLIANCE_MODULE_KEY, None),
    code_of=lambda row: row.unique_code,
    approval_gated=True,
    in_overview=False,
)


# --- Required-action assessments ---------------------------------------------------------------------------------


class _ActionRow(_AssessedRow):
    """A row of a required-action assessment: adds the action definition."""

    def __init__(
        self, record: ComplianceRequiredActionAssessment, project_id: uuid.UUID, requirement: Any, version: Any, standard: Any,
        applicability: Any, action: ComplianceRequiredAction,
    ) -> None:
        super().__init__(record, project_id, requirement, version, standard, applicability)
        self.action = action


def _list_action_assessments(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[_ActionRow]:
    rows: list[_ActionRow] = []
    today = effective_today()
    for pc, cache in _assigned(db, project_id, filters):
        version = cache.version(pc.standard_version_id)
        standard = cache.standard(version.standard_id)
        requirements = cache.requirements(version.id)
        pcrs, applicability = load_pcrs_and_applicability(
            db, project_compliance_id=pc.id, standard_version_id=version.id, requirements=requirements, pcrs=cache.pcrs(pc.id),
        )
        if not pcrs:
            continue
        by_id = {r.id: r for r in requirements}
        pcr_requirement = {p.id: by_id[p.requirement_id] for p in pcrs}
        actions = cache.required_actions_by_id(version.id)
        assessments = db.scalars(select(ComplianceRequiredActionAssessment).where(
            ComplianceRequiredActionAssessment.project_compliance_requirement_id.in_(list(pcr_requirement)),
        ).order_by(ComplianceRequiredActionAssessment.created_at)).all()
        for assessment in assessments:
            requirement = pcr_requirement[assessment.project_compliance_requirement_id]
            row = _ActionRow(
                assessment, project_id, requirement, version, standard, applicability[requirement.id], actions[assessment.required_action_id],
            )
            if not _in_section(filters, requirement, by_id):
                continue
            if filters.flag("outstanding") and (assessment.is_completed or row.effective != ComplianceApplicability.APPLICABLE):
                continue
            if filters.flag("overdue") and (assessment.is_completed or assessment.due_date is None or assessment.due_date >= today):
                continue
            if _hit(filters, *_identifying(row), row.action.name):
                rows.append(row)
    return rows


def _action_assessment_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        *_clause_columns(),
        RecordColumn("required_action", "Required action", lambda t, r: r.action.name, kind="text"),
        RecordColumn("mandatory", "Mandatory", lambda t, r: bool_cell(r.action.is_mandatory), kind="bool"),
        RecordColumn(
            "assignee", "Assignee", lambda t, r: t.people.text(r.record.assignee_type, r.record.assignee_id), kind="principal",
        ),
        RecordColumn("due_date", "Due date", lambda t, r: _date_cell(r.record.due_date), kind="date"),
        RecordColumn("completed", "Completed", lambda t, r: bool_cell(r.record.is_completed), kind="bool"),
        RecordColumn("completed_at", "Completed at", lambda t, r: instant_cell(r.record.completed_at), kind="instant"),
        RecordColumn("applicability", "Applicability", lambda t, r: COMPLIANCE_APPLICABILITY_LABEL[r.effective.value], kind="enum"),
        RecordColumn("notes", "Notes", lambda t, r: r.record.notes or "", kind="text"),
        RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list"),
    ]


ACTION_ASSESSMENT_TABLE = RecordTableProvider(
    label="Required action assessments",
    columns=_action_assessment_columns,
    list_records=_list_action_assessments,
    find=_never_found,
    prepare=lambda db, project, records: _TaggedPrepared(db, records, ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT, assignees=True),
    filter_params=ASSESSMENT_FILTERS | {"outstanding", "overdue"},
    gate=(COMPLIANCE_MODULE_KEY, None),
    code_of=lambda row: row.unique_code,
    in_overview=False,
)


# --- Standard requirements (organisation-owned) ------------------------------------------------------------------


def _requirement_rows(
    db: Session, standards: list[ComplianceStandard], versions: list[ComplianceStandardVersion], project_id: uuid.UUID | None,
    filters: RecordFilters,
) -> list[_Row]:
    """The requirements of `versions` (of `standards`), depth-first within a version, the page's search applied."""
    standard_by_id = {s.id: s for s in standards}
    rows: list[_Row] = []
    for version in versions:
        requirements = db.scalars(select(ComplianceRequirement).where(
            ComplianceRequirement.standard_version_id == version.id,
        ).order_by(ComplianceRequirement.sort_order, ComplianceRequirement.created_at)).all()
        for requirement in requirements:
            row = _Row(requirement, project_id, requirement, version, standard_by_id[version.standard_id])
            if _hit(filters, *_identifying(row)):
                rows.append(row)
    return rows


def _list_org_requirements(db: Session, user: User, organization: Organization, filters: RecordFilters) -> list[_Row]:
    query = select(ComplianceStandard).where(ComplianceStandard.organization_id == organization.id)
    if not filters.flag("include_archived"):
        query = query.where(ComplianceStandard.is_archived.is_(False))
    standard_id, version_id = _uuid_filter(filters, "standard"), _uuid_filter(filters, "version")
    if standard_id is not None:
        query = query.where(ComplianceStandard.id == standard_id)
    standards = list(db.scalars(query.order_by(ComplianceStandard.reference)).all())
    if not standards:
        return []
    version_query = select(ComplianceStandardVersion).where(
        ComplianceStandardVersion.standard_id.in_([s.id for s in standards]),
    ).order_by(ComplianceStandardVersion.standard_id, ComplianceStandardVersion.version_number)
    if version_id is not None:
        version_query = version_query.where(ComplianceStandardVersion.id == version_id)
    return _requirement_rows(db, standards, list(db.scalars(version_query).all()), None, filters)


def _list_project_requirements(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[_Row]:
    """The requirements of the standard versions assigned to the project (the clauses it is assessed against)."""
    assigned = _assigned(db, project_id, filters)
    if not assigned:
        return []
    cache = assigned[0][1]
    versions = [cache.version(pc.standard_version_id) for pc, _ in assigned]
    standards = [cache.standard(v.standard_id) for v in versions]
    return _requirement_rows(db, standards, versions, project_id, filters)


def _requirement_columns(db: Session, scope: Any) -> list[RecordColumn]:
    return [
        *_clause_columns(),
        RecordColumn("description", "Description", lambda t, r: r.requirement.description or "", kind="text"),
        RecordColumn("reasoning", "Reasoning", lambda t, r: r.requirement.reasoning or "", kind="text"),
        RecordColumn(
            "version_status", "Version status", lambda t, r: COMPLIANCE_STANDARD_VERSION_STATUS_LABEL[r.version.status.value],
            kind="enum",
        ),
    ]


REQUIREMENT_TABLE = RecordTableProvider(
    label="Standard requirements",
    columns=_requirement_columns,
    list_records=_list_project_requirements,
    find=_never_found,
    filter_params=ASSESSMENT_FILTERS | {"include_archived"},
    gate=(COMPLIANCE_MODULE_KEY, None),
    code_of=lambda row: row.unique_code,
    organization_owned=lambda record: True,
    in_overview=False,
    organization=OrganizationRecordTable(
        subcomponent=None,
        columns=_requirement_columns,
        list_records=_list_org_requirements,
        find=lambda db, organization, code: None,
        filter_params=frozenset({"standard", "version", "search", "include_archived"}),
    ),
)

RECORD_TABLES: dict[str, RecordTableProvider] = {
    ARTEFACT_TYPE_EVIDENCE: EVIDENCE_TABLE,
    ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT: ASSESSMENT_TABLE,
    ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT: ACTION_ASSESSMENT_TABLE,
    ARTEFACT_TYPE_COMPLIANCE_REQUIREMENT: REQUIREMENT_TABLE,
}
