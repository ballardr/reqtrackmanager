"""
Module: routers.artefact_links

Links on any artefact of a project:
- `GET .../{type}/{id}/link-graph`: the records linked to it out to a few hops,
  with edge direction resolved against the organisation's link-type settings.
- `GET .../{type}/{id}/link-types`: the link types usable from it.
- `GET .../{type}/{id}/link-candidates`: the records a link could point at, found by a
  bounded search over every linkable type or within one type narrowed by browse levels.
- `GET .../{type}/{id}/link-browse`: the next browse level of a type (standard -> version
  -> requirement, component -> category, status, ...) given the choices so far.
- `GET .../{type}/{id}/activity`: the record's activity timeline (audit events, versions, link events).
- `POST .../{type}/{id}/links/bulk`: several links in one all-or-nothing call (create forms' quick-link field).
- `POST .../{type}/{id}/links` and `DELETE .../{type}/{id}/links/{link_id}`:
  generic link authoring from either end, whatever the artefact types.

This router is the authorisation point: project membership is checked here, and
the services then authorise every record (same project or visible org record,
module enabled, `view` permission; `link` or `manage` on the page artefact's type
for writes), so a hidden record is counted but never revealed or traversed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.registry import get_artefact_type_label
from app.schemas.artefact_links import (
    ArtefactLinkBrowseOption,
    ArtefactLinkBrowseStepOut,
    ArtefactLinkBulkCreate,
    ArtefactLinkBulkOut,
    ArtefactLinkCandidate,
    ArtefactLinkCandidatesOut,
    ArtefactLinkCreate,
    ArtefactLinkOtherEnd,
    ArtefactLinkOut,
    ArtefactLinkTypeOption,
    LinkOrientation,
)
from app.schemas.changes import RecordActivityOut
from app.schemas.link_graph import LinkGraphDirection, LinkGraphOut
from app.schemas.link_type import ArtefactTypeOut
from app.services.link_authoring import (
    CreatedLink,
    create_link_for_artefact,
    delete_link_for_artefact,
    related_project_or_404,
    require_finder_artefact,
    usable_options,
)
from app.services.link_browse import CANDIDATE_LIMIT, next_browse_step, parse_selected, search_link_candidates
from app.services.link_graph import MAX_DEPTH, ArtefactResolver, build_link_graph
from app.services.link_types import ensure_org_seeds
from app.services.rbac import require_project_view
from app.services.record_activity import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, get_record_activity

router = APIRouter(prefix="/api/v1/projects/{project_id}/artefacts", tags=["artefact-links"])


@router.get("/{artefact_type}/{artefact_id}/link-graph", response_model=LinkGraphOut)
def get_artefact_link_graph(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    depth: int = Query(2, ge=1, le=MAX_DEPTH, description="Hops to follow from the artefact."),
    direction: LinkGraphDirection = Query(LinkGraphDirection.BOTH, description="Which stored link orientations to follow."),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> LinkGraphOut:
    """Returns the link graph around one artefact of the project.

    Args:
        project_id: The project; the caller must be a member.
        artefact_type: A registered artefact type (`requirement`, `decision`, ...).
        artefact_id: The artefact's id.
        depth: Hops to follow (1-3).
        direction: `outgoing`, `incoming` or `both`.

    Returns:
        The root, the visible nodes and edges, whether the node cap truncated
        the result, and how many linked records were not shown.

    Raises:
        HTTPException: 404 if the type is unregistered or the artefact is not a
            visible record of this project (indistinguishable by design).
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    graph = build_link_graph(
        db, project=project, user_id=current_user.id, root_type=artefact_type, root_id=artefact_id,
        depth=depth, direction=direction,
    )
    if graph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    return graph


@router.get("/{artefact_type}/{artefact_id}/activity", response_model=RecordActivityOut)
def get_artefact_activity(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Entries per page."),
    offset: int = Query(0, ge=0, description="Entries to skip."),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> RecordActivityOut:
    """Returns one page of a record's activity timeline, newest first.

    Authorised like the record itself: the viewer must be able to open it in this project, and a
    link event is shown only when the record at its other end is also visible to them.

    Args:
        project_id: The project; the caller must be a member.
        artefact_type: A registered artefact type.
        artefact_id: The artefact's id.
        limit: Page size (1-100).
        offset: Entries to skip.

    Returns:
        The page and whether more entries follow.

    Raises:
        HTTPException: 404 if the type is unregistered or the artefact is not a visible record of
            this project (indistinguishable by design).
    """
    project = _project_or_404(db, project_id)
    return get_record_activity(
        db, project=project, user=current_user, artefact_type=artefact_type, artefact_id=artefact_id,
        limit=limit, offset=offset,
    )


def _project_or_404(db: Session, project_id: UUID) -> Project:
    """The project, or 404 (membership is checked separately by the route dependency)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


@router.get("/{artefact_type}/{artefact_id}/link-types", response_model=list[ArtefactLinkTypeOption])
def list_artefact_link_types(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    other_type: str | None = Query(None, description="Only options that can reach this artefact type."),
    other_project_id: UUID | None = Query(
        None, description="Only options usable with the other end in this ancestor or descendant project."
    ),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> list[ArtefactLinkTypeOption]:
    """The link types usable from this artefact, with orientation, the phrase to
    show and the artefact types reachable at the other end.

    Types a link-type restriction or either end's artefact-type rule rules out
    are left out, as are dedicated types (made with their own action). Missing
    module-seeded types are created first. With `other_project_id` (an ancestor or
    descendant project) only types whose nesting scope permits that pairing are listed,
    each with the orientation it can be used in.

    Raises:
        HTTPException: 404 if the artefact is not a visible record of the project, or
            `other_project_id` is not a related project the caller can open.
    """
    project = _project_or_404(db, project_id)
    require_finder_artefact(db, ArtefactResolver(db, project, current_user.id), project, artefact_type, artefact_id)
    other_project = (
        related_project_or_404(db, project, current_user.id, other_project_id)
        if other_project_id is not None and other_project_id != project.id else None
    )
    ensure_org_seeds(db, project.organization_id)
    db.commit()
    return [
        ArtefactLinkTypeOption(
            link_type_id=option.link_type.id, forward_name=option.link_type.forward_name,
            reverse_name=option.link_type.reverse_name, flow=option.link_type.flow,
            nesting_scope=option.link_type.nesting_scope,
            direction=LinkOrientation.OUTGOING if option.outgoing else LinkOrientation.INCOMING,
            phrase=option.phrase,
            other_types=[ArtefactTypeOut(type=t, label=get_artefact_type_label(t)) for t in option.other_types],
        )
        for option in usable_options(db, project, artefact_type, other_type, other_project)
    ]


@router.get("/{artefact_type}/{artefact_id}/link-candidates", response_model=ArtefactLinkCandidatesOut)
def list_artefact_link_candidates(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    other_type: str | None = Query(
        None, description="The artefact type to search; omit to search every linkable type (needs `q`, 2+ characters)."
    ),
    other_project_id: UUID | None = Query(None, description="Search this ancestor or descendant project instead."),
    selected: str | None = Query(
        None, max_length=2000, description="Browse choices narrowing `other_type`, as `level:option,level:option`."
    ),
    q: str | None = Query(None, max_length=100, description="Text the record's label must contain."),
    limit: int = Query(CANDIDATE_LIMIT, ge=1, le=CANDIDATE_LIMIT),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> ArtefactLinkCandidatesOut:
    """Records this artefact could be linked to (the add dialog's finder).

    Without `other_type` this is a bounded search across every type a usable link type can
    reach: it needs at least two characters of `q`, takes a few records per type and merges
    them. With `other_type` it searches that type, narrowed by `selected` (the options chosen
    at the type's browse levels). Only records the caller may view in the searched project
    are returned; the artefact itself and archived records are left out. Whether the link
    type allows the pairing is checked when the link is created.

    Raises:
        HTTPException: 404 the artefact is not visible, `other_type` is unregistered, or
            `other_project_id` is not a related project the caller can open; 400 an invalid
            `selected`.
    """
    project = _project_or_404(db, project_id)
    found, truncated = search_link_candidates(
        db, project=project, user_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id,
        other_type=other_type, other_project_id=other_project_id, selected=parse_selected(selected), query=q,
        limit=limit,
    )
    return ArtefactLinkCandidatesOut(
        items=[
            ArtefactLinkCandidate(
                type=c.type, id=c.summary.id, type_label=get_artefact_type_label(c.type), label=c.summary.label,
                status=c.summary.status, project_id=c.summary.project_id,
            )
            for c in found
        ],
        truncated=truncated,
    )


@router.get("/{artefact_type}/{artefact_id}/link-browse", response_model=ArtefactLinkBrowseStepOut | None)
def get_artefact_link_browse_step(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    other_type: str = Query(..., description="The artefact type being browsed."),
    other_project_id: UUID | None = Query(None, description="Browse this ancestor or descendant project instead."),
    selected: str | None = Query(None, max_length=2000, description="Choices so far, as `level:option,level:option`."),
    q: str | None = Query(None, max_length=100, description="Text the options' labels must contain."),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> ArtefactLinkBrowseStepOut | None:
    """The next browse level of `other_type` given the choices so far, or `null` once the chain
    is complete (or the type is not offered or viewable there).

    Each level is computed from the previous choices only and a choice is checked against what
    its level offered, so a client cannot widen a level by naming an option from elsewhere.

    Raises:
        HTTPException: 404 the artefact is not visible, `other_type` is unregistered, or
            `other_project_id` is not a related project the caller can open; 400 an invalid
            `selected`.
    """
    project = _project_or_404(db, project_id)
    step = next_browse_step(
        db, project=project, user_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id,
        other_type=other_type, other_project_id=other_project_id, selected=parse_selected(selected), query=q or "",
    )
    if step is None:
        return None
    return ArtefactLinkBrowseStepOut(
        key=step.key, label=step.label, truncated=step.truncated,
        options=[ArtefactLinkBrowseOption(id=option_id, label=label) for option_id, label in step.options],
    )


@router.post("/{artefact_type}/{artefact_id}/links", response_model=ArtefactLinkOut, status_code=status.HTTP_201_CREATED)
def create_artefact_link(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    payload: ArtefactLinkCreate,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> ArtefactLinkOut:
    """Links this artefact to another record of the project, or of an ancestor or
    descendant project (`other_project_id`), from either end.

    Raises:
        HTTPException: 404 an end is not a visible record of its project, or
            `other_project_id` is not a related project the caller can open; 403
            neither `link` nor `manage` on this artefact type held; 400 the link type is unusable
            here (other organisation, dedicated, or a link-type restriction or
            artefact-type rule or the type's nesting scope forbids the pair) or a self-link;
            409 duplicate or
            a change request is required for an approved requirement.
    """
    project = _project_or_404(db, project_id)
    created = create_link_for_artefact(
        db, project=project, user_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id,
        link_type_id=payload.link_type_id, outgoing=payload.direction is LinkOrientation.OUTGOING,
        other_type=payload.other_type, other_id=payload.other_id, other_project_id=payload.other_project_id,
    )
    db.commit()
    return _link_out(created)


@router.post(
    "/{artefact_type}/{artefact_id}/links/bulk", response_model=ArtefactLinkBulkOut, status_code=status.HTTP_201_CREATED
)
def create_artefact_links_bulk(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    payload: ArtefactLinkBulkCreate,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
) -> ArtefactLinkBulkOut:
    """Links this artefact to several records in one all-or-nothing call.

    Each link goes through exactly the checks of the single-link endpoint (visibility of both
    ends, `link`/`manage` or default role, link-type rules, nesting scope, change-request gate,
    duplicates), in request order, so a pair repeated within the request is a duplicate too. If
    any link is refused nothing is created and the error names which one (`Link 2 of 3: ...`),
    with the status the single-link endpoint would give.

    Raises:
        HTTPException: as `create_artefact_link`, for the first link refused.
    """
    project = _project_or_404(db, project_id)
    total = len(payload.links)
    created: list[CreatedLink] = []
    try:
        for index, link in enumerate(payload.links, start=1):
            try:
                created.append(create_link_for_artefact(
                    db, project=project, user_id=current_user.id, artefact_type=artefact_type,
                    artefact_id=artefact_id, link_type_id=link.link_type_id,
                    outgoing=link.direction is LinkOrientation.OUTGOING, other_type=link.other_type,
                    other_id=link.other_id, other_project_id=link.other_project_id,
                ))
            except HTTPException as exc:
                raise HTTPException(exc.status_code, f"Link {index} of {total}: {exc.detail}") from exc
    except HTTPException:
        db.rollback()
        raise
    db.commit()
    return ArtefactLinkBulkOut(items=[_link_out(c) for c in created])


def _link_out(created: CreatedLink) -> ArtefactLinkOut:
    """A created link read from the page artefact's side."""
    return ArtefactLinkOut(
        id=created.link.id, link_type_id=created.link_type.id,
        phrase=created.link_type.forward_name if created.outgoing else created.link_type.reverse_name,
        direction=LinkOrientation.OUTGOING if created.outgoing else LinkOrientation.INCOMING,
        other=ArtefactLinkOtherEnd(
            type=created.other_type, id=created.other.id, type_label=get_artefact_type_label(created.other_type),
            label=created.other.label, status=created.other.status, is_archived=created.other.is_archived,
            project_id=created.other.project_id,
        ),
    )


@router.delete("/{artefact_type}/{artefact_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artefact_link(
    project_id: UUID,
    artefact_type: str,
    artefact_id: UUID,
    link_id: UUID,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Removes a link touching this artefact.

    Raises:
        HTTPException: 404 the artefact is not visible or the link does not touch
            it; 403 neither `link` nor `manage` held; 400 the link belongs to a dedicated action;
            409 a change request is required for an approved requirement.
    """
    project = _project_or_404(db, project_id)
    delete_link_for_artefact(
        db, project=project, user_id=current_user.id, artefact_type=artefact_type, artefact_id=artefact_id,
        link_id=link_id,
    )
    db.commit()
