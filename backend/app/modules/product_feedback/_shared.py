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

Closing the loop: `close_the_loop_out` reads what became of a request (who was told, the problems and work it is
linked to, the cue to mark it delivered), `inform_from_payload` is the gated, audited body of the "told" endpoint and
`open_loops_out` is the project's list of delivered or declined requests with requesters still to be told.

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
from app.modules.product_feedback import references as refs
from app.modules.product_feedback.channels import ChannelChoice, channels_by_request, set_channels
from app.modules.product_feedback.demand import EMPTY_DEMAND, Demand, Requester, compute_demand
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus, SubmissionPolicy
from app.modules.product_feedback.loop import (
    CLOSED_STATUSES,
    PartyKey,
    delivery_state,
    informed_by_request,
    open_count,
    open_loop_requests,
    requirements_complete,
    set_informed,
)
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestComment,
    EnhancementRequestCommentFile,
    EnhancementRequestFile,
    EnhancementRequestMerge,
    EnhancementRequestVersion,
)
from app.modules.product_feedback.ratings import (
    RatingContext,
    RequestScore,
    derived_levels,
    load_rating_context,
    parse_model_keys,
    score_levels,
)
from app.modules.product_feedback.relationships import NO_LINKS, RequestLinks, compute_links
from app.modules.product_feedback.schemas import (
    ChannelOut,
    ChannelUpdate,
    CloseTheLoopOut,
    DemandEngagementOut,
    DemandOut,
    ExternalRefIn,
    ExternalRefOut,
    ExternalRefUpdate,
    FeedbackAccessOut,
    InformedUpdate,
    LinkedRecordOut,
    LoopRequesterOut,
    OpenLoopOut,
    RealisingRequirementOut,
    RequestCommentOut,
    RequestCreate,
    RequesterOut,
    RequestMergeOut,
    RequestOut,
    RequestRefOut,
    RequestScoreOut,
    RequestUpdate,
    RequestVersionOut,
    ScorePreviewIn,
    ScorePreviewOut,
)
from app.modules.product_feedback.service import (
    ALLOWED_TRANSITIONS,
    EXTERNAL_REFERENCES_SUBCOMPONENT_KEY,
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
    validate_levels,
    version_levels,
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
        links: `{request id: RequestLinks}` (its Pain Points and Requirements); absent for an inbox request.
        informed: `{request id: the requesters recorded as told}`.
        references: `{request id: its external references}`.
    """

    merged_into: dict[uuid.UUID, RequestRefOut] = field(default_factory=dict)
    merged_count: dict[uuid.UUID, int] = field(default_factory=dict)
    demand: dict[uuid.UUID, Demand] = field(default_factory=dict)
    links: dict[uuid.UUID, RequestLinks] = field(default_factory=dict)
    informed: dict[uuid.UUID, set[PartyKey]] = field(default_factory=dict)
    references: dict[uuid.UUID, list[ExternalRefOut]] = field(default_factory=dict)


def request_extras(db: Session, requests: Sequence[EnhancementRequest]) -> RequestExtras:
    """Merge status, demand, links and informed requesters for `requests` in a fixed number of statements however
    many there are (demand and links only for project-owned ones: an inbox request cannot hold links)."""
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
            extras.links.update(compute_links(db, project, project_request_ids))
    extras.informed = {rid: set(rows) for rid, rows in informed_by_request(db, ids).items()}
    extras.references = refs.references_by_request(db, ids)
    return extras


def _score_out(score: RequestScore | None) -> RequestScoreOut | None:
    return RequestScoreOut(**score.__dict__) if score is not None else None


def rating_context_for(
    db: Session, request: EnhancementRequest, scoring_model: Sequence[str] | None = None,
    cache: dict[tuple[uuid.UUID, uuid.UUID | None], RatingContext] | None = None,
) -> RatingContext:
    """The scoring configuration that applies to `request`: its project's overrides, or the organisation's own
    for an inbox request. `cache` (keyed by owner) lets a list load each project's configuration once."""
    if request.project_id is not None:
        project = db.get(Project, request.project_id)
        assert project is not None  # the FK guarantees it
        organization_id = project.organization_id
    else:
        assert request.organization_id is not None  # the scope CHECK guarantees one owner
        organization_id = request.organization_id
    key = (organization_id, request.project_id)
    if cache is not None and key in cache:
        return cache[key]
    ctx = load_rating_context(db, organization_id, request.project_id, parse_model_keys(scoring_model))
    if cache is not None:
        cache[key] = ctx
    return ctx


def request_to_out(
    db: Session, request: EnhancementRequest, version: EnhancementRequestVersion, labels: OwnerLabels | None = None,
    extras: RequestExtras | None = None, ctx: RatingContext | None = None,
    scoring_model: Sequence[str] | None = None, levels: dict[str, uuid.UUID] | None = None,
) -> RequestOut:
    """Merges a request with its current version. `labels` (owner data), `extras` (merge status and demand),
    `ctx` (scoring configuration) and `levels` (the version's scoring levels) are pre-resolved when building
    many, resolved here when omitted; `scoring_model` picks the models scored (default: the enabled ones)."""
    labels = labels if labels is not None else owner_labels(db, [version])
    extras = extras if extras is not None else request_extras(db, [request])
    ctx = ctx if ctx is not None else rating_context_for(db, request, scoring_model)
    levels = levels if levels is not None else version_levels(db, [version.id])[version.id]
    demand = extras.demand.get(request.id, EMPTY_DEMAND)
    links = extras.links.get(request.id, NO_LINKS)
    informed = extras.informed.get(request.id, set())
    scores = score_levels(ctx, levels, demand.weighted)
    return RequestOut(
        id=request.id, scope=request.scope, organization_id=request.organization_id, project_id=request.project_id,
        unique_code=request.unique_code, creator_id=request.creator_id, is_archived=request.is_archived,
        archived_at=request.archived_at, archived_by=request.archived_by, title=version.title,
        description=version.description, status=version.status,
        allowed_next_statuses=sorted(
            ALLOWED_TRANSITIONS[version.status] - {EnhancementRequestStatus.DUPLICATE},
            key=list(EnhancementRequestStatus).index,
        ),
        owner=_owner_of(labels, version), external_refs=extras.references.get(request.id, []),
        decline_reason=version.decline_reason,
        levels=levels, derived_levels=derived_levels(ctx, levels, demand.weighted),
        score=_score_out(scores[ctx.model.key]), scoring_model_key=ctx.model.key,
        scores={key: _score_out(score) for key, score in scores.items()},
        version_number=version.version_number, created_at=request.created_at,
        updated_at=max(request.updated_at, version.created_at),
        merged_into=extras.merged_into.get(request.id), merged_count=extras.merged_count.get(request.id, 0),
        requester_count=demand.count, weighted_demand=demand.weighted,
        pain_point_count=len(links.pain_point_ids), requirement_count=len(links.requirement_ids),
        informed_count=sum(1 for r in demand.requesters if (r.artefact_type, r.id) in informed),
        loop_open_count=open_count(demand, version.status, informed),
    )


def requests_to_out(
    db: Session, requests: Sequence[EnhancementRequest], scoring_model: Sequence[str] | None = None,
) -> list[RequestOut]:
    """The list response: each current version loaded, every owner resolved, the merge and demand data read and
    the scores derived (under `scoring_model`, else each owner's enabled models) in a fixed number of statements
    per project."""
    by_id = current_versions(db, EnhancementRequestVersion, "request_id", [r.id for r in requests])
    versions = [by_id[r.id] for r in requests]
    labels = owner_labels(db, versions)
    extras = request_extras(db, requests)
    levels = version_levels(db, [v.id for v in versions])
    contexts: dict[tuple[uuid.UUID, uuid.UUID | None], RatingContext] = {}
    return [
        request_to_out(
            db, r, v, labels, extras, rating_context_for(db, r, scoring_model, contexts), levels=levels[v.id],
        )
        for r, v in zip(requests, versions, strict=True)
    ]


def current_request_out(
    db: Session, request: EnhancementRequest, scoring_model: Sequence[str] | None = None,
) -> RequestOut:
    """The API shape of one request, loading its current version; the scores are derived under `scoring_model`
    (default: the enabled models)."""
    return request_to_out(db, request, get_current_version(db, request.id), scoring_model=scoring_model)


def request_versions_out(db: Session, versions: Sequence[EnhancementRequestVersion]) -> list[RequestVersionOut]:
    """The API shape of a request's version history, resolving every owner in one batch."""
    labels = owner_labels(db, versions)
    levels = version_levels(db, [v.id for v in versions])
    return [
        RequestVersionOut(
            id=v.id, request_id=v.request_id, version_number=v.version_number, valid_from=v.valid_from,
            valid_to=v.valid_to, title=v.title, description=v.description, status=v.status, owner=_owner_of(labels, v),
            decline_reason=v.decline_reason, levels=levels[v.id],
            change_note=v.change_note, created_by=v.created_by, created_at=v.created_at,
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


def access_out(db: Session, current_user: User, holder: RecordOwner) -> FeedbackAccessOut:
    """The caller's submit and triage rights on this tier, computed with the same checks the write endpoints use."""
    can_triage = can_manage(db, current_user, holder)
    project_id = holder.project_id
    restricted = project_id is not None and get_submission_policy(db, project_id) == SubmissionPolicy.TRIAGERS
    return FeedbackAccessOut(can_submit=can_triage or not restricted, can_triage=can_triage)


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


def _check_levels(db: Session, holder: RecordOwner, sent: dict) -> None:
    """Validates the scoring levels present in `sent["levels"]`.

    Raises:
        HTTPException: 400 for an unknown axis, or a level of another organisation, scheme or axis.
    """
    try:
        validate_levels(db, holder.organization_id, holder.project_id, sent.get("levels") or {})
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def preview_scores(
    db: Session, holder: RecordOwner, payload: ScorePreviewIn, request: EnhancementRequest | None = None,
) -> ScorePreviewOut:
    """Scores levels that are still being chosen, under the enabled models, exactly as a saved request would be.

    Nothing is stored or audited. A new request has no requesters yet, so its weighted demand is 0; an existing
    one (`request`) reads its own, so the derived Demand axis shows what saving would give.

    Args:
        db: Active session (read only).
        holder: The project, or the organisation for an inbox request.
        payload: The levels chosen so far.
        request: The existing request being edited, if any (already checked to belong to `holder`).

    Raises:
        HTTPException: 400 for an unknown axis, or a level of another organisation, scheme or axis.
    """
    levels = {axis: level for axis, level in payload.levels.items() if level is not None}
    _check_levels(db, holder, {"levels": levels})
    ctx = load_rating_context(db, holder.organization_id, holder.project_id)
    weighted = 0.0
    if request is not None and holder.project_id is not None:
        project = db.get(Project, holder.project_id)
        assert project is not None  # the FK guarantees it
        weighted = compute_demand(db, project, [request.id])[request.id].weighted
    scores = score_levels(ctx, levels, weighted)
    return ScorePreviewOut(
        scores={key: _score_out(score) for key, score in scores.items()},
        derived_levels=derived_levels(ctx, levels, weighted), weighted_demand=weighted,
    )


def references_enabled(db: Session, holder: RecordOwner) -> bool:
    """Whether External references are switched on for the holder: a project's effective state (its own switch, else
    the organisation default), or the organisation's own for an inbox."""
    from app.modules.registry import is_module_subcomponent_enabled, is_org_module_subcomponent_enabled

    if holder.project_id is not None:
        return is_module_subcomponent_enabled(
            db, holder.project_id, PRODUCT_FEEDBACK_MODULE_KEY, EXTERNAL_REFERENCES_SUBCOMPONENT_KEY,
        )
    return is_org_module_subcomponent_enabled(
        db, holder.organization_id, PRODUCT_FEEDBACK_MODULE_KEY, EXTERNAL_REFERENCES_SUBCOMPONENT_KEY,
    )


def stage_request(db: Session, holder: RecordOwner, payload: RequestCreate, creator: User) -> EnhancementRequest:
    """Validates a create payload, creates the request (`NEW`) and audit-logs it. Does not commit: the endpoint and
    the record-table import each own their transaction. The caller has checked `require_request_submit`.

    Raises:
        HTTPException: 400 for an unusable owner or scoring level.
    """
    content = payload.model_dump(exclude={"owner", "references"})
    if (payload.references or payload.external_ref_url or payload.external_ref_key) and not references_enabled(db, holder):
        raise HTTPException(status.HTTP_409_CONFLICT, "External references are switched off here.")
    _check_levels(db, holder, content)
    content.update(_owner_columns(db, holder, payload))
    request = create_request(db, holder, creator, **content)
    try:
        for ref in payload.references:
            refs.add_reference(
                db, request, system_id=ref.system_id, key=ref.key, url=ref.url, role=ref.role, actor=creator,
            )
        if payload.external_ref_url or payload.external_ref_key:
            refs.apply_legacy_link(db, request, changes={
                "external_ref_url": payload.external_ref_url, "external_ref_key": payload.external_ref_key,
            }, actor=creator)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit_request(db, holder, request, "created", creator, {
        "title": payload.title, "unique_code": request.unique_code, "references": len(payload.references),
    })
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
        HTTPException: 422 for a null title, 400 for an unusable owner or scoring level.
    """
    sent = payload.model_dump(exclude_unset=True, exclude={"change_note", "owner"})
    legacy = {k: sent.pop(k) for k in ("external_ref_url", "external_ref_key") if k in sent}
    if "title" in sent and sent["title"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An enhancement request title cannot be null.")
    if "description" in sent and sent["description"] is None:
        sent["description"] = ""
    _check_levels(db, holder, sent)
    sent.update(_owner_columns(db, holder, payload))
    lock_row_for_update(db, EnhancementRequest, request.id)
    if legacy:
        try:
            refs.apply_legacy_link(db, request, changes=legacy, actor=actor)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        if not sent and "owner" not in payload.model_fields_set and not payload.change_note:
            audit_request(db, holder, request, "updated", actor)
            return
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
            "references": result.references,
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
    merge = apply_value_error_as_conflict(merge_requests, db, canonical, duplicate, actor, note)
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
            merged_by=m.merged_by, merged_at=m.merged_at, note=m.note, unmerged_by=m.unmerged_by, unmerged_at=m.unmerged_at,
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


#: How many requesters a demand response carries unless the caller asks for more or fewer.
DEMAND_PAGE_SIZE = 50
#: The most requesters one demand response may carry.
DEMAND_PAGE_MAX = 500


def demand_out(
    db: Session, project: Project, request: EnhancementRequest, viewer: User, *, limit: int = DEMAND_PAGE_SIZE, offset: int = 0,
) -> DemandOut:
    """The request's demand broken down for `viewer`, one page of requesters at a time.

    The totals (`requester_count`, `weighted_demand`) count every party the project can see, however many are on the
    page. `requesters` is the page `[offset, offset + limit)` of the heaviest-first list, and only those parties'
    names are looked up. A party's name and weight are given only when `viewer` holds `view` on its type (the same
    rule the link finder applies), and are null otherwise, so a count never reveals who a hidden party is.
    """
    demand = compute_demand(db, project, [request.id])[request.id]
    page = demand.requesters[offset:offset + limit]
    resolver = ArtefactResolver(db, project, viewer.id)
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for requester in page:
        wanted[requester.artefact_type].add(requester.id)
    wanted["engagement"].update(demand.engagement_ids)
    resolver.resolve(dict(wanted))
    engagement_labels = {e: resolver.visible(("engagement", e)) for e in demand.engagement_ids}
    channels = channels_by_request(db, [request.id])[request.id]
    return DemandOut(
        request_id=request.id, requester_count=demand.count, weighted_demand=demand.weighted, offset=offset, limit=limit,
        requesters=[_requester_out(r, resolver, channels) for r in page],
        engagements=[
            DemandEngagementOut(id=e, label=s.label if s else None, hidden=s is None, link_id=demand.engagement_links.get(e))
            for e, s in engagement_labels.items()
        ],
        merged_duplicates=_merged_duplicate_refs(db, request.id),
    )


def _requester_out(
    requester: Requester, resolver: ArtefactResolver, channels: dict[PartyKey, ChannelChoice] | None = None,
) -> RequesterOut:
    """A requester as `resolver`'s user may see it: the name and weight only when they can view the record. The
    channel (how they asked) is not personal data of the party, so it is given whether or not the party is visible."""
    seen = resolver.visible((requester.artefact_type, requester.id)) is not None
    choice = (channels or {}).get((requester.artefact_type, requester.id))
    return RequesterOut(
        artefact_type=requester.artefact_type, id=requester.id, label=requester.label if seen else None,
        weight=requester.weight if seen else None, weight_source=requester.weight_source if seen else "",
        effective_weight=requester.effective_weight,
        from_merge=requester.from_merge, via_engagement=requester.via_engagement, hidden=not seen, link_id=requester.link_id,
        channel=ChannelOut(id=choice.id, name=choice.name) if choice else None,
    )


# --- Closing the loop ------------------------------------------------------------


def _linked_records(
    resolver: ArtefactResolver, artefact_type: str, ids: Sequence[uuid.UUID],
) -> list[tuple[uuid.UUID, str | None]]:
    """`(id, label or None when the viewer cannot see it)` for each id, in order."""
    resolver.resolve({artefact_type: set(ids)})
    return [(i, s.label if (s := resolver.visible((artefact_type, i))) else None) for i in ids]


def close_the_loop_out(db: Session, project: Project, request: EnhancementRequest, viewer: User) -> CloseTheLoopOut:
    """What became of `request`: its requesters with whether each was told, the Pain Points it addresses, the
    Requirements that realise it and the cue to mark it delivered. Names are withheld (counts kept) for records the
    viewer cannot see, as `demand_out` does."""
    version = get_current_version(db, request.id)
    demand = compute_demand(db, project, [request.id])[request.id]
    links = compute_links(db, project, [request.id])[request.id]
    told = informed_by_request(db, [request.id]).get(request.id, {})
    channels = channels_by_request(db, [request.id])[request.id]
    resolver = ArtefactResolver(db, project, viewer.id, include_related=True)
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for requester in demand.requesters:
        wanted[requester.artefact_type].add(requester.id)
    resolver.resolve(dict(wanted))
    requesters = []
    for r in demand.requesters:
        row = told.get((r.artefact_type, r.id))
        base = _requester_out(r, resolver, channels)
        requesters.append(LoopRequesterOut(
            **base.model_dump(), informed=row is not None, informed_at=row.informed_at if row else None,
            informed_by=row.informed_by if row else None, note=row.note if row else "",
        ))
    complete = requirements_complete(db, links.requirement_ids)
    state = delivery_state(db, links.requirement_ids)
    return CloseTheLoopOut(
        request_id=request.id, status=version.status, decline_reason=version.decline_reason,
        can_record=version.status in CLOSED_STATUSES, requesters=requesters,
        informed_count=sum(1 for r in requesters if r.informed), open_count=open_count(demand, version.status, told),
        pain_points=[
            LinkedRecordOut(id=i, label=label, hidden=label is None)
            for i, label in _linked_records(resolver, "pain_point", links.pain_point_ids)
        ],
        realising_requirements=[
            RealisingRequirementOut(
                id=i, label=label, hidden=label is None, is_completed=complete.get(i) if label is not None else None,
            )
            for i, label in _linked_records(resolver, "requirement", links.requirement_ids)
        ],
        all_requirements_complete=state,
        suggest_delivered=version.status == EnhancementRequestStatus.ACCEPTED and state is True,
    )


def inform_from_payload(
    db: Session, holder: RecordOwner, project: Project, request: EnhancementRequest, payload: InformedUpdate,
    actor: User,
) -> CloseTheLoopOut:
    """Records (or withdraws) that requesters were told the outcome (the caller has checked the actor may),
    audit-logs one event with the party keys and counts (never the note), commits and returns the close-the-loop view.
    Locks the request row first so two concurrent ticks cannot race on the same party.

    Raises:
        HTTPException: 409 if the request is archived or has no outcome yet, or a party is not one of its requesters.
    """
    lock_row_for_update(db, EnhancementRequest, request.id)
    db.refresh(request)
    parties = [(p.artefact_type, p.id) for p in payload.parties]
    changed = apply_value_error_as_conflict(set_informed, db, project, request, parties, payload.informed, payload.note, actor)
    audit_request(db, holder, request, "requesters_informed" if payload.informed else "requesters_informed_withdrawn", actor, {
        "parties": [{"type": t, "id": str(i)} for t, i in parties], "changed": changed,
    })
    db.commit()
    return close_the_loop_out(db, project, request, actor)


def open_loops_out(db: Session, project: Project, viewer: User) -> list[OpenLoopOut]:
    """The project's delivered or declined requests with requesters still to be told, names withheld for records the
    viewer cannot see (the count of those still to be told is exact)."""
    loops = open_loop_requests(db, project)
    if not loops:
        return []
    resolver = ArtefactResolver(db, project, viewer.id)
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for loop in loops:
        for artefact_type, party_id in loop.uninformed:
            wanted[artefact_type].add(party_id)
    resolver.resolve(dict(wanted))
    channels = channels_by_request(db, [loop.request.id for loop in loops])
    out = []
    for loop in loops:
        pending = set(loop.uninformed)
        out.append(OpenLoopOut(
            request=RequestRefOut(id=loop.request.id, unique_code=loop.request.unique_code, title=loop.version.title),
            status=loop.version.status, decline_reason=loop.version.decline_reason,
            requester_count=loop.demand.count, open_count=len(pending),
            uninformed=[
                _requester_out(r, resolver, channels[loop.request.id])
                for r in loop.demand.requesters if (r.artefact_type, r.id) in pending
            ],
        ))
    return out


# --- External references and the channel per ask -----------------------------


def add_reference_from_payload(
    db: Session, holder: RecordOwner, request: EnhancementRequest, payload: ExternalRefIn, actor: User,
) -> ExternalRefOut:
    """Adds a reference (the caller has checked the actor may), audit-logs its system and role (never the key or the
    link), commits and returns it.

    Raises:
        HTTPException: 409 for an archived request; 400 for a system the request cannot use or too many references.
    """
    _require_unarchived(request)
    lock_row_for_update(db, EnhancementRequest, request.id)
    try:
        row = refs.add_reference(
            db, request, system_id=payload.system_id, key=payload.key, url=payload.url, role=payload.role, actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit_request(db, holder, request, "reference_added", actor, {"reference_id": str(row.id), "role": row.role.value})
    db.commit()
    return next(r for r in refs.references_by_request(db, [request.id])[request.id] if r.id == row.id)


def update_reference_from_payload(
    db: Session, holder: RecordOwner, request: EnhancementRequest, reference_id: uuid.UUID, payload: ExternalRefUpdate,
    actor: User,
) -> ExternalRefOut:
    """Changes a reference (partial), audit-logs which fields changed, commits and returns it.

    Raises:
        HTTPException: 404 for a reference of another request; 409 for an archived request; 400 for an unusable
            system or a result with neither a key nor a link.
    """
    _require_unarchived(request)
    row = refs.get_reference(db, request, reference_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference not found.")
    changes = payload.model_dump(exclude_unset=True)
    try:
        refs.update_reference(db, request, row, changes)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit_request(db, holder, request, "reference_updated", actor, {"reference_id": str(row.id), "fields": sorted(changes)})
    db.commit()
    return next(r for r in refs.references_by_request(db, [request.id])[request.id] if r.id == row.id)


def remove_reference_from_payload(
    db: Session, holder: RecordOwner, request: EnhancementRequest, reference_id: uuid.UUID, actor: User,
) -> None:
    """Removes a reference, audit-logs it and commits.

    Raises:
        HTTPException: 404 for a reference of another request; 409 for an archived request.
    """
    _require_unarchived(request)
    row = refs.get_reference(db, request, reference_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference not found.")
    refs.remove_reference(db, row)
    audit_request(db, holder, request, "reference_removed", actor, {"reference_id": str(reference_id)})
    db.commit()


def _require_unarchived(request: EnhancementRequest) -> None:
    """Raises 409 for an archived request: its references and channels are frozen until it is unarchived."""
    if request.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "An archived request cannot be changed; unarchive it first.")


def set_channel_from_payload(
    db: Session, holder: RecordOwner, project: Project, request: EnhancementRequest, payload: ChannelUpdate,
    actor: User,
) -> DemandOut:
    """Sets (or clears) how requesters asked (the caller has checked the actor may), audit-logs the party keys and
    the count changed, commits and returns the request's demand view.

    Raises:
        HTTPException: 409 for an archived request, a party that is not a requester or a channel the project cannot use.
    """
    lock_row_for_update(db, EnhancementRequest, request.id)
    db.refresh(request)
    parties = [(p.artefact_type, p.id) for p in payload.parties]
    changed = apply_value_error_as_conflict(set_channels, db, project, request, parties, payload.channel_id, actor)
    audit_request(db, holder, request, "requester_channel_set" if payload.channel_id else "requester_channel_cleared", actor, {
        "parties": [{"type": t, "id": str(i)} for t, i in parties], "changed": changed,
    })
    db.commit()
    return demand_out(db, project, request, actor)


# --- Comments and files (shared kit, see `services.module_attachments`) ------

REQUEST_ATTACHMENTS = att.AttachmentKit(
    artefact_type=REQUEST_ARTEFACT_TYPE, label="Enhancement request", comment_model=EnhancementRequestComment,
    comment_file_model=EnhancementRequestCommentFile, file_model=EnhancementRequestFile, fk="request_id",
    comment_out=RequestCommentOut,
)
