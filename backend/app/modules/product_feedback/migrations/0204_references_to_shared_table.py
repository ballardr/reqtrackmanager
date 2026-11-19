"""Move Product Feedback's external references onto the shared `external_references` table.

Revision ID: 0204
Revises: 0203
Create Date: 2026-11-19

Every row of `enhancement_request_external_refs` becomes an `external_references` row for the
`enhancement_request` type with the same id, system, key, link, role, author and times (the owner columns come from
the request), and the old table is dropped. The systems tables are shared already and are not touched. The downgrade
recreates the old table and copies the Product Feedback rows back (a missing role reads as `delivery`).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0204"
down_revision: str | None = "0203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO external_references (
            id, created_at, updated_at, artefact_type, artefact_id, organization_id, project_id, org_system_id,
            project_system_id, key, url, note, role, created_by
        )
        SELECT r.id, r.created_at, r.updated_at, 'enhancement_request', r.request_id,
               COALESCE(p.organization_id, q.organization_id), q.project_id, r.org_system_id, r.project_system_id,
               r.key, r.url, '', r.role, r.created_by
        FROM enhancement_request_external_refs r
        JOIN enhancement_requests q ON q.id = r.request_id
        LEFT JOIN projects p ON p.id = q.project_id
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("DROP TABLE IF EXISTS enhancement_request_external_refs")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS enhancement_request_external_refs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            request_id UUID NOT NULL REFERENCES enhancement_requests(id) ON DELETE CASCADE,
            org_system_id UUID REFERENCES external_system_definitions(id) ON DELETE CASCADE,
            project_system_id UUID REFERENCES project_external_systems(id) ON DELETE CASCADE,
            key VARCHAR(100) NOT NULL DEFAULT '',
            url VARCHAR(500),
            role VARCHAR(20) NOT NULL DEFAULT 'delivery',
            created_by UUID NOT NULL REFERENCES users(id),
            CONSTRAINT ck_enhancement_request_external_refs_one_system
                CHECK ((org_system_id IS NOT NULL) <> (project_system_id IS NOT NULL))
        )
    """)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_external_refs_request ON enhancement_request_external_refs (request_id)",
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_external_refs_org_system_id ON enhancement_request_external_refs (org_system_id)",
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_external_refs_project_system_id ON enhancement_request_external_refs (project_system_id)",
    ):
        op.execute(statement)
    op.execute("""
        INSERT INTO enhancement_request_external_refs (
            id, created_at, updated_at, request_id, org_system_id, project_system_id, key, url, role, created_by
        )
        SELECT e.id, e.created_at, e.updated_at, e.artefact_id, e.org_system_id, e.project_system_id, e.key, e.url,
               COALESCE(e.role, 'delivery'), e.created_by
        FROM external_references e
        JOIN enhancement_requests q ON q.id = e.artefact_id
        WHERE e.artefact_type = 'enhancement_request'
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("DELETE FROM external_references WHERE artefact_type = 'enhancement_request'")
