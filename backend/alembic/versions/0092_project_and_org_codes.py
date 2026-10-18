"""Projects and organisations get short codes that qualify record codes

Revision ID: 0092
Revises: 0091
Create Date: 2026-10-18

Adds `projects.code` (unique per organisation), `organizations.code`, the organisation's
`project_code_policy` (JSONB) and `enforce_code_everywhere`. Existing organisations and
projects are backfilled from their name's initials under the default policy (alphanumeric,
2 to 6 characters), adding a numeric suffix on a collision; a project code never equals its
organisation's code. Existing codes are never rewritten afterwards. The derivation is a
frozen copy of `app.code_rules` so this migration keeps working if those rules change.
Guarded throughout: a database built from the current models already has the columns.
"""

import re
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0092"
down_revision: str | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIN, _MAX = 2, 6
_WORD = re.compile(r"[A-Za-z0-9]+")


def _candidates(name: str):
    """Initials of `name` (padded to the minimum, cut to the maximum), then suffixed variants."""
    words = [w.upper() for w in _WORD.findall(name)]
    base = "".join(w[0] for w in words)
    if len(base) < _MIN:
        base += "".join(c for w in words for c in w[1:])[: _MIN - len(base)]
    if len(base) < _MIN:
        base += "X" * (_MIN - len(base))
    base = base[:_MAX]
    yield base
    for n in range(2, 10_000):
        tail = str(n)
        yield base[: _MAX - len(tail)] + tail


def upgrade() -> None:
    conn = op.get_bind()
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS code VARCHAR(10)")
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS project_code_policy JSONB NOT NULL DEFAULT "
        "'{\"kind\": \"alphanumeric\", \"min_length\": 2, \"max_length\": 6, \"assignment\": \"auto\"}'::jsonb"
    )
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS enforce_code_everywhere BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS code VARCHAR(10)")

    for org_id, name in conn.execute(text("SELECT id, name FROM organizations WHERE code IS NULL")).all():
        conn.execute(text("UPDATE organizations SET code = :code WHERE id = :id"), {"code": next(_candidates(name)), "id": org_id})

    orgs = conn.execute(text("SELECT id, code FROM organizations")).all()
    for org_id, org_code in orgs:
        taken = {org_code}
        taken.update(
            code for (code,) in conn.execute(
                text("SELECT code FROM projects WHERE organization_id = :o AND code IS NOT NULL"), {"o": org_id}
            ).all()
        )
        rows = conn.execute(
            text("SELECT id, name FROM projects WHERE organization_id = :o AND code IS NULL ORDER BY created_at, id"),
            {"o": org_id},
        ).all()
        for project_id, name in rows:
            code = next(c for c in _candidates(name) if c not in taken)
            taken.add(code)
            conn.execute(text("UPDATE projects SET code = :code WHERE id = :id"), {"code": code, "id": project_id})

    op.execute("ALTER TABLE organizations ALTER COLUMN code SET NOT NULL")
    op.execute("ALTER TABLE projects ALTER COLUMN code SET NOT NULL")
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'projects_organization_id_code_key') THEN "
        "ALTER TABLE projects ADD CONSTRAINT projects_organization_id_code_key UNIQUE (organization_id, code); END IF; END $$"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_organization_id_code_key")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS code")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS enforce_code_everywhere")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS project_code_policy")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS code")
