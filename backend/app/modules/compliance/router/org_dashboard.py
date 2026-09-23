"""
Module: modules.compliance.router.org_dashboard

This organisation's project-compliance assignments and the org-wide
rollup GETs built on top of them: assign a standard to a project
(`create_project_compliance`) and archive/unarchive that assignment,
list every project-compliance row org-wide, and the non-compliant-
requirements/pending-approvals/outstanding-required-actions/expiring-
evidence/reviews-due/recent-activity/report rollups across every
project. Kept as one bucket rather than splitting the rollup GETs out
on their own, since every one of them shares this file's
`_get_project_or_404`/`_get_project_compliance_or_404`/`_org_projects`
helpers and the same `ProjectCompliance` resource the assignment
mutations manage.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.notification import NotificationType
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.enums import ComplianceStandardVersionStatus
from app.modules.compliance.models import ProjectCompliance
from app.modules.compliance.reports import collect_org_compliance_report, generate_org_compliance_csv, generate_org_compliance_pdf
from app.modules.compliance.router._shared import _get_version_or_404, _require_manage
from app.modules.compliance.schemas import (
    ComplianceRecentActivityOut,
    OrgExpiringEvidenceOut,
    OrgNonCompliantRequirementOut,
    OrgPendingApprovalOut,
    OrgReviewDueOut,
    OutstandingRequiredActionOut,
    ProjectComplianceCreate,
    ProjectComplianceOut,
    ProjectComplianceStatusOut,
)
from app.modules.compliance.service import (
    build_evidence_out,
    build_review_out,
    build_status_out,
    get_effective_compliance_officers,
    list_expiring_or_expired_evidence,
    list_non_compliant_requirements_for_project,
    list_outstanding_required_actions_for_project,
    list_pending_approvals_for_project,
    list_recent_compliance_activity,
    list_reviews_due_for_project,
    materialize_assessment_rows,
)
from app.services import notifications
from app.services.audit import log_event
from app.services.downloads import filename_safe

router = APIRouter(tags=["compliance-org-dashboard"])


def _get_project_or_404(db: Session, organization_id: UUID, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _get_project_compliance_or_404(
    db: Session, organization_id: UUID, project_id: UUID, project_compliance_id: UUID
) -> ProjectCompliance:
    _get_project_or_404(db, organization_id, project_id)
    project_compliance = db.get(ProjectCompliance, project_compliance_id)
    if project_compliance is None or project_compliance.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project compliance assignment not found.")
    return project_compliance


@router.post(
    "/projects/{project_id}/project-compliance", response_model=ProjectComplianceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project_compliance(
    organization_id: UUID, project_id: UUID, payload: ProjectComplianceCreate,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Assigns a compliance standard version to a project (§7) — a
    Compliance Manager decision (module.py's own role description; §26
    doesn't list this as a Project Manager/Compliance Officer capability).
    Only a `PUBLISHED` version may be assigned (409 otherwise) — see
    `models.py`'s own docstring for why. Materialises the full per-
    requirement/per-required-action assessment row set for this
    assignment in the same transaction (`service.materialize_assessment_
    rows`) — see that function's own docstring for why this happens once,
    upfront, rather than lazily.

    As of Phase 20, this is the *secondary*, administrative assignment
    path (a Compliance Manager assigning on a project's behalf, or in
    bulk) — the default, primary path is `project_router.py::create_
    project_compliance_self_service`, usable by a plain Project Manager.
    This endpoint's own payload/response/behaviour are otherwise
    unchanged."""
    _get_project_or_404(db, organization_id, project_id)
    _, version = _get_version_or_404(db, organization_id, payload.standard_id, payload.standard_version_id)
    if version.status != ComplianceStandardVersionStatus.PUBLISHED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only a published standard version can be assigned to a project."
        )
    existing = db.scalar(
        select(ProjectCompliance.id).where(
            ProjectCompliance.project_id == project_id, ProjectCompliance.standard_version_id == version.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project is already assigned to this standard version.")

    project_compliance = ProjectCompliance(
        project_id=project_id, standard_version_id=version.id,
        assigned_at=datetime.now(UTC), assigned_by=current_user.id,
        target_compliance_date=payload.target_compliance_date,
    )
    db.add(project_compliance)
    db.flush()
    materialize_assessment_rows(db, project_compliance_id=project_compliance.id, standard_version_id=version.id)
    log_event(db, entity_type="project_compliance", entity_id=project_compliance.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, project_id=project_id,
              detail={"standard_version_id": str(version.id)})
    for recipient_id in get_effective_compliance_officers(db, project_id):
        recipient = db.get(User, recipient_id)
        if recipient is None:
            continue
        notifications.notify(
            db, recipient, notification_type=NotificationType.COMPLIANCE_ASSIGNMENT_CREATED,
            title="New compliance assignment",
            body="This project was assigned to a compliance standard and needs assessment to begin.",
            project_id=project_id, entity_type="project_compliance", entity_id=str(project_compliance.id),
            actor_id=current_user.id,
        )
    db.commit()
    db.refresh(project_compliance)
    return project_compliance


@router.get("/project-compliance", response_model=list[ProjectComplianceStatusOut])
def list_all_project_compliance(
    organization_id: UUID, include_archived: bool = Query(False),
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Lists every `ProjectCompliance` assignment across this
    organisation's projects, each with its computed §20 overall status —
    the Compliance Manager's "View compliance across projects" capability
    (§26). Manage-gated, not view-gated: §26 lists this specifically under
    Compliance Manager, not under any project role or general org
    membership."""
    query = (
        select(ProjectCompliance)
        .join(Project, Project.id == ProjectCompliance.project_id)
        .where(Project.organization_id == organization_id)
    )
    if not include_archived:
        query = query.where(ProjectCompliance.is_archived.is_(False))
    assignments = db.scalars(query).all()
    return [build_status_out(db, pc) for pc in assignments]


# per-project analogue) are `_require_manage`-gated like `list_all_project_
# compliance` itself, not `_require_view` — §26 lists "View compliance
# across projects" specifically under Compliance Manager, not under any
# project role or general org membership, and §22's own looser-sounding
# "Compliance Managers and authorised users" text does not override §26's
# own dedicated Security and Permissions section, which is this module's
# authoritative RBAC source (confirmed by reading both sections; see
# docs/compliance-module-plan.md's Phase 14 notes for the full reasoning).
# Each iterates every project in the organisation (not only ones with an
# active assignment — the shared per-project service function already
# returns an empty list for a project with none) and calls the exact same
# per-project computation `project_router.py`'s own sibling endpoint uses,
# so none of this module's cross-assignment business logic is duplicated
# between scopes.


def _org_projects(db: Session, organization_id: UUID) -> list[Project]:
    """Every project in this organisation — the fixed iteration set every
    Phase 14 org-wide aggregation below loops over."""
    return list(db.scalars(select(Project).where(Project.organization_id == organization_id)).all())


@router.get("/non-compliant-requirements", response_model=list[OrgNonCompliantRequirementOut])
def list_org_non_compliant_requirements(
    organization_id: UUID, current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Every applicable, Non-Compliant requirement across every project in
    this organisation (§22's "identifying projects with Non-Compliant
    requirements" as its own drillable list, §23's related dashboard
    count)."""
    results: list[OrgNonCompliantRequirementOut] = []
    for project in _org_projects(db, organization_id):
        for row in list_non_compliant_requirements_for_project(db, project_id=project.id):
            results.append(OrgNonCompliantRequirementOut(**row.model_dump(), project_id=project.id, project_name=project.name))
    return results


@router.get("/pending-approvals", response_model=list[OrgPendingApprovalOut])
def list_org_pending_approvals(
    organization_id: UUID, current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Every requirement currently `PENDING_APPROVAL` across every project
    in this organisation (§22's "compliance assessments awaiting approval",
    §23's related dashboard count)."""
    results: list[OrgPendingApprovalOut] = []
    for project in _org_projects(db, organization_id):
        for row in list_pending_approvals_for_project(db, project_id=project.id):
            results.append(OrgPendingApprovalOut(**row.model_dump(), project_id=project.id, project_name=project.name))
    return results


@router.get("/outstanding-required-actions", response_model=list[OutstandingRequiredActionOut])
def list_org_outstanding_required_actions(
    organization_id: UUID, current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Every incomplete required-action assessment whose owning requirement
    is currently applicable, across every project in this organisation
    (§22's "identifying projects with outstanding Required Actions", §23's
    related dashboard count). `OutstandingRequiredActionOut` already
    carries `project_id`/`project_name` (see that schema's own docstring),
    so unlike the two endpoints above, no wrapping is needed here — this
    endpoint's response rows are identical in shape to `project_router.py::
    list_outstanding_required_actions`'s own, just gathered across every
    project rather than one."""
    results: list[OutstandingRequiredActionOut] = []
    for project in _org_projects(db, organization_id):
        results.extend(list_outstanding_required_actions_for_project(db, project_id=project.id))
    return results


@router.get("/expiring-evidence", response_model=list[OrgExpiringEvidenceOut])
def list_org_expiring_evidence(
    organization_id: UUID, current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Every non-archived piece of evidence approaching or past its expiry,
    across every project in this organisation (§22's "identifying projects
    with expired evidence", §23's "projects with expired evidence" and
    "projects with evidence approaching expiry" — the frontend splits this
    one list by `validity_state` for those two separate counts rather than
    this endpoint offering two, mirroring how `compute_evidence_validity_
    state` already treats `EXPIRED`/`EXPIRING_SOON` as two values of one
    computed field, not two independently-queried concepts)."""
    results: list[OrgExpiringEvidenceOut] = []
    for project in _org_projects(db, organization_id):
        for evidence in list_expiring_or_expired_evidence(db, project_id=project.id):
            evidence_out = build_evidence_out(db, evidence)
            results.append(OrgExpiringEvidenceOut(**evidence_out.model_dump(), project_name=project.name))
    return results


@router.get("/reviews-due", response_model=list[OrgReviewDueOut])
def list_org_reviews_due(
    organization_id: UUID, include_upcoming: bool = Query(False),
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Scheduled compliance reviews across every project in this
    organisation (§22's "identifying projects with overdue compliance
    reviews", `include_upcoming=False` — the default, and this endpoint's
    only mode until §23's dashboard needed more). §23's own "Upcoming
    compliance deadlines/reviews" widget passes `include_upcoming=true` to
    also get reviews not yet due, since a deadline that's merely upcoming
    (not yet due or overdue) is exactly what that widget needs to show and
    the plain `reviews-due` semantics deliberately exclude — see `service.
    py::list_reviews_due_for_project`'s own docstring for the full
    parameter rationale. Returns one `OrgReviewDueOut` per (project,
    review) pair — a single standard-level review due for three assigned
    projects appears three times, tagged with each project it's due for,
    since it is a materially different fact (an outstanding item on three
    separate projects' own compliance record) at this org-wide, per-project
    scope, in contrast to `recent-activity`'s below, which is deliberately
    per-audit-event rather than per-project."""
    results: list[OrgReviewDueOut] = []
    for project in _org_projects(db, organization_id):
        for review in list_reviews_due_for_project(db, project_id=project.id, include_upcoming=include_upcoming):
            results.append(OrgReviewDueOut(project_id=project.id, project_name=project.name, review=build_review_out(db, review)))
    return results


@router.get("/recent-activity", response_model=list[ComplianceRecentActivityOut])
def list_org_recent_activity(
    organization_id: UUID, limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """The most recent compliance-assessment audit events across every
    project in this organisation (§23's "Recently changed compliance
    assessments")."""
    return list_recent_compliance_activity(db, organization_id=organization_id, limit=limit)


@router.get("/reports")
def get_org_compliance_report(
    organization_id: UUID, format: Literal["pdf", "csv"] = Query(...), project_id: UUID | None = Query(None),
    standard_id: UUID | None = Query(None), standard_version_id: UUID | None = Query(None),
    requirement_id: UUID | None = Query(None),
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Generates the organisation-wide compliance roll-up (§29's
    "organisation-level reporting") in `format` — PDF or CSV — merged from
    two separate `/reports/pdf`/`/reports/csv` GETs on 2026-09-22 (see
    docs/decisions.md) since they only differed in output format, not the
    data collected. PDF: one row per project/assigned-standard-version
    pair, plus cross-project non-compliant/pending-approval/expiring-
    evidence appendices. CSV: the same rows as a flat export. Manage-gated
    like every other Phase 14 org-wide aggregation on this router (§26:
    "View compliance across projects" is a Compliance Manager capability,
    not general org membership) — see this router's own Phase 14 comment
    for the full reasoning, which applies identically to a report as to the
    live dashboard listings it's built from.

    `project_id`/`standard_id`/`standard_version_id`/`requirement_id`
    (Phase 43) are optional scoping filters — see `collect_org_compliance_
    report`'s own docstring — passed by `OrgComplianceStandardsPanel.tsx`'s
    and `OrgComplianceOutstandingPanel.tsx`'s own Export triggers to match
    whichever of their filters is currently applied."""
    org = db.get(Organization, organization_id)
    data = collect_org_compliance_report(
        db, organization_id, project_id=project_id, standard_id=standard_id,
        standard_version_id=standard_version_id, requirement_id=requirement_id,
    )
    if format == "csv":
        csv_bytes = generate_org_compliance_csv(data)
        return Response(
            content=csv_bytes, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_safe(org.name, fallback="organisation")}-compliance-report.csv"'},
        )
    pdf_bytes = generate_org_compliance_pdf(org.name, data)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename_safe(org.name, fallback="organisation")}-compliance-report.pdf"'},
    )


@router.post(
    "/projects/{project_id}/project-compliance/{project_compliance_id}/archive",
    response_model=ProjectComplianceOut,
)
def archive_project_compliance(
    organization_id: UUID, project_id: UUID, project_compliance_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Soft-archives a project's assignment to a standard — used when a
    project no longer needs to track compliance against it. Never a hard
    delete: the `ProjectComplianceRequirement` rows underneath carry real
    assessment/audit history (§16) that must survive this."""
    project_compliance = _get_project_compliance_or_404(db, organization_id, project_id, project_compliance_id)
    project_compliance.is_archived = True
    project_compliance.archived_at = datetime.now(UTC)
    project_compliance.archived_by = current_user.id
    log_event(db, entity_type="project_compliance", entity_id=project_compliance.id, action="archived",
              actor_id=current_user.id, organization_id=organization_id, project_id=project_id)
    db.commit()
    db.refresh(project_compliance)
    return project_compliance


@router.post(
    "/projects/{project_id}/project-compliance/{project_compliance_id}/unarchive",
    response_model=ProjectComplianceOut,
)
def unarchive_project_compliance(
    organization_id: UUID, project_id: UUID, project_compliance_id: UUID,
    current_user: User = Depends(_require_manage), db: Session = Depends(get_db),
):
    """Restores an archived project compliance assignment. Idempotent."""
    project_compliance = _get_project_compliance_or_404(db, organization_id, project_id, project_compliance_id)
    project_compliance.is_archived = False
    project_compliance.archived_at = None
    project_compliance.archived_by = None
    log_event(db, entity_type="project_compliance", entity_id=project_compliance.id, action="unarchived",
              actor_id=current_user.id, organization_id=organization_id, project_id=project_id)
    db.commit()
    db.refresh(project_compliance)
    return project_compliance
