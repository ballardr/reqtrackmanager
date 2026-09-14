"""Link/action-removal change requests (Platform review 2026-09, Phase 8)

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-14

Closes an asymmetry `unlink_action` had ever since ADD_ACTION (0013): adding
an action to a locked requirement already required a change request, but
removing one didn't — `unlink_action` had no lock check at all. Also adds an
opt-in sibling for `RequirementLink`: a project (or an org-wide force, minus
a per-project exemption) can now require that adding/removing a
traceability link on an already-approved requirement go through a change
request too, mirroring the same mechanism rather than inventing a new one.

Three new `ChangeRequestKind` values (`remove_action`, `add_link`,
`remove_link` — plain VARCHAR `str_enum` column, no migration needed for the
enum value itself, same reasoning as 0012/0013's own notes) plus:

- Three new nullable columns on `change_request_versions`:
  `proposed_link_target_requirement_id` + `proposed_link_type_id`
  (ADD_LINK-only — the target and org link type to link to) and
  `proposed_link_id` (REMOVE_LINK-only — the existing `RequirementLink` row
  to remove on approval). `REMOVE_ACTION` reuses the existing
  `proposed_action_link_id` column (0013) rather than adding a duplicate —
  the two kinds never coexist on one version row.
- Two new boolean columns on `projects`:
  `require_change_request_for_approved_links` (opt-in per-project gate,
  default false) and `exempt_from_org_link_lock` (escape hatch from the
  org-wide force below, default false).
- One new boolean column on `organizations`:
  `force_require_change_request_for_approved_links` (org-wide force,
  default false, overridden per-project by `exempt_from_org_link_lock`).

All-nullable/defaulted additive columns, so every existing row is
unaffected — `NULL`/`false` on backfill is correct (an existing
`change_request_versions` row of a different kind has nothing to do with
links; an existing project/org has this feature off by default, matching
`Project.allow_member_change_requests`'s own permissive-default precedent).
No backfill needed.
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
