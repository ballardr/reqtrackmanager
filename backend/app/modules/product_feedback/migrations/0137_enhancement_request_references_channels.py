"""Enhancement request external references and channel per ask

Revision ID: 0137
Revises: 0136
Create Date: 2026-11-05

Adds the two organisation/project vocabularies a request's references and requesters are classified by
(`external_system_definitions` / `project_external_systems`, `request_channel_definitions` /
`project_request_channels`), the many-per-request `enhancement_request_external_refs` table and the per-requester
`enhancement_request_requester_channel` table. Every existing organisation is given the default systems and channels.

The one delivery-tool link a request version used to carry (`external_ref_url` / `external_ref_key`) becomes a
`delivery` reference on the "Other" system, taken from the request's current version, and the two columns are
dropped (the references are not versioned with the request).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0137"
down_revision: str | None = "0136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SYSTEMS = ("Jira", "ServiceNow", "Zendesk", "Azure DevOps", "GitHub", "Other")
_CHANNELS = (
    "Engagement", "Support ticket", "Call", "Chat", "Conversation", "Email", "Survey", "Internal", "Other",
)


def _vocabulary(org_table: str, project_table: str) -> None:
    """Creates one organisation list and its project-side table."""
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {org_table} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_{org_table}_org_name UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {project_table} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            org_type_id UUID REFERENCES {org_table}(id) ON DELETE SET NULL,
            name_override VARCHAR(100),
            display_order_override INTEGER,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            CONSTRAINT uq_{project_table}_project_org_type UNIQUE (project_id, org_type_id),
            CONSTRAINT ck_{project_table}_local_has_name CHECK (org_type_id IS NOT NULL OR name_override IS NOT NULL)
        )
        """
    )


def _seed(org_table: str, names: tuple[str, ...]) -> None:
    """Gives every existing organisation the default names."""
    for order, name in enumerate(names):
        op.execute(
            f"INSERT INTO {org_table} (organization_id, name, sort_order) "
            f"SELECT id, '{name}', {order} FROM organizations ON CONFLICT (organization_id, name) DO NOTHING"
        )


def upgrade() -> None:
    _vocabulary("external_system_definitions", "project_external_systems")
    _vocabulary("request_channel_definitions", "project_request_channels")
    _seed("external_system_definitions", _SYSTEMS)
    _seed("request_channel_definitions", _CHANNELS)
    op.execute(
        """
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
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_external_refs_request "
        "ON enhancement_request_external_refs (request_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_external_refs_org_system_id "
        "ON enhancement_request_external_refs (org_system_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_external_refs_project_system_id "
        "ON enhancement_request_external_refs (project_system_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enhancement_request_requester_channel (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            request_id UUID NOT NULL REFERENCES enhancement_requests(id) ON DELETE CASCADE,
            party_type VARCHAR(64) NOT NULL,
            party_id UUID NOT NULL,
            channel_id UUID NOT NULL REFERENCES project_request_channels(id) ON DELETE CASCADE,
            set_by UUID NOT NULL REFERENCES users(id),
            CONSTRAINT uq_enhancement_request_requester_channel_party UNIQUE (request_id, party_type, party_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_requester_channel_request_id "
        "ON enhancement_request_requester_channel (request_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enhancement_request_requester_channel_channel_id "
        "ON enhancement_request_requester_channel (channel_id)"
    )
    # The old single link becomes a delivery reference on "Other" (the project's row for it, for a project request).
    columns = op.get_bind().exec_driver_sql(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'enhancement_request_versions' "
        "AND column_name IN ('external_ref_url', 'external_ref_key')"
    ).fetchall()
    if len(columns) == 2:
        source = (
            "FROM enhancement_request_versions v JOIN enhancement_requests r ON r.id = v.request_id "
            "LEFT JOIN projects p ON p.id = r.project_id "
            "JOIN external_system_definitions s ON s.name = 'Other' "
            "AND s.organization_id = COALESCE(r.organization_id, p.organization_id) "
        )
        current = "v.valid_to IS NULL AND (v.external_ref_url IS NOT NULL OR v.external_ref_key IS NOT NULL)"
        op.execute(
            "INSERT INTO project_external_systems (project_id, org_type_id) "
            f"SELECT DISTINCT r.project_id, s.id {source} WHERE {current} AND r.project_id IS NOT NULL "
            "ON CONFLICT (project_id, org_type_id) DO NOTHING"
        )
        op.execute(
            "INSERT INTO enhancement_request_external_refs "
            "(request_id, org_system_id, project_system_id, key, url, role, created_by) "
            "SELECT r.id, CASE WHEN r.project_id IS NULL THEN s.id END, ps.id, COALESCE(v.external_ref_key, ''), "
            f"v.external_ref_url, 'delivery', v.created_by {source} "
            "LEFT JOIN project_external_systems ps ON ps.project_id = r.project_id AND ps.org_type_id = s.id "
            f"WHERE {current}"
        )
        op.execute("ALTER TABLE enhancement_request_versions DROP COLUMN external_ref_url")
        op.execute("ALTER TABLE enhancement_request_versions DROP COLUMN external_ref_key")


def downgrade() -> None:
    # Lossy: only the first delivery reference of each request returns to the version columns.
    op.execute("ALTER TABLE enhancement_request_versions ADD COLUMN IF NOT EXISTS external_ref_url VARCHAR(500)")
    op.execute("ALTER TABLE enhancement_request_versions ADD COLUMN IF NOT EXISTS external_ref_key VARCHAR(100)")
    op.execute(
        "UPDATE enhancement_request_versions v SET external_ref_url = x.url, external_ref_key = NULLIF(x.key, '') "
        "FROM (SELECT DISTINCT ON (request_id) request_id, url, key FROM enhancement_request_external_refs "
        "WHERE role = 'delivery' ORDER BY request_id, created_at) x "
        "WHERE x.request_id = v.request_id AND v.valid_to IS NULL"
    )
    op.execute("DROP TABLE IF EXISTS enhancement_request_requester_channel")
    op.execute("DROP TABLE IF EXISTS enhancement_request_external_refs")
    op.execute("DROP TABLE IF EXISTS project_request_channels")
    op.execute("DROP TABLE IF EXISTS request_channel_definitions")
    op.execute("DROP TABLE IF EXISTS project_external_systems")
    op.execute("DROP TABLE IF EXISTS external_system_definitions")
