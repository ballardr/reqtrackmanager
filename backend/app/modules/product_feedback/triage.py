"""
Module: modules.product_feedback.triage

Triage of an inbox request into a project (`move_to_project`): re-owns the row
in place (versions, comments, links and audit stay attached) and fixes what the
owner tier decides: the code is renumbered from the project's `ENH` counter,
tags are re-resolved by name, files lose `is_org_resource`. A link or a merge
(either end) blocks the move. Nothing commits or checks the role.
Dependencies: `services.sequences`, `services.tags`, `models.file`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.tag import ArtefactTag
from app.models.user import User
from app.modules.product_feedback.enums import EnhancementRequestScope
from app.modules.product_feedback.merge import has_active_merge
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestComment,
    EnhancementRequestCommentFile,
    EnhancementRequestFile,
)
from app.modules.product_feedback.references import convert_to_project
from app.modules.product_feedback.service import (
    REQUEST_ARTEFACT_TYPE,
    REQUEST_CODE_PREFIX,
    apply_new_version,
    get_current_version,
)
from app.services import tags as tag_service
from app.services.lookups import affected_rows
from app.services.sequences import generate_unique_code


@dataclass(frozen=True)
class MoveResult:
    """What a move changed, for the audit detail.

    Attributes:
        previous_code: The inbox code the request carried (e.g. `ENH-004`).
        new_code: The code the project's counter gave it.
        tags: The tag names carried across.
        files: How many files (direct and on comments) became project files.
        references: How many external references were re-pointed at the project's systems.
    """

    previous_code: str
    new_code: str
    tags: list[str]
    files: int
    references: int = 0


def move_to_project(db: Session, request: EnhancementRequest, project: Project, actor: User) -> MoveResult:
    """Moves an inbox request into `project`, keeping its id, status and history.

    Args:
        db: Active session; the caller has locked the request row, checked the actor's authority in both
            tiers and commits.
        request: An organisation-owned request.
        project: A project of the same organisation.
        actor: The acting user; recorded on the version that notes the move.

    Returns:
        What changed (for the audit event).

    Raises:
        ValueError: If the request is not an inbox request, the project belongs to another organisation, or
            the request has links.
    """
    if request.scope != EnhancementRequestScope.ORGANIZATION:
        raise ValueError("Only an organisation inbox request can be moved into a project.")
    if project.organization_id != request.organization_id:
        raise ValueError("A request can only move to a project of its own organisation.")
    if db.scalar(select(ArtefactLink.id).where(
        or_(
            (ArtefactLink.source_type == REQUEST_ARTEFACT_TYPE) & (ArtefactLink.source_id == request.id),
            (ArtefactLink.target_type == REQUEST_ARTEFACT_TYPE) & (ArtefactLink.target_id == request.id),
        )
    ).limit(1)) is not None:
        raise ValueError("Remove the request's links before moving it into a project.")

    if has_active_merge(db, request.id):
        raise ValueError("A request in a merge cannot be moved; unmerge it first.")

    previous_code = request.unique_code
    request.unique_code = generate_unique_code(db, project, REQUEST_ARTEFACT_TYPE, REQUEST_CODE_PREFIX)
    request.scope = EnhancementRequestScope.PROJECT
    request.organization_id = None
    request.project_id = project.id
    db.flush()

    names = [t.name for t in tag_service.get_record_tags(db, REQUEST_ARTEFACT_TYPE, request.id)]
    db.execute(delete(ArtefactTag).where(
        ArtefactTag.artefact_type == REQUEST_ARTEFACT_TYPE, ArtefactTag.artefact_id == request.id,
    ))
    tag_service.restore_record_tags(
        db, organization_id=project.organization_id, record_project_id=project.id, actor_id=actor.id,
        artefact_type=REQUEST_ARTEFACT_TYPE, artefact_id=request.id, names=names,
    )

    direct = select(EnhancementRequestFile.file_id).where(EnhancementRequestFile.request_id == request.id)
    on_comments = (
        select(EnhancementRequestCommentFile.file_id)
        .join(EnhancementRequestComment, EnhancementRequestComment.id == EnhancementRequestCommentFile.comment_id)
        .where(EnhancementRequestComment.request_id == request.id)
    )
    files = affected_rows(db.execute(
        update(FileAsset).where(FileAsset.id.in_(direct.union(on_comments)), FileAsset.is_org_resource.is_(True))
        .values(is_org_resource=False)
    ))

    references = convert_to_project(db, request, project)
    apply_new_version(
        db, request, get_current_version(db, request.id), actor, changes={},
        change_note=f"Moved from the organisation inbox ({previous_code}) into project {project.name}.",
    )
    return MoveResult(previous_code, request.unique_code, names, files or 0, references)
