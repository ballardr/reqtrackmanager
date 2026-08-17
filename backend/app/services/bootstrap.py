"""
Module: services.bootstrap

Creates the deployment-config server admin user on first startup (I-M-05,
I-M-06) and, if configured, an initial organisation with that user as
organisation admin (I-M-08). This runs once at application startup; it is
idempotent so repeated container restarts do not duplicate data.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OrgRole
from app.models.organization import Organization, UserOrgRole
from app.models.user import User
from app.security import hash_password
from app.services.definitions import seed_link_types, seed_project_statuses

settings = get_settings()


def run_bootstrap(db: Session) -> None:
    """Ensures the server admin user (and optional default org) exist.

    Args:
        db: An active database session. Commits its own transaction.
    """
    if not settings.server_admin_enabled:
        return

    admin = db.scalar(select(User).where(User.email == settings.server_admin_email.lower()))
    if admin is None:
        admin = User(
            email=settings.server_admin_email.lower(),
            display_name="Server Administrator",
            password_hash=hash_password(settings.server_admin_password),
            auth_backend="native",
            is_server_admin=True,
        )
        db.add(admin)
        db.flush()

    if settings.server_admin_create_org:
        has_org_role = db.scalar(select(UserOrgRole).where(UserOrgRole.user_id == admin.id)) is not None
        if not has_org_role:
            org = Organization(name="Default Organization")
            db.add(org)
            db.flush()
            seed_project_statuses(db, org.id)
            seed_link_types(db, org.id)
            db.add(UserOrgRole(user_id=admin.id, organization_id=org.id, role=OrgRole.ORG_ADMIN))

    db.commit()
