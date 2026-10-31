"""One report look per organisation: report templates are folded into the organisation

Revision ID: 0121
Revises: 0120
Create Date: 2026-10-31

Adds the organisation's report look to `organizations` (`report_accent_color_hex`, `report_include_logo`,
`report_footer_text`, `report_include_cover_page`, `report_chapters_per_component`), fills it from the organisation's
default report template (else its only template; an organisation with neither keeps the plain look its reports have
always had), then drops `report_templates`, `report_layouts.report_template_id` and a pack's `template` name.

A custom layout used to be forced to print its template's footer text, logo and cover page. It now prints them only
where it reads them (`{{org.footer_text}}`, the `org_logo` image, `if org.include_cover_page`), so each existing
document layout whose effective template (its own, else the default) had any of them is saved as a new version that reads
them where the old output printed them. Every other layout is left as it is.

Extra templates (more than the one that became the look) are dropped; their number is logged. Guarded so a database built
from the current models, which has no `report_templates`, passes through.
"""

import copy
import hashlib
import json
import logging
import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0121"
down_revision: str | None = "0120"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

FOOTER_TEXT = "{{org.footer_text}}  ·  Page {{page}}"
LOGO_HEIGHT_CM = 0.9
COVER_LOGO_WIDTH_CM = 4
MIGRATION_COMMENT = "Reads the organisation's report settings"


def _tree_hash(tree: dict[str, Any]) -> str:
    """SHA-256 hex of the tree's canonical JSON, as `services.report_layout_tree.tree_hash` computes it."""
    return hashlib.sha256(json.dumps(tree, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _migrated_tree(tree: dict[str, Any], *, footer_text: bool, cover: bool, logo: bool) -> dict[str, Any] | None:
    """`tree` reading the organisation's values where the old output printed them, or `None` when nothing changes.

    Only a band the layout wrote nothing for is filled, as the old default was. A cover page is a block at the start
    of the layout, shown when the organisation wants one, with the logo and the title.
    """
    changed = copy.deepcopy(tree)
    touched = False
    first_page = "none" if cover else "same"
    if "footer" not in changed and (footer_text or cover):
        changed["footer"] = {"centre": FOOTER_TEXT if footer_text else "Page {{page}}", "first_page": first_page}
        touched = True
    if "header" not in changed and logo:
        changed["header"] = {"logo": {"file": "org_logo", "height": LOGO_HEIGHT_CM, "slot": "left"}, "first_page": first_page}
        touched = True
    if cover:
        children: list[dict[str, Any]] = []
        if logo:
            children.append({
                "type": "image", "file": "org_logo", "alt": "", "decorative": True,
                "width": COVER_LOGO_WIDTH_CM, "width_unit": "cm",
            })
        children += [{"type": "heading", "text": "{{report_title}}", "level": 1}, {"type": "page_break"}]
        changed["nodes"] = [
            {"type": "if", "when": {"ref": "org.include_cover_page", "op": "eq", "value": True}, "children": children},
            *changed.get("nodes", []),
        ]
        touched = True
    return changed if touched else None


def _migrate_layouts(conn: sa.Connection, templates: dict[Any, Any], defaults: dict[Any, Any], logos: set[Any]) -> int:
    """Saves a new version of each document layout whose old output printed template branding. Returns how many."""
    has_override = any(c["name"] == "report_template_id" for c in sa.inspect(conn).get_columns("report_layouts"))
    layouts = conn.execute(sa.text(
        f"SELECT l.id, l.organization_id, {'l.report_template_id' if has_override else 'NULL'}, l.current_version, v.tree "
        "FROM report_layouts l JOIN report_layout_versions v ON v.layout_id = l.id AND v.version = l.current_version "
        "WHERE l.family = 'document'"
    )).all()
    count = 0
    for layout_id, org_id, own_template_id, version, tree in layouts:
        template = templates.get(own_template_id) or defaults.get(org_id)
        if template is None or not isinstance(tree, dict):
            continue
        footer_text, cover, include_logo = bool(template["footer_text"]), bool(template["include_cover_page"]), bool(template["include_logo"])
        migrated = _migrated_tree(tree, footer_text=footer_text, cover=cover, logo=include_logo and org_id in logos)
        if migrated is None:
            continue
        conn.execute(sa.text(
            "INSERT INTO report_layout_versions (id, layout_id, version, schema_version, tree, tree_hash, comment, created_by, created_at) "
            "SELECT :id, :layout_id, :version, schema_version, CAST(:tree AS JSONB), :hash, :comment, NULL, now() "
            "FROM report_layout_versions WHERE layout_id = :layout_id AND version = :previous"
        ), {
            "id": uuid.uuid4(), "layout_id": layout_id, "version": version + 1, "previous": version,
            "tree": json.dumps(migrated, ensure_ascii=False), "hash": _tree_hash(migrated), "comment": MIGRATION_COMMENT,
        })
        conn.execute(sa.text("UPDATE report_layouts SET current_version = :version, updated_at = now() WHERE id = :id"), {"id": layout_id, "version": version + 1})
        count += 1
    return count


def _strip_pack_templates(conn: sa.Connection) -> int:
    """Removes the `template` name from every stored pack definition (and re-hashes it). Returns how many changed."""
    rows = conn.execute(sa.text("SELECT id, definition FROM report_pack_versions WHERE jsonb_exists(definition, 'template')")).all()
    for row_id, definition in rows:
        stripped = {k: v for k, v in definition.items() if k != "template"}
        conn.execute(
            sa.text("UPDATE report_pack_versions SET definition = CAST(:d AS JSONB), definition_hash = :h WHERE id = :id"),
            {"d": json.dumps(stripped, ensure_ascii=False), "h": _tree_hash(stripped), "id": row_id},
        )
    return len(rows)


def upgrade() -> None:
    conn = op.get_bind()
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS report_accent_color_hex VARCHAR(7)")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS report_include_logo BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS report_footer_text TEXT")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS report_include_cover_page BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS report_chapters_per_component BOOLEAN NOT NULL DEFAULT true")
    if _has_table("report_templates"):
        rows = conn.execute(sa.text(
            "SELECT id, organization_id, accent_color_hex, include_cover_page, include_logo, footer_text, chapters_per_component, "
            "is_default FROM report_templates ORDER BY organization_id, is_default DESC, created_at"
        )).mappings().all()
        templates = {r["id"]: dict(r) for r in rows}
        by_org: dict[Any, list[dict[str, Any]]] = {}
        for r in rows:
            by_org.setdefault(r["organization_id"], []).append(dict(r))
        defaults: dict[Any, Any] = {}  # the template an organisation's reports used when a run named none
        chosen: dict[Any, dict[str, Any]] = {}  # the template that becomes the organisation's look
        dropped = 0
        for org_id, items in by_org.items():
            default = next((t for t in items if t["is_default"]), None)
            if default is not None:
                defaults[org_id] = default
            look = default or (items[0] if len(items) == 1 else None)
            if look is not None:
                chosen[org_id] = look
            dropped += len(items) - (1 if look is not None else 0)
        # An organisation with no template used no branding: its look stays plain (no logo, no cover, no footer).
        conn.execute(sa.text("UPDATE organizations SET report_include_logo = false"))
        for org_id, t in chosen.items():
            conn.execute(sa.text(
                "UPDATE organizations SET report_accent_color_hex = :accent, report_include_cover_page = :cover, "
                "report_include_logo = :logo, report_footer_text = :footer, report_chapters_per_component = :chapters WHERE id = :id"
            ), {
                "accent": t["accent_color_hex"], "cover": t["include_cover_page"], "logo": t["include_logo"],
                "footer": t["footer_text"], "chapters": t["chapters_per_component"], "id": org_id,
            })
        logos = {r[0] for r in conn.execute(sa.text("SELECT id FROM organizations WHERE logo_file_id IS NOT NULL"))}
        rewritten = _migrate_layouts(conn, templates, defaults, logos)
        log.info("Report look: %d layout(s) now read the organisation's settings; %d extra template(s) dropped.", rewritten, dropped)
    if _has_table("report_pack_versions"):
        log.info("Report look: %d pack definition(s) lost their template name.", _strip_pack_templates(conn))
    op.execute("ALTER TABLE report_layouts DROP COLUMN IF EXISTS report_template_id")
    op.execute("DROP TABLE IF EXISTS report_templates")


def downgrade() -> None:
    """Restores the empty structures and one default template from the organisation's look (layout versions stay)."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_templates (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            accent_color_hex VARCHAR(7) NOT NULL DEFAULT '#475569',
            include_cover_page BOOLEAN NOT NULL DEFAULT true,
            include_logo BOOLEAN NOT NULL DEFAULT true,
            footer_text TEXT,
            chapters_per_component BOOLEAN NOT NULL DEFAULT true,
            is_default BOOLEAN NOT NULL DEFAULT false,
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_report_templates_organization_id_name UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_templates_one_default ON report_templates (organization_id) WHERE is_default"
    )
    op.execute(
        "ALTER TABLE report_layouts ADD COLUMN IF NOT EXISTS report_template_id UUID "
        "CONSTRAINT fk_report_layouts_report_template_id REFERENCES report_templates(id) ON DELETE SET NULL"
    )
    op.execute(
        """
        INSERT INTO report_templates (id, organization_id, name, accent_color_hex, include_cover_page, include_logo, footer_text,
                                      chapters_per_component, is_default, created_by)
        SELECT gen_random_uuid(), o.id, 'Default', COALESCE(o.report_accent_color_hex, '#475569'), o.report_include_cover_page,
               o.report_include_logo, o.report_footer_text, o.report_chapters_per_component, true,
               (SELECT r.user_id FROM user_org_roles r WHERE r.organization_id = o.id ORDER BY r.created_at LIMIT 1)
        FROM organizations o
        WHERE EXISTS (SELECT 1 FROM user_org_roles r WHERE r.organization_id = o.id)
        """
    )
    for column in (
        "report_chapters_per_component", "report_include_cover_page", "report_footer_text", "report_include_logo",
        "report_accent_color_hex",
    ):
        op.execute(f"ALTER TABLE organizations DROP COLUMN IF EXISTS {column}")
