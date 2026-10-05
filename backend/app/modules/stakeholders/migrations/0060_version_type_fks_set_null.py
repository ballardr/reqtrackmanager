"""Let persona/stakeholder type references cascade away with their org/project (Module 2 Phase 1.2)

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-05

`persona_versions.org_type_id`/`project_type_id` were plain foreign keys into the
org and project type tables. Both type tables cascade-delete with their
organisation/project, in the same cascade that removes the personas and their
versions, so deleting an organisation (or a project) that had a typed persona
failed with a foreign-key violation (HTTP 500) depending on the order Postgres
ran the cascades in. They become `ON DELETE SET NULL`. `stakeholder_versions`
gets the same treatment (0059 creates it that way; re-applying here is
idempotent and also repairs a database that ran an earlier draft of 0059). A type that is still in use is protected by the service
layer (`TypeVocabulary.delete_org_type`/`delete_project_type`), not by these
constraints, so deleting a type through the API behaves exactly as before.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FKS = (
    ("persona_versions", "persona_versions_org_type_id_fkey", "org_type_id", "persona_type_definitions"),
    ("persona_versions", "persona_versions_project_type_id_fkey", "project_type_id", "project_persona_types"),
    ("stakeholder_versions", "stakeholder_versions_org_type_id_fkey", "org_type_id", "stakeholder_type_definitions"),
    ("stakeholder_versions", "stakeholder_versions_project_type_id_fkey", "project_type_id", "project_stakeholder_types"),
)


def _recreate(on_delete: str) -> None:
    for table, name, column, target in _FKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {target}(id){on_delete}"
        )


def upgrade() -> None:
    _recreate(" ON DELETE SET NULL")


def downgrade() -> None:
    _recreate("")
