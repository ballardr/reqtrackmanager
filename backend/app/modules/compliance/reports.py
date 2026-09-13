"""
Module: modules.compliance.reports

Compliance Module Phase 15 (docs/compliance-module-plan.md; docs/
Compliance_Module_Requirements.md §29 "Reporting and Export") — PDF and CSV
report generation covering a project's compliance assessments against its
assigned standards, and an organisation-wide roll-up across every project.

Lives in this module's own package, not `app.services.reports`, mirroring
this module's own established convention for cross-cutting logic that
touches a core service: `project_router.py` already calls
`app.services.files.upload_file` directly from module code for evidence
attachments rather than routing through a new core wrapper (see that
router's own module docstring), and `app.modules.registry.
build_mcp_tool_manifest` is the one core-owned exception to that pattern
(the manifest builder has to live centrally since it aggregates *every*
module's declared tools, not just this one's). A compliance report is a
single module's own reporting surface, so — like the evidence-upload
precedent — it belongs here, reusing `app.services.reports`'s ReportLab/csv
approach and escaping discipline rather than routing report generation
through core `services/reports.py`/`routers/reports.py`, which are already
fully committed to the *requirement*-report shape (`ReportRequirementRow`,
`ProjectReportConfig`'s intro/chapters/appendices) that has no equivalent
concept here.

Two report kinds, one PDF/CSV pair each:
- Project-level (`generate_project_compliance_pdf`/`_csv`, collected by
  `collect_project_compliance_report`): every one of a project's
  (non-archived, unless `include_archived`) `ProjectCompliance` assignments,
  each requirement's applicability/compliance/approval state under it, its
  required actions and linked evidence, plus appendices for the full
  evidence register, review history (project- and standard-level), and any
  cross-standard/cross-version requirement mappings touching this project's
  assigned standards (§29's full field list: standards, standard versions,
  compliance requirements, project compliance assessments, required
  actions, evidence, evidence validity/expiry, approval/sign-off
  information, review history, applicability decisions, cross-standard
  mappings).
- Organisation-level (`generate_org_compliance_pdf`/`_csv`, collected by
  `collect_org_compliance_report`): one row per (project, assigned standard
  version) roll-up across every project in the organisation, plus
  appendices for non-compliant requirements, pending approvals, and
  expiring/expired evidence across every project — deliberately built by
  calling `service.py`'s existing per-project listing functions
  (`list_non_compliant_requirements_for_project` etc., the same functions
  `router.py`'s own Phase 14 org-wide aggregation endpoints call) rather
  than re-deriving any of that traversal or the §20 compliance-percentage
  calculation, per this module's own "avoid duplicating existing
  infrastructure" principle (§31) and so compliance percentages stay
  calculated exactly once, consistently, everywhere they're surfaced (§32).

CSV intentionally carries only the main assessment-row table for each
report kind (one row per requirement, or per project/standard assignment)
— not a separate CSV per appendix — mirroring `services.reports.
generate_csv_report`'s own "CSV is the flat, single-table export; PDF is
where the richer, multi-section layout lives" split for core requirement
reports. The PDF is what carries every appendix (evidence register, review
history, mappings, cross-project drill-downs), since CSV's flat-file shape
has no natural place for them anyway and nothing in §29 requires every
listed field to appear in *both* export formats, only that reports overall
be *capable* of including them.

Report cell layout (Phase 42, docs/compliance-module-plan.md): the PDF's
main requirement table (both report kinds) renders each requirement as one
narrative cell — title always shown, then any of reasoning/description/
clarification/justification/notes present, each on its own bold-prefixed
line — via `_narrative_requirement_paragraph`, rather than one column per
field. This mirrors `docs/requirements.md`'s own table convention (title,
`**Reasoning:**`, `**Clarification:**`, all in one cell) rather than a
spreadsheet-style layout, since a PDF report is read by a person for
context, not machine-parsed the way the CSV export or the standard-
definition JSON export (Phase 21) are. This replaced a real bug where the
PDF's "Requirement" column was built from `_requirement_path`'s breadcrumb,
which silently drops a requirement's own title whenever it also has a
section reference (a `reference` won at every level, leaf included) — see
`_requirement_path`'s own docstring for the full account. The CSV export is
deliberately unaffected: it keeps one column per field for downstream
spreadsheet/pivot use, since a CSV cell has no rich-text/bold-prefix concept
and was never affected by the title-loss bug (it already carries the
requirement's title as its own separate column).

Security note (data classification, `docs/soc2/policies/
data-classification-and-confidentiality-policy.md`): every field surfaced
here (requirement text, justifications/notes, evidence titles/metadata,
approval decisions, user emails) is already returned to the same
organisation/project members via this module's own JSON endpoints
(`router.py`/`project_router.py`), gated by the identical `require_org_
module_enabled`/`require_project_module_enabled`/`require_module_role`
dependencies used here — a report never surfaces anything a caller with
that same access couldn't already read via the API, and evidence *file
contents* are never embedded (only an evidence row's own metadata/title),
so no Restricted-classified attachment payload is pulled into a report
body. All requirement/free-text fields are escaped via `_safe` before
reaching a ReportLab `Paragraph`, for the identical SSRF/markup-injection
reason `app.services.reports._safe`'s own docstring documents — duplicated
here (a five-line function) rather than importing that module's private
helper, so this file stays self-contained the same way `project_router.py`
calling `app.services.files.upload_file` directly does not also reach into
that module's private internals.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.compliance.enums import ComplianceApplicability
from app.modules.compliance.labels import (
    compliance_applicability_label,
    compliance_applicability_source_label,
    compliance_approval_state_label,
    compliance_overall_state_label,
    compliance_review_outcome_label,
    compliance_review_schedule_state_label,
    compliance_review_status_label,
    compliance_status_label,
)
from app.modules.compliance.models import (
    ComplianceEvidence,
    ComplianceEvidenceActionLink,
    ComplianceEvidenceRequirementLink,
    ComplianceMappingRelationshipTypeDefinition,
    ComplianceRequiredAction,
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ComplianceRequirementMapping,
    ComplianceReview,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
)
from app.modules.compliance.service import (
    build_evidence_out,
    build_status_out,
    compute_evidence_validity_state,
    compute_review_schedule_state,
    list_expiring_or_expired_evidence,
    list_non_compliant_requirements_for_project,
    list_pending_approvals_for_project,
    load_pcrs_and_applicability,
)
from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.csv_safety import csv_safe

_styles = getSampleStyleSheet()
_ACCENT = colors.HexColor(DEFAULT_ACCENT_COLOR_HEX)


def _safe(text: str | None) -> str:
    """Escapes `&`/`<`/`>` before handing text to a ReportLab `Paragraph` —
    see this module's own docstring for why this is a deliberate, small
    duplication of `app.services.reports._safe` rather than an import of
    that module's private helper."""
    return _xml_escape(text or "")


def _fmt_date(value: date | None) -> str:
    return value.isoformat() if value else ""


def _fmt_datetime(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


# --- Requirement ordering/path helpers (shared by both collectors) ---------------


def _ordered_requirements(requirements: list[ComplianceRequirement]) -> list[ComplianceRequirement]:
    """Orders a standard version's requirements depth-first, siblings by
    `sort_order` then `name` — the same "chapters/sections read top to
    bottom, in tree order" shape `RequirementTree.tsx`/`ApplicabilityTree.tsx`
    render client-side, reproduced here since a report has no expand/
    collapse tree widget to lean on."""
    by_parent: dict[uuid.UUID | None, list[ComplianceRequirement]] = {}
    for r in requirements:
        by_parent.setdefault(r.parent_requirement_id, []).append(r)
    for siblings in by_parent.values():
        siblings.sort(key=lambda r: (r.sort_order, r.name))

    ordered: list[ComplianceRequirement] = []

    def _walk(parent_id: uuid.UUID | None) -> None:
        for r in by_parent.get(parent_id, []):
            ordered.append(r)
            _walk(r.id)

    _walk(None)
    return ordered


def _requirement_ancestor_breadcrumb(
    requirement: ComplianceRequirement, by_id: dict[uuid.UUID, ComplianceRequirement]
) -> str:
    """Builds a breadcrumb ("3 > 3.2") of `requirement`'s ancestors *only*,
    excluding `requirement` itself — the brief section-context line
    `_narrative_requirement_paragraph` (Phase 42) prints above a
    requirement's own title, so a report reader sees which section a
    requirement lives under without the leaf's own reference/name being
    printed twice. Uses each ancestor's `reference` where set and `name`
    otherwise, same as `_requirement_path` below (which this function is
    itself the ancestor-only half of). Cycle-safe the same way that
    function documents, for the same reason.
    """
    parts: list[str] = []
    seen: set[uuid.UUID] = {requirement.id}
    current: ComplianceRequirement | None = (
        by_id.get(requirement.parent_requirement_id) if requirement.parent_requirement_id else None
    )
    while current is not None and current.id not in seen:
        seen.add(current.id)
        parts.append(current.reference or current.name)
        current = by_id.get(current.parent_requirement_id) if current.parent_requirement_id else None
    return " > ".join(reversed(parts))


def _requirement_path(requirement: ComplianceRequirement, by_id: dict[uuid.UUID, ComplianceRequirement]) -> str:
    """Builds a breadcrumb ("3 > 3.2 > 3.2.1") from a requirement up through
    its ancestors, using each row's `reference` where set and its `name`
    otherwise for *every* segment, including the leaf itself — this is the
    CSV export's "Requirement path" column, a compact machine-oriented
    locator, not the human-facing report cell. Cycle-safe (a malformed tree
    can never infinite-loop this), though `parent_requirement_id` cannot
    actually form a cycle in practice — enforced structurally the same way
    `Project.parent_project_id`'s own hierarchy is (see that field's own
    docstring).

    Deliberately *not* used for the PDF's own "Requirement" column
    (`_narrative_requirement_paragraph` below) — Phase 42 fixed a real bug
    where that column used to call this function directly, which silently
    drops a requirement's own `name` (its title) whenever it also has a
    `reference`, since a `reference` wins over `name` at every level
    including the leaf's. A CSV row always carries `requirement_name` as
    its own separate column, so this function's leaf-drops-title behaviour
    never lost the title there — only the PDF, which had no other column
    carrying it, was actually affected.
    """
    leaf = requirement.reference or requirement.name
    ancestors = _requirement_ancestor_breadcrumb(requirement, by_id)
    return f"{ancestors} > {leaf}" if ancestors else leaf


# --- Project-level report ---------------------------------------------------------


@dataclass
class ComplianceReportRequirementRow:
    """One requirement's project-specific assessment, under one assigned
    standard version — the main row of both the project- and (implicitly,
    via §29's "project compliance assessments") org-level compliance
    reports' primary table.

    `ancestor_path`/`requirement_reasoning`/`requirement_description`/
    `requirement_clarification` are Phase 42's own addition, feeding
    `_narrative_requirement_paragraph`'s single-cell report layout — they
    default to `""` so `_requirement_report_row_from_out` (the org report's
    non-compliant/pending-approval appendix adapter, built from an already-
    narrower `NonCompliantRequirementOut`/`PendingApprovalOut` response
    schema with no reasoning/description/clarification fields of its own)
    doesn't need to change to keep constructing this dataclass.
    """

    standard_reference: str
    standard_name: str
    version_label: str
    requirement_path: str
    requirement_reference: str
    requirement_name: str
    effective_applicability: str
    applicability_source: str
    compliance_status: str
    justification: str
    notes: str
    approval_state: str
    approval_decided_at: str
    approval_decided_by_email: str
    decision_note: str
    required_actions_summary: str
    evidence_titles: str
    ancestor_path: str = ""
    requirement_reasoning: str = ""
    requirement_description: str = ""
    requirement_clarification: str = ""


@dataclass
class ComplianceReportEvidenceRow:
    """One piece of evidence, for a report's evidence-register appendix
    (§29's "Evidence," "Evidence validity/expiry")."""

    title: str
    issuing_organisation: str
    issued_date: str
    expiry_date: str
    validity_state: str
    provided_by_email: str
    is_archived: bool
    linked_requirement_count: int


@dataclass
class ComplianceReportReviewRow:
    """One scheduled or completed compliance review, for a report's review-
    history appendix (§29's "Review history")."""

    scope: str
    frequency_label: str
    next_due_date: str
    status: str
    schedule_state: str
    outcome: str
    completed_at: str
    completed_by_email: str


@dataclass
class ComplianceReportMappingRow:
    """One cross-standard/cross-version requirement mapping touching a
    requirement in scope for this report (§29's "Cross-standard mappings")."""

    from_label: str
    relationship_type: str
    to_label: str
    notes: str


@dataclass
class ProjectComplianceReportData:
    """Everything `generate_project_compliance_pdf`/`_csv` need, collected
    once by `collect_project_compliance_report` — see that function's own
    docstring for exactly what each field covers."""

    requirement_rows: list[ComplianceReportRequirementRow] = field(default_factory=list)
    evidence_rows: list[ComplianceReportEvidenceRow] = field(default_factory=list)
    review_rows: list[ComplianceReportReviewRow] = field(default_factory=list)
    mapping_rows: list[ComplianceReportMappingRow] = field(default_factory=list)


def _requirement_label(reference: str | None, name: str) -> str:
    return f"{reference} {name}".strip() if reference else name


def collect_project_compliance_report(
    db: Session, project: Project, *, include_archived: bool = False
) -> ProjectComplianceReportData:
    """Gathers every field §29 asks a compliance report to be capable of
    including, for one project, across every standard it is (or, with
    `include_archived=True`, has ever been) assigned to.

    Reuses `service.py`'s existing computed-state builders throughout
    (`load_pcrs_and_applicability` for §9's hierarchical applicability
    resolution, `compute_evidence_validity_state`/`compute_review_schedule_
    state` for §14/§17's derived states) rather than re-deriving any of
    them — the same "one calculation, every caller" principle `service.py`'s
    own docstring already establishes for its cross-project/cross-scope
    callers, extended to this report generator.

    Args:
        db: An active database session.
        project: The project to report on.
        include_archived: Whether to include assignments the project has
            archived (stopped tracking) — off by default, mirroring every
            other listing in this module's own "active unless asked
            otherwise" convention.

    Returns:
        The collected report data.
    """
    query = select(ProjectCompliance).where(ProjectCompliance.project_id == project.id)
    if not include_archived:
        query = query.where(ProjectCompliance.is_archived.is_(False))
    assignments = list(db.scalars(query).all())

    data = ProjectComplianceReportData()
    all_requirement_ids: set[uuid.UUID] = set()
    organization_id = project.organization_id

    for pc in assignments:
        version = db.get(ComplianceStandardVersion, pc.standard_version_id)
        standard = db.get(ComplianceStandard, version.standard_id)
        requirements = list(
            db.scalars(
                select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == version.id)
            ).all()
        )
        by_id = {r.id: r for r in requirements}
        all_requirement_ids.update(by_id)

        pcrs, applicability = load_pcrs_and_applicability(
            db, project_compliance_id=pc.id, standard_version_id=version.id
        )
        pcr_by_requirement_id = {pcr.requirement_id: pcr for pcr in pcrs}

        # Batched, not per-requirement: required actions/assessments/evidence
        # links for every requirement under this one assignment, gathered in
        # a handful of `IN (...)` queries rather than N+1 per requirement.
        required_actions = list(
            db.scalars(select(ComplianceRequiredAction).where(ComplianceRequiredAction.requirement_id.in_(by_id))).all()
        ) if by_id else []
        actions_by_requirement: dict[uuid.UUID, list[ComplianceRequiredAction]] = {}
        for action in required_actions:
            actions_by_requirement.setdefault(action.requirement_id, []).append(action)

        pcr_ids = [pcr.id for pcr in pcrs]
        assessments = list(
            db.scalars(
                select(ComplianceRequiredActionAssessment).where(
                    ComplianceRequiredActionAssessment.project_compliance_requirement_id.in_(pcr_ids)
                )
            ).all()
        ) if pcr_ids else []
        assessment_by_action_id = {a.required_action_id: a for a in assessments}
        assessment_ids = [a.id for a in assessments]

        req_evidence_links = list(
            db.scalars(
                select(ComplianceEvidenceRequirementLink).where(
                    ComplianceEvidenceRequirementLink.project_compliance_requirement_id.in_(pcr_ids)
                )
            ).all()
        ) if pcr_ids else []
        action_evidence_links = list(
            db.scalars(
                select(ComplianceEvidenceActionLink).where(
                    ComplianceEvidenceActionLink.required_action_assessment_id.in_(assessment_ids)
                )
            ).all()
        ) if assessment_ids else []
        evidence_ids = {link.evidence_id for link in req_evidence_links} | {link.evidence_id for link in action_evidence_links}
        evidence_rows_for_ids = (
            db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.id.in_(evidence_ids))).all() if evidence_ids else []
        )
        evidence_title_by_id = {e.id: e.title for e in evidence_rows_for_ids}
        evidence_ids_by_pcr: dict[uuid.UUID, set[uuid.UUID]] = {}
        for link in req_evidence_links:
            evidence_ids_by_pcr.setdefault(link.project_compliance_requirement_id, set()).add(link.evidence_id)
        assessment_pcr_by_id = {a.id: a.project_compliance_requirement_id for a in assessments}
        for link in action_evidence_links:
            pcr_id = assessment_pcr_by_id.get(link.required_action_assessment_id)
            if pcr_id is not None:
                evidence_ids_by_pcr.setdefault(pcr_id, set()).add(link.evidence_id)

        approver_emails = _emails_by_id(
            db, {pcr.approval_decided_by for pcr in pcrs if pcr.approval_decided_by}
        )

        for requirement in _ordered_requirements(requirements):
            pcr = pcr_by_requirement_id.get(requirement.id)
            if pcr is None:
                continue
            effective, source = applicability[requirement.id]
            actions = actions_by_requirement.get(requirement.id, [])
            done = sum(1 for a in actions if assessment_by_action_id.get(a.id) and assessment_by_action_id[a.id].is_completed)
            actions_summary = f"{done}/{len(actions)} done" if actions else ""
            evidence_titles = ", ".join(
                sorted(evidence_title_by_id[e_id] for e_id in evidence_ids_by_pcr.get(pcr.id, set()) if e_id in evidence_title_by_id)
            )
            data.requirement_rows.append(ComplianceReportRequirementRow(
                standard_reference=standard.reference, standard_name=standard.name, version_label=version.version_label,
                requirement_path=_requirement_path(requirement, by_id),
                requirement_reference=requirement.reference or "", requirement_name=requirement.name,
                effective_applicability=compliance_applicability_label(effective.value),
                applicability_source=compliance_applicability_source_label(source.value),
                compliance_status=(
                    compliance_status_label(pcr.compliance_status.value)
                    if effective == ComplianceApplicability.APPLICABLE else ""
                ),
                justification=pcr.justification, notes=pcr.notes,
                approval_state=(
                    compliance_approval_state_label(pcr.approval_state.value)
                    if effective == ComplianceApplicability.APPLICABLE else ""
                ),
                approval_decided_at=_fmt_datetime(pcr.approval_decided_at),
                approval_decided_by_email=approver_emails.get(pcr.approval_decided_by, ""),
                decision_note=pcr.decision_note, required_actions_summary=actions_summary, evidence_titles=evidence_titles,
                ancestor_path=_requirement_ancestor_breadcrumb(requirement, by_id),
                requirement_reasoning=requirement.reasoning, requirement_description=requirement.description,
                requirement_clarification=requirement.last_clarification_note,
            ))

        # Review history for this assignment: its own project-level reviews,
        # plus its standard's own standard-level reviews (§17's "Compliance
        # Standards and Project Compliance records must support scheduled
        # reviews" — both owners are relevant background for a project's own
        # compliance report against that standard).
        reviews = list(
            db.scalars(
                select(ComplianceReview)
                .where(
                    (ComplianceReview.project_compliance_id == pc.id) | (ComplianceReview.standard_id == standard.id)
                )
                .order_by(ComplianceReview.created_at)
            ).all()
        )
        review_user_ids = {r.owner_id for r in reviews if r.owner_id} | {r.completed_by for r in reviews if r.completed_by}
        review_emails = _emails_by_id(db, review_user_ids)
        for review in reviews:
            scope = f"{standard.name} (standard)" if review.standard_id else f"{project.name} (project)"
            data.review_rows.append(ComplianceReportReviewRow(
                scope=scope, frequency_label=review.frequency_label, next_due_date=_fmt_date(review.next_due_date),
                status=compliance_review_status_label(review.status.value),
                schedule_state=compliance_review_schedule_state_label(compute_review_schedule_state(review)),
                outcome=compliance_review_outcome_label(review.outcome.value if review.outcome else None),
                completed_at=_fmt_datetime(review.completed_at),
                completed_by_email=review_emails.get(review.completed_by, ""),
            ))

    # Evidence register: every piece of evidence for the project (not just
    # what's linked under the assignments above — §13's evidence is
    # project-scoped and may exist unlinked, or linked only to an assignment
    # this report excluded via `include_archived=False`).
    evidence_rows = list(db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.project_id == project.id)).all())
    evidence_provider_emails = _emails_by_id(db, {e.provided_by for e in evidence_rows})
    for evidence in evidence_rows:
        linked_count = len(build_evidence_out(db, evidence).linked_requirement_ids)
        data.evidence_rows.append(ComplianceReportEvidenceRow(
            title=evidence.title, issuing_organisation=evidence.issuing_organisation or "",
            issued_date=_fmt_date(evidence.issued_date), expiry_date=_fmt_date(evidence.expiry_date),
            validity_state=compute_evidence_validity_state(evidence).value, provided_by_email=evidence_provider_emails.get(evidence.provided_by, ""),
            is_archived=evidence.is_archived, linked_requirement_count=linked_count,
        ))

    # Cross-standard/cross-version mappings touching any requirement in
    # scope for this report (§29's "Cross-standard mappings").
    if all_requirement_ids:
        mappings = list(
            db.scalars(
                select(ComplianceRequirementMapping).where(
                    ComplianceRequirementMapping.organization_id == organization_id,
                    ComplianceRequirementMapping.is_archived.is_(False),
                    (
                        ComplianceRequirementMapping.from_requirement_id.in_(all_requirement_ids)
                        | ComplianceRequirementMapping.to_requirement_id.in_(all_requirement_ids)
                    ),
                )
            ).all()
        )
        other_ids = {m.from_requirement_id for m in mappings} | {m.to_requirement_id for m in mappings}
        requirement_by_id = {
            r.id: r for r in db.scalars(select(ComplianceRequirement).where(ComplianceRequirement.id.in_(other_ids))).all()
        } if other_ids else {}
        version_ids = {r.standard_version_id for r in requirement_by_id.values()}
        version_by_id = {
            v.id: v for v in db.scalars(select(ComplianceStandardVersion).where(ComplianceStandardVersion.id.in_(version_ids))).all()
        } if version_ids else {}
        standard_ids = {v.standard_id for v in version_by_id.values()}
        standard_by_id = {
            s.id: s for s in db.scalars(select(ComplianceStandard).where(ComplianceStandard.id.in_(standard_ids))).all()
        } if standard_ids else {}
        relationship_type_by_id = {
            t.id: t for t in db.scalars(select(ComplianceMappingRelationshipTypeDefinition).where(
                ComplianceMappingRelationshipTypeDefinition.organization_id == organization_id
            )).all()
        }

        def _side_label(requirement_id: uuid.UUID) -> str:
            r = requirement_by_id.get(requirement_id)
            if r is None:
                return "(unknown requirement)"
            v = version_by_id.get(r.standard_version_id)
            s = standard_by_id.get(v.standard_id) if v else None
            standard_bit = f"{s.reference} v{v.version_label}" if s and v else ""
            return f"{standard_bit}: {_requirement_label(r.reference, r.name)}".strip(": ")

        for mapping in mappings:
            relationship_type = relationship_type_by_id.get(mapping.relationship_type_id)
            data.mapping_rows.append(ComplianceReportMappingRow(
                from_label=_side_label(mapping.from_requirement_id),
                relationship_type=relationship_type.name if relationship_type else "",
                to_label=_side_label(mapping.to_requirement_id),
                notes=mapping.notes,
            ))

    return data


def _emails_by_id(db: Session, user_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    """One batched user lookup for a set of possibly-`None` ids, mirroring
    `services.project_export`'s own established "single deployment-wide
    lookup, not N+1" pattern."""
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    return {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids))).all()}


_TABLE_CELL_STYLE = ParagraphStyle("compliance_cell", parent=_styles["BodyText"], fontSize=7.5, leading=9)


def _p(text: str) -> Paragraph:
    return Paragraph(_safe(text), _TABLE_CELL_STYLE)


def _styled_table(data: list[list], col_widths: list[float]) -> Table:
    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _narrative_requirement_paragraph(row: ComplianceReportRequirementRow) -> Paragraph:
    """Builds one requirement's report-table cell as a single narrative
    block — title, then each present free-text field on its own bold-
    prefixed line — mirroring `docs/requirements.md`'s own table convention
    (one requirement per cell: its own text, then `**Reasoning:**`/
    `**Clarification:**`, newline-separated in the same cell) rather than
    one column per field (Phase 42; see this module's own docstring for the
    full "why").

    The requirement's own title (`requirement_reference` + `requirement_
    name`, or just `requirement_name` when there's no reference) is always
    the lead line, regardless of whether `requirement_reference` is set —
    the specific bug Phase 42 fixes (the PDF's "Requirement" column used to
    be built from `_requirement_path`, which drops a requirement's own name
    whenever it has a reference; see that function's own docstring).
    `ancestor_path`, when non-empty, prints above the title in italics as
    brief section context (e.g. "4 > 4.1") without duplicating the leaf's
    own label.

    Every other field (`requirement_reasoning`/`requirement_description`/
    `requirement_clarification`/`justification`/`notes`) prints only when
    non-empty, in that order, so a requirement with nothing to say beyond
    its title and status doesn't grow a stack of empty "X:" lines — the
    same "present-if-non-empty" convention `_markdown_to_flowables`'s core-
    report sibling in `app.services.reports` already uses for its own
    optional sections.

    Every interpolated field value is escaped via `_safe()` before being
    embedded in the returned `Paragraph`'s markup — only the literal
    `<b>`/`<br/>`/`<i>` structural tags this function itself adds are ever
    left unescaped, for the identical SSRF/markup-injection reason this
    module's own docstring documents for `_safe()`.
    """
    segments: list[str] = []
    if row.ancestor_path:
        segments.append(f"<i>{_safe(row.ancestor_path)}</i>")
    title = f"{row.requirement_reference} {row.requirement_name}".strip() if row.requirement_reference else row.requirement_name
    segments.append(f"<b>{_safe(title)}</b>")
    for label, value in (
        ("Reasoning", row.requirement_reasoning),
        ("Description", row.requirement_description),
        ("Clarification", row.requirement_clarification),
        ("Justification", row.justification),
        ("Notes", row.notes),
    ):
        if value:
            segments.append(f"<b>{label}:</b> {_safe(value)}")
    return Paragraph("<br/>".join(segments), _TABLE_CELL_STYLE)


def generate_project_compliance_pdf(project_name: str, data: ProjectComplianceReportData) -> bytes:
    """Builds a PDF compliance report for one project — suitable for
    internal review and external audit preparation alike (§29's explicit
    requirement for both), since every section is the same regardless of
    audience: this module deliberately does not maintain two different
    report shapes for "internal" vs. "for an auditor."

    Sections, in order: a main table (one row per requirement per assigned
    standard, §29's "compliance requirements"/"project compliance
    assessments"/"applicability decisions"/"approval-sign-off information"),
    an evidence register appendix (§29's "evidence"/"evidence validity/
    expiry"), a review history appendix (§29's "review history"), and a
    cross-standard mappings appendix (§29's "cross-standard mappings") —
    the last three omitted entirely when empty, rather than printing an
    empty heading with nothing under it.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    story: list = [
        Paragraph(_safe(f"{project_name} — Compliance Report"), _styles["Title"]),
        Spacer(1, 0.5 * cm),
    ]

    if not data.requirement_rows:
        story.append(Paragraph("This project has no assigned compliance standards.", _styles["BodyText"]))
    else:
        # "Requirement" is a Phase 42 narrative cell (title, then any of
        # reasoning/description/clarification/justification/notes present)
        # rather than a separate column per field — see
        # `_narrative_requirement_paragraph`'s own docstring. There is no
        # longer a standalone "Justification/Notes" column: those two
        # fields now fold into the same narrative cell as the requirement
        # they belong to, and the Requirement column's width absorbs what
        # that column used to occupy (both tables' total width unchanged).
        header = ["Standard", "Requirement", "Applicability", "Status", "Approval", "Actions", "Evidence"]
        rows = [header]
        for r in data.requirement_rows:
            rows.append([
                _p(f"{r.standard_reference} v{r.version_label}"),
                _narrative_requirement_paragraph(r),
                _p(f"{r.effective_applicability} ({r.applicability_source})" if r.applicability_source != "Explicit" else r.effective_applicability),
                _p(r.compliance_status),
                _p(r.approval_state),
                _p(r.required_actions_summary),
                _p(r.evidence_titles),
            ])
        story.append(_styled_table(rows, [2.5 * cm, 6.5 * cm, 2.3 * cm, 1.8 * cm, 1.8 * cm, 1.4 * cm, 2.7 * cm]))

    if data.evidence_rows:
        story.append(PageBreak())
        story.append(Paragraph("Evidence Register", _styles["Heading1"]))
        story.append(Spacer(1, 0.3 * cm))
        rows = [["Title", "Issuing organisation", "Issued", "Expiry", "Validity", "Provided by", "Linked to", "Archived"]]
        for e in data.evidence_rows:
            rows.append([
                _p(e.title), _p(e.issuing_organisation), _p(e.issued_date), _p(e.expiry_date), _p(e.validity_state.replace("_", " ").title()),
                _p(e.provided_by_email), _p(str(e.linked_requirement_count)), _p("Yes" if e.is_archived else "No"),
            ])
        story.append(_styled_table(rows, [3 * cm, 3 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 3 * cm, 1.5 * cm, 1.6 * cm]))

    if data.review_rows:
        story.append(PageBreak())
        story.append(Paragraph("Review History", _styles["Heading1"]))
        story.append(Spacer(1, 0.3 * cm))
        rows = [["Scope", "Frequency", "Next due", "Status", "Schedule", "Outcome", "Completed", "Completed by"]]
        for rv in data.review_rows:
            rows.append([
                _p(rv.scope), _p(rv.frequency_label), _p(rv.next_due_date), _p(rv.status), _p(rv.schedule_state),
                _p(rv.outcome), _p(rv.completed_at), _p(rv.completed_by_email),
            ])
        story.append(_styled_table(rows, [3 * cm, 2 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 2 * cm, 2.2 * cm, 3 * cm]))

    if data.mapping_rows:
        story.append(PageBreak())
        story.append(Paragraph("Cross-Standard Mappings", _styles["Heading1"]))
        story.append(Spacer(1, 0.3 * cm))
        rows = [["From", "Relationship", "To", "Notes"]]
        for m in data.mapping_rows:
            rows.append([_p(m.from_label), _p(m.relationship_type), _p(m.to_label), _p(m.notes)])
        story.append(_styled_table(rows, [5.5 * cm, 2.5 * cm, 5.5 * cm, 4 * cm]))

    doc.build(story)
    return buffer.getvalue()


def generate_project_compliance_csv(data: ProjectComplianceReportData) -> bytes:
    """Builds a flat, one-row-per-requirement CSV export of a project's
    compliance assessments — see this module's own docstring for why CSV
    carries only this main table, not the PDF's other appendices."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Standard reference", "Standard name", "Version", "Requirement path", "Requirement reference", "Requirement title",
        "Applicability", "Applicability source", "Compliance status", "Justification", "Notes", "Approval state",
        "Approval decided at", "Approved/rejected by", "Decision note", "Required actions", "Evidence",
    ])
    for r in data.requirement_rows:
        writer.writerow([csv_safe(v) for v in [
            r.standard_reference, r.standard_name, r.version_label, r.requirement_path, r.requirement_reference,
            r.requirement_name, r.effective_applicability, r.applicability_source, r.compliance_status, r.justification,
            r.notes, r.approval_state, r.approval_decided_at, r.approval_decided_by_email, r.decision_note,
            r.required_actions_summary, r.evidence_titles,
        ]])
    return buffer.getvalue().encode("utf-8")


# --- Organisation-level report ------------------------------------------------


@dataclass
class OrgComplianceReportAssignmentRow:
    """One project's assignment to one standard version, with its computed
    §20 status — the organisation-level report's main table (one row per
    (project, assigned standard version) pair, mirroring `router.py::
    list_all_project_compliance`'s own per-assignment iteration)."""

    project_name: str
    standard_reference: str
    standard_name: str
    version_label: str
    compliance_percentage: float
    overall_compliance_state: str
    overall_approval_state: str
    total_requirements: int
    applicable_count: int
    not_applicable_count: int
    non_compliant_count: int
    target_compliance_date: str


@dataclass
class OrgComplianceReportData:
    """Everything `generate_org_compliance_pdf`/`_csv` need, collected once
    by `collect_org_compliance_report`."""

    assignment_rows: list[OrgComplianceReportAssignmentRow] = field(default_factory=list)
    non_compliant_rows: list[tuple[str, ComplianceReportRequirementRow]] = field(default_factory=list)
    pending_approval_rows: list[tuple[str, ComplianceReportRequirementRow]] = field(default_factory=list)
    expiring_evidence_rows: list[tuple[str, ComplianceReportEvidenceRow]] = field(default_factory=list)


def collect_org_compliance_report(db: Session, organization_id: uuid.UUID) -> OrgComplianceReportData:
    """Gathers an organisation-wide compliance roll-up: every project's
    every (non-archived) standard assignment with its computed §20 status,
    plus cross-project appendices for non-compliant requirements, pending
    approvals, and expiring/expired evidence — the same three listings
    `router.py`'s own Phase 14 org-wide aggregation endpoints
    (`list_org_non_compliant_requirements` etc.) expose, reused here via
    `service.py`'s underlying per-project functions rather than duplicated,
    per this module's own "one calculation, every caller" principle.

    Args:
        db: An active database session.
        organization_id: The organisation to report on.

    Returns:
        The collected report data.
    """
    projects = list(db.scalars(select(Project).where(Project.organization_id == organization_id)).all())
    data = OrgComplianceReportData()

    for project in projects:
        assignments = list(
            db.scalars(
                select(ProjectCompliance).where(
                    ProjectCompliance.project_id == project.id, ProjectCompliance.is_archived.is_(False)
                )
            ).all()
        )
        for pc in assignments:
            status_out = build_status_out(db, pc)
            data.assignment_rows.append(OrgComplianceReportAssignmentRow(
                project_name=project.name, standard_reference=status_out.standard_reference,
                standard_name=status_out.standard_name, version_label=status_out.version_label,
                compliance_percentage=status_out.compliance_percentage,
                overall_compliance_state=compliance_overall_state_label(status_out.overall_compliance_state),
                overall_approval_state=compliance_approval_state_label(status_out.overall_approval_state.value),
                total_requirements=status_out.total_requirements, applicable_count=status_out.applicable_count,
                not_applicable_count=status_out.not_applicable_count,
                non_compliant_count=status_out.counts_by_status.get("non_compliant", 0),
                target_compliance_date=_fmt_date(status_out.target_compliance_date),
            ))

        for row in list_non_compliant_requirements_for_project(db, project_id=project.id):
            data.non_compliant_rows.append((project.name, _requirement_report_row_from_out(row)))
        for row in list_pending_approvals_for_project(db, project_id=project.id):
            data.pending_approval_rows.append((project.name, _requirement_report_row_from_out(row, is_pending=True)))
        for evidence in list_expiring_or_expired_evidence(db, project_id=project.id):
            evidence_out = build_evidence_out(db, evidence)
            data.expiring_evidence_rows.append((project.name, ComplianceReportEvidenceRow(
                title=evidence.title, issuing_organisation=evidence.issuing_organisation or "",
                issued_date=_fmt_date(evidence.issued_date), expiry_date=_fmt_date(evidence.expiry_date),
                validity_state=evidence_out.validity_state.value, provided_by_email="", is_archived=evidence.is_archived,
                linked_requirement_count=len(evidence_out.linked_requirement_ids),
            )))

    return data


def _requirement_report_row_from_out(row, *, is_pending: bool = False) -> ComplianceReportRequirementRow:
    """Adapts `NonCompliantRequirementOut`/`PendingApprovalOut` (already-
    built response schemas `service.py` produces for the JSON API) into this
    module's own report row shape, so the org report's appendices reuse
    those exact, already-correct listings instead of re-querying."""
    return ComplianceReportRequirementRow(
        standard_reference=row.standard_reference, standard_name=row.standard_name, version_label=row.version_label,
        requirement_path=_requirement_label(row.requirement_reference, row.requirement_name),
        requirement_reference=row.requirement_reference or "", requirement_name=row.requirement_name,
        effective_applicability="", applicability_source="",
        compliance_status=compliance_status_label(row.compliance_status.value) if is_pending else "Non-compliant",
        justification=getattr(row, "justification", ""), notes=getattr(row, "notes", ""),
        approval_state="", approval_decided_at="", approval_decided_by_email="", decision_note="",
        required_actions_summary="", evidence_titles="",
    )


def generate_org_compliance_pdf(org_name: str, data: OrgComplianceReportData) -> bytes:
    """Builds an organisation-wide PDF compliance roll-up: a main table (one
    row per project/assigned-standard-version pair, §29's "organisation-
    level reporting") plus non-compliant/pending-approval/expiring-evidence
    appendices across every project — the same drill-downs the Org
    Compliance Dashboard offers interactively (`OrgComplianceDashboard.tsx`),
    reproduced here as a static, exportable snapshot for audit preparation."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    story: list = [
        Paragraph(_safe(f"{org_name} — Organisation Compliance Report"), _styles["Title"]),
        Spacer(1, 0.5 * cm),
    ]

    if not data.assignment_rows:
        story.append(Paragraph("No projects in this organisation are assigned any compliance standard.", _styles["BodyText"]))
    else:
        rows = [["Project", "Standard", "Compliance %", "Overall status", "Approval status", "Non-compliant", "Target date"]]
        for a in data.assignment_rows:
            rows.append([
                _p(a.project_name), _p(f"{a.standard_reference} v{a.version_label}"), _p(f"{a.compliance_percentage:.1f}%"),
                _p(a.overall_compliance_state), _p(a.overall_approval_state), _p(str(a.non_compliant_count)), _p(a.target_compliance_date),
            ])
        story.append(_styled_table(rows, [3.5 * cm, 3.5 * cm, 2 * cm, 2.5 * cm, 2.5 * cm, 2 * cm, 1.8 * cm]))

    def _appendix(title: str, rows_with_project: list, columns: list[str], cell_fn, col_widths: list[float]) -> None:
        if not rows_with_project:
            return
        story.append(PageBreak())
        story.append(Paragraph(title, _styles["Heading1"]))
        story.append(Spacer(1, 0.3 * cm))
        table_rows = [columns]
        for project_name, item in rows_with_project:
            table_rows.append(cell_fn(project_name, item))
        story.append(_styled_table(table_rows, col_widths))

    # Both appendices' "Requirement" column is the same Phase 42 narrative
    # cell the main project report uses (`_narrative_requirement_paragraph`)
    # — for "Non-Compliant Requirements" this also folds in the separate
    # "Justification" column the two-column version used to carry, since
    # `_requirement_report_row_from_out` already populates `justification`
    # on these rows the same way the project report's own rows do.
    _appendix(
        "Non-Compliant Requirements", data.non_compliant_rows, ["Project", "Standard", "Requirement"],
        lambda project_name, r: [_p(project_name), _p(f"{r.standard_reference} v{r.version_label}"), _narrative_requirement_paragraph(r)],
        [3 * cm, 3 * cm, 11 * cm],
    )
    _appendix(
        "Pending Approvals", data.pending_approval_rows, ["Project", "Standard", "Requirement", "Status"],
        lambda project_name, r: [_p(project_name), _p(f"{r.standard_reference} v{r.version_label}"), _narrative_requirement_paragraph(r), _p(r.compliance_status)],
        [3 * cm, 3 * cm, 7 * cm, 4 * cm],
    )
    _appendix(
        "Expiring/Expired Evidence", data.expiring_evidence_rows, ["Project", "Title", "Expiry", "Validity"],
        lambda project_name, e: [_p(project_name), _p(e.title), _p(e.expiry_date), _p(e.validity_state.replace("_", " ").title())],
        [4 * cm, 6 * cm, 3 * cm, 4 * cm],
    )

    doc.build(story)
    return buffer.getvalue()


def generate_org_compliance_csv(data: OrgComplianceReportData) -> bytes:
    """Builds a flat, one-row-per-(project, assigned standard version) CSV
    export of the organisation-wide roll-up — see this module's own
    docstring for why CSV carries only this main table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Project", "Standard reference", "Standard name", "Version", "Compliance %", "Overall status", "Approval status",
        "Total requirements", "Applicable", "Not applicable", "Non-compliant count", "Target compliance date",
    ])
    for a in data.assignment_rows:
        writer.writerow([csv_safe(str(v)) for v in [
            a.project_name, a.standard_reference, a.standard_name, a.version_label, f"{a.compliance_percentage:.1f}",
            a.overall_compliance_state, a.overall_approval_state, a.total_requirements, a.applicable_count,
            a.not_applicable_count, a.non_compliant_count, a.target_compliance_date,
        ]])
    return buffer.getvalue().encode("utf-8")
