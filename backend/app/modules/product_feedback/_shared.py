"""
Module: modules.product_feedback._shared

Helpers behind the two routers (`project_router.py`, `router.py`) and the record-table import: the
gates, the API shape (a request merged with its current version), the create / update / transition
bodies, and the comment and file wrappers over the shared `services.module_attachments` kit.

RBAC: viewing needs the sub-component enabled and membership. Submitting needs only that, unless a
project administrator restricted submission to triagers (`SubmissionPolicy.TRIAGERS`). Editing,
transitions, archiving and attachments need the triager role of the tier (`feedback_triager` in a
project, `org_feedback_triager` in the organisation) or a Fine-Grained Access Control
`(enhancement_request, manage)` grant.

Demand and merging: `request_extras` adds each request's place in a merge and its demand to the list and detail
shapes in a fixed number of statements; `merge_from_payload` / `unmerge_from_payload` are the gated, audited
bodies of the merge endpoints, and `demand_out` is the per-request demand breakdown with names the caller may
view.

Tenancy: every lookup is scoped to the project or organisation in the URL, so another tenant's ids
look absent (404), and an owner must belong to the organisation.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PermissionLevel
from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback.demand import EMPTY_DEMAND, Demand, compute_demand
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, SubmissionPolicy
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestComment,
    EnhancementRequestCommentFile,
    EnhancementRequestFile,
    EnhancementRequestMerge,
    EnhancementRequestVersion,
)
from app.modules.product_feedback.schemas import (
    DemandEngagementOut,
    DemandOut,
    RequestCommentOut,
    RequestCreate,
    RequesterOut,
    RequestMergeOut,
    RequestOut,
    RequestRefOut,
    RequestUpdate,
    RequestVersionOut,
)
from app.modules.product_feedback.service import (
    ALLOWED_TRANSITIONS,
    PRODUCT_FEEDBACK_MODULE_KEY,
    REQUEST_ARTEFACT_TYPE,
    REQUEST_SUBCOMPONENT_KEY,
    RecordOwner,
    apply_new_version,
    archive_request,
    create_request,
    get_current_version,
    get_submission_policy,
    transition_request,
    unarchive_request,
)
from app.schemas.principal import PrincipalOut
from app.services import module_attachments as att
from app.services.audit import log_event
from app.services.current_versions import current_versions
from app.services.link_graph import ArtefactResolver
from app.services.permissions import encode_permission
from app.services.principals import principal_columns, principal_labels, principal_ref, validate_principal
from app.services.rbac import (
    check_pat_project_scope,
    get_effective_permissions,
    get_effective_project_roles,
    lock_row_for_update,
    permission_satisfied,
    user_satisfies_module_role,
)

REQUEST_MANAGE_PERMISSION = encode_permission(REQUEST_ARTEFACT_TYPE, PermissionLevel.MANAGE.value)

#: The triager module role of each tier.
TRIAGER_ROLE_KEY: dict[EnhancementRequestScope, str] = {
    EnhancementRequestScope.PROJECT: "feedback_triager",
    EnhancementRequestScope.ORGANIZATION: "org_feedback_triager",
}

# Resolved display data for owners, keyed by `(owner_type, owner_id)` (`services.principals.principal_labels`).
OwnerLabels = dict[tuple[str, uuid.UUID], PrincipalOut]


def owner_labels(db: Session, versions: Sequence[EnhancementRequestVersion]) -> OwnerLabels:
    """Display data for the owner of every version in `versions`, in one batch."""
    return principal_labels(db, [principal_ref(v.owner_type, v.owner_id) for v in versions])


def _owner_of(labels: OwnerLabels, version: EnhancementRequestVersion) -> PrincipalOut | None:
    """The resolved owner of `version`, or None when it has none."""
    if version.owner_type is None or version.owner_id is None:
        return None
    return labels[(version.owner_type, version.owner_id)]


@dataclass
class RequestExtras:
    """What a list or detail shape adds to a request's own row: its merge status and its demand.

    Attributes:
        merged_into: `{duplicate id: the canonical request it is merged into}` (active merges only).
        merged_count: `{canonical id: how many duplicates are merged into it}`.
        demand: `{request id: Demand}`; absent for a request with no project (an inbox request).
    """

    merged_into: dict[uuid.UUID, RequestRefOut] = field(default_factory=dict)
    merged_count: dict[uuid.UUID, int] = field(default_factory=dict)
    demand: dict[uuid.UUID, Demand] = field(default_factory=dict)


def request_extras(db: Session, requests: Sequence[EnhancementRequest]) -> RequestExtras:
    """Merge status and demand for `requests` in a fixed number of statements however many there are (demand
    only for project-owned ones: an inbox request cannot hold requesters)."""
    extras = RequestExtras()
    ids = [r.id for r in requests]
    if not ids:
        return extras
    rows = db.execute(
        select(EnhancementRequestMerge.duplicate_id, EnhancementRequestMerge.canonical_id).where(
            (EnhancementRequestMerge.duplicate_id.in_(ids)) | (EnhancementRequestMerge.canonical_id.in_(ids)),
            EnhancementRequestMerge.unmerged_at.is_(None),
        )
    ).all()
    counts: dict[uuid.UUID, int] = defaultdict(int)
    canonical_of = {}
    for duplicate_id, canonical_id in rows:
        counts[canonical_id] += 1
        if duplicate_id in ids:
            canonical_of[duplicate_id] = canonical_id
    extras.merged_count = dict(counts)
    if canonical_of:
        canonicals = {c.id: c for c in db.scalars(select(EnhancementRequest).where(EnhancementRequest.id.in_(set(canonical_of.values()))))}
        titles = current_versions(db, EnhancementRequestVersion, "request_id", list(canonicals))
        extras.merged_into = {
            duplicate_id: RequestRefOut(
                id=canonical_id, unique_code=canonicals[canonical_id].unique_code, title=titles[canonical_id].title,
            )
            for duplicate_id, canonical_id in canonical_of.items()
        }
    by_project: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for request in requests:
        if request.project_id is not None:
            by_project[request.project_id].append(request.id)
    for project_id, project_request_ids in by_project.items():
        project = db.get(Project, project_id)
        if project is not None:
            extras.demand.update(compute_demand(db, project, project_request_ids))
    return extras


def request_to_out(
    db: Session, request: EnhancementRequest, version: EnhancementRequestVersion, labels: OwnerLabels | None = None,
    extras: RequestExtras | None = None,
) -> RequestOut:
    """Merges a request with its current version. `labels` (owner data) and `extras` (merge status and demand)
    are pre-resolved when building many, resolved here when omitted."""
    labels = labels if labels is not None else owner_labels(db, [version])
    extras = extras if extras is not None else request_extras(db, [request])
    demand = extras.demand.get(request.id, EMPTY_DEMAND)
    return RequestOut(
        id=request.id, scope=request.scope, organization_id=request.organization_id, project_id=request.project_id,
        unique_code=request.unique_code, creator_id=request.creator_id, is_archived=request.is_archived,
        archived_at=request.archived_at, archived_by=request.archived_by, title=version.title,
        description=version.description, status=version.status,
        allowed_next_statuses=sorted(
            ALLOWED_TRANSITIONS[version.status] - {EnhancementRequestStatus.DUPLICATE},
            key=list(EnhancementRequestStatus).index,
        ),
        owner=_owner_of(labels, version), external_ref_url=version.external_ref_url,
        external_ref_key=version.external_ref_key, decline_reason=version.decline_reason,
        version_number=version.version_number, created_at=request.created_at, updated_at=request.updated_at,
        merged_into=extras.merged_into.get(request.id), merged_count=extras.merged_count.get(request.id, 0),
        requester_count=demand.count, weighted_demand=demand.weighted,
    )


def requests_to_out(db: Session, requests: Sequence[EnhancementRequest]) -> list[RequestOut]:
    """The list response: each current version loaded, every owner resolved and the merge and demand data read in
    a fixed number of statements."""
    by_id = current_versions(db, EnhancementRequestVersion, "request_id", [r.id for r in requests])
    versions = [by_id[r.id] for r in requests]
    labels = owner_labels(db, versions)
    extras = request_extras(db, requests)
    return [request_to_out(db, r, v, labels, extras) for r, v in zip(requests, versions, strict=True)]


def current_request_out(db: Session, request: EnhancementRequest) -> RequestOut:
    """The API shape of one request, loading its current version."""
    return request_to_out(db, request, get_current_version(db, request.id))


def request_versions_out(db: Session, versions: Sequence[EnhancementRequestVersion]) -> list[RequestVersionOut]:
    """The API shape of a request's version history, resolving every owner in one batch."""
    labels = owner_labels(db, versions)
    return [
        RequestVersionOut(
            id=v.id, request_id=v.request_id, version_number=v.version_number, valid_from=v.valid_from,
            valid_to=v.valid_to, title=v.title, description=v.description, status=v.status, owner=_owner_of(labels, v),
            external_ref_url=v.external_ref_url, external_ref_key=v.external_ref_key,
            decline_reason=v.decline_reason, change_note=v.change_note, created_by=v.created_by,
            created_at=v.created_at,
        )
        for v in versions
    ]


def get_request_in_scope(db: Session, holder: RecordOwner, request_id: uuid.UUID) -> EnhancementRequest:
    """Loads a request, 404ing unless it belongs to the project (or organisation inbox) of `holder`, so another
    tenant's ids look absent."""
    request = db.get(EnhancementRequest, request_id)
    if request is None or request.scope != holder.scope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enhancement request not found.")
    if holder.is_project and request.project_id != holder.project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enhancement request not found.")
    if not holder.is_project and request.organization_id != holder.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enhancement request not found.")
    return request


def can_manage(db: Session, current_user: User, holder: RecordOwner) -> bool:
    """Whether `current_user` holds the tier's triager role (composing with server admin, org admin and project
    manager) or an FGAC `(enhancement_request, manage)` grant."""
    if user_satisfies_module_role(
        db, current_user, PRODUCT_FEEDBACK_MODULE_KEY, TRIAGER_ROLE_KEY[holder.scope],
        organization_id=holder.organization_id, project_id=holder.project_id,
    ):
        return True
    held = get_effective_permissions(
        db, current_user.id, organization_id=holder.organization_id, project_id=holder.project_id,
    )
    return permission_satisfied(held, REQUEST_MANAGE_PERMISSION)


def require_request_manage(db: Session, current_user: User, holder: RecordOwner) -> None:
    """Gate for edit, transition, archive and attachment actions.

    Raises:
        HTTPException: 403 unless `can_manage`.
    """
    if not can_manage(db, current_user, holder):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Feedback Triager (or admin/manager) may do this.")


def require_request_submit(db: Session, current_user: User, holder: RecordOwner) -> None:
    """Gate for creating a request: any member who can see the list, unless the project's administrator
    restricted submission to triagers (organisation requests are always open to members).

    Raises:
        HTTPException: 403 when the project's policy is `TRIAGERS` and the caller is not a triager.
    """
    project_id = holder.project_id
    if project_id is not None and get_submission_policy(db, project_id) == SubmissionPolicy.TRIAGERS:
        if not can_manage(db, current_user, holder):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Feedback Triager may submit requests in this project.")


def apply_value_error_as_conflict(fn, *args, **kwargs):
    """Calls `fn`, translating `ValueError` (an illegal move) into HTTP 409."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def audit_request(
    db: Session, holder: RecordOwner, request: EnhancementRequest, action: str, actor: User, detail: dict | None = None,
) -> None:
    """Records an audit event about `request`, placed under its project or (for an inbox request) its organisation."""
    log_event(
        db, entity_type=REQUEST_ARTEFACT_TYPE, entity_id=request.id, action=action, actor_id=actor.id, detail=detail,
        organization_id=holder.audit_organization_id, project_id=holder.project_id,
    )


def _owner_columns(db: Session, holder: RecordOwner, payload: RequestCreate | RequestUpdate) -> dict:
    """The `owner_type` / `owner_id` column values for the payload's owner, validated; empty when an update does
    not mention the owner (so it is carried forward).

    Raises:
        HTTPException: 400 when the owner is not a member of the organisation, or is a group of another
            organisation or project.
    """
    if "owner" not in payload.model_fields_set:
        return {}
    validate_principal(db, payload.owner, organization_id=holder.organization_id, project_id=holder.project_id, field="owner")
    return principal_columns("owner", payload.owner)


def stage_request(db: Session, holder: RecordOwner, payload: RequestCreate, creator: User) -> EnhancementRequest:
    """Validates a create payload, creates the request (`NEW`) and audit-logs it. Does not commit: the endpoint and
    the record-table import each own their transaction. The caller has checked `require_request_submit`.

    Raises:
        HTTPException: 400 for an unusable owner.
    """
    content = payload.model_dump(exclude={"owner"})
    content.update(_owner_columns(db, holder, payload))
    request = create_request(db, holder, creator, **content)
    audit_request(db, holder, request, "created", creator, {"title": payload.title, "unique_code": request.unique_code})
    return request


def create_from_payload(db: Session, holder: RecordOwner, payload: RequestCreate, creator: User) -> RequestOut:
    """`stage_request`, then commits and returns the API shape."""
    request = stage_request(db, holder, payload, creator)
    db.commit()
    db.refresh(request)
    return current_request_out(db, request)


def stage_request_update(
    db: Session, holder: RecordOwner, request: EnhancementRequest, payload: RequestUpdate, actor: User,
) -> None:
    """Applies a partial update as a new version (only fields present in the request body change) and audit-logs
    it. Does not commit. The caller has checked `require_request_manage`.

    Raises:
        HTTPException: 422 for a null title, 400 for an unusable owner.
    """
    sent = payload.model_dump(exclude_unset=True, exclude={"change_note", "owner"})
    if "title" in sent and sent["title"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An enhancement request title cannot be null.")
    if "description" in sent and sent["description"] is None:
        sent["description"] = ""
    sent.update(_owner_columns(db, holder, payload))
    lock_row_for_update(db, EnhancementRequest, request.id)
    current = get_current_version(db, request.id)
    apply_new_version(db, request, current, actor, changes=sent, change_note=payload.change_note)
    audit_request(db, holder, request, "updated", actor)


def update_from_payload(
    db: Session, holder: RecordOwner, request: EnhancementRequest, payload: RequestUpdate, actor: User,
) -> RequestOut:
    """`stage_request_update`, then commits and returns the API shape."""
    stage_request_update(db, holder, request, payload, actor)
    db.commit()
    return current_request_out(db, request)


def transition_from_payload(
    db: Session, holder: RecordOwner, request: EnhancementRequest, target: EnhancementRequestStatus, comment: str,
    actor: User,
) -> RequestOut:
    """Moves a request to `target` (the caller has checked the actor may), audit-logs, commits and returns the API
    shape. Locks the request row first so two concurrent moves cannot both pass the transition check.

    Raises:
        HTTPException: 409 for an illegal move, an archived request or a decline without a reason.
    """
    lock_row_for_update(db, EnhancementRequest, request.id)
    db.refresh(request)
    current = get_current_version(db, request.id)
    previous = current.status
    apply_value_error_as_conflict(transition_request, db, request, current, target, actor, comment=comment)
    detail: dict = {"from": previous.value, "to": target.value}
    if comment.strip():
        detail["comment"] = comment.strip()
    audit_request(db, holder, request, "status_changed", actor, detail)
    db.commit()
    return current_request_out(db, request)


def set_archived(
    db: Session, holder: RecordOwner, request: EnhancementRequest, actor: User, *, archived: bool,
) -> RequestOut:
    """Archives or unarchives a request (the caller has checked the actor may), audit-logs and commits."""
    if archived:
        archive_request(request, actor)
    else:
        unarchive_request(request)
    audit_request(db, holder, request, "archived" if archived else "unarchived", actor)
    db.commit()
    return current_request_out(db, request)


def move_to_project_from_payload(
    db: Session, http_request: Request, holder: RecordOwner, request: EnhancementRequest, project_id: uuid.UUID,
    actor: User,
) -> RequestOut:
    """Triages an inbox request into a project: the caller has checked the organisation triager gate.

    The target must be a project of the same organisation that the actor can open and that has the request list
    enabled, and the actor must be allowed to submit there (its submission policy applies, so a triager of the
    inbox cannot push requests into a project that restricted submission to its own triagers). Anything else about
    the project looks absent (404). Locks the request, re-owns it (`triage.move_to_project`), writes one audit event
    carrying the old code and commits.

    Raises:
        HTTPException: 404 for a project the actor cannot open, of another organisation or with the list disabled;
            403 when the project's submission policy excludes the actor; 409 for a request that is not an inbox
            request any more or has links.
    """
    from app.modules.product_feedback.triage import move_to_project
    from app.modules.registry import is_module_subcomponent_enabled

    project = db.get(Project, project_id)
    if project is None or project.organization_id != holder.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    check_pat_project_scope(http_request, project.id)
    if not get_effective_project_roles(db, actor.id, project.id) or not is_module_subcomponent_enabled(
        db, project.id, PRODUCT_FEEDBACK_MODULE_KEY, REQUEST_SUBCOMPONENT_KEY,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    require_request_submit(db, actor, RecordOwner.of_project(project))

    lock_row_for_update(db, EnhancementRequest, request.id)
    db.refresh(request)
    result = apply_value_error_as_conflict(move_to_project, db, request, project, actor)
    log_event(
        db, entity_type=REQUEST_ARTEFACT_TYPE, entity_id=request.id, action="moved_to_project", actor_id=actor.id,
        organization_id=holder.organization_id, project_id=project.id,
        detail={
            "from_code": result.previous_code, "to_code": result.new_code, "tags": result.tags, "files": result.files,
        },
    )
    db.commit()
    return current_request_out(db, request)


# --- Merging and demand --------------------------------------------------------


def _lock_both(db: Session, first: EnhancementRequest, second: EnhancementRequest) -> None:
    """Locks two request rows in id order (so two opposite merges cannot deadlock) and refreshes them."""
    for row in sorted((first, second), key=lambda r: str(r.id)):
        lock_row_for_update(db, EnhancementRequest, row.id)
    db.refresh(first)
    db.refresh(second)


def merge_from_payload(
    db: Session, holder: RecordOwner, duplicate: EnhancementRequest, canonical_id: uuid.UUID, note: str, actor: User,
) -> RequestOut:
    """Merges `duplicate` into the request `canonical_id` of the same project (or inbox); the caller has checked
    the triager gate. Locks both rows, writes one audit event (codes only, never text) and commits.

    Raises:
        HTTPException: 404 when the canonical request is not in this project or inbox; 409 for an illegal merge
            (see `merge.merge_requests`).
    """
    from app.modules.product_feedback.merge import merge_requests

    canonical = get_request_in_scope(db, holder, canonical_id)
    _lock_both(db, duplicate, canonical)
    merge = apply_value_error_as_conflict(merge_requests, db, canonical, duplicate, actor)
    detail: dict = {"canonical": canonical.unique_code, "duplicate": duplicate.unique_code, "prior_status": merge.prior_status.value}
    if note.strip():
        detail["note"] = note.strip()
    audit_request(db, holder, duplicate, "merged", actor, detail)
    audit_request(db, holder, canonical, "duplicate_merged_in", actor, detail)
    db.commit()
    return current_request_out(db, duplicate)


def unmerge_from_payload(db: Session, holder: RecordOwner, duplicate: EnhancementRequest, actor: User) -> RequestOut:
    """Reverses the merge of `duplicate`; the caller has checked the triager gate. Locks the rows, audits and commits.

    Raises:
        HTTPException: 409 when the request is not merged into another.
    """
    from app.modules.product_feedback.merge import active_merge_of, unmerge_request

    current = active_merge_of(db, duplicate.id)
    canonical = db.get(EnhancementRequest, current.canonical_id) if current is not None else None
    if canonical is None:
        _lock_both(db, duplicate, duplicate)
    else:
        _lock_both(db, duplicate, canonical)
    merge = apply_value_error_as_conflict(unmerge_request, db, duplicate, actor)
    detail = {
        "canonical": canonical.unique_code if canonical else None, "duplicate": duplicate.unique_code,
        "restored_status": merge.prior_status.value,
    }
    audit_request(db, holder, duplicate, "unmerged", actor, detail)
    if canonical is not None:
        audit_request(db, holder, canonical, "duplicate_unmerged", actor, detail)
    db.commit()
    return current_request_out(db, duplicate)


def merges_out(db: Session, request: EnhancementRequest) -> list[RequestMergeOut]:
    """Every merge the request took part in (as canonical or duplicate), newest first, active and ended."""
    rows = list(db.scalars(
        select(EnhancementRequestMerge).where(
            (EnhancementRequestMerge.canonical_id == request.id) | (EnhancementRequestMerge.duplicate_id == request.id)
        ).order_by(EnhancementRequestMerge.merged_at.desc())
    ))
    ids = {r for m in rows for r in (m.canonical_id, m.duplicate_id)}
    requests = {r.id: r for r in db.scalars(select(EnhancementRequest).where(EnhancementRequest.id.in_(ids)))} if ids else {}
    titles = current_versions(db, EnhancementRequestVersion, "request_id", list(requests))

    def ref(request_id: uuid.UUID) -> RequestRefOut:
        return RequestRefOut(id=request_id, unique_code=requests[request_id].unique_code, title=titles[request_id].title)

    return [
        RequestMergeOut(
            id=m.id, canonical=ref(m.canonical_id), duplicate=ref(m.duplicate_id), prior_status=m.prior_status,
            merged_by=m.merged_by, merged_at=m.merged_at, unmerged_by=m.unmerged_by, unmerged_at=m.unmerged_at,
            active=m.unmerged_at is None,
        )
        for m in rows
    ]


def _merged_duplicate_refs(db: Session, canonical_id: uuid.UUID) -> list[RequestRefOut]:
    """The requests actively merged into `canonical_id`, oldest merge first."""
    from app.modules.product_feedback.demand import active_merged_duplicates

    ids = active_merged_duplicates(db, [canonical_id]).get(canonical_id, [])
    if not ids:
        return []
    codes = {r.id: r.unique_code for r in db.scalars(select(EnhancementRequest).where(EnhancementRequest.id.in_(ids)))}
    titles = current_versions(db, EnhancementRequestVersion, "request_id", ids)
    return [RequestRefOut(id=i, unique_code=codes[i], title=titles[i].title) for i in ids]


def demand_out(db: Session, project: Project, request: EnhancementRequest, viewer: User) -> DemandOut:
    """The request's demand broken down for `viewer`.

    The totals count every party the project can see. A party's name and weight are given only when `viewer`
    holds `view` on its type (the same rule the link finder applies), and are null otherwise, so a count never
    reveals who a hidden party is.
    """
    demand = compute_demand(db, project, [request.id])[request.id]
    resolver = ArtefactResolver(db, project, viewer.id)
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for requester in demand.requesters:
        wanted[requester.artefact_type].add(requester.id)
    wanted["engagement"].update(demand.engagement_ids)
    resolver.resolve(dict(wanted))

    def can_see(artefact_type: str, record_id: uuid.UUID) -> bool:
        return resolver.visible((artefact_type, record_id)) is not None

    engagement_labels = {e: resolver.visible(("engagement", e)) for e in demand.engagement_ids}
    return DemandOut(
        request_id=request.id, requester_count=demand.count, weighted_demand=demand.weighted,
        requesters=[
            RequesterOut(
                artefact_type=r.artefact_type, id=r.id, label=r.label if can_see(r.artefact_type, r.id) else None,
                weight=r.weight if can_see(r.artefact_type, r.id) else None, effective_weight=r.effective_weight,
                from_merge=r.from_merge, via_engagement=r.via_engagement, hidden=not can_see(r.artefact_type, r.id),
            )
            for r in demand.requesters
        ],
        engagements=[
            DemandEngagementOut(id=e, label=s.label if s else None, hidden=s is None) for e, s in engagement_labels.items()
        ],
        merged_duplicates=_merged_duplicate_refs(db, request.id),
    )


# --- Comments and files (shared kit, see `services.module_attachments`) ------

REQUEST_ATTACHMENTS = att.AttachmentKit(
    artefact_type=REQUEST_ARTEFACT_TYPE, label="Enhancement request", comment_model=EnhancementRequestComment,
    comment_file_model=EnhancementRequestCommentFile, file_model=EnhancementRequestFile, fk="request_id",
    comment_out=RequestCommentOut,
)
