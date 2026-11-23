"""Link/action-removal change requests

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-14

Gates removing an action from a locked requirement behind a change request, as adding one is since 0013
(`unlink_action` had no lock check). Also adds an opt-in gate for `RequirementLink`: a project (or an
org-wide force, with a per-project exemption) can require that adding or removing a traceability link on
an approved requirement goes through a change request.

Three `ChangeRequestKind` values (`remove_action`, `add_link`, `remove_link`; a plain VARCHAR `str_enum`
column needs no migration for the value, as in 0012/0013) plus:

- `change_request_versions`: nullable `proposed_link_target_requirement_id` and `proposed_link_type_id`
  (ADD_LINK) and `proposed_link_id` (REMOVE_LINK: the `RequirementLink` to remove on approval).
  REMOVE_ACTION reuses `proposed_action_link_id` (0013); the two kinds never share a version row.
- `projects`: boolean `require_change_request_for_approved_links` (per-project gate) and
  `exempt_from_org_link_lock` (exemption from the org-wide force), both default false.
- `organizations`: boolean `force_require_change_request_for_approved_links` (org-wide force), default false.

New columns are nullable or default false (matching `Project.allow_member_change_requests`), so existing
rows need no backfill.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # change_request_versions: ADD_LINK/REMOVE_LINK payload columns.
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_link_target_requirement_id UUID"
    )
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS "
        "change_request_versions_proposed_link_target_requirement_id_fkey"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD CONSTRAINT "
        "change_request_versions_proposed_link_target_requirement_id_fkey "
        "FOREIGN KEY (proposed_link_target_requirement_id) REFERENCES requirements(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_link_type_id UUID"
    )
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_link_type_id_fkey"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD CONSTRAINT change_request_versions_proposed_link_type_id_fkey "
        "FOREIGN KEY (proposed_link_type_id) REFERENCES requirement_link_type_definitions(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD COLUMN IF NOT EXISTS proposed_link_id UUID"
    )
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_link_id_fkey"
    )
    op.execute(
        "ALTER TABLE change_request_versions ADD CONSTRAINT change_request_versions_proposed_link_id_fkey "
        "FOREIGN KEY (proposed_link_id) REFERENCES requirement_links(id) ON DELETE SET NULL"
    )

    # projects: per-project opt-in + org-force exemption.
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS require_change_request_for_approved_links "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS exempt_from_org_link_lock BOOLEAN NOT NULL DEFAULT false"
    )

    # organizations: org-wide force.
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS force_require_change_request_for_approved_links "
        "BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS force_require_change_request_for_approved_links")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS exempt_from_org_link_lock")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS require_change_request_for_approved_links")
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_link_id_fkey"
    )
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_link_id")
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS change_request_versions_proposed_link_type_id_fkey"
    )
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_link_type_id")
    op.execute(
        "ALTER TABLE change_request_versions DROP CONSTRAINT IF EXISTS "
        "change_request_versions_proposed_link_target_requirement_id_fkey"
    )
    op.execute("ALTER TABLE change_request_versions DROP COLUMN IF EXISTS proposed_link_target_requirement_id")
