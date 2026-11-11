"""
Module: services.storage_usage

Measures how much file storage an organisation uses and applies the operator's rules for it.

Responsibilities:
- `used_bytes` / `file_count`: the one definition of usage (stored files plus stored report-run outputs), shared by the
  upload gate, the organisation usage table and the server administration view, so a limit and the figure shown against
  it cannot disagree.
- `effective_quota`: the organisation's own limit, else the server default, else none.
- `refusal`: the single decision "may this organisation store `incoming` more bytes?" used by `services.files`.
- `note_upload`: sends the 90% notice once per crossing.

Design decisions: usage is an aggregate over an indexed column, read only when a limit applies (an organisation with no
limit pays nothing) and never a stored counter that can drift; the check locks the organisation row for the transaction
so two concurrent uploads cannot both pass on the same remaining space; lowering a limit below usage only blocks new
files. External dependencies: SQLAlchemy models `FileAsset`, `GeneratedReport`, `Organization`, `ServerSettings`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import OrgRole
from app.models.file import FileAsset
from app.models.generated_report import GeneratedReport
from app.models.notification import NotificationType
from app.models.organization import Organization, ServerSettings, UserOrgRole
from app.models.user import User
from app.services.audit import log_event

#: Percentage of the limit at which an organisation's administrators are told.
WARNING_PERCENT = 90

#: Where an effective limit comes from.
SOURCE_ORGANIZATION = "organization"
SOURCE_SERVER = "server"


@dataclass(frozen=True)
class Quota:
    """An organisation's effective storage limit.

    Attributes:
        bytes: The limit in bytes, or None when there is none.
        source: `SOURCE_ORGANIZATION`, `SOURCE_SERVER`, or None when there is no limit.
    """

    bytes: int | None
    source: str | None


def used_bytes(db: Session, organization_id: UUID) -> int:
    """The bytes an organisation stores: its files plus the stored outputs of its background report runs.

    Args:
        db: An active database session.
        organization_id: The organisation.

    Returns:
        The total in bytes.
    """
    files = db.scalar(
        select(func.coalesce(func.sum(FileAsset.size_bytes), 0)).where(FileAsset.organization_id == organization_id)
    ) or 0
    outputs = db.scalar(
        select(func.coalesce(func.sum(GeneratedReport.output_size), 0)).where(
            GeneratedReport.organization_id == organization_id, GeneratedReport.output_key.is_not(None),
        )
    ) or 0
    return int(files) + int(outputs)


def file_count(db: Session, organization_id: UUID) -> int:
    """The number of files an organisation stores (report-run outputs are not counted as files).

    Args:
        db: An active database session.
        organization_id: The organisation.

    Returns:
        The count of stored files.
    """
    return db.scalar(select(func.count()).select_from(FileAsset).where(FileAsset.organization_id == organization_id)) or 0


def effective_quota(db: Session, organization: Organization) -> Quota:
    """The limit that applies to an organisation: its own, else the server default, else none.

    Args:
        db: An active database session.
        organization: The organisation.

    Returns:
        The limit and where it came from.
    """
    if organization.storage_quota_bytes is not None:
        return Quota(organization.storage_quota_bytes, SOURCE_ORGANIZATION)
    default = db.scalar(select(ServerSettings.default_storage_quota_bytes))
    if default is not None:
        return Quota(default, SOURCE_SERVER)
    return Quota(None, None)


def refusal(db: Session, organization_id: UUID, incoming_bytes: int) -> dict[str, object] | None:
    """Decides whether an organisation may store more bytes, under its own switch and limit.

    The deployment-wide switch is checked by the caller first. When a limit applies, the organisation row is locked for
    the rest of the transaction (an organisation with no limit is not locked) so concurrent uploads are serialised on
    the remaining space.

    Args:
        db: An active database session.
        organization_id: The organisation that would own the bytes.
        incoming_bytes: The size about to be stored (0 asks only whether storing is allowed at all).

    Returns:
        None when allowed; otherwise the 403 detail (`code`, `message` and, for a limit, `quota_bytes`, `used_bytes`).
    """
    organization = db.get(Organization, organization_id)
    if organization is None:
        return None
    if not organization.file_uploads_enabled:
        return {
            "code": "organization_uploads_disabled",
            "message": "File uploads are disabled for this organisation. Contact the server administrator.",
        }
    quota = effective_quota(db, organization)
    if quota.bytes is None:
        return None
    db.execute(select(Organization.id).where(Organization.id == organization_id).with_for_update())
    used = used_bytes(db, organization_id)
    if used + incoming_bytes > quota.bytes:
        return {
            "code": "storage_quota_exceeded",
            "message": (
                "The storage limit of this organisation has been reached. Delete files to free space, or ask the "
                "server administrator to raise the limit."
            ),
            "quota_bytes": quota.bytes, "used_bytes": used, "remaining_bytes": max(quota.bytes - used, 0),
        }
    return None


def note_upload(db: Session, organization_id: UUID, incoming_bytes: int) -> None:
    """Tells the organisation's administrators once when storage reaches the warning level.

    Called by the upload gate after it has allowed the file. The flag is cleared when usage (before the new file) is below
    the level, so a later crossing is announced again. The audit event carries counts only.

    Args:
        db: An active database session; the notifications and flag are added, the caller commits.
        organization_id: The organisation.
        incoming_bytes: The size of the file being stored.
    """
    organization = db.get(Organization, organization_id)
    if organization is None:
        return
    quota = effective_quota(db, organization)
    if quota.bytes is None or quota.bytes <= 0:
        if organization.storage_warned:
            organization.storage_warned = False
        return
    level = quota.bytes * WARNING_PERCENT // 100
    used = used_bytes(db, organization_id)
    if used < level and organization.storage_warned:
        organization.storage_warned = False
    if used + incoming_bytes < level or organization.storage_warned:
        return
    organization.storage_warned = True
    from app.services.notifications import notify

    admins = db.scalars(
        select(User).join(UserOrgRole, UserOrgRole.user_id == User.id).where(
            UserOrgRole.organization_id == organization_id, UserOrgRole.role == OrgRole.ORG_ADMIN,
            User.is_active.is_(True), User.is_archived.is_(False),
        ).distinct()
    ).all()
    sent = 0
    for admin in admins:
        created = notify(
            db, admin, notification_type=NotificationType.STORAGE_LIMIT_NEAR,
            title="Organisation file storage is nearly full",
            body=(
                f"The organisation has used {WARNING_PERCENT}% or more of its storage limit. "
                "Delete files or ask the server administrator to raise the limit."
            ),
            entity_type="organization", entity_id=str(organization_id),
        )
        sent += 1 if created is not None else 0
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="storage_limit_near", actor_id=None,
        organization_id=organization_id,
        detail={"used_bytes": used + incoming_bytes, "quota_bytes": quota.bytes, "recipient_count": sent},
    )
