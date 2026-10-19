"""
Module: modules.risk_management.project_router

Project-scoped Risk API, mounted at
`/api/v1/projects/{project_id}/modules/risk_management`: Risk
CRUD/archive/versions/comments/files and the project's Risk type vocabulary
(effective list plus rename/reorder/disable/add).

RBAC: sub-component enablement and project membership to view; any project member
may propose (create) a risk; `_shared.require_risk_manage` (project Risk Manager
role or FGAC grant) to edit, archive, attach evidence or change the project's
types. The lifecycle `transition` endpoint needs the Risk Manager role, except a
move to `ACCEPTED`, which needs the Risk Acceptor role and (via MCP) the
org+project AI-approval gate. Relationships are made through the generic artefact
link endpoints; this router lists a risk's treatment links and records the verdict
on each (`treatment.py`): the risk's owner (a user, or a member of its owner group) or a Risk Manager
may assess, and likewise record a periodic review (`reviews.py`). A risk's files resolve through `service.resolve_risk_file_project_id`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_request_channel
from app.models.project import Project
from app.models.user import User
from app.modules.risk_management import _shared as sh
from app.modules.risk_management.enums import RiskStatus
from app.modules.risk_management.models import Risk, RiskReview
from app.modules.risk_management.ratings import load_rating_context
from app.modules.risk_management.reports import REPORT_ROUTERS
from app.modules.risk_management.reviews import count_stale_treatments, list_reviews, record_review
from app.modules.risk_management.schemas import (
    RiskCommentCreate,
    RiskCommentOut,
    RiskCommentUpdate,
    RiskCreate,
    RiskOut,
    RiskReviewCreate,
    RiskReviewOut,
    RiskTransitionRequest,
    RiskUpdate,
    RiskVersionOut,
    TreatmentAssessmentRequest,
    TreatmentListOut,
    TreatmentOut,
)
from app.modules.risk_management.scoring import RISK_SCORING_SCHEME_KEY
from app.modules.risk_management.service import (
    RISK_ARTEFACT_TYPE,
    RISK_MODULE_KEY,
    RISK_SUBCOMPONENT_KEY,
    RISK_TYPES,
    archive_risk,
    get_current_risk_version,
    list_project_risks,
    unarchive_risk,
)
from app.modules.risk_management.treatment import (
    TreatmentLink,
    assess_treatment,
    effective_treatment_counts,
    far_type_label,
    list_treatment_links,
)
from app.schemas.file import FileAssetOut
from app.schemas.scoring import ScoringSchemeOut
from app.schemas.type_vocabulary import (
    EffectiveTypeOut,
    HiddenTypeOut,
    ProjectTypeCreate,
    ProjectTypeOut,
    ProjectTypeOverrideUpdate,
    RestoreTypesOut,
    RestoreTypesRequest,
)
from app.services import scoring
from app.services.audit import log_event
from app.services.rbac import lock_row_for_update, require_ai_approvals_enabled, require_project_subcomponent_enabled
from app.services.type_vocabulary_routes import list_hidden_types, remove_project_type, restore_hidden_types

router = APIRouter(prefix=f"/api/v1/projects/{{project_id}}/modules/{RISK_MODULE_KEY}", tags=["risk-management-project"])

_require_view = require_project_subcomponent_enabled(RISK_MODULE_KEY, RISK_SUBCOMPONENT_KEY)

# The module's reports (`reports.py`): generated routes at `/reports/<slug>`, under this router's prefix.
router.include_router(REPORT_ROUTERS.project)


def _project(db: Session, project_id: UUID) -> Project:
    """Loads the project in the URL, 404ing if it does not exist."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _get(db: Session, project_id: UUID, risk_id: UUID) -> Risk:
    """A risk of this project (404 for anything else)."""
    return sh.get_risk_in_project(db, project_id, risk_id)


# --- Risk type vocabulary (project half) -------------------------------------


@router.get("/risk-types", response_model=list[EffectiveTypeOut])
def list_project_risk_types(project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The project's effective Risk type list (org types with overrides applied,
    plus project-local ones). Open to any project member so a type picker can be
    populated."""
    project = _project(db, project_id)
    return RISK_TYPES.resolve_effective(db, project_id, project.organization_id)


@router.post("/risk-types", response_model=ProjectTypeOut, status_code=status.HTTP_201_CREATED)
def create_project_local_risk_type(
    project_id: UUID, payload: ProjectTypeCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Creates a project-local Risk type. Needs the Risk Manager role; 400 on a duplicate name."""
    project = _project(db, project_id)
    sh.require_risk_manage(db, current_user, project)
    try:
        row = RISK_TYPES.create_project_local(db, project_id, payload.name, display_order=payload.display_order)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    log_event(db, entity_type="project_risk_type", entity_id=row.id, action="created", actor_id=current_user.id,
              project_id=project_id, detail={"name": payload.name})
    db.commit()
    db.refresh(row)
    return row


@router.put("/risk-types/{type_ref_id}", response_model=ProjectTypeOut)
def override_project_risk_type(
    project_id: UUID, type_ref_id: UUID, payload: ProjectTypeOverrideUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Partial override of a type here. `type_ref_id` is an `EffectiveTypeOut.id`:
    an org type gets its override row on first use."""
    project = _project(db, project_id)
    sh.require_risk_manage(db, current_user, project)
    try:
        row = RISK_TYPES.get_or_create_project_type(db, project_id, project.organization_id, type_ref_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    RISK_TYPES.set_override(db, row, name=payload.name, display_order=payload.display_order, is_enabled=payload.is_enabled)
    log_event(db, entity_type="project_risk_type", entity_id=row.id, action="updated", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/risk-types/{type_ref_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_risk_type(
    project_id: UUID, type_ref_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Deletes a project-local type, or hides an organisation default in this
    project (restore it with `POST /risk-types/restore`); `type_ref_id` is an
    `EffectiveTypeOut.id`. Hiding keeps the project's row, so existing records
    are unaffected. 409 while a project-local type is still in use."""
    project = _project(db, project_id)
    sh.require_risk_manage(db, current_user, project)
    remove_project_type(db, RISK_TYPES, project, type_ref_id, current_user, "project_risk_type")


@router.get("/risk-types/hidden", response_model=list[HiddenTypeOut])
def list_hidden_project_risk_types(
    project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The organisation defaults this project has hidden. Needs the manage role."""
    project = _project(db, project_id)
    sh.require_risk_manage(db, current_user, project)
    return list_hidden_types(db, RISK_TYPES, project)


@router.post("/risk-types/restore", response_model=RestoreTypesOut)
def restore_hidden_project_risk_types(
    project_id: UUID, payload: RestoreTypesRequest, current_user: User = Depends(_require_view),
    db: Session = Depends(get_db),
):
    """Shows hidden organisation defaults in this project again: every one, or
    only `org_type_ids`. Needs the manage role."""
    project = _project(db, project_id)
    sh.require_risk_manage(db, current_user, project)
    return restore_hidden_types(db, RISK_TYPES, project, payload, current_user, "project_risk_type")


@router.get("/scoring-scheme", response_model=ScoringSchemeOut)
def get_risk_scoring_scheme(project_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """The `risk` scoring scheme as it applies to this project: each axis's level
    ids and weights (what a risk's `*_level_id` fields take), the default model,
    its rating bands and per-cell ratings. A read-only mirror of the core scoring
    endpoint under this module's prefix, so a client confined to the module (the
    MCP server) can discover the level ids."""
    project = _project(db, project_id)
    return scoring.build_scheme_config(
        db, project.organization_id, scoring.get_registered_scheme(RISK_SCORING_SCHEME_KEY), project
    )


# --- Risk CRUD ---------------------------------------------------------------


@router.post("/risks", response_model=RiskOut, status_code=status.HTTP_201_CREATED)
def create_risk(
    project_id: UUID, payload: RiskCreate, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Proposes a risk in `IDENTIFIED`. Any project member may do so (overview
    §11.7); assessing and managing it afterwards needs the Risk Manager role."""
    project = _project(db, project_id)
    return sh.create_risk_from_payload(db, payload, current_user, project)


@router.get("/risks", response_model=list[RiskOut])
def list_risks(
    project_id: UUID, include_archived: bool = False, effectively_treated: bool | None = None,
    review_overdue: bool | None = None, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The project's risks with derived ratings; archived ones only with
    `include_archived`. `effectively_treated=false` answers "which risks have no
    effective treatment yet", `true` the opposite. `review_overdue=true` lists the
    risks whose scheduled review date has passed."""
    project = _project(db, project_id)
    ctx = load_rating_context(db, project)
    risks = list_project_risks(db, project_id, include_archived=include_archived)
    counts = effective_treatment_counts(db, [r.id for r in risks])
    if effectively_treated is not None:
        risks = [r for r in risks if (counts.get(r.id, 0) > 0) == effectively_treated]
    versions = {r.id: get_current_risk_version(db, r.id) for r in risks}
    labels = sh.owner_labels(db, list(versions.values()))
    out = [
        sh.risk_to_out(db, r, versions[r.id], ctx, effective_treatments=counts.get(r.id, 0), labels=labels)
        for r in risks
    ]
    if review_overdue is not None:
        out = [r for r in out if r.is_review_overdue == review_overdue]
    return out


@router.get("/risks/{risk_id}", response_model=RiskOut)
def get_risk(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """One risk with its current version and derived ratings."""
    project = _project(db, project_id)
    return sh.current_risk_out(db, _get(db, project_id, risk_id), project)


@router.put("/risks/{risk_id}", response_model=RiskOut)
def update_risk(
    project_id: UUID, risk_id: UUID, payload: RiskUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Applies a partial update as a new version (fields absent from the body are
    kept). Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    return sh.update_risk_from_payload(db, risk, payload, current_user, project)


@router.get("/risks/{risk_id}/versions", response_model=list[RiskVersionOut])
def list_risk_versions(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """A risk's full version history, oldest first."""
    _project(db, project_id)
    return sh.risk_versions_out(db, _get(db, project_id, risk_id).versions)


@router.post("/risks/{risk_id}/transition", response_model=RiskOut)
def transition(
    project_id: UUID, risk_id: UUID, payload: RiskTransitionRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
    channel: str = Depends(get_request_channel),
):
    """Moves a risk along its lifecycle (`RiskOut.allowed_next_statuses` lists the
    legal targets). Needs the Risk Manager role; moving to `ACCEPTED` needs the
    Risk Acceptor role instead, and reached through the MCP server additionally
    needs this project and its organisation to have enabled AI approval (a plain
    UI/API call is unaffected by that flag). 409 for an illegal move or an unmet
    precondition (e.g. no residual rating)."""
    project = _project(db, project_id)
    if payload.status == RiskStatus.ACCEPTED:
        if channel == "mcp":
            require_ai_approvals_enabled(db, project)
        sh.require_risk_accept(db, current_user, project)
    else:
        sh.require_risk_manage(db, current_user, project)
    return sh.transition_risk_from_payload(
        db, _get(db, project_id, risk_id), payload.status, payload.comment, current_user, project,
        via_mcp=channel == "mcp" and payload.status == RiskStatus.ACCEPTED,
    )


@router.post("/risks/{risk_id}/archive", response_model=RiskOut)
def archive(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Soft-archives a risk. Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    archive_risk(risk, current_user)
    log_event(db, entity_type=RISK_ARTEFACT_TYPE, entity_id=risk.id, action="archived", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    return sh.current_risk_out(db, risk, project)


@router.post("/risks/{risk_id}/unarchive", response_model=RiskOut)
def unarchive(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Restores an archived risk. Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    unarchive_risk(risk)
    log_event(db, entity_type=RISK_ARTEFACT_TYPE, entity_id=risk.id, action="unarchived", actor_id=current_user.id,
              project_id=project_id)
    db.commit()
    return sh.current_risk_out(db, risk, project)


# --- Treatment links and their assessment ------------------------------------


def _treatment_out(treatment: TreatmentLink) -> TreatmentOut:
    """The API shape of one treatment link."""
    verdict = treatment.assessment
    return TreatmentOut(
        link_id=treatment.link.id, relationship=treatment.phrase, other_type=treatment.other_type,
        other_type_label=far_type_label(treatment), other_id=treatment.other.id,
        other_project_id=treatment.other.project_id, label=treatment.other.label,
        other_status=treatment.other.status, other_is_archived=treatment.other.is_archived,
        status=treatment.status, rationale=verdict.rationale if verdict else "",
        reassessment_reason=verdict.reassessment_reason if verdict else "",
        assessed_by=verdict.assessed_by if verdict else None, assessed_at=verdict.assessed_at if verdict else None,
    )


@router.get("/risks/{risk_id}/treatments", response_model=TreatmentListOut)
def list_risk_treatments(
    project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """The risk's treatment links (requirements, designs and actions that mitigate
    or treat it), each with its verdict; `proposed` until someone assesses it. Far
    ends the caller cannot view are counted in `hidden_count`, not described."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    items, hidden = list_treatment_links(db, project, risk.id, current_user.id)
    return TreatmentListOut(
        items=[_treatment_out(t) for t in items], hidden_count=hidden,
        effective_count=effective_treatment_counts(db, [risk.id]).get(risk.id, 0),
        needs_reassessment_count=count_stale_treatments(db, risk.id),
    )


@router.put("/risks/{risk_id}/treatments/{link_id}", response_model=TreatmentOut)
def assess_risk_treatment(
    project_id: UUID, risk_id: UUID, link_id: UUID, payload: TreatmentAssessmentRequest,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Records whether one treatment link effectively reduces the risk. The risk's
    owner (or a member of its owner group) or a Risk Manager may assess. `effective` and `ineffective` need a
    rationale (409 otherwise); 404 for a link that is not a visible treatment link
    of this risk; 409 on an archived risk."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    if not sh.is_risk_owner(db, get_current_risk_version(db, risk.id), current_user.id):
        sh.require_risk_manage(db, current_user, project)
    lock_row_for_update(db, Risk, risk.id)
    db.refresh(risk)
    if risk.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "An archived risk's treatments cannot be assessed; unarchive it first.")
    items, _hidden = list_treatment_links(db, project, risk.id, current_user.id)
    target = next((t for t in items if t.link.id == link_id), None)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Treatment link not found.")
    previous = target.status
    sh.apply_value_error_as_conflict(
        assess_treatment, db, risk_id=risk.id, link_id=link_id, status=payload.status, rationale=payload.rationale,
        actor_id=current_user.id,
    )
    log_event(
        db, entity_type=RISK_ARTEFACT_TYPE, entity_id=risk.id, action="treatment_assessed", actor_id=current_user.id,
        project_id=project_id,
        detail={
            "link_id": str(link_id), "other_type": target.other_type, "other_id": str(target.other.id),
            "from": previous.value, "to": payload.status.value,
        },
    )
    db.commit()
    refreshed, _ = list_treatment_links(db, project, risk.id, current_user.id)
    return _treatment_out(next(t for t in refreshed if t.link.id == link_id))


# --- Reviews -----------------------------------------------------------------


@router.post("/risks/{risk_id}/reviews", response_model=RiskReviewOut, status_code=status.HTTP_201_CREATED)
def create_risk_review(
    project_id: UUID, risk_id: UUID, payload: RiskReviewCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Records a periodic review and sets the date of the next one. The risk's
    owner (or a member of its owner group) or a Risk Manager may review. A review is immutable;
    correct a mistake with a newer one. 409 for an archived or closed risk, blank notes, a
    non-future `next_review_date`, or `confirmed` while a treatment still needs
    reassessment."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    if not sh.is_risk_owner(db, get_current_risk_version(db, risk.id), current_user.id):
        sh.require_risk_manage(db, current_user, project)
    lock_row_for_update(db, Risk, risk.id)
    db.refresh(risk)
    current = get_current_risk_version(db, risk.id)
    review = sh.apply_value_error_as_conflict(
        record_review, db, risk, current, current_user, load_rating_context(db, project),
        outcome=payload.outcome, notes=payload.notes, next_review_date=payload.next_review_date,
    )
    log_event(
        db, entity_type=RISK_ARTEFACT_TYPE, entity_id=risk.id, action="reviewed", actor_id=current_user.id,
        project_id=project_id,
        detail={
            "review_id": str(review.id), "outcome": payload.outcome.value,
            "next_review_date": payload.next_review_date.isoformat() if payload.next_review_date else None,
        },
    )
    db.commit()
    db.refresh(review)
    return review


@router.get("/risks/{risk_id}/reviews", response_model=list[RiskReviewOut])
def list_risk_reviews(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """A risk's review history, newest first."""
    _project(db, project_id)
    return list_reviews(db, _get(db, project_id, risk_id).id)


@router.get("/risks/{risk_id}/reviews/{review_id}", response_model=RiskReviewOut)
def get_risk_review(
    project_id: UUID, risk_id: UUID, review_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """One review of the risk (404 for another risk's review)."""
    _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    review = db.get(RiskReview, review_id)
    if review is None or review.risk_id != risk.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    return review


# --- Comments ----------------------------------------------------------------


@router.post("/risks/{risk_id}/comments", response_model=RiskCommentOut, status_code=status.HTTP_201_CREATED)
def add_risk_comment(
    project_id: UUID, risk_id: UUID, payload: RiskCommentCreate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Adds a discussion comment. Any project member may comment."""
    _project(db, project_id)
    return sh.add_comment(db, _get(db, project_id, risk_id), current_user, payload.body, project_id=project_id)


@router.get("/risks/{risk_id}/comments", response_model=list[RiskCommentOut])
def list_risk_comments(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """A risk's comments, oldest first, with attachments."""
    _project(db, project_id)
    return sh.list_comments(db, _get(db, project_id, risk_id))


@router.patch("/risks/{risk_id}/comments/{comment_id}", response_model=RiskCommentOut)
def edit_risk_comment(
    project_id: UUID, risk_id: UUID, comment_id: UUID, payload: RiskCommentUpdate,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Edits a comment. Author only."""
    _project(db, project_id)
    return sh.edit_comment(db, _get(db, project_id, risk_id), comment_id, current_user, payload.body, project_id=project_id)


@router.post("/risks/{risk_id}/comments/{comment_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_risk_comment_attachment(
    project_id: UUID, risk_id: UUID, comment_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Attaches a file to a comment. Comment author only."""
    project = _project(db, project_id)
    return await sh.attach_to_comment(
        db, _get(db, project_id, risk_id), comment_id, current_user, file,
        organization_id=project.organization_id, project_id=project_id,
    )


@router.delete("/risks/{risk_id}/comments/{comment_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_risk_comment_attachment(
    project_id: UUID, risk_id: UUID, comment_id: UUID, file_id: UUID,
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes (and deletes) a comment's attachment. Comment author only."""
    _project(db, project_id)
    sh.remove_comment_attachment(db, _get(db, project_id, risk_id), comment_id, file_id, current_user, project_id=project_id)


# --- Direct files (evidence) -------------------------------------------------


@router.post("/risks/{risk_id}/files", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_risk_file(
    project_id: UUID, risk_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Uploads evidence directly to a risk. Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    return await sh.attach_file(db, risk, current_user, file, organization_id=project.organization_id, project_id=project_id)


@router.get("/risks/{risk_id}/files", response_model=list[FileAssetOut])
def list_risk_files(project_id: UUID, risk_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db)):
    """Files attached directly to a risk."""
    _project(db, project_id)
    return sh.list_files(db, _get(db, project_id, risk_id))


@router.delete("/risks/{risk_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_risk_file(
    project_id: UUID, risk_id: UUID, file_id: UUID, current_user: User = Depends(_require_view), db: Session = Depends(get_db),
):
    """Removes (and deletes) a directly attached file. Needs the Risk Manager role."""
    project = _project(db, project_id)
    risk = _get(db, project_id, risk_id)
    sh.require_risk_manage(db, current_user, project)
    sh.unlink_file(db, risk, file_id, current_user, project_id=project_id)
