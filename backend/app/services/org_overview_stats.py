"""
Module: services.org_overview_stats

The organisation overview's headline figures (projects, requirements, members, file storage) for one caller.

Responsibilities:
- Count what the caller may see: an organisation administrator sees the organisation's real totals, anyone else sees
  counts limited to the projects they can open (`project_access.accessible_project_ids`).
- Serve both the stats endpoint and the organisation dashboards' core metrics, so the two cannot disagree.

Design decisions: a server administrator with no role in the organisation gets no figures (the caller's route gates
that first); member count is never scoped, because anyone who reaches the figures may already list the members.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole
from app.models.file import FileAsset, RequirementActionFile, RequirementFile
from app.models.organization import UserOrgRole
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.schemas.org import OrgOverviewStatsOut
from app.services.project_access import accessible_project_ids
from app.services.rbac import get_effective_org_roles


def org_overview_stats(db: Session, current_user: User, organization_id: UUID) -> OrgOverviewStatsOut:
    """The headline figures of the organisation as `current_user` may see them.

    Project and requirement counts cover active items only (archived projects and requirements are excluded, like the
    lists they summarise); the file total includes archived projects' files, which still occupy storage. A scoped
    member's file total is a strict undercount (a comment attachment is not attributed to a project), never an
    over-exposure.

    Args:
        db: The session (read only).
        current_user: The caller; their organisation roles decide whether the totals are full or scoped.
        organization_id: The organisation.

    Returns:
        The figures and `is_full_org_total`, which says which of the two meanings they have.
    """
    org_roles = get_effective_org_roles(db, current_user.id, organization_id)
    sees_full_totals = current_user.is_server_admin or OrgRole.ORG_ADMIN in org_roles

    member_count = db.scalar(
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .join(UserOrgRole, UserOrgRole.user_id == User.id)
        .where(UserOrgRole.organization_id == organization_id, User.is_archived.is_(False))
    ) or 0

    if sees_full_totals:
        project_count = db.scalar(
            select(func.count()).select_from(Project).where(
                Project.organization_id == organization_id, Project.is_archived.is_(False)
            )
        ) or 0
        requirement_count = db.scalar(
            select(func.count())
            .select_from(Requirement)
            .join(Project, Project.id == Requirement.project_id)
            .where(
                Project.organization_id == organization_id, Project.is_archived.is_(False),
                Requirement.is_archived.is_(False),
            )
        ) or 0
        total_file_size_bytes = db.scalar(
            select(func.coalesce(func.sum(FileAsset.size_bytes), 0)).where(
                FileAsset.organization_id == organization_id
            )
        ) or 0
    else:
        accessible_ids = accessible_project_ids(db, current_user.id)
        org_project_ids = set(
            db.scalars(
                select(Project.id).where(
                    Project.organization_id == organization_id, Project.id.in_(accessible_ids)
                )
            ).all()
        ) if accessible_ids else set()
        active_project_ids = set(
            db.scalars(select(Project.id).where(Project.id.in_(org_project_ids), Project.is_archived.is_(False))).all()
        ) if org_project_ids else set()
        project_count = len(active_project_ids)
        requirement_count = (
            db.scalar(select(func.count()).select_from(Requirement).where(
                Requirement.project_id.in_(active_project_ids), Requirement.is_archived.is_(False),
            ))
            if active_project_ids
            else 0
        ) or 0

        # Distinct files this member can account for: this org's own shared
        # resources (`is_org_resource`, visible to any member regardless of
        # per-project access — same as `GET /{organization_id}/resources`)
        # plus files attached to a requirement/action within their
        # accessible-project set. A file could match both a requirement
        # attachment and (if it's also an org resource) the first clause —
        # `union()` de-duplicates by file id so it's never double-counted.
        #
        # Known, deliberate gap: `CommentFile` (a file attached to a
        # `ReviewComment`, C-M-02's discussion-thread attachment path) is
        # NOT included here. `ReviewComment.target_id` is polymorphic
        # (`ReviewTargetType.REQUIREMENT`/`ACTION`/`CHANGE_REQUEST`, no FK),
        # so resolving it back to a project id for scoping would need a
        # three-way branch per target type — a disproportionate amount of
        # complexity for what these comment-thread attachments actually
        # weigh, versus the admin branch above (a plain per-org sum, which
        # *does* include every `CommentFile`'s underlying `FileAsset`
        # regardless of type). This makes a scoped member's own total a
        # strict undercount, never an over-exposure — the safe direction
        # for a visibility boundary — but it is a real, known accuracy gap:
        # revisit if comment attachments turn out to matter for this figure.
        org_resource_file_ids = select(FileAsset.id.label("file_id")).where(
            FileAsset.organization_id == organization_id, FileAsset.is_org_resource.is_(True)
        )
        if org_project_ids:
            requirement_ids = select(Requirement.id).where(Requirement.project_id.in_(org_project_ids))
            action_ids = select(RequirementAction.id).where(RequirementAction.project_id.in_(org_project_ids))
            file_ids_via_requirement = select(RequirementFile.file_id).where(
                RequirementFile.requirement_id.in_(requirement_ids)
            )
            file_ids_via_action = select(RequirementActionFile.file_id).where(
                RequirementActionFile.action_id.in_(action_ids)
            )
            distinct_file_ids = org_resource_file_ids.union(file_ids_via_requirement, file_ids_via_action).subquery()
        else:
            distinct_file_ids = org_resource_file_ids.subquery()
        total_file_size_bytes = db.scalar(
            select(func.coalesce(func.sum(FileAsset.size_bytes), 0)).where(
                FileAsset.id.in_(select(distinct_file_ids.c.file_id))
            )
        ) or 0

    return OrgOverviewStatsOut(
        project_count=project_count,
        requirement_count=requirement_count,
        member_count=member_count,
        total_file_size_bytes=total_file_size_bytes,
        is_full_org_total=sees_full_totals,
    )
