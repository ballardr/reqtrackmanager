"""
Module: services.org_deletion

Application-level cleanup required before an organisation row can be hard-
deleted (`routers/orgs.py::delete_organization`) — everything a database
foreign-key cascade can't do on its own:

- Removing every uploaded file's actual bytes from storage, not just its
  `FileAsset` row (a DB-only cascade would silently orphan the object in
  S3/local storage — see docs/soc2/policies/data-retention-and-disposal-
  policy.md's disposal-completeness requirement).
- Descoping/auto-revoking every Personal Access Token that reaches this
  org — `PersonalAccessToken.allowed_organization_ids` is a JSONB list of
  id strings chosen by the token's own owner, not a foreign key, so nothing
  else would ever clean it up.
- Deleting `ReviewComment`/`Subscription` rows that reference a requirement
  or change request *polymorphically* (a plain UUID column, not a real FK)
  — these would otherwise become silently orphaned rather than erroring,
  which is its own disposal-completeness gap even though it wouldn't break
  the delete itself.
- Nulling `Organization.logo_file_id`/`login_background_file_id` before any
  of the org's `FileAsset` rows are touched — both are self-referential FKs
  back to `file_assets` with no `ondelete` action, so deleting the file they
  point at would otherwise raise an `IntegrityError` partway through the
  file-deletion loop below.

Everything else scoped to this organisation (projects, requirements,
change requests, groups, report templates, custom field definitions,
notifications, ...) is removed by the `ondelete="CASCADE"`/`"SET NULL"`
foreign keys declared across the relevant models once the caller deletes
the `Organization` row itself — see docs/decisions.md for the full design
and the reasoning behind each cascade choice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequest, ReviewComment
from app.models.engagement import Subscription
from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.pat import PersonalAccessToken
from app.models.project import Project
from app.models.requirement import Requirement
from app.services.files import delete_file


def delete_organization_cascade(db: Session, organization_id: UUID) -> None:
    """Runs every cleanup step above, then flushes. Must be called (and its
    work flushed) before the caller deletes the `Organization` row —
    `ReviewComment`/`Subscription` in particular have no FK relationship to
    lean on, so this is the only place they ever get cleaned up.
    """
    project_ids = list(db.scalars(select(Project.id).where(Project.organization_id == organization_id)).all())

    if project_ids:
        requirement_ids = list(
            db.scalars(select(Requirement.id).where(Requirement.project_id.in_(project_ids))).all()
        )
        change_request_ids = list(
            db.scalars(select(ChangeRequest.id).where(ChangeRequest.project_id.in_(project_ids))).all()
        )
        entity_ids = requirement_ids + change_request_ids
        if entity_ids:
            db.execute(ReviewComment.__table__.delete().where(ReviewComment.target_id.in_(entity_ids)))
            db.execute(Subscription.__table__.delete().where(Subscription.entity_id.in_(entity_ids)))

    # Organization.logo_file_id/login_background_file_id are self-referential
    # FKs to file_assets with no ondelete action (models/organization.py) —
    # deleting a FileAsset row still referenced there raises a raw
    # IntegrityError, which a hardening-review pass found is only ever
    # discovered via SQLAlchemy's autoflush partway through the loop below,
    # by which point that loop's earlier storage-backend deletes (which
    # aren't transactional/rollback-able) had already run: an org that ever
    # had a logo or login-background image set could not be hard-deleted at
    # all, and the crash destroyed some of its other files' storage bytes
    # without the org (or those rows) actually being deleted. Nulling both
    # columns first, before any FileAsset is touched, removes the reference
    # so the loop below can never hit this — a raw Core update rather than
    # loading the ORM object, since the caller may already hold its own
    # `Organization` instance in the session identity map and this only
    # needs to affect what's persisted before the row itself is deleted.
    db.execute(
        Organization.__table__.update()
        .where(Organization.id == organization_id)
        .values(logo_file_id=None, login_background_file_id=None)
    )

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

    db.flush()
