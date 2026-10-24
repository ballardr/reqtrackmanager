"""
Module: services.bundle_links

Shared export/import of the `ArtefactLink` rows between a module's own records
(and Requirements) for a project bundle, so each module's bundle hooks do not
re-implement it.

Responsibilities:
- `export_artefact_links`: same-project links whose two ends are both known to
  the caller (its own records, by bundle ref) or are Requirements (by code).
- `import_artefact_links`: recreates them against the new records, skipping with
  a warning anything that no longer resolves.

Design decisions (Decided by: Agent):
- Ends are portable `(type, ref)` pairs, never ids. A module chooses its refs;
  a Requirement's ref is its unique code, which the core import keeps.
- A link to a record the caller does not own (another module's record, an
  organisation-level record, another project's record) is not exported: those
  records are not in this bundle, and an import must never reference one.
- Requirement-to-Requirement links stay with the core sections.
- Link types travel by name. On import a project-visible type of that name is
  used, else the organisation's is created from the registered seed
  (`services.link_types.ensure_org_link_type`).
- Links are replayed with `enforce_rules=False`: they were valid when created.

Dependencies: `app.services.relationships`, `app.services.link_types`,
`app.services.link_type_scope`, `app.services.bundle_common`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.services.bundle_common import BundleImportWarnings, UserResolver
from app.services.link_type_scope import resolve_link_type_scope
from app.services.link_types import ensure_org_link_type
from app.services.relationships import create_link

REQUIREMENT_END = "requirement"


def export_artefact_links(
    db: Session, project: Project, refs: Mapping[str, Mapping[uuid.UUID, str]],
) -> list[dict[str, Any]]:
    """The project's same-project links between the given records and Requirements.

    Args:
        db: Active session (read only).
        project: The project being exported.
        refs: `{artefact type: {record id: bundle ref}}` for the records the caller exports.

    Returns:
        One entry per link: `source` and `target` as `{"type", "ref"}`, the link type's
        `forward_name`/`reverse_name` (or `None` for an untyped link) and `created_by_email`.
        A link with a Requirement on both ends, or an end outside `refs` and the project's
        Requirements, is left out.
    """
    clauses = []
    for artefact_type, by_id in refs.items():
        if not by_id:
            continue
        ids = list(by_id)
        clauses.append((ArtefactLink.source_type == artefact_type) & (ArtefactLink.source_id.in_(ids)))
        clauses.append((ArtefactLink.target_type == artefact_type) & (ArtefactLink.target_id.in_(ids)))
    if not clauses:
        return []
    requirement_codes = {
        r.id: r.unique_code for r in db.scalars(select(Requirement).where(Requirement.project_id == project.id))
    }
    links = db.scalars(
        select(ArtefactLink).where(or_(*clauses), ArtefactLink.source_project_id.is_(None)).order_by(ArtefactLink.created_at)
    ).all()
    link_types = {
        t.id: t for t in db.scalars(
            select(RequirementLinkTypeDefinition).where(
                RequirementLinkTypeDefinition.id.in_({lk.link_type_id for lk in links if lk.link_type_id})
            )
        )
    } if links else {}
    emails = {
        u.id: u.email for u in db.scalars(select(User).where(User.id.in_({lk.created_by for lk in links if lk.created_by})))
    } if links else {}

    def end(artefact_type: str, artefact_id: uuid.UUID) -> dict[str, str] | None:
        if artefact_type == REQUIREMENT_END:
            code = requirement_codes.get(artefact_id)
            return {"type": artefact_type, "ref": code} if code else None
        ref = refs.get(artefact_type, {}).get(artefact_id)
        return {"type": artefact_type, "ref": ref} if ref else None

    out: list[dict[str, Any]] = []
    for link in links:
        if link.source_type == REQUIREMENT_END and link.target_type == REQUIREMENT_END:
            continue
        source, target = end(link.source_type, link.source_id), end(link.target_type, link.target_id)
        if source is None or target is None:
            continue
        link_type = link_types.get(link.link_type_id) if link.link_type_id else None
        out.append({
            "source": source, "target": target,
            "forward_name": link_type.forward_name if link_type else None,
            "reverse_name": link_type.reverse_name if link_type else None,
            "created_by_email": emails.get(link.created_by),
        })
    return out


def import_artefact_links(
    db: Session, project: Project, entries: list[dict[str, Any]], refs: Mapping[str, Mapping[str, uuid.UUID]],
    current_user: User, users: UserResolver, warnings: BundleImportWarnings, *, context: str,
) -> None:
    """Recreates exported links against the new records.

    Args:
        db: Active session; rows are flushed, not committed.
        project: The importing project.
        entries: `export_artefact_links` output.
        refs: `{artefact type: {bundle ref: new record id}}` for the records just created.
        current_user: The importing user (creator when the original cannot be matched).
        users: The import's user resolver.
        warnings: Collects each link that could not be recreated.
        context: Prefix for warnings (the module's name).
    """
    requirement_ids = {
        r.unique_code: r.id for r in db.scalars(select(Requirement).where(Requirement.project_id == project.id))
    }
    visible_types = {s.link_type.forward_name: s.link_type.id for s in resolve_link_type_scope(db, project) if s.shadowed_by is None}

    def resolve(end: dict[str, str]) -> uuid.UUID | None:
        if end["type"] == REQUIREMENT_END:
            return requirement_ids.get(end["ref"])
        return refs.get(end["type"], {}).get(end["ref"])

    for entry in entries:
        source_id, target_id = resolve(entry["source"]), resolve(entry["target"])
        if source_id is None or target_id is None:
            warnings.add(
                f"{context}: link {entry['source']['ref']} -> {entry['target']['ref']} skipped — "
                "one end is not in this project."
            )
            continue
        link_type_id = None
        if entry.get("forward_name"):
            link_type_id = visible_types.get(entry["forward_name"])
            if link_type_id is None:
                link_type_id = ensure_org_link_type(
                    db, project.organization_id, entry["forward_name"], entry.get("reverse_name")
                ).id
        creator = users.resolve(entry.get("created_by_email"), required=False, context=f"{context} link creator")
        try:
            with db.begin_nested():
                create_link(
                    db, source_type=entry["source"]["type"], source_id=source_id,
                    target_type=entry["target"]["type"], target_id=target_id, link_type_id=link_type_id,
                    created_by=creator or current_user.id, project_id=project.id,
                    enforce_rules=False,  # replaying existing data
                )
        except IntegrityError:
            continue  # the same link was already recreated by another section
    db.flush()
