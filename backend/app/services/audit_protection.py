"""
Module: services.audit_protection

Makes the audit trail append-only for the role the application connects as (system operations policy, audit row
protection).

Responsibilities:
- At start-up, with the owner connection that also runs the migrations, revoke every privilege the runtime role holds on
  `audit_events` and `login_events` and grant back only what the application needs: SELECT and INSERT, plus UPDATE of
  the one column that is filled in afterwards (`login_events.location`, resolved from the address in the background).
- Say plainly in the log when the protection cannot work: the role is not configured, does not exist, or is the owner.

Design decisions:
- Two database roles, not a trigger: a trigger can be dropped by the role that owns the table, a revoke from a role
  that does not own it cannot be undone by that role. Foreign-key actions (`ON DELETE SET NULL` when a project or an
  organisation is deleted) run as the table owner, so they keep working.
- Idempotent and cheap: it runs at every start, so a restored database or a new table grant converges.

External dependencies: PostgreSQL roles and privileges; `app.config` (`audit_runtime_role`, `database_migration_url`).
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)

AUDIT_TABLES = ("audit_events", "login_events")
_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def apply_audit_protection() -> str:
    """Revokes the runtime role's write access to the audit tables, using the owner connection.

    Returns:
        `disabled` (no role configured), `role_missing`, `owner` (the role owns the tables, so nothing was changed),
        or `applied`.
    """
    settings = get_settings()
    role = settings.audit_runtime_role.strip()
    if not role:
        return "disabled"
    if not _ROLE_NAME.match(role):
        logger.error("AUDIT_RUNTIME_ROLE is not a plain lower-case role name; the audit tables were not protected.")
        return "role_missing"
    owner_engine = create_engine(settings.database_migration_url or settings.database_url)
    try:
        with owner_engine.begin() as conn:
            if not conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}):
                logger.error("AUDIT_RUNTIME_ROLE names a role that does not exist; the audit tables were not protected.")
                return "role_missing"
            owners = set(conn.scalars(text("SELECT tableowner FROM pg_tables WHERE tablename = ANY(:t)"), {"t": list(AUDIT_TABLES)}))
            if role in owners:
                logger.error("The application role owns the audit tables, so it can change them: use a separate owner role.")
                return "owner"
            quoted = conn.dialect.identifier_preparer.quote(role)
            for table in AUDIT_TABLES:
                # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                # DDL cannot take bind parameters; the role matched a strict name pattern and is quoted by the dialect.
                conn.execute(text(f"REVOKE ALL ON TABLE {table} FROM {quoted}"))
                # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                conn.execute(text(f"GRANT SELECT, INSERT ON TABLE {table} TO {quoted}"))
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            conn.execute(text(f"GRANT UPDATE (location) ON TABLE login_events TO {quoted}"))
    finally:
        owner_engine.dispose()
    return "applied"
