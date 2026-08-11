"""
Module: services.bundle_common

Shared helpers for the portable export/import bundle formats (project
bundles: `services.project_export`; organisation bundles:
`services.org_export`). A bundle references users by email (never by id,
which isn't portable across a different organisation/deployment) and
embeds file attachments by their original filename under a synthetic ref —
both concerns are the same regardless of which bundle kind is being built
or read, so they live here rather than being duplicated per bundle type.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.user import User
from app.services.files import upload_file


class BundleImportWarnings:
    """Accumulates human-readable warnings during a bundle import — e.g. a
    user reference that didn't match anyone in the target deployment and
    was remapped to whoever performed the import. Surfaced to the caller so
    data loss during import is visible, never silent (same principle as
    `RequirementImportResult.errors` for CSV import)."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def add(self, message: str) -> None:
        self.messages.append(message)


class UserResolver:
    """Resolves the `*_email` references inside a bundle back to real
    `User` ids in the target deployment, caching lookups within one import.

    A `User` is global (one row can hold roles in many organisations, see
    `models.user.User.email`'s uniqueness), so "does this email exist here"
    is a single deployment-wide lookup, independent of which org/project is
    being imported into.
    """

    def __init__(self, db: Session, importing_user: User, warnings: BundleImportWarnings) -> None:
        self._db = db
        self._importing_user = importing_user
        self._warnings = warnings
        self._cache: dict[str, UUID | None] = {}

    def _lookup(self, email: str) -> UUID | None:
        normalized = email.strip().lower()
        if not normalized:
            return None
        if normalized not in self._cache:
            user = self._db.scalar(select(User).where(User.email == normalized))
            self._cache[normalized] = user.id if user else None
        return self._cache[normalized]

    def resolve(self, email: str | None, *, required: bool, context: str) -> UUID | None:
        """Resolves an email to a user id.

        Args:
            email: The bundle's recorded email, or None/blank if the
                original field was itself null.
            required: Whether the target column is NOT NULL. A required
                reference that can't be matched falls back to the user
                performing the import (recorded as a warning); an optional
                one is simply left null.
            context: Short human-readable description of what this
                reference is for, used only in the warning message.

        Returns:
            A matched (or fallback) user id, or None for an unmatched
            optional reference.
        """
        if not email:
            return self._importing_user.id if required else None
        user_id = self._lookup(email)
        if user_id is not None:
            return user_id
        if required:
            self._warnings.add(f"{context}: no user found for '{email}' — attributed to the importing user instead.")
            return self._importing_user.id
        self._warnings.add(f"{context}: no user found for '{email}' — left unset.")
        return None


def import_bundled_file(
    db: Session, *, organization_id: UUID, uploaded_by: UUID,
    filename: str, content_type: str, data: bytes,
) -> FileAsset:
    """Re-uploads a file embedded in a bundle as a new `FileAsset` owned by
    the target organisation — storage keys aren't portable across
    deployments/backends, so every attachment gets a fresh key via the
    normal upload path rather than trying to preserve the original one."""
    return upload_file(
        db, organization_id=organization_id, uploaded_by=uploaded_by,
        filename=filename, content_type=content_type, data=data,
    )
