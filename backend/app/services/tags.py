"""
Module: services.tags

Tags on any record of any registered artefact type: a governed vocabulary, attachment, the
list filter and the vocabulary-wide maintenance operations (rename, merge, delete, reclassify).

Responsibilities:
- Normalise tag names (`normalise_tag_name`) and keep a vocabulary free of near-duplicates.
- Resolve which vocabulary and mode apply to a record: the project's, the nearest ancestor's
  when the project has no tags of its own, or the organisation's for an organisation-owned
  record (`vocabulary_for_project`, `resolve_tag_mode`).
- Attach, detach and replace the tags of a record (`set_record_tags`, `add_record_tag`,
  `remove_record_tag`), writing the audit events the record's Activity tab reads.
- Answer "which records carry these tags" for list endpoints (`tagged_ids`) and the usage tables
  (`usage_by_type`).
- Vocabulary maintenance for a project or the organisation (`create_tag`, `update_tag`,
  `merge_tags`, `delete_tag`, `reclassify`).
- Keep requirement keywords (`get_keywords`, `set_keywords`): a keyword is a tag.

Design decisions:
- A project with no tags of its own offers its nearest ancestor's vocabulary and mode, exactly
  as action types fall back (`services.project_hierarchy.resolve_effective_action_types`). A
  tag a child coins in free mode is created in the child, which then has a vocabulary of its
  own; records keep the ancestor tags they already carry.
- Mode `restricted` only constrains *new* names: a tag a record already carries is never
  rejected, so an unchanged edit cannot fail because the list later changed.
- Authority: a tag is metadata, not record content, so it is not blocked by an approved
  requirement's lock; it needs `manage` on the record's type (or, for requirements and actions,
  the roles that can edit them). Vocabulary management needs the project's settings authority.
- Tag names forbid `,` and `;` so CSV keyword columns (`;`-separated) and comma-separated
  inputs round-trip.

External dependencies: `models.tag`, `services.link_graph` (record visibility),
`services.project_hierarchy` (ancestors), `services.audit`, `modules.registry` (types).
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, TypeVar

from fastapi import HTTPException, Query, status
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.tag import MAX_TAG_NAME_LENGTH, ArtefactTag, Tag
from app.modules.registry import get_all_registered_artefact_types, get_artefact_type_label
from app.services.audit import log_event
from app.services.link_graph import ArtefactResolver
from app.services.project_hierarchy import get_project_chain_ids

TAG_MODE_FREE = "free"
TAG_MODE_RESTRICTED = "restricted"
TAG_MODES = (TAG_MODE_FREE, TAG_MODE_RESTRICTED)

#: Most records one reclassify call may touch, so it cannot become an unbounded writer.
MAX_RECLASSIFY_RECORDS = 1000
#: Most tags one record may carry.
MAX_TAGS_PER_RECORD = 50

_FORBIDDEN_CHARS = re.compile(r"[,;\x00-\x1f]")
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
_SPACES = re.compile(r"\s+")
#: Core types whose project roles (not only `manage`) may tag, mirroring who may edit them.
_ROLE_TAGGABLE_TYPES = frozenset({"requirement", "requirement_action"})


@dataclass(frozen=True)
class TagScope:
    """Whose vocabulary: a project's (`project_id` set) or the organisation's (`project_id` None)."""

    organization_id: uuid.UUID
    project_id: uuid.UUID | None


@dataclass
class Vocabulary:
    """The tags a scope offers and how new names are treated.

    Attributes:
        tags: The offered tags, by name.
        owner_project_id: The project that owns `tags` (the scope's own project or an ancestor);
            `None` for the organisation's vocabulary.
        inherited: True when `tags` belong to an ancestor of the project asked about.
        mode: `"free"` or `"restricted"`.
        mode_inherited: True when the mode comes from an ancestor (or the default), not the project.
    """

    tags: list[Tag]
    owner_project_id: uuid.UUID | None
    inherited: bool
    mode: str
    mode_inherited: bool


@dataclass
class TagChange:
    """What an operation did to one record."""

    added: list[Tag] = field(default_factory=list)
    removed: list[Tag] = field(default_factory=list)


def normalise_tag_name(raw: str) -> tuple[str, str]:
    """Trims and validates a tag name.

    Args:
        raw: The name as typed.

    Returns:
        `(name, name_key)`: the name with whitespace collapsed (casing kept) and its
        case-folded key, which is what makes `Safety`, `safety` and ` safety ` one tag.

    Raises:
        HTTPException: 422 when the name is empty, longer than 40 characters, or contains a
            comma, semicolon or control character.
    """
    name = _SPACES.sub(" ", (raw or "").strip())
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A tag needs a name.")
    if len(name) > MAX_TAG_NAME_LENGTH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"A tag name can be at most {MAX_TAG_NAME_LENGTH} characters."
        )
    if _FORBIDDEN_CHARS.search(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A tag name cannot contain a comma or semicolon.")
    return name, name.casefold()


def validate_colour(colour: str | None) -> str | None:
    """Returns `colour` lower-cased if it is `#rrggbb` (or empty -> `None`).

    Raises:
        HTTPException: 422 for any other value.
    """
    if not colour:
        return None
    if not _COLOUR.fullmatch(colour):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A tag colour must look like #1a2b3c.")
    return colour.lower()


def _validate_mode(mode: str) -> str:
    """Returns `mode` if it is a known tag mode.

    Raises:
        HTTPException: 422 otherwise.
    """
    if mode not in TAG_MODES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tag mode must be 'free' or 'restricted'.")
    return mode


# --- vocabulary and mode resolution ---------------------------------------------------------


def scope_of_record(project: Project, record_project_id: uuid.UUID | None) -> TagScope:
    """The vocabulary scope of a record seen from `project`: its own project, or the
    organisation for an organisation-owned record (no project)."""
    return TagScope(project.organization_id, record_project_id)


def resolve_tag_mode(db: Session, project: Project) -> tuple[str, bool]:
    """The mode that applies to `project` and whether it is inherited.

    Returns:
        `(mode, inherited)`: the project's own `tag_mode` if set, else the nearest ancestor's,
        else `"free"`.
    """
    for index, project_id in enumerate(get_project_chain_ids(db, project.id)):
        mode = db.scalar(select(Project.tag_mode).where(Project.id == project_id))
        if mode:
            return mode, index > 0
    return TAG_MODE_FREE, True


def vocabulary_for_project(db: Session, project: Project) -> Vocabulary:
    """The tags `project` offers: its own if it has any, else the nearest ancestor's with any.

    Always on and independent of RBAC, like the action-type fallback; the ancestor's identity
    is not returned, only whether the list is inherited.
    """
    mode, mode_inherited = resolve_tag_mode(db, project)
    for index, project_id in enumerate(get_project_chain_ids(db, project.id)):
        tags = list(db.scalars(select(Tag).where(Tag.project_id == project_id).order_by(func.lower(Tag.name))).all())
        if tags:
            return Vocabulary(tags, project_id, index > 0, mode, mode_inherited)
    return Vocabulary([], project.id, False, mode, mode_inherited)


def vocabulary_for_organization(db: Session, organization_id: uuid.UUID) -> Vocabulary:
    """The organisation's own vocabulary (used by organisation-owned records) and its mode."""
    tags = list(
        db.scalars(
            select(Tag).where(Tag.organization_id == organization_id, Tag.project_id.is_(None)).order_by(func.lower(Tag.name))
        ).all()
    )
    org = db.get(Organization, organization_id)
    return Vocabulary(tags, None, False, org.tag_mode if org else TAG_MODE_FREE, False)


def mode_for_scope(db: Session, scope: TagScope) -> str:
    """The mode (`free` or `restricted`) that applies to a record in `scope`."""
    if scope.project_id is None:
        org = db.get(Organization, scope.organization_id)
        return org.tag_mode if org else TAG_MODE_FREE
    project = db.get(Project, scope.project_id)
    return resolve_tag_mode(db, project)[0] if project else TAG_MODE_FREE


def offered_tags(db: Session, scope: TagScope) -> dict[str, Tag]:
    """The tags a record in `scope` may pick from, by `name_key` (own tags win over inherited)."""
    if scope.project_id is None:
        return {t.name_key: t for t in vocabulary_for_organization(db, scope.organization_id).tags}
    project = db.get(Project, scope.project_id)
    if project is None:
        return {}
    offered = {t.name_key: t for t in vocabulary_for_project(db, project).tags}
    for tag in db.scalars(select(Tag).where(Tag.project_id == scope.project_id)).all():
        offered[tag.name_key] = tag
    return offered


# --- authorisation ----------------------------------------------------------------------------


def can_tag(resolver: ArtefactResolver, artefact_type: str) -> bool:
    """Whether the user may add or remove tags on `artefact_type` records in the request project:
    `manage` on the type, or (requirements and actions) a role that can edit them."""
    if resolver.holds(artefact_type, "manage"):
        return True
    return artefact_type in _ROLE_TAGGABLE_TYPES and resolver.has_default_link_role(artefact_type)


def require_tag_authority(resolver: ArtefactResolver, artefact_type: str) -> None:
    """Raises 403 unless `can_tag(resolver, artefact_type)`."""
    if not can_tag(resolver, artefact_type):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"You do not have permission to tag {get_artefact_type_label(artefact_type).lower()} records.",
        )


def require_visible_record(
    resolver: ArtefactResolver, project: Project, artefact_type: str, artefact_id: uuid.UUID
) -> uuid.UUID | None:
    """The owning project id of a record the user may open from `project` (`None` for an
    organisation-owned record).

    Raises:
        HTTPException: 404 when the type is unregistered, or the record is not visible in this
            project (the two are indistinguishable, as for the Links panel).
    """
    if artefact_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    resolver.resolve({artefact_type: {artefact_id}})
    summary = resolver.visible((artefact_type, artefact_id))
    if summary is None or (summary.project_id is not None and summary.project_id != project.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact not found.")
    return summary.project_id


# --- reading ----------------------------------------------------------------------------------


def get_record_tags(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> list[Tag]:
    """The tags on one record, by name."""
    return list(
        db.scalars(
            select(Tag).join(ArtefactTag, ArtefactTag.tag_id == Tag.id)
            .where(ArtefactTag.artefact_type == artefact_type, ArtefactTag.artefact_id == artefact_id)
            .order_by(func.lower(Tag.name))
        ).all()
    )


def tags_for_records(db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[Tag]]:
    """The tags of several records of one type in one query (`{record id: tags}`, absent = none)."""
    ids = list(artefact_ids)
    found: dict[uuid.UUID, list[Tag]] = defaultdict(list)
    if not ids:
        return found
    rows = db.execute(
        select(ArtefactTag.artefact_id, Tag).join(Tag, Tag.id == ArtefactTag.tag_id)
        .where(ArtefactTag.artefact_type == artefact_type, ArtefactTag.artefact_id.in_(ids))
        .order_by(func.lower(Tag.name))
    ).all()
    for artefact_id, tag in rows:
        found[artefact_id].append(tag)
    return found


def tagged_ids(
    db: Session, *, project: Project, artefact_type: str, names: list[str], match_all: bool = False
) -> set[uuid.UUID]:
    """Ids of the records of `artefact_type` in `project` (and the organisation-owned ones it can
    see) that carry any (or, with `match_all`, every) one of `names`.

    Names match case-insensitively. An empty `names` is the caller's cue not to filter, so it
    returns an empty set only when no name was given and the caller should skip the call.

    Args:
        db: Active session (read only).
        project: The request project.
        artefact_type: The list's record type.
        names: Tag names to look for.
        match_all: Require every name instead of any.
    """
    keys = {normalise_tag_name(n)[1] for n in names if n and n.strip()}
    if not keys:
        return set()
    owner = or_(
        ArtefactTag.project_id == project.id,
        and_(ArtefactTag.project_id.is_(None), Tag.organization_id == project.organization_id),
    )
    query = (
        select(ArtefactTag.artefact_id)
        .join(Tag, Tag.id == ArtefactTag.tag_id)
        .where(ArtefactTag.artefact_type == artefact_type, Tag.name_key.in_(keys), owner)
        .group_by(ArtefactTag.artefact_id)
    )
    if match_all:
        query = query.having(func.count(func.distinct(Tag.name_key)) == len(keys))
    return set(db.scalars(query).all())


@dataclass
class TaggedRecord:
    """A visible record found by tag (`find_tagged_records`)."""

    artefact_type: str
    type_label: str
    id: uuid.UUID
    label: str
    status: str | None
    is_archived: bool
    project_id: uuid.UUID | None
    project_name: str | None = None
    project_code: str | None = None


#: Most records `find_tagged_records` returns.
MAX_TAGGED_RECORDS = 200


def find_tagged_records(
    db: Session, *, project: Project, resolver: ArtefactResolver, names: list[str], match_all: bool = False,
    artefact_type: str | None = None, limit: int = MAX_TAGGED_RECORDS,
    project_ids: set[uuid.UUID] | None = None,
) -> tuple[list[TaggedRecord], bool]:
    """Records of any type, visible to the caller in `project`, carrying any (or all) of `names`.

    A record the caller cannot open is omitted, never described, so the result and its size
    reveal nothing about hidden records.

    Args:
        db: Active session (read only).
        project: The request project.
        resolver: The caller's visibility rules (`ArtefactResolver`).
        names: Tag names; at least one is needed.
        match_all: Require every name instead of any.
        artefact_type: Restrict to one registered type.
        limit: Most rows to return (capped at `MAX_TAGGED_RECORDS`).
        project_ids: The projects to look in (the request project plus the related projects of a
            widened scope, `services.project_scope`); `None` means the request project only. The
            resolver must have been built with `include_related=True` for any other project to
            resolve.

    Returns:
        `(records, truncated)`, newest tag use first.

    Raises:
        HTTPException: 422 when `names` is empty; 404 for an unregistered `artefact_type`.
    """
    keys = {normalise_tag_name(n)[1] for n in names if n and n.strip()}
    if not keys:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give at least one tag.")
    if artefact_type is not None and artefact_type not in get_all_registered_artefact_types():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artefact type not found.")
    scope_ids = project_ids if project_ids is not None else {project.id}
    owner = or_(
        ArtefactTag.project_id.in_(scope_ids),
        and_(ArtefactTag.project_id.is_(None), Tag.organization_id == project.organization_id),
    )
    query = (
        select(ArtefactTag.artefact_type, ArtefactTag.artefact_id, func.max(ArtefactTag.created_at))
        .join(Tag, Tag.id == ArtefactTag.tag_id).where(Tag.name_key.in_(keys), owner)
        .group_by(ArtefactTag.artefact_type, ArtefactTag.artefact_id)
    )
    if artefact_type is not None:
        query = query.where(ArtefactTag.artefact_type == artefact_type)
    if match_all:
        query = query.having(func.count(func.distinct(Tag.name_key)) == len(keys))
    hits = db.execute(query.order_by(func.max(ArtefactTag.created_at).desc()).limit(MAX_TAGGED_RECORDS * 5)).all()
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for hit_type, hit_id, _ in hits:
        wanted[hit_type].add(hit_id)
    resolver.resolve(wanted)
    cap = max(1, min(limit, MAX_TAGGED_RECORDS))
    found: list[TaggedRecord] = []
    for hit_type, hit_id, _ in hits:
        summary = resolver.visible((hit_type, hit_id))
        if summary is None or (summary.project_id is not None and summary.project_id not in scope_ids):
            continue
        found.append(TaggedRecord(
            hit_type, get_artefact_type_label(hit_type), hit_id, summary.label, summary.status, summary.is_archived,
            summary.project_id, resolver.project_name(summary.project_id), resolver.project_code(summary.project_id),
        ))
        if len(found) > cap:
            break
    return found[:cap], len(found) > cap


_Row = TypeVar("_Row")


class TagFilter:
    """The `?tag=a&tag=b&tag_mode=any|all` list filter, as a FastAPI dependency
    (`tag_filter: TagFilter = Depends()`), so every list endpoint offers the same parameters.

    Attributes:
        names: The requested tag names (blank entries dropped).
        match_all: True for `tag_mode=all`.
    """

    def __init__(
        self,
        tag: list[str] = Query([], description="Only records carrying these tags (case-insensitive)."),
        tag_mode: Literal["any", "all"] = Query("any", description="Whether a record needs any or all of the `tag`s."),
    ) -> None:
        """Reads the `tag` and `tag_mode` query parameters (blank names are ignored)."""
        self.names = [t for t in tag if t and t.strip()]
        self.match_all = tag_mode == "all"

    @property
    def active(self) -> bool:
        """Whether the caller asked to filter."""
        return bool(self.names)

    def ids(self, db: Session, project_id: uuid.UUID, artefact_type: str) -> set[uuid.UUID]:
        """Ids of the project's records of `artefact_type` that satisfy the filter."""
        project = db.get(Project, project_id)
        if project is None:
            return set()
        return tagged_ids(db, project=project, artefact_type=artefact_type, names=self.names, match_all=self.match_all)

    def keep(
        self, db: Session, project_id: uuid.UUID, artefact_type: str, rows: list[_Row],
        id_of=lambda row: row.id,
    ) -> list[_Row]:
        """`rows` narrowed to the matching records (unchanged when the filter is not active).

        Args:
            db: Active session (read only).
            project_id: The project the list is for.
            artefact_type: The listed record type.
            rows: The rows the endpoint would return.
            id_of: Reads a row's record id (default `row.id`).
        """
        if not self.active:
            return rows
        wanted = self.ids(db, project_id, artefact_type)
        return [row for row in rows if id_of(row) in wanted]


# --- attaching --------------------------------------------------------------------------------


def _resolve_names(
    db: Session, *, scope: TagScope, actor_id: uuid.UUID | None, names: list[str], attached: dict[str, Tag],
    enforce_mode: bool = True,
) -> list[Tag]:
    """Maps names to tags: one already on the record, else one the vocabulary offers, else a new
    one (free mode, or any mode when `enforce_mode` is false) or an error (restricted mode)."""
    offered: dict[str, Tag] | None = None
    mode: str | None = None
    resolved: dict[str, Tag] = {}
    for raw in names:
        name, key = normalise_tag_name(raw)
        if key in resolved:
            continue
        tag = attached.get(key)
        if tag is None:
            if offered is None:
                offered = offered_tags(db, scope)
            tag = offered.get(key)
        if tag is None:
            if mode is None:
                mode = mode_for_scope(db, scope) if enforce_mode else TAG_MODE_FREE
            if mode == TAG_MODE_RESTRICTED:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"'{name}' is not in the tag list. A project administrator can add it.",
                )
            tag = Tag(
                organization_id=scope.organization_id, project_id=scope.project_id, name=name, name_key=key,
                created_by=actor_id,
            )
            db.add(tag)
            db.flush()
            log_event(
                db, entity_type="tag", entity_id=tag.id, action="created", actor_id=actor_id,
                organization_id=scope.organization_id, project_id=scope.project_id, detail={"name": name},
            )
            offered[key] = tag
        resolved[key] = tag
    return list(resolved.values())


def _audit_record(
    db: Session, scope: TagScope, actor_id: uuid.UUID | None, artefact_type: str, artefact_id: uuid.UUID,
    action: str, tag: Tag, project_id: uuid.UUID | None = None,
) -> None:
    """Writes a `tagged`/`untagged` event against the record (`project_id` defaults to the scope's)."""
    log_event(
        db, entity_type=artefact_type, entity_id=artefact_id, action=action, actor_id=actor_id,
        organization_id=scope.organization_id, project_id=project_id if project_id is not None else scope.project_id,
        detail={"tag": tag.name, "tag_id": str(tag.id)},
    )


def set_record_tags(
    db: Session, *, scope: TagScope, actor_id: uuid.UUID | None, artefact_type: str, artefact_id: uuid.UUID,
    names: list[str], enforce_mode: bool = True,
) -> TagChange:
    """Makes the record carry exactly `names`.

    Args:
        db: Active session; changes and audit events are added, not committed.
        scope: The record's vocabulary scope (`scope_of_record`).
        actor_id: The acting user.
        artefact_type / artefact_id: The record; the caller has authorised it.
        names: The wanted tag names.
        enforce_mode: False for a bundle import, which keeps the tags it was exported with even
            in a restricted project (an administrator is restoring them, not coining them).

    Returns:
        The tags added and removed.

    Raises:
        HTTPException: 422 for an invalid name, a name not on the list in restricted mode, or
            more than `MAX_TAGS_PER_RECORD` tags.
    """
    current = get_record_tags(db, artefact_type, artefact_id)
    attached = {t.name_key: t for t in current}
    wanted = _resolve_names(
        db, scope=scope, actor_id=actor_id, names=names, attached=attached, enforce_mode=enforce_mode,
    )
    if len(wanted) > MAX_TAGS_PER_RECORD:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"A record can carry at most {MAX_TAGS_PER_RECORD} tags."
        )
    change = TagChange()
    wanted_ids = {t.id for t in wanted}
    for tag in current:
        if tag.id not in wanted_ids:
            db.execute(
                delete(ArtefactTag).where(
                    ArtefactTag.tag_id == tag.id, ArtefactTag.artefact_type == artefact_type,
                    ArtefactTag.artefact_id == artefact_id,
                )
            )
            change.removed.append(tag)
            _audit_record(db, scope, actor_id, artefact_type, artefact_id, "untagged", tag)
    have = {t.id for t in current}
    for tag in wanted:
        if tag.id not in have:
            db.add(ArtefactTag(
                tag_id=tag.id, artefact_type=artefact_type, artefact_id=artefact_id, project_id=scope.project_id,
                created_by=actor_id,
            ))
            change.added.append(tag)
            _audit_record(db, scope, actor_id, artefact_type, artefact_id, "tagged", tag)
    db.flush()
    return change


def add_record_tag(
    db: Session, *, scope: TagScope, actor_id: uuid.UUID | None, artefact_type: str, artefact_id: uuid.UUID, name: str,
) -> TagChange:
    """Adds one tag by name, keeping the others. See `set_record_tags` for the rules."""
    current = get_record_tags(db, artefact_type, artefact_id)
    return set_record_tags(
        db, scope=scope, actor_id=actor_id, artefact_type=artefact_type, artefact_id=artefact_id,
        names=[t.name for t in current] + [name],
    )


def remove_record_tag(
    db: Session, *, scope: TagScope, actor_id: uuid.UUID | None, artefact_type: str, artefact_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> TagChange:
    """Removes one tag from the record; a tag the record does not carry is a no-op."""
    current = get_record_tags(db, artefact_type, artefact_id)
    return set_record_tags(
        db, scope=scope, actor_id=actor_id, artefact_type=artefact_type, artefact_id=artefact_id,
        names=[t.name for t in current if t.id != tag_id],
    )


def forget_record_tags(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> None:
    """Drops every attachment of a record that is being deleted for good (there is no foreign
    key, so the record's owner calls this)."""
    db.execute(delete(ArtefactTag).where(ArtefactTag.artefact_type == artefact_type, ArtefactTag.artefact_id == artefact_id))


# --- vocabulary maintenance -------------------------------------------------------------------


def _load_tag(db: Session, scope: TagScope, tag_id: uuid.UUID) -> Tag:
    """A tag of exactly this scope (not an inherited one), else 404."""
    tag = db.get(Tag, tag_id)
    if tag is None or tag.organization_id != scope.organization_id or tag.project_id != scope.project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found.")
    return tag


def usage_count(db: Session, tag_id: uuid.UUID) -> int:
    """How many records carry the tag."""
    return db.scalar(select(func.count()).select_from(ArtefactTag).where(ArtefactTag.tag_id == tag_id)) or 0


def usage_counts(
    db: Session, tag_ids: Iterable[uuid.UUID], project_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, int]:
    """`{tag id: records carrying it}` for several tags in one query (absent = 0).

    With `project_id`, only that project's records are counted: a project that merely inherits a
    tag must not learn how many records elsewhere in the tree carry it."""
    ids = list(tag_ids)
    if not ids:
        return {}
    query = select(ArtefactTag.tag_id, func.count()).where(ArtefactTag.tag_id.in_(ids))
    if project_id is not None:
        query = query.where(ArtefactTag.project_id == project_id)
    return {tag_id: count for tag_id, count in db.execute(query.group_by(ArtefactTag.tag_id)).all()}


def create_tag(
    db: Session, *, scope: TagScope, actor_id: uuid.UUID, name: str, colour: str | None = None,
) -> Tag:
    """Adds a tag to the vocabulary (the way a restricted list grows).

    Raises:
        HTTPException: 422 for an invalid name or colour; 409 when the vocabulary already has it.
    """
    display, key = normalise_tag_name(name)
    existing = db.scalar(_scope_query(scope).where(Tag.name_key == key))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The tag '{existing.name}' already exists.")
    tag = Tag(
        organization_id=scope.organization_id, project_id=scope.project_id, name=display, name_key=key,
        colour=validate_colour(colour), created_by=actor_id,
    )
    db.add(tag)
    db.flush()
    log_event(
        db, entity_type="tag", entity_id=tag.id, action="created", actor_id=actor_id,
        organization_id=scope.organization_id, project_id=scope.project_id, detail={"name": display},
    )
    return tag


def _scope_query(scope: TagScope):
    """A select of exactly `scope`'s own tags (not an ancestor's)."""
    query = select(Tag).where(Tag.organization_id == scope.organization_id)
    return query.where(Tag.project_id == scope.project_id) if scope.project_id else query.where(Tag.project_id.is_(None))


def update_tag(
    db: Session, *, scope: TagScope, actor_id: uuid.UUID, tag_id: uuid.UUID, name: str | None = None,
    colour: str | None = None, clear_colour: bool = False,
) -> Tag:
    """Renames a tag and/or sets its colour; every record carrying it shows the new name.

    Raises:
        HTTPException: 404 for a tag outside the scope; 409 when another tag already has the
            new name (merge instead); 422 for an invalid name or colour.
    """
    tag = _load_tag(db, scope, tag_id)
    detail: dict[str, str | None] = {}
    if name is not None:
        display, key = normalise_tag_name(name)
        clash = db.scalar(_scope_query(scope).where(Tag.name_key == key, Tag.id != tag.id))
        if clash is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"The tag '{clash.name}' already exists. Merge the two tags instead.",
            )
        if display != tag.name:
            detail["renamed_from"], detail["name"] = tag.name, display
        tag.name, tag.name_key = display, key
    if clear_colour:
        tag.colour = None
        detail["colour"] = None
    elif colour is not None:
        tag.colour = validate_colour(colour)
        detail["colour"] = tag.colour
    if detail:
        log_event(
            db, entity_type="tag", entity_id=tag.id, action="updated", actor_id=actor_id,
            organization_id=scope.organization_id, project_id=scope.project_id, detail=detail,
        )
    db.flush()
    return tag


def merge_tags(db: Session, *, scope: TagScope, actor_id: uuid.UUID, source_id: uuid.UUID, target_id: uuid.UUID) -> int:
    """Moves every record from `source` to `target` and deletes `source`.

    Returns:
        How many records now carry `target` because of the merge.

    Raises:
        HTTPException: 404 for a tag outside the scope; 422 when both are the same tag.
    """
    if source_id == target_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a different tag to merge into.")
    source, target = _load_tag(db, scope, source_id), _load_tag(db, scope, target_id)
    already = select(ArtefactTag.artefact_type, ArtefactTag.artefact_id).where(ArtefactTag.tag_id == target.id)
    rows = db.scalars(select(ArtefactTag).where(ArtefactTag.tag_id == source.id)).all()
    have = {(t, i) for t, i in db.execute(already).all()}
    moved = 0
    for row in rows:
        if (row.artefact_type, row.artefact_id) in have:
            continue
        db.add(ArtefactTag(
            tag_id=target.id, artefact_type=row.artefact_type, artefact_id=row.artefact_id,
            project_id=row.project_id, created_by=row.created_by, created_at=row.created_at,
        ))
        moved += 1
    log_event(
        db, entity_type="tag", entity_id=target.id, action="merged", actor_id=actor_id,
        organization_id=scope.organization_id, project_id=scope.project_id,
        detail={"merged": source.name, "into": target.name, "records_moved": moved, "records_already_tagged": len(rows) - moved},
    )
    db.delete(source)
    db.flush()
    return moved


def delete_tag(db: Session, *, scope: TagScope, actor_id: uuid.UUID, tag_id: uuid.UUID) -> int:
    """Deletes a tag and removes it from every record.

    Returns:
        How many records carried it.

    Raises:
        HTTPException: 404 for a tag outside the scope.
    """
    tag = _load_tag(db, scope, tag_id)
    affected = usage_count(db, tag.id)
    log_event(
        db, entity_type="tag", entity_id=tag.id, action="deleted", actor_id=actor_id,
        organization_id=scope.organization_id, project_id=scope.project_id,
        detail={"name": tag.name, "records_untagged": affected},
    )
    db.delete(tag)
    db.flush()
    return affected


def set_mode(db: Session, *, project: Project | None, organization: Organization | None, actor_id: uuid.UUID, mode: str | None) -> None:
    """Sets the project's tag mode (`None` inherits) or the organisation's.

    Raises:
        HTTPException: 422 for an unknown mode, or `None` for an organisation.
    """
    if project is not None:
        project.tag_mode = None if mode is None else _validate_mode(mode)
        log_event(
            db, entity_type="tag_settings", entity_id=project.id, action="updated", actor_id=actor_id,
            organization_id=project.organization_id, project_id=project.id, detail={"tag_mode": project.tag_mode},
        )
    elif organization is not None:
        if mode is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "An organisation must choose a tag mode.")
        organization.tag_mode = _validate_mode(mode)
        log_event(
            db, entity_type="tag_settings", entity_id=organization.id, action="updated", actor_id=actor_id,
            organization_id=organization.id, detail={"tag_mode": organization.tag_mode},
        )


@dataclass
class ReclassifyResult:
    """The outcome (or, for a dry run, the forecast) of a reclassify call."""

    matched: int = 0
    added: int = 0
    removed: int = 0


def reclassify(
    db: Session, *, scope: TagScope, actor_id: uuid.UUID, records: list[tuple[str, uuid.UUID, uuid.UUID | None]],
    add_ids: list[uuid.UUID], remove_ids: list[uuid.UUID], dry_run: bool,
) -> ReclassifyResult:
    """Adds and removes tags on many records in one transaction.

    The caller has chosen and authorised `records` (all of them in `scope`). Writes one audit
    event per changed record (so each record's Activity tab shows it) and one batch event.

    Args:
        db: Active session; nothing is committed.
        scope: The vocabulary scope; `add_ids` and `remove_ids` must belong to it.
        actor_id: The acting user.
        records: `(artefact_type, artefact_id, owning project id or None)` triples; a repeat is counted once.
        add_ids: Tags to add to each record.
        remove_ids: Tags to remove from each record.
        dry_run: Count only; change nothing.

    Returns:
        How many records matched and how many attachments would be (or were) added and removed.

    Raises:
        HTTPException: 404 for a tag outside the scope; 422 when over `MAX_RECLASSIFY_RECORDS`
            or when neither list names a tag.
    """
    if not add_ids and not remove_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a tag to add or remove.")
    if len(records) > MAX_RECLASSIFY_RECORDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Reclassify at most {MAX_RECLASSIFY_RECORDS} records at a time.",
        )
    to_add = [_load_tag(db, scope, i) for i in dict.fromkeys(add_ids)]
    to_remove = [_load_tag(db, scope, i) for i in dict.fromkeys(remove_ids)]
    owner_of: dict[tuple[str, uuid.UUID], uuid.UUID | None] = {}
    for artefact_type, artefact_id, record_project_id in records:
        owner_of.setdefault((artefact_type, artefact_id), record_project_id)
    result = ReclassifyResult(matched=len(owner_of))
    by_type: dict[str, list[uuid.UUID]] = defaultdict(list)
    for artefact_type, artefact_id in owner_of:
        by_type[artefact_type].append(artefact_id)
    for artefact_type, ids in by_type.items():
        existing = {
            (tag_id, rid)
            for tag_id, rid in db.execute(
                select(ArtefactTag.tag_id, ArtefactTag.artefact_id).where(
                    ArtefactTag.artefact_type == artefact_type, ArtefactTag.artefact_id.in_(ids),
                    ArtefactTag.tag_id.in_([t.id for t in to_add + to_remove]),
                )
            ).all()
        }
        for rid in ids:
            for tag in to_add:
                if (tag.id, rid) not in existing:
                    result.added += 1
                    if not dry_run:
                        db.add(ArtefactTag(
                            tag_id=tag.id, artefact_type=artefact_type, artefact_id=rid,
                            project_id=owner_of[(artefact_type, rid)], created_by=actor_id,
                        ))
                        _audit_record(
                            db, scope, actor_id, artefact_type, rid, "tagged", tag, owner_of[(artefact_type, rid)],
                        )
            for tag in to_remove:
                if (tag.id, rid) in existing:
                    result.removed += 1
                    if not dry_run:
                        db.execute(delete(ArtefactTag).where(
                            ArtefactTag.tag_id == tag.id, ArtefactTag.artefact_type == artefact_type,
                            ArtefactTag.artefact_id == rid,
                        ))
                        _audit_record(
                            db, scope, actor_id, artefact_type, rid, "untagged", tag, owner_of[(artefact_type, rid)],
                        )
    if not dry_run:
        log_event(
            db, entity_type="tag", entity_id=(to_add or to_remove)[0].id, action="reclassified", actor_id=actor_id,
            organization_id=scope.organization_id, project_id=scope.project_id,
            detail={
                "added": [t.name for t in to_add], "removed": [t.name for t in to_remove],
                "records": result.matched, "attachments_added": result.added, "attachments_removed": result.removed,
            },
        )
        db.flush()
    return result


def records_with_tag(
    db: Session, *, scope: TagScope, tag_id: uuid.UUID, artefact_types: list[str] | None = None,
) -> list[tuple[str, uuid.UUID, uuid.UUID | None]]:
    """Every record carrying a tag of `scope` as `(type, id, owning project id)`, optionally limited to some types.

    A project's tag can be carried by records of a child project that inherits it; each triple names
    the record's own project so a later write keeps the record's ownership.

    Raises:
        HTTPException: 404 for a tag outside the scope.
    """
    tag = _load_tag(db, scope, tag_id)
    query = select(ArtefactTag.artefact_type, ArtefactTag.artefact_id, ArtefactTag.project_id).where(ArtefactTag.tag_id == tag.id)
    if artefact_types:
        query = query.where(ArtefactTag.artefact_type.in_(artefact_types))
    return [(t, i, p) for t, i, p in db.execute(query.order_by(ArtefactTag.artefact_type, ArtefactTag.created_at)).all()]


# --- usage ------------------------------------------------------------------------------------


@dataclass
class UsageRow:
    """One tag's use on one record type."""

    tag: Tag
    count: int
    last_used: datetime | None


@dataclass
class TypeUsage:
    """The tags used on one record type, most used first."""

    artefact_type: str
    label: str
    rows: list[UsageRow]


def usage_by_type(db: Session, scope: TagScope, artefact_type: str | None = None) -> list[TypeUsage]:
    """Tag x record-type usage for a project (its own records) or the organisation (its own records).

    Args:
        db: Active session (read only).
        scope: The project or organisation.
        artefact_type: Restrict to one type.

    Returns:
        One entry per type that has tagged records, in label order; rows by count (most first) then name.
    """
    owner = ArtefactTag.project_id == scope.project_id if scope.project_id else (
        and_(ArtefactTag.project_id.is_(None), Tag.organization_id == scope.organization_id)
    )
    query = (
        select(ArtefactTag.artefact_type, Tag, func.count(), func.max(ArtefactTag.created_at))
        .join(Tag, Tag.id == ArtefactTag.tag_id).where(owner).group_by(ArtefactTag.artefact_type, Tag.id)
    )
    if artefact_type:
        query = query.where(ArtefactTag.artefact_type == artefact_type)
    grouped: dict[str, list[UsageRow]] = defaultdict(list)
    for a_type, tag, count, last in db.execute(query).all():
        grouped[a_type].append(UsageRow(tag, count, last))
    tables = [
        TypeUsage(a_type, get_artefact_type_label(a_type), sorted(rows, key=lambda r: (-r.count, r.tag.name.lower())))
        for a_type, rows in grouped.items()
    ]
    return sorted(tables, key=lambda t: t.label.lower())


# --- requirement keywords ---------------------------------------------------------------------


def get_keywords(db: Session, requirement_id: uuid.UUID) -> list[str]:
    """The names of a requirement's tags (its keywords), by name."""
    return [t.name for t in get_record_tags(db, "requirement", requirement_id)]


def set_keywords(
    db: Session, requirement, keywords: list[str], actor_id: uuid.UUID | None = None, enforce_mode: bool = True,
) -> TagChange:
    """Makes a requirement carry exactly `keywords` as tags in its project.

    Blank entries are skipped. Names obey the project's tag mode: a name not on the list is
    created in free mode and rejected (422) in restricted mode, unless the requirement already
    carries it.

    Args:
        db: Active session; nothing is committed.
        requirement: The `Requirement` (its project supplies the vocabulary).
        keywords: The wanted names.
        actor_id: The acting user, for the audit trail.
        enforce_mode: False for a bundle import (see `set_record_tags`).

    Raises:
        HTTPException: 422 as `set_record_tags`.
    """
    project = db.get(Project, requirement.project_id)
    return set_record_tags(
        db, scope=TagScope(project.organization_id, project.id), actor_id=actor_id, artefact_type="requirement",
        artefact_id=requirement.id, names=[k for k in keywords if k and k.strip()], enforce_mode=enforce_mode,
    )


def keywords_for_requirements(db: Session, requirement_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """`{requirement id: tag names}` for several requirements in one query (absent = none)."""
    return {rid: [t.name for t in tags] for rid, tags in tags_for_records(db, "requirement", requirement_ids).items()}



# --- project bundle ---------------------------------------------------------------------------


def export_vocabulary(db: Session, project: Project) -> dict:
    """The project's own vocabulary and mode for a bundle: `{"mode": ..., "tags": [{"name", "colour"}]}`
    (an inherited list belongs to the ancestor and is not exported; `mode` is `None` when the
    project follows its parent)."""
    tags = db.scalars(select(Tag).where(Tag.project_id == project.id).order_by(func.lower(Tag.name))).all()
    return {"mode": project.tag_mode, "tags": [{"name": t.name, "colour": t.colour} for t in tags]}


def import_vocabulary(db: Session, project: Project, data: dict | None, actor_id: uuid.UUID | None) -> None:
    """Restores a bundle's vocabulary and mode into `project` (a bundle without them changes nothing).
    A name already in the vocabulary is left as it is; an invalid one is skipped."""
    if not data:
        return
    scope = TagScope(project.organization_id, project.id)
    existing = {t.name_key for t in db.scalars(_scope_query(scope)).all()}
    for entry in data.get("tags", []):
        try:
            name, key = normalise_tag_name(entry.get("name", ""))
            colour = validate_colour(entry.get("colour"))
        except HTTPException:
            continue
        if key in existing:
            continue
        db.add(Tag(
            organization_id=scope.organization_id, project_id=scope.project_id, name=name, name_key=key,
            colour=colour, created_by=actor_id,
        ))
        existing.add(key)
    if data.get("mode") in TAG_MODES:
        project.tag_mode = data["mode"]
    db.flush()


def tag_names_for_records(db: Session, artefact_type: str, artefact_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """`{record id: tag names}` for a bundle's rows of one type (absent = none)."""
    return {rid: [t.name for t in tags] for rid, tags in tags_for_records(db, artefact_type, artefact_ids).items()}


def record_tag_names(db: Session, artefact_type: str, artefact_id: uuid.UUID) -> list[str]:
    """The names of one record's tags, for a bundle row."""
    return [t.name for t in get_record_tags(db, artefact_type, artefact_id)]


def restore_record_tags(
    db: Session, *, organization_id: uuid.UUID, record_project_id: uuid.UUID | None, actor_id: uuid.UUID | None,
    artefact_type: str, artefact_id: uuid.UUID, names: list[str] | None,
) -> None:
    """Applies a bundle row's tag names to its newly created record, whatever the vocabulary's mode.

    Args:
        organization_id: The organisation being imported into.
        record_project_id: The record's owning project, or `None` for a record the organisation owns.
        actor_id: The importing user.
        artefact_type / artefact_id: The new record.
        names: The row's tag names (nothing to do when empty or absent).
    """
    if not names:
        return
    set_record_tags(
        db, scope=TagScope(organization_id, record_project_id), actor_id=actor_id,
        artefact_type=artefact_type, artefact_id=artefact_id, names=names, enforce_mode=False,
    )
