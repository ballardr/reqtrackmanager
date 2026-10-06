"""
Module: services.relationships

Module 0 (Platform Foundations), Phase 1: generic CRUD/query helpers over
the polymorphic `ArtefactLink` table (`models.relationship`) — one query
surface for "what does X link to" / "what links to X" across every
registered artefact type, replacing the old requirement-only
`RequirementLink` queries and the old action-only `RequirementActionLink`
queries with a single generic implementation.

**Deliberately does not perform any authorization or tenant-scoping check.**
This module has no way to know how to resolve an arbitrary
`(artefact_type, artefact_id)` pair into its owning project/organisation —
that mapping is owned by each artefact type's own router (e.g.
`routers.requirements._get_requirement_in_project` resolves a `Requirement`
id and 404s on cross-project access). Every caller of `create_link` must
have already independently resolved and authorized *both* the source and
target artefact before calling this module — see `routers.requirements`'s
`create_link`/`list_links`/`delete_link`/`link_action`/`unlink_action` for
the established pattern this module's callers must keep following. This
module's own responsibility ends at "store/query this relationship row
generically"; it is not a second place tenant isolation is enforced.

`source_type`/`target_type` are plain strings, not the closed
`app.models.enums.ArtefactType` enum (Module 0 Phase 3 revised the
original Phase 1 design, under which a module extended that enum directly
— a fixed Python `enum.Enum` can't gain members at runtime, so that still
meant a core file being hand-edited per module). `create_link` validates
both against `app.modules.registry.get_all_registered_artefact_types` —
the two built-in core values (`ArtefactType.REQUIREMENT`/
`REQUIREMENT_ACTION`, themselves plain strings since `ArtefactType`
subclasses `str`) plus every registered module's own declared
`ModuleDefinition.artefact_types` — so a typo or an unregistered value
fails fast here rather than surfacing later as a silent, unqueryable row.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.relationship import ArtefactLink


def create_link(
    db: Session,
    *,
    source_type: str,
    source_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    link_type_id: uuid.UUID | None,
    created_by: uuid.UUID,
    enforce_rules: bool = True,
    project_id: uuid.UUID | None = None,
    enforce_offered: bool = False,
) -> ArtefactLink:
    """Creates and flushes a new `ArtefactLink` row. Does not commit — the
    caller commits once, alongside its own audit-log write, matching every
    other service function in this codebase's transaction convention.

    A typed link is checked against the link type's own source/target
    restriction and both ends' artefact-type rules
    (`services.link_types.validate_link_allowed`), so every creator, legacy
    typed endpoints and MCP included, goes through one check. `enforce_rules`
    is false only for a fixed-semantic action (a "Supersedes" link that flips a
    status) and for replaying already-validated data (project import,
    approving a change request that was validated when proposed).

    `project_id` is the project the link is created in: with it the link type must
    also be usable there (organisation-wide, or local to that project or an
    ancestor, and not locked out; `services.link_type_scope.assert_link_type_usable`)
    and project/ancestor artefact-type rules apply. Every creator that knows its
    project passes it; omitting it checks the organisation-level rules only.
    `enforce_offered` additionally rejects a type the project hides, for creators
    where a user picked the type (fixed-semantic actions leave it false).

    Raises:
        ValueError: if `source_type`/`target_type` isn't a currently
            registered artefact type (see this module's own docstring) —
            almost always a caller-side typo or a value from a module that
            forgot to declare it on its own `ModuleDefinition.
            artefact_types`, not something an end user's request can
            trigger (both are always internal literals, never taken
            directly from request input).
        sqlalchemy.exc.IntegrityError: if this exact link already exists —
            either the typed 5-column unique constraint or the untyped
            partial unique index on `ArtefactLink` will reject a duplicate;
            callers that want a clean 400 instead of a raw DB error should
            check for an existing row first (see
            `routers.requirements.link_action`'s pre-check for the
            established pattern).
        services.link_types.LinkRuleError: (a `ValueError`) if a link type
            restriction or artefact-type rule forbids this pair.
    """
    from app.modules.registry import get_all_registered_artefact_types

    valid_types = get_all_registered_artefact_types()
    for label, value in (("source_type", source_type), ("target_type", target_type)):
        if value not in valid_types:
            raise ValueError(f"{label} {value!r} is not a registered artefact type.")
    if enforce_rules and link_type_id is not None:
        from app.models.requirement_link_type import RequirementLinkTypeDefinition
        from app.services.link_types import validate_link_allowed

        link_type = db.get(RequirementLinkTypeDefinition, link_type_id)
        if link_type is not None:
            validate_link_allowed(
                db, link_type=link_type, source_type=source_type, target_type=target_type,
                project_id=project_id, enforce_offered=enforce_offered,
            )
    link = ArtefactLink(
        source_type=source_type, source_id=source_id,
        target_type=target_type, target_id=target_id,
        link_type_id=link_type_id, created_by=created_by,
    )
    db.add(link)
    db.flush()
    return link


def get_links_from(db: Session, source_type: str, source_id: uuid.UUID) -> list[ArtefactLink]:
    """Returns every `ArtefactLink` row with the given artefact as its
    source (i.e. "what does X link to")."""
    return list(
        db.scalars(
            select(ArtefactLink).where(ArtefactLink.source_type == source_type, ArtefactLink.source_id == source_id)
        ).all()
    )


def get_links_to(db: Session, target_type: str, target_id: uuid.UUID) -> list[ArtefactLink]:
    """Returns every `ArtefactLink` row with the given artefact as its
    target (i.e. "what links to X")."""
    return list(
        db.scalars(
            select(ArtefactLink).where(ArtefactLink.target_type == target_type, ArtefactLink.target_id == target_id)
        ).all()
    )


def get_links_to_many(db: Session, target_type: str, target_ids: Sequence[uuid.UUID]) -> list[ArtefactLink]:
    """Returns every `ArtefactLink` row targeting any of `target_ids` (same
    `target_type`) in one query — the bulk counterpart of `get_links_to`,
    for callers building a report/export across many targets at once
    instead of running one query per target. Returns an empty list for an
    empty `target_ids`, without issuing a query."""
    if not target_ids:
        return []
    return list(
        db.scalars(
            select(ArtefactLink).where(
                ArtefactLink.target_type == target_type, ArtefactLink.target_id.in_(target_ids)
            )
        ).all()
    )


def get_links_from_many(db: Session, source_type: str, source_ids: Sequence[uuid.UUID]) -> list[ArtefactLink]:
    """Returns every `ArtefactLink` row sourced from any of `source_ids`
    (same `source_type`) in one query — the mirror of `get_links_to_many`.
    Returns an empty list for an empty `source_ids`, without issuing a
    query."""
    if not source_ids:
        return []
    return list(
        db.scalars(
            select(ArtefactLink).where(
                ArtefactLink.source_type == source_type, ArtefactLink.source_id.in_(source_ids)
            )
        ).all()
    )


def get_links_touching_many(
    db: Session, frontier: dict[str, Sequence[uuid.UUID]], *, outgoing: bool = True, incoming: bool = True
) -> list[ArtefactLink]:
    """Returns every `ArtefactLink` row with an artefact of `frontier` (a
    `{artefact_type: ids}` mapping, any mix of types) as its source
    (`outgoing`) and/or its target (`incoming`), in one query — the batched
    step a breadth-first traversal takes per level. A link between two
    frontier artefacts is returned once. Empty when nothing is requested.
    """
    clauses = []
    for artefact_type, ids in frontier.items():
        if not ids:
            continue
        if outgoing:
            clauses.append(and_(ArtefactLink.source_type == artefact_type, ArtefactLink.source_id.in_(ids)))
        if incoming:
            clauses.append(and_(ArtefactLink.target_type == artefact_type, ArtefactLink.target_id.in_(ids)))
    if not clauses:
        return []
    return list(db.scalars(select(ArtefactLink).where(or_(*clauses)).order_by(ArtefactLink.created_at, ArtefactLink.id)).all())


def get_link_between(
    db: Session,
    *,
    source_type: str,
    source_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    link_type_id: uuid.UUID | None = None,
) -> ArtefactLink | None:
    """Returns the `ArtefactLink` row for this exact
    `(source, target, link_type_id)` combination, if one exists — the
    "does this link already exist" pre-check every mutating caller in this
    codebase runs before creating a link, so a duplicate produces a clean
    400 rather than a raw `IntegrityError` from the unique
    constraint/partial index (mirrors `routers.requirements.link_action`'s
    pre-existing pattern, now shared rather than re-derived per call site
    across `routers.requirements`/`routers.change_requests`)."""
    return db.scalar(
        select(ArtefactLink).where(
            ArtefactLink.source_type == source_type, ArtefactLink.source_id == source_id,
            ArtefactLink.target_type == target_type, ArtefactLink.target_id == target_id,
            ArtefactLink.link_type_id == link_type_id,
        )
    )


def get_all_links(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> list[ArtefactLink]:
    """Returns every `ArtefactLink` row touching the given artefact, in
    either direction — the generic equivalent of
    `routers.requirements.list_links`'s old
    `(source_requirement_id == X) | (target_requirement_id == X)` query,
    now expressed once for any artefact type rather than re-derived per
    caller."""
    return list(
        db.scalars(
            select(ArtefactLink).where(
                ((ArtefactLink.source_type == artefact_type) & (ArtefactLink.source_id == artefact_id))
                | ((ArtefactLink.target_type == artefact_type) & (ArtefactLink.target_id == artefact_id))
            )
        ).all()
    )


def delete_link(db: Session, link: ArtefactLink) -> None:
    """Deletes an `ArtefactLink` row. Does not commit — same convention as
    `create_link` above."""
    db.delete(link)
