"""
Module: services.org_deletion

Application-level cleanup required before an organisation row is hard-deleted
(`routers/orgs.py::delete_organization`): everything a database cascade cannot do.

- Remove the stored output of background custom report runs (`GeneratedReport.output_key`) and every uploaded
  file's bytes from storage, not only its `FileAsset` row (disposal completeness, data-retention policy).
- Deactivate and archive the organisation's service users, which belong to it alone.
- Descope or revoke every Personal Access Token that reaches the organisation
  (`allowed_organization_ids` is a JSONB list, not a foreign key).
- Delete `ReviewComment`/`Subscription` rows that reference records polymorphically (no FK), and
  `ArtefactLink` rows that touch the organisation's artefacts (core and every module's, via
  `artefact_ids_in_organization`) or use its link types.
- Delete link rules and their entries before the link types (the entry FK has no cascade), and the
  projects before the organisation row.
- Null `Organization.logo_file_id`/`login_background_file_id` before any `FileAsset` is deleted (FKs to
  `file_assets` with no `ondelete`).

Everything else scoped to the organisation is removed by the `ondelete="CASCADE"`/`"SET NULL"` foreign keys
once the `Organization` row is deleted (`docs/decisions.md`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest, ReviewComment
from app.models.engagement import Subscription
from app.models.file import FileAsset
from app.models.generated_report import GeneratedReport
from app.models.organization import Organization
from app.models.pat import PersonalAccessToken
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.models.requirement_action import RequirementAction
from app.models.requirement_link_type import (
    ArtefactTypeLinkRule,
    ArtefactTypeLinkRuleEntry,
    RequirementLinkTypeDefinition,
)
from app.models.service_user import ServiceUserProfile
from app.models.user import User
from app.modules.registry import get_module_artefact_ids_in_organization
from app.services.files import delete_file, get_storage_backend


def delete_organization_cascade(db: Session, organization_id: UUID) -> None:
    """Runs every cleanup step above, then flushes. Must be called (and its
    work flushed) before the caller deletes the `Organization` row —
    `ReviewComment`/`Subscription` in particular have no FK relationship to
    lean on, so this is the only place they ever get cleaned up.
    """
    project_ids = list(db.scalars(select(Project.id).where(Project.organization_id == organization_id)).all())

    module_artefact_ids = get_module_artefact_ids_in_organization(db, organization_id)
    artefact_ids: set[UUID] = set(module_artefact_ids)
    if project_ids:
        requirement_ids = list(
            db.scalars(select(Requirement.id).where(Requirement.project_id.in_(project_ids))).all()
        )
        change_request_ids = list(
            db.scalars(select(ChangeRequest.id).where(ChangeRequest.project_id.in_(project_ids))).all()
        )
        action_ids = list(
            db.scalars(select(RequirementAction.id).where(RequirementAction.project_id.in_(project_ids))).all()
        )
        artefact_ids.update(requirement_ids, action_ids)
        entity_ids = [*requirement_ids, *change_request_ids, *action_ids, *module_artefact_ids]
        if entity_ids:
            db.execute(delete(ReviewComment).where(ReviewComment.target_id.in_(entity_ids)))
            db.execute(delete(Subscription).where(Subscription.entity_id.in_(entity_ids)))

    link_type_ids = select(RequirementLinkTypeDefinition.id).where(
        RequirementLinkTypeDefinition.organization_id == organization_id
    )
    link_conditions = [ArtefactLink.link_type_id.in_(link_type_ids)]
    if artefact_ids:
        link_conditions += [ArtefactLink.source_id.in_(artefact_ids), ArtefactLink.target_id.in_(artefact_ids)]
    db.execute(delete(ArtefactLink).where(or_(*link_conditions)))

    rule_ids = select(ArtefactTypeLinkRule.id).where(ArtefactTypeLinkRule.organization_id == organization_id)
    db.execute(delete(ArtefactTypeLinkRuleEntry).where(ArtefactTypeLinkRuleEntry.rule_id.in_(rule_ids)))
    db.execute(delete(ArtefactTypeLinkRule).where(ArtefactTypeLinkRule.organization_id == organization_id))

    # Organization.logo_file_id/login_background_file_id are FKs to file_assets with no ondelete action:
    # clearing them first keeps the FileAsset deletes below from failing midway, after storage bytes
    # (which cannot be rolled back) are already gone. A Core update avoids touching the caller's loaded Organization.
    db.execute(
        update(Organization)
        .where(Organization.id == organization_id)
        .values(logo_file_id=None, login_background_file_id=None)
    )

    # Stored report output is not a FileAsset: its object is named on the provenance row the cascade deletes.
    storage = get_storage_backend()
    for output_key in db.scalars(
        select(GeneratedReport.output_key).where(
            GeneratedReport.organization_id == organization_id, GeneratedReport.output_key.is_not(None)
        )
    ).all():
        if output_key is not None:  # the query excludes rows without one
            storage.delete(output_key)

    file_assets = list(db.scalars(select(FileAsset).where(FileAsset.organization_id == organization_id)).all())
    for file_asset in file_assets:
        delete_file(db, file_asset)

    org_id_str = str(organization_id)
    pats = list(
        db.scalars(
            select(PersonalAccessToken).where(
                PersonalAccessToken.revoked_at.is_(None),
                PersonalAccessToken.allowed_organization_ids.contains([org_id_str]),
            )
        ).all()
    )
    for pat in pats:
        pat.allowed_organization_ids = [oid for oid in pat.allowed_organization_ids if oid != org_id_str]
        if not pat.allowed_organization_ids:
            pat.revoked_at = datetime.now(UTC)

    # A service user belongs to this organisation alone; with the organisation gone nothing can reach it, so the
    # account is deactivated and archived (its profile row goes with the organisation) rather than left active.
    db.execute(
        update(User).where(
            User.is_service_account.is_(True),
            User.id.in_(select(ServiceUserProfile.user_id).where(ServiceUserProfile.organization_id == organization_id)),
        ).values(is_active=False, is_archived=True, deactivated_at=datetime.now(UTC))
    )

    # Projects go first so project-scoped rows (including module rows such as project type overrides)
    # are removed before the org row's cascade reaches the org-level definitions they reference; the
    # cascade order between the two is not fixed and can violate a CHECK or FK.
    db.execute(delete(Project).where(Project.organization_id == organization_id))

    db.flush()
