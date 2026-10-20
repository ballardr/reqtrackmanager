"""
Module: modules.stakeholders.groups

Business logic for Stakeholder Groups: a tree of org- or
project-scoped classification groups with many-to-many stakeholder membership.

Responsibilities:
- Create/update/move/delete groups with the scope rules (an org group's parent
  and members are org-scoped only; a project group's parent is an org group or
  a group of the same project and its members are org or own-project
  stakeholders), cycle and depth guards, and unique sibling names.
- Direct membership add/remove, with the `exclusive_children` rule (a stakeholder
  sits in at most one direct-child branch of such a group).
- Transitive membership: being in a group means being in all its ancestors, so
  `descendant_ids` + `member_ids` answer "everyone in Acme".
- Reading groups per stakeholder (`group_refs`) and sorting by a root group
  (`branch_sort_key`) for lists.
- Proposing and creating groups from the stakeholders' free-text
  "organisation / group" field.

Design decisions (Decided by: Agent):
- Walks are cycle-safe and depth-capped (`MAX_GROUP_DEPTH`).
- A viewer's "universe" is its org's groups plus, in a project, that project's
  own groups: another project's groups are never read or named.
- Rule violations raise `GroupRuleError`, which carries the HTTP status the
  router should answer with (404 absent, 400 invalid, 409 conflicting).
- Groups are classification, not principals: no version table, comments or
  lifecycle. Mutations are audit-logged by the callers' routers with ids only.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.modules.stakeholders.enums import StakeholderScope
from app.modules.stakeholders.models import Stakeholder, StakeholderGroup, StakeholderGroupMember, StakeholderVersion
from app.services.relationships import delete_link, get_all_links
from app.services.sequences import code_owner, generate_unique_code

GROUP_ARTEFACT_TYPE = "stakeholder_group"
GROUP_CODE_PREFIX = "SGP"
MAX_GROUP_DEPTH = 10
TEXT_ROOT_NAME = "Organisation / group"


class GroupRuleError(ValueError):
    """A group rule was broken; `status_code` is the HTTP status to answer with."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class GroupRef:
    """A group as shown on a stakeholder: id, name, owning scope and parent."""

    id: uuid.UUID
    name: str
    scope: StakeholderScope
    parent_group_id: uuid.UUID | None
    unique_code: str = ""
    organization_id: uuid.UUID | None = None


# --- Universe and tree walks -----------------------------------------------------------------


def load_groups(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None = None
) -> dict[uuid.UUID, StakeholderGroup]:
    """Every group a viewer can see: the organisation's, plus `project_id`'s own when given."""
    query = select(StakeholderGroup).where(
        (StakeholderGroup.scope == StakeholderScope.ORGANIZATION) & (StakeholderGroup.organization_id == organization_id)
        if project_id is None
        else ((StakeholderGroup.scope == StakeholderScope.ORGANIZATION) & (StakeholderGroup.organization_id == organization_id))
        | ((StakeholderGroup.scope == StakeholderScope.PROJECT) & (StakeholderGroup.project_id == project_id))
    )
    return {g.id: g for g in db.scalars(query.order_by(StakeholderGroup.sort_order, StakeholderGroup.name))}


def ancestor_chain(groups: dict[uuid.UUID, StakeholderGroup], group_id: uuid.UUID) -> list[StakeholderGroup]:
    """The group's ancestors, nearest first, within `groups`; cycle-safe and capped."""
    chain: list[StakeholderGroup] = []
    seen = {group_id}
    current = groups.get(group_id)
    while current is not None and current.parent_group_id is not None and len(chain) < MAX_GROUP_DEPTH * 2:
        parent = groups.get(current.parent_group_id)
        if parent is None or parent.id in seen:
            break
        chain.append(parent)
        seen.add(parent.id)
        current = parent
    return chain


def descendant_ids(groups: dict[uuid.UUID, StakeholderGroup], group_id: uuid.UUID) -> set[uuid.UUID]:
    """The ids of every group below `group_id` within `groups` (not itself); cycle-safe."""
    children: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for g in groups.values():
        if g.parent_group_id is not None:
            children[g.parent_group_id].append(g.id)
    found: set[uuid.UUID] = set()
    frontier = [group_id]
    while frontier and len(found) < len(groups):
        nxt = []
        for gid in frontier:
            for child in children.get(gid, []):
                if child not in found and child != group_id:
                    found.add(child)
                    nxt.append(child)
        frontier = nxt
    return found


def _db_chain(db: Session, group: StakeholderGroup) -> list[StakeholderGroup]:
    """Ancestors of `group` nearest first, read from the database (any scope)."""
    chain: list[StakeholderGroup] = []
    seen = {group.id}
    current = group
    while current.parent_group_id is not None and current.parent_group_id not in seen and len(chain) < MAX_GROUP_DEPTH * 2:
        parent = db.get(StakeholderGroup, current.parent_group_id)
        if parent is None:
            break
        chain.append(parent)
        seen.add(parent.id)
        current = parent
    return chain


def _db_subtree(db: Session, group: StakeholderGroup) -> dict[uuid.UUID, StakeholderGroup]:
    """`group` and all its descendants read from the database (any scope), keyed by id."""
    found = {group.id: group}
    frontier = [group.id]
    while frontier and len(found) < 5000:
        children = db.scalars(select(StakeholderGroup).where(StakeholderGroup.parent_group_id.in_(frontier))).all()
        frontier = []
        for child in children:
            if child.id not in found:
                found[child.id] = child
                frontier.append(child.id)
    return found


def _height(subtree: dict[uuid.UUID, StakeholderGroup], group: StakeholderGroup) -> int:
    """Levels below `group` within `subtree` (0 for a leaf)."""
    children: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for g in subtree.values():
        if g.parent_group_id is not None:
            children[g.parent_group_id].append(g.id)
    height, frontier = 0, [group.id]
    while True:
        frontier = [c for gid in frontier for c in children.get(gid, [])]
        if not frontier or height > MAX_GROUP_DEPTH * 2:
            return height
        height += 1


# --- Lookup ----------------------------------------------------------------------------------


def get_group_in_scope(
    db: Session, scope: StakeholderScope, *, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    group_id: uuid.UUID,
) -> StakeholderGroup:
    """A group of exactly this scope owner.

    Raises:
        GroupRuleError: 404 if absent, of another scope, or owned by another organisation/project.
    """
    group = db.get(StakeholderGroup, group_id)
    owned = group is not None and group.scope == scope and (
        group.organization_id == organization_id if scope == StakeholderScope.ORGANIZATION
        else group.project_id == project_id
    )
    if not owned:
        raise GroupRuleError("Stakeholder group not found.", 404)
    return group


# --- Create / update / delete ----------------------------------------------------------------


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise GroupRuleError("A group needs a name.", 400)
    return name


def _owner_filters(scope: StakeholderScope, organization_id: uuid.UUID, project_id: uuid.UUID | None) -> list:
    return [
        StakeholderGroup.scope == scope,
        StakeholderGroup.organization_id == organization_id if scope == StakeholderScope.ORGANIZATION
        else StakeholderGroup.project_id == project_id,
    ]


def sibling_filters(group_scope: StakeholderScope, organization_id: uuid.UUID, project_id: uuid.UUID | None,
                    parent_group_id: uuid.UUID | None) -> list:
    """Filter expressions selecting a group's siblings (same owner and parent)."""
    parent = StakeholderGroup.parent_group_id.is_(None) if parent_group_id is None else StakeholderGroup.parent_group_id == parent_group_id
    return [*_owner_filters(group_scope, organization_id, project_id), parent]


def _assert_name_free(
    db: Session, scope: StakeholderScope, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    parent_group_id: uuid.UUID | None, name: str, *, except_id: uuid.UUID | None = None,
) -> None:
    clash = db.scalar(select(StakeholderGroup.id).where(
        *sibling_filters(scope, organization_id, project_id, parent_group_id),
        func.lower(StakeholderGroup.name) == name.lower(),
        *([StakeholderGroup.id != except_id] if except_id else []),
    ))
    if clash is not None:
        raise GroupRuleError(f"A group named {name!r} already exists here.", 409)


def _validate_parent(
    db: Session, scope: StakeholderScope, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    parent_group_id: uuid.UUID, *, own_subtree: dict[uuid.UUID, StakeholderGroup] | None = None,
    own: StakeholderGroup | None = None,
) -> StakeholderGroup:
    """The parent group, after the scope, cycle and depth rules.

    Raises:
        GroupRuleError: 400 if the parent is absent/out of reach or the depth cap would be exceeded;
            409 if it would create a cycle.
    """
    universe = load_groups(db, organization_id, project_id if scope == StakeholderScope.PROJECT else None)
    parent = universe.get(parent_group_id)
    if parent is None:
        raise GroupRuleError("Parent group not found.", 400)
    if own is not None and own_subtree is not None and parent.id in own_subtree:
        raise GroupRuleError("A group cannot be moved under itself or one of its own descendants.", 409)
    below = 0 if own is None or own_subtree is None else _height(own_subtree, own)
    if len(ancestor_chain(universe, parent.id)) + 2 + below > MAX_GROUP_DEPTH:
        raise GroupRuleError(f"Groups can be nested at most {MAX_GROUP_DEPTH} levels deep.", 400)
    return parent


def create_group(
    db: Session, *, scope: StakeholderScope, organization_id: uuid.UUID, project_id: uuid.UUID | None, name: str,
    description: str = "", parent_group_id: uuid.UUID | None = None, exclusive_children: bool = False,
) -> StakeholderGroup:
    """Creates a group as the last of its siblings.

    Raises:
        GroupRuleError: On a blank/duplicate name, an unreachable parent or a too-deep tree.
    """
    name = _clean_name(name)
    if parent_group_id is not None:
        _validate_parent(db, scope, organization_id, project_id, parent_group_id)
    _assert_name_free(db, scope, organization_id, project_id, parent_group_id, name)
    last = db.scalar(select(func.max(StakeholderGroup.sort_order)).where(
        *sibling_filters(scope, organization_id, project_id, parent_group_id)
    ))
    code_scope = code_owner(
        db, is_org_scope=scope == StakeholderScope.ORGANIZATION, organization_id=organization_id, project_id=project_id
    )
    group = StakeholderGroup(
        scope=scope, organization_id=organization_id if scope == StakeholderScope.ORGANIZATION else None,
        project_id=project_id if scope == StakeholderScope.PROJECT else None,
        unique_code=generate_unique_code(db, code_scope, GROUP_ARTEFACT_TYPE, GROUP_CODE_PREFIX),
        parent_group_id=parent_group_id, name=name, description=description or "", exclusive_children=exclusive_children,
        sort_order=0 if last is None else last + 1,
    )
    db.add(group)
    db.flush()
    return group


def update_group(
    db: Session, group: StakeholderGroup, organization_id: uuid.UUID, project_id: uuid.UUID | None, changes: dict,
) -> StakeholderGroup:
    """Applies a partial edit (`name`, `description`, `exclusive_children`, `parent_group_id`).

    Raises:
        GroupRuleError: On a blank/duplicate name, a bad move, or when the new shape would leave a
            stakeholder in two branches of an exclusive group.
    """
    new_parent = changes["parent_group_id"] if "parent_group_id" in changes else group.parent_group_id
    new_name = _clean_name(changes["name"]) if "name" in changes else group.name
    if new_parent != group.parent_group_id:
        subtree = _db_subtree(db, group)
        if new_parent is not None:
            _validate_parent(db, group.scope, organization_id, project_id, new_parent, own_subtree=subtree, own=group)
        group.sort_order = (db.scalar(select(func.max(StakeholderGroup.sort_order)).where(
            *sibling_filters(group.scope, organization_id, project_id, new_parent)
        )) or -1) + 1
    if new_parent != group.parent_group_id or new_name != group.name:
        _assert_name_free(db, group.scope, organization_id, project_id, new_parent, new_name, except_id=group.id)
    group.parent_group_id, group.name = new_parent, new_name
    if "description" in changes:
        group.description = changes["description"] or ""
    if "exclusive_children" in changes:
        group.exclusive_children = bool(changes["exclusive_children"])
    db.flush()
    if "exclusive_children" in changes or "parent_group_id" in changes:
        assert_exclusive_integrity(db, group)
    return group


def delete_group(db: Session, group: StakeholderGroup) -> tuple[int, int]:
    """Deletes a group: its memberships and every `ArtefactLink` touching it (an Engagement's audience
    link, a Requirement's "affects") go (never the stakeholders) and its children are promoted
    to its parent. Returns `(members removed, children promoted)`.

    Raises:
        GroupRuleError: 409 if a promoted child's name clashes with a sibling at the new level, or
            promotion would put a stakeholder in two branches of an exclusive parent.
    """
    children = list(db.scalars(select(StakeholderGroup).where(StakeholderGroup.parent_group_id == group.id)))
    for child in children:
        clash = db.scalar(select(StakeholderGroup.id).where(
            *sibling_filters(child.scope, child.organization_id, child.project_id, group.parent_group_id),
            func.lower(StakeholderGroup.name) == child.name.lower(), StakeholderGroup.id != child.id,
        ))
        if clash is not None:
            # A project's group under an organisation group is not named: the deleter may not be in that project.
            label = repr(child.name) if child.scope == group.scope else "a project group"
            raise GroupRuleError(
                f"Cannot delete: promoting {label} would clash with a sibling of the same name. Rename one first.", 409,
            )
    member_count = db.scalar(select(func.count()).select_from(StakeholderGroupMember).where(
        StakeholderGroupMember.group_id == group.id)) or 0
    parent_id = group.parent_group_id
    for child in children:
        child.parent_group_id = parent_id
    db.execute(delete(StakeholderGroupMember).where(StakeholderGroupMember.group_id == group.id))
    for link in get_all_links(db, GROUP_ARTEFACT_TYPE, group.id, include_cross_project=True):
        delete_link(db, link)
    db.flush()
    db.delete(group)
    db.flush()
    if parent_id is not None:
        parent = db.get(StakeholderGroup, parent_id)
        if parent is not None:
            assert_exclusive_integrity(db, parent)
    return member_count, len(children)


# --- Membership ------------------------------------------------------------------------------


def _branch_under(chain_nodes: list[StakeholderGroup], node_id: uuid.UUID) -> uuid.UUID | None:
    """Given `[g, parent, grandparent, …]`, the child of `node_id` on the path (None if `node_id` isn't above)."""
    for i, g in enumerate(chain_nodes):
        if g.id == node_id:
            return chain_nodes[i - 1].id if i > 0 else None
    return None


def _exclusive_conflict(
    db: Session, group: StakeholderGroup, stakeholder_id: uuid.UUID, universe: dict[uuid.UUID, StakeholderGroup],
) -> str | None:
    """Why adding the stakeholder to `group` would break an `exclusive_children` ancestor, else None."""
    mine = [group, *ancestor_chain(universe, group.id)]
    existing = db.scalars(select(StakeholderGroupMember.group_id).where(
        StakeholderGroupMember.stakeholder_id == stakeholder_id, StakeholderGroupMember.group_id != group.id
    )).all()
    for i, node in enumerate(mine[1:], start=1):
        if not node.exclusive_children:
            continue
        my_branch = mine[i - 1].id
        for gid in existing:
            other = universe.get(gid)
            if other is None:
                continue
            other_branch = _branch_under([other, *ancestor_chain(universe, other.id)], node.id)
            if other_branch is not None and other_branch != my_branch:
                return (
                    f"{node.name!r} allows one branch per stakeholder, and this stakeholder is already in "
                    f"{universe[other_branch].name!r}."
                )
    return None


def add_member(
    db: Session, group: StakeholderGroup, stakeholder: Stakeholder, universe: dict[uuid.UUID, StakeholderGroup],
    organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> StakeholderGroupMember:
    """Adds `stakeholder` to `group` directly.

    Raises:
        GroupRuleError: 400 if the scope rules forbid the pair; 409 on a duplicate or an
            `exclusive_children` conflict naming the existing branch.
    """
    if group.scope == StakeholderScope.ORGANIZATION:
        allowed = stakeholder.scope == StakeholderScope.ORGANIZATION and stakeholder.organization_id == organization_id
    else:
        allowed = (stakeholder.scope == StakeholderScope.PROJECT and stakeholder.project_id == project_id) or (
            stakeholder.scope == StakeholderScope.ORGANIZATION and stakeholder.organization_id == organization_id
        )
    if not allowed:
        raise GroupRuleError("That Stakeholder cannot be added to this group.", 400)
    if db.scalar(select(StakeholderGroupMember.id).where(
        StakeholderGroupMember.group_id == group.id, StakeholderGroupMember.stakeholder_id == stakeholder.id
    )) is not None:
        raise GroupRuleError("This Stakeholder is already in the group.", 409)
    conflict = _exclusive_conflict(db, group, stakeholder.id, universe)
    if conflict:
        raise GroupRuleError(conflict, 409)
    member = StakeholderGroupMember(group_id=group.id, stakeholder_id=stakeholder.id)
    db.add(member)
    db.flush()
    return member


def remove_member(db: Session, group: StakeholderGroup, stakeholder_id: uuid.UUID) -> bool:
    """Removes a direct membership. Returns whether one existed."""
    result = db.execute(delete(StakeholderGroupMember).where(
        StakeholderGroupMember.group_id == group.id, StakeholderGroupMember.stakeholder_id == stakeholder_id
    ))
    return bool(result.rowcount)


def _branch_in(subtree: dict[uuid.UUID, StakeholderGroup], node_id: uuid.UUID, group: StakeholderGroup) -> uuid.UUID | None:
    """The direct child of `node_id` that `group` sits under (or is), within `subtree`; None if not below it."""
    steps = 0
    while group.parent_group_id is not None and steps < MAX_GROUP_DEPTH * 2:
        if group.parent_group_id == node_id:
            return group.id
        parent = subtree.get(group.parent_group_id)
        if parent is None:
            return None
        group, steps = parent, steps + 1
    return None


def assert_exclusive_integrity(db: Session, group: StakeholderGroup) -> None:
    """After a structural change, checks `group` and its ancestors that are exclusive still hold
    (no stakeholder in two direct-child branches).

    Raises:
        GroupRuleError: 409 if some stakeholder is in several branches of an exclusive group.
    """
    for node in [group, *_db_chain(db, group)]:
        if not node.exclusive_children:
            continue
        subtree = _db_subtree(db, node)

        branches: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for sid, gid in db.execute(select(StakeholderGroupMember.stakeholder_id, StakeholderGroupMember.group_id).where(
            StakeholderGroupMember.group_id.in_(list(subtree))
        )).all():
            branch = _branch_in(subtree, node.id, subtree[gid])
            if branch is not None:
                branches[sid].add(branch)
        if any(len(b) > 1 for b in branches.values()):
            raise GroupRuleError(
                f"{node.name!r} allows one branch per stakeholder, but some stakeholders are already in several of "
                "its branches. Remove them from all but one first.",
                409,
            )


def set_tier_memberships(
    db: Session, stakeholder: Stakeholder, wanted_ids: set[uuid.UUID], scope: StakeholderScope,
    universe: dict[uuid.UUID, StakeholderGroup], organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Makes the stakeholder's memberships in groups of `scope` equal `wanted_ids`, leaving groups
    of the other scope alone. Returns `(added ids, removed ids)`.

    Raises:
        GroupRuleError: 400 if a wanted id is not a reachable group of `scope`; otherwise as `add_member`.
    """
    tier = {gid for gid, g in universe.items() if g.scope == scope}
    if not wanted_ids <= tier:
        raise GroupRuleError("A group was not found.", 400)
    current = set(db.scalars(select(StakeholderGroupMember.group_id).where(
        StakeholderGroupMember.stakeholder_id == stakeholder.id, StakeholderGroupMember.group_id.in_(tier or {uuid.uuid4()})
    )))
    removed = current - wanted_ids
    for gid in removed:
        remove_member(db, universe[gid], stakeholder.id)
    added = wanted_ids - current
    for gid in sorted(added, key=lambda i: universe[i].name):
        add_member(db, universe[gid], stakeholder, universe, organization_id, project_id)
    return added, removed


# --- Reading ---------------------------------------------------------------------------------


def group_refs(
    db: Session, stakeholder_ids: list[uuid.UUID], universe: dict[uuid.UUID, StakeholderGroup]
) -> dict[uuid.UUID, list[GroupRef]]:
    """Each stakeholder's direct groups within `universe`, ordered by name."""
    out: dict[uuid.UUID, list[GroupRef]] = {sid: [] for sid in stakeholder_ids}
    if not stakeholder_ids or not universe:
        return out
    rows = db.execute(select(StakeholderGroupMember.stakeholder_id, StakeholderGroupMember.group_id).where(
        StakeholderGroupMember.stakeholder_id.in_(stakeholder_ids), StakeholderGroupMember.group_id.in_(list(universe))
    )).all()
    for sid, gid in rows:
        g = universe[gid]
        out[sid].append(GroupRef(
            id=g.id, name=g.name, scope=g.scope, parent_group_id=g.parent_group_id, unique_code=g.unique_code,
            organization_id=g.organization_id,
        ))
    for refs in out.values():
        refs.sort(key=lambda r: r.name.lower())
    return out


def member_ids(db: Session, group_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The stakeholders directly in any of `group_ids` (pass a group plus its descendants for transitive membership)."""
    if not group_ids:
        return set()
    return set(db.scalars(select(StakeholderGroupMember.stakeholder_id).where(
        StakeholderGroupMember.group_id.in_(list(group_ids))
    )))


def branch_sort_key(
    refs: list[GroupRef], universe: dict[uuid.UUID, StakeholderGroup], root_id: uuid.UUID
) -> tuple[int, str]:
    """Sort key for a stakeholder by its branch under the root group `root_id`: the alphabetically
    first branch name (a stakeholder in several branches sorts by that one); unassigned sort last."""
    names = [name.lower() for name in branch_names(refs, universe, root_id)]
    return (0, min(names)) if names else (1, "")


def branch_names(refs: list[GroupRef], universe: dict[uuid.UUID, StakeholderGroup], root_id: uuid.UUID) -> list[str]:
    """The names of the branches under the root group `root_id` that a stakeholder's groups sit in
    (one per branch, alphabetical; empty when none of their groups is under the root)."""
    names: set[str] = set()
    for ref in refs:
        chain = [universe[ref.id], *ancestor_chain(universe, ref.id)]
        branch = _branch_under(chain, root_id)
        if branch is not None:
            names.add(universe[branch].name)
    return sorted(names, key=str.lower)


# --- From free text --------------------------------------------------------------------------


def text_proposals(
    db: Session, stakeholders: list[Stakeholder], universe: dict[uuid.UUID, StakeholderGroup]
) -> list[dict]:
    """Distinct non-blank `organisation_group` values (case-insensitive, first spelling kept) among
    `stakeholders`, each with its stakeholder count and the existing child of the text root with
    that name, if one exists."""
    ids = [s.id for s in stakeholders]
    texts = dict(db.execute(select(StakeholderVersion.stakeholder_id, StakeholderVersion.organisation_group).where(
        StakeholderVersion.stakeholder_id.in_(ids), StakeholderVersion.valid_to.is_(None)
    )).all()) if ids else {}
    counts: dict[str, int] = defaultdict(int)
    spelling: dict[str, str] = {}
    for sid in ids:
        text = (texts.get(sid) or "").strip()
        if text:
            counts[text.lower()] += 1
            spelling.setdefault(text.lower(), text)
    root = next((g for g in universe.values() if g.parent_group_id is None and g.name.lower() == TEXT_ROOT_NAME.lower()), None)
    existing = {g.name.lower(): g.id for g in universe.values() if root and g.parent_group_id == root.id}
    return [
        {"name": spelling[key], "stakeholder_count": counts[key], "existing_group_id": existing.get(key)}
        for key in sorted(counts)
    ]


def create_from_text(
    db: Session, *, scope: StakeholderScope, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    stakeholders: list[Stakeholder], names: list[str],
) -> tuple[StakeholderGroup, list[StakeholderGroup], int]:
    """Creates (or reuses) the "Organisation / group" root, a child per chosen text and the
    memberships that text implies. The root is `exclusive_children` since the text is single-valued.
    Returns `(root, child groups, memberships added)`.

    Raises:
        GroupRuleError: If a chosen name is not among the proposals.
    """
    universe = load_groups(db, organization_id, project_id if scope == StakeholderScope.PROJECT else None)
    proposals = {p["name"].lower(): p for p in text_proposals(db, stakeholders, universe)}
    chosen = []
    for name in names:
        if name.strip().lower() not in proposals:
            raise GroupRuleError(f"{name!r} is not an organisation / group value of any Stakeholder.", 400)
        chosen.append(proposals[name.strip().lower()]["name"])
    root = next((g for g in universe.values()
                 if g.scope == scope and g.parent_group_id is None and g.name.lower() == TEXT_ROOT_NAME.lower()), None)
    if root is None:
        root = create_group(db, scope=scope, organization_id=organization_id, project_id=project_id,
                            name=TEXT_ROOT_NAME, exclusive_children=True,
                            description="Created from the Stakeholders' free-text organisation / group field.")
        universe[root.id] = root
    by_name = {g.name.lower(): g for g in universe.values() if g.parent_group_id == root.id}
    texts = dict(db.execute(select(StakeholderVersion.stakeholder_id, StakeholderVersion.organisation_group).where(
        StakeholderVersion.stakeholder_id.in_([s.id for s in stakeholders]), StakeholderVersion.valid_to.is_(None)
    )).all()) if stakeholders else {}
    children, added = [], 0
    for name in chosen:
        child = by_name.get(name.lower())
        if child is None:
            child = create_group(db, scope=scope, organization_id=organization_id, project_id=project_id,
                                 name=name, parent_group_id=root.id)
            universe[child.id] = child
        children.append(child)
        for s in stakeholders:
            if (texts.get(s.id) or "").strip().lower() == name.lower():
                try:
                    add_member(db, child, s, universe, organization_id, project_id)
                    added += 1
                except GroupRuleError as exc:
                    if exc.status_code != 409 or "already in the group" not in str(exc):
                        raise
    return root, children, added
