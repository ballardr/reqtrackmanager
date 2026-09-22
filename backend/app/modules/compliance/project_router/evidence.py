"""
Module: modules.compliance.project_router.evidence

A project's own supporting evidence (Phase 8): CRUD, archive/
unarchive, revalidate (with the approvals-it-supported-invalidated
side effect, `_invalidate_approvals_supported_by_evidence`, local to
this file only), links to a requirement or a required-action
assessment, and file attachment (upload or link an existing org
resource).
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import FileAsset
from app.models.project import Project
from app.models.user import User
from app.modules.compliance.models import (
    ARTEFACT_TYPE_EVIDENCE,
    ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT,
    ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT,
    ComplianceEvidence,
    ComplianceEvidenceFile,
    ComplianceEvidenceRevalidation,
)
from app.modules.compliance.project_router._shared import (
    _get_assessment_for_project_or_404,
    _get_evidence_or_404,
    _get_pcr_for_project_or_404,
    _notify_approval_invalidated,
    _require_officer,
    _require_view,
)
from app.modules.compliance.schemas import (
    ComplianceEvidenceActionLinkCreate,
    ComplianceEvidenceCreate,
    ComplianceEvidenceOut,
    ComplianceEvidenceRequirementLinkCreate,
    ComplianceEvidenceRevalidateRequest,
    ComplianceEvidenceRevalidationOut,
    ComplianceEvidenceUpdate,
)
from app.modules.compliance.service import (
    build_evidence_out,
    find_pcrs_linked_to_evidence,
    invalidate_approval_if_in_flight,
    list_expiring_or_expired_evidence,
)
from app.schemas.file import FileAssetOut, LinkResourceRequest
from app.services import relationships
from app.services.audit import log_event
from app.services.files import delete_file, upload_file

router = APIRouter(tags=["compliance-project-evidence"])


def _invalidate_approvals_supported_by_evidence(
    db: Session, project_id: UUID, evidence: ComplianceEvidence, actor_id: UUID, *, reason: str
) -> None:
    """Applies §12/§16/§27's evidence-side auto-invalidation: for every
    `ProjectComplianceRequirement` this evidence supports (directly or via
    a required-action assessment — `service.py::find_pcrs_linked_to_evidence`),
    downgrades an in-flight or decided approval to `REQUIRES_REASSESSMENT`
    (`service.py::invalidate_approval_if_in_flight`) and logs the
    transition against that requirement's own history, exactly like every
    other approval-state change on this router. Called by `archive_evidence`
    (evidence marked no longer applicable) and `revalidate_evidence`
    (evidence's expiry information changed) — see each of those endpoints'
    own docstrings; a no-op for a piece of evidence that supports nothing,
    or whose linked rows aren't currently `PENDING_APPROVAL`/`APPROVED`.
    `actor_id` is the user who performed the evidence mutation that
    triggered this — a real human action, unlike a future Phase 10
    passive-expiry sweep, which would log with `actor_id=None` instead.

    Does not commit — callers commit as part of their own single
    transaction, same convention as every other mutation on this router.
    """
    for pcr in find_pcrs_linked_to_evidence(db, evidence_id=evidence.id):
        previous_approval_state = invalidate_approval_if_in_flight(pcr)
        if previous_approval_state is None:
            continue
        log_event(
            db, entity_type="project_compliance_requirement", entity_id=pcr.id, action="approval_invalidated",
            actor_id=actor_id, project_id=project_id,
            detail={
                "reason": reason, "evidence_id": str(evidence.id),
                "previous_approval_state": previous_approval_state.value,
                "new_approval_state": pcr.approval_state.value,
            },
        )
        _notify_approval_invalidated(db, project_id, pcr, actor_id=actor_id)


@router.post("/evidence", response_model=ComplianceEvidenceOut, status_code=status.HTTP_201_CREATED)
def create_evidence(
    project_id: UUID, payload: ComplianceEvidenceCreate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Creates a piece of supporting evidence for this project (§13),
    optionally linked to one or more requirement/required-action
    assessments at creation time — each id is verified to belong to this
    project before the row or any link is created (404 on a mismatch,
    mirroring this router's own established "wrong scope -> 404"
    convention for every other cross-reference check). `provided_by`/
    `provided_at` are never caller-supplied."""
    for pcr_id in payload.project_compliance_requirement_ids:
        _get_pcr_for_project_or_404(db, project_id, pcr_id)
    for assessment_id in payload.required_action_assessment_ids:
        _get_assessment_for_project_or_404(db, project_id, assessment_id)

    now = datetime.now(UTC)
    evidence = ComplianceEvidence(
        project_id=project_id, title=payload.title, description=payload.description,
        issuing_organisation=payload.issuing_organisation, issued_date=payload.issued_date,
        expiry_date=payload.expiry_date, provided_by=current_user.id, provided_at=now, notes=payload.notes,
    )
    db.add(evidence)
    db.flush()
    for pcr_id in payload.project_compliance_requirement_ids:
        relationships.create_link(
            db, source_type=ARTEFACT_TYPE_EVIDENCE, source_id=evidence.id,
            target_type=ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT, target_id=pcr_id,
            link_type_id=None, created_by=current_user.id,
        )
    for assessment_id in payload.required_action_assessment_ids:
        relationships.create_link(
            db, source_type=ARTEFACT_TYPE_EVIDENCE, source_id=evidence.id,
            target_type=ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT, target_id=assessment_id,
            link_type_id=None, created_by=current_user.id,
        )
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="created",
              actor_id=current_user.id, project_id=project_id, detail={"title": evidence.title})
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.get("/evidence", response_model=list[ComplianceEvidenceOut])
def list_evidence(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Lists every piece of evidence for this project, including archived
    rows — a caller wanting only active evidence filters client-side,
    mirroring `list_project_compliance`'s own identical judgment call."""
    evidence_rows = db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.project_id == project_id)).all()
    return [build_evidence_out(db, evidence) for evidence in evidence_rows]


@router.get("/expiring-evidence", response_model=list[ComplianceEvidenceOut])
def get_expiring_evidence(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Every non-archived piece of evidence approaching or past its
    expiry (§14) — the `compliance_list_expiring_evidence` MCP tool
    (`module.py`)."""
    return [build_evidence_out(db, evidence) for evidence in list_expiring_or_expired_evidence(db, project_id=project_id)]


@router.get("/evidence/{evidence_id}", response_model=ComplianceEvidenceOut)
def get_evidence(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Fetches a single piece of evidence."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    return build_evidence_out(db, evidence)


@router.patch("/evidence/{evidence_id}", response_model=ComplianceEvidenceOut)
def update_evidence(
    project_id: UUID, evidence_id: UUID, payload: ComplianceEvidenceUpdate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Updates evidence metadata — deliberately excludes `expiry_date`;
    see `ComplianceEvidenceUpdate`'s own docstring for §15's
    revalidation-only rule."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    evidence.title = payload.title
    evidence.description = payload.description
    evidence.issuing_organisation = payload.issuing_organisation
    evidence.issued_date = payload.issued_date
    evidence.notes = payload.notes
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="updated",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.post("/evidence/{evidence_id}/archive", response_model=ComplianceEvidenceOut)
def archive_evidence(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Marks evidence as no longer applicable (§13's "Whether it remains
    applicable"), retained (not deleted) since other assessments' own
    audit trail (§16) may still reference it via a link row."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    if evidence.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This evidence is already archived.")
    evidence.is_archived = True
    evidence.archived_at = datetime.now(UTC)
    evidence.archived_by = current_user.id
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="archived",
              actor_id=current_user.id, project_id=project_id)
    _invalidate_approvals_supported_by_evidence(db, project_id, evidence, current_user.id, reason="evidence_archived")
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.post("/evidence/{evidence_id}/unarchive", response_model=ComplianceEvidenceOut)
def unarchive_evidence(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Reverts `archive_evidence`, to correct a mistake."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    if not evidence.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "This evidence is not archived.")
    evidence.is_archived = False
    evidence.archived_at = None
    evidence.archived_by = None
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="unarchived",
              actor_id=current_user.id, project_id=project_id)
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.post("/evidence/{evidence_id}/revalidate", response_model=ComplianceEvidenceOut)
def revalidate_evidence(
    project_id: UUID, evidence_id: UUID, payload: ComplianceEvidenceRevalidateRequest,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Revalidates a piece of evidence (§15) — records the *previous*
    expiry in an append-only `ComplianceEvidenceRevalidation` row before
    updating `expiry_date` in place, so revalidating a second time never
    loses the first revalidation's own "previous" value (§15: "must not
    overwrite the historical record")."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    previous_expiry_date = evidence.expiry_date
    now = datetime.now(UTC)
    evidence.expiry_date = payload.new_expiry_date
    evidence.expiry_reminder_sent_at = None
    evidence.expiry_notified_at = None
    db.add(ComplianceEvidenceRevalidation(
        evidence_id=evidence.id, revalidated_by=current_user.id, revalidated_at=now,
        previous_expiry_date=previous_expiry_date, new_expiry_date=payload.new_expiry_date,
        justification=payload.justification, created_at=now,
    ))
    log_event(
        db, entity_type="compliance_evidence", entity_id=evidence.id, action="revalidated",
        actor_id=current_user.id, project_id=project_id,
        detail={
            "previous_expiry_date": previous_expiry_date.isoformat() if previous_expiry_date else None,
            "new_expiry_date": payload.new_expiry_date.isoformat() if payload.new_expiry_date else None,
            "justification": payload.justification,
        },
    )
    _invalidate_approvals_supported_by_evidence(db, project_id, evidence, current_user.id, reason="evidence_revalidated")
    db.commit()
    db.refresh(evidence)
    return build_evidence_out(db, evidence)


@router.get("/evidence/{evidence_id}/revalidations", response_model=list[ComplianceEvidenceRevalidationOut])
def list_evidence_revalidations(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """This evidence's full revalidation history (§15), oldest first —
    never overwritten, only ever appended to."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    return db.scalars(
        select(ComplianceEvidenceRevalidation)
        .where(ComplianceEvidenceRevalidation.evidence_id == evidence.id)
        .order_by(ComplianceEvidenceRevalidation.created_at)
    ).all()


@router.post(
    "/evidence/{evidence_id}/requirement-links", response_model=ComplianceEvidenceOut,
    status_code=status.HTTP_201_CREATED,
)
def link_evidence_to_requirement(
    project_id: UUID, evidence_id: UUID, payload: ComplianceEvidenceRequirementLinkCreate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Links existing evidence to an additional requirement's assessment
    (§13's "a single piece of evidence should be capable of supporting
    multiple compliance requirements") — idempotent (re-linking an
    already-linked pair is a no-op, not a 409/duplicate error)."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    pcr = _get_pcr_for_project_or_404(db, project_id, payload.project_compliance_requirement_id)
    existing = relationships.get_link_between(
        db, source_type=ARTEFACT_TYPE_EVIDENCE, source_id=evidence.id,
        target_type=ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT, target_id=pcr.id,
    )
    if existing is None:
        relationships.create_link(
            db, source_type=ARTEFACT_TYPE_EVIDENCE, source_id=evidence.id,
            target_type=ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT, target_id=pcr.id,
            link_type_id=None, created_by=current_user.id,
        )
        log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="requirement_linked",
                  actor_id=current_user.id, project_id=project_id,
                  detail={"project_compliance_requirement_id": str(pcr.id)})
        db.commit()
    return build_evidence_out(db, evidence)


@router.delete("/evidence/{evidence_id}/requirement-links/{pcr_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_evidence_from_requirement(
    project_id: UUID, evidence_id: UUID, pcr_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    link = relationships.get_link_between(
        db, source_type=ARTEFACT_TYPE_EVIDENCE, source_id=evidence.id,
        target_type=ARTEFACT_TYPE_PROJECT_COMPLIANCE_REQUIREMENT, target_id=pcr_id,
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This evidence is not linked to that requirement.")
    relationships.delete_link(db, link)
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="requirement_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"project_compliance_requirement_id": str(pcr_id)})
    db.commit()


@router.post(
    "/evidence/{evidence_id}/action-links", response_model=ComplianceEvidenceOut,
    status_code=status.HTTP_201_CREATED,
)
def link_evidence_to_action_assessment(
    project_id: UUID, evidence_id: UUID, payload: ComplianceEvidenceActionLinkCreate,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """The required-action equivalent of `link_evidence_to_requirement`."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    assessment = _get_assessment_for_project_or_404(db, project_id, payload.required_action_assessment_id)
    existing = relationships.get_link_between(
        db, source_type=ARTEFACT_TYPE_EVIDENCE, source_id=evidence.id,
        target_type=ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT, target_id=assessment.id,
    )
    if existing is None:
        relationships.create_link(
            db, source_type=ARTEFACT_TYPE_EVIDENCE, source_id=evidence.id,
            target_type=ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT, target_id=assessment.id,
            link_type_id=None, created_by=current_user.id,
        )
        log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="action_linked",
                  actor_id=current_user.id, project_id=project_id,
                  detail={"required_action_assessment_id": str(assessment.id)})
        db.commit()
    return build_evidence_out(db, evidence)


@router.delete("/evidence/{evidence_id}/action-links/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_evidence_from_action_assessment(
    project_id: UUID, evidence_id: UUID, assessment_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    link = relationships.get_link_between(
        db, source_type=ARTEFACT_TYPE_EVIDENCE, source_id=evidence.id,
        target_type=ARTEFACT_TYPE_REQUIRED_ACTION_ASSESSMENT, target_id=assessment_id,
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This evidence is not linked to that required action assessment.")
    relationships.delete_link(db, link)
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="action_unlinked",
              actor_id=current_user.id, project_id=project_id,
              detail={"required_action_assessment_id": str(assessment_id)})
    db.commit()


@router.post("/evidence/{evidence_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_evidence_attachment(
    project_id: UUID, evidence_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Uploads and attaches a new file to a piece of evidence — mirrors
    `routers.requirements.upload_requirement_attachment`'s shape exactly,
    reusing `services.files.upload_file` per §13's "reuse ReqTrackManager's
    existing attachment/file mechanisms where possible" rather than a
    second, independent file storage mechanism."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    project = db.get(Project, project_id)
    data = await file.read()
    asset = upload_file(
        db, organization_id=project.organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    db.add(ComplianceEvidenceFile(
        evidence_id=evidence.id, file_id=asset.id, linked_by=current_user.id, created_at=asset.created_at
    ))
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="file_attached",
              actor_id=current_user.id, project_id=project_id, detail={"filename": asset.filename})
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/evidence/{evidence_id}/files/link", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
def link_evidence_org_resource(
    project_id: UUID, evidence_id: UUID, payload: LinkResourceRequest,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Links an organisation shared resource file to a piece of evidence —
    mirrors `routers.requirements.link_org_resource`'s shape exactly."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    project = db.get(Project, project_id)
    asset = db.get(FileAsset, payload.file_id)
    if asset is None or not asset.is_org_resource or asset.organization_id != project.organization_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "file_id must be a shared resource in this project's organisation."
        )
    existing = db.scalar(
        select(ComplianceEvidenceFile).where(
            ComplianceEvidenceFile.evidence_id == evidence.id, ComplianceEvidenceFile.file_id == asset.id
        )
    )
    if existing is None:
        db.add(ComplianceEvidenceFile(
            evidence_id=evidence.id, file_id=asset.id, linked_by=current_user.id, created_at=datetime.now(UTC)
        ))
        log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="file_linked",
                  actor_id=current_user.id, project_id=project_id, detail={"file_id": str(asset.id)})
        db.commit()
    return asset


@router.get("/evidence/{evidence_id}/files", response_model=list[FileAssetOut])
def list_evidence_files(
    project_id: UUID, evidence_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    return db.scalars(
        select(FileAsset)
        .join(ComplianceEvidenceFile, ComplianceEvidenceFile.file_id == FileAsset.id)
        .where(ComplianceEvidenceFile.evidence_id == evidence.id)
    ).all()


@router.delete("/evidence/{evidence_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_evidence_file(
    project_id: UUID, evidence_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_officer), db: Session = Depends(get_db),
):
    """Removes a file from a piece of evidence. Direct (non-shared)
    uploads are deleted outright; shared org resources are only unlinked —
    mirrors `routers.requirements.unlink_requirement_file`'s shape."""
    evidence = _get_evidence_or_404(db, project_id, evidence_id)
    link = db.scalar(
        select(ComplianceEvidenceFile).where(
            ComplianceEvidenceFile.evidence_id == evidence.id, ComplianceEvidenceFile.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not attached to this evidence.")
    asset = db.get(FileAsset, file_id)
    db.delete(link)
    db.flush()
    if asset is not None and not asset.is_org_resource:
        delete_file(db, asset)
    log_event(db, entity_type="compliance_evidence", entity_id=evidence.id, action="file_unlinked",
              actor_id=current_user.id, project_id=project_id, detail={"file_id": str(file_id)})
    db.commit()
