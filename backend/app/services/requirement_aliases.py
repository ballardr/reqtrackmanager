"""
Module: services.requirement_aliases

Requirement aliases: placing one requirement in further components and categories, each with a code of its own.

Responsibilities:
- Resolve whether new aliases are allowed (`resolve_mode`: the project, its nearest ancestor project that sets one,
  then the organisation) and store the setting (`set_mode`).
- Read a requirement's aliases, singly or for a page in one query (`aliases_for_requirements`), and count a
  project's (`alias_count`).
- Add, retire and promote an alias (`set_aliases`, `retire_alias`, `promote_alias`), issuing each alias code from the
  project's one requirement counter inside the same transaction.
- Find a requirement by any of its codes, primary or alias, retired ones included (`find_by_code`).
- Make an alias independent (`make_independent`): a new draft requirement that takes over the alias code, with the
  original's links, comments, tags and attachments copied under the same rules a person would meet making them.

Design decisions:
- An alias names the same requirement: content, versions, approval, comments, links and attachments are one set.
  The alias is its own table (`models.requirement_alias`) rather than a row of `artefact_placements` because it
  carries a code. The primary pair stays on the requirement; `services.placements.pairs_for_records` presents
  primary then aliases as one view for every placement reader.
- A requirement is always placed under a category, so an alias pair needs a category and is never the primary pair.
- Adding an alias is metadata like a tag (an approved requirement's lock does not apply); promoting one moves the
  primary pair and so follows the requirement's own edit lock.
- The setting only stops new aliases. Existing ones keep resolving and are listed, and can be made independent one
  by one or in bulk, so a project moves to one code per record on purpose, never by a switch removing them.
- Promotion swaps the primary and alias pairs and their codes, so every code still matches the prefixes of the pair
  it names and no code is lost.
- Make independent copies links through `create_link_for_artefact`, so the approved-link lock and the
  organisation's change-request setting apply to the other end exactly as in the Links panel; a link refused is
  reported, never forced through. Copied comments keep their author and time, with a marker, and are never
  attributed to the person who made the copy.

External dependencies: `models.requirement_alias`, `services.placements`, `services.requirements`,
`services.link_authoring`, `services.audit`, `services.project_hierarchy`.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metrics import requirements_created_total
from app.models.change_request import ReviewComment
from app.models.enums import LinkFlow, PrincipalType, ReviewTargetType
from app.models.file import FileAsset, RequirementFile
from app.models.organization import Organization
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement
from app.models.requirement_alias import RequirementAlias
from app.models.user import User
from app.schemas.principal import PrincipalRef
from app.services.audit import log_event
from app.services.files import read_file, upload_file
from app.services.link_authoring import create_link_for_artefact, usable_options
from app.services.link_graph import ArtefactResolver
from app.services.placements import MAX_PLACEMENTS_PER_RECORD, PlacementPair, placement_text, resolve_pairs
from app.services.project_hierarchy import get_project_chain_ids
from app.services.relationships import create_link, get_links_touching_many
from app.services.requirements import (
    create_requirement,
    generate_unique_code,
    get_current_version_for_update,
    get_keywords,
    is_locked,
)

logger = logging.getLogger(__name__)

MODE_ALLOWED = "allowed"
MODE_DISABLED = "disabled"
MODES = (MODE_ALLOWED, MODE_DISABLED)

ModeSource = Literal["project", "parent_project", "organization"]

_REQUIREMENT = "requirement"


@dataclass(frozen=True)
class ModeResolution:
    """The effective alias setting of a project.

    Attributes:
        mode: `allowed` or `disabled`.
        source: Which tier set it: the project itself, an ancestor project, or the organisation.
    """

    mode: str
    source: ModeSource

    @property
    def allowed(self) -> bool:
        """Whether new aliases may be added."""
        return self.mode == MODE_ALLOWED


# --- the setting ------------------------------------------------------------------------------


def _validate_mode(mode: str) -> str:
    """Returns `mode` when it is a known setting.

    Raises:
        HTTPException: 422 for anything else.
    """
    if mode not in MODES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The setting must be Allowed or Disabled.")
    return mode


def resolve_mode(db: Session, project: Project) -> ModeResolution:
    """The alias setting that applies to `project`: its own, else the nearest ancestor project's, else the
    organisation's (the nested-project rule for a sparse override)."""
    for index, project_id in enumerate(get_project_chain_ids(db, project.id)):
        mode = db.scalar(select(Project.requirement_aliases).where(Project.id == project_id))
        if mode:
            return ModeResolution(mode, "project" if index == 0 else "parent_project")
    organisation = db.get(Organization, project.organization_id)
    return ModeResolution(organisation.requirement_aliases if organisation else MODE_ALLOWED, "organization")


def aliases_allowed(db: Session, project: Project) -> bool:
    """Whether new aliases may be added in `project`."""
    return resolve_mode(db, project).allowed


def require_allowed(db: Session, project: Project) -> None:
    """Raises 409 when the project's setting forbids new aliases."""
    if not aliases_allowed(db, project):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Requirement aliases are disabled for this project, so a requirement cannot be placed in another component.",
        )


def set_mode(
    db: Session, *, project: Project | None, organization: Organization | None, actor_id: uuid.UUID, mode: str | None,
) -> None:
    """Sets the project's alias setting (`None` inherits) or the organisation's.

    Raises:
        HTTPException: 422 for an unknown value, or `None` for an organisation.
    """
    if project is not None:
        project.requirement_aliases = None if mode is None else _validate_mode(mode)
        log_event(
            db, entity_type="requirement_alias_settings", entity_id=project.id, action="updated", actor_id=actor_id,
            organization_id=project.organization_id, project_id=project.id, detail={"requirement_aliases": project.requirement_aliases},
        )
    elif organization is not None:
        if mode is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An organisation must choose Allowed or Disabled.")
        organization.requirement_aliases = _validate_mode(mode)
        log_event(
            db, entity_type="requirement_alias_settings", entity_id=organization.id, action="updated", actor_id=actor_id,
            organization_id=organization.id, detail={"requirement_aliases": organization.requirement_aliases},
        )
    db.flush()


# --- reading ----------------------------------------------------------------------------------


def _ordered(query):
    """Orders an alias query by the tree's display order, then by code."""
    return (
        query.outerjoin(ProjectComponent, ProjectComponent.id == RequirementAlias.component_id)
        .outerjoin(ProjectCategory, ProjectCategory.id == RequirementAlias.category_id)
        .order_by(
            ProjectComponent.sort_order, ProjectComponent.name, ProjectCategory.sort_order, ProjectCategory.name,
            RequirementAlias.unique_code,
        )
    )


def aliases_for_requirements(
    db: Session, requirement_ids: Iterable[uuid.UUID], *, include_retired: bool = False,
) -> dict[uuid.UUID, list[RequirementAlias]]:
    """The aliases of several requirements in one query (`{requirement id: aliases}`, absent = none)."""
    ids = list(requirement_ids)
    found: dict[uuid.UUID, list[RequirementAlias]] = defaultdict(list)
    if not ids:
        return found
    query = select(RequirementAlias).where(RequirementAlias.requirement_id.in_(ids))
    if not include_retired:
        query = query.where(RequirementAlias.is_retired.is_(False))
    for row in db.scalars(_ordered(query)).all():
        found[row.requirement_id].append(row)
    return found


def active_aliases(db: Session, requirement_id: uuid.UUID) -> list[RequirementAlias]:
    """A requirement's active aliases in tree order."""
    return aliases_for_requirements(db, [requirement_id]).get(requirement_id, [])


def alias_count(db: Session, project_id: uuid.UUID) -> int:
    """How many active aliases the project holds (one grouped read for the settings panel)."""
    return int(
        db.scalar(
            select(func.count()).select_from(RequirementAlias).where(
                RequirementAlias.project_id == project_id, RequirementAlias.is_retired.is_(False)
            )
        )
        or 0
    )


def project_aliases(db: Session, project_id: uuid.UUID) -> list[RequirementAlias]:
    """Every active alias of the project, in tree order (the bulk make-independent reads this)."""
    return list(db.scalars(_ordered(select(RequirementAlias).where(
        RequirementAlias.project_id == project_id, RequirementAlias.is_retired.is_(False)
    ))).all())


def get_alias(db: Session, project_id: uuid.UUID, requirement_id: uuid.UUID, alias_id: uuid.UUID) -> RequirementAlias:
    """The requirement's alias.

    Raises:
        HTTPException: 404 when there is no such alias on the requirement in the project.
    """
    alias = db.get(RequirementAlias, alias_id)
    if alias is None or alias.project_id != project_id or alias.requirement_id != requirement_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alias not found.")
    return alias


@dataclass(frozen=True)
class CodeMatch:
    """A requirement found by one of its codes.

    Attributes:
        requirement: The requirement.
        alias: The alias row when the code is an alias code, `None` for the primary code.
    """

    requirement: Requirement
    alias: RequirementAlias | None

    @property
    def is_retired(self) -> bool:
        """Whether the code was retired (the requirement was taken out of that place)."""
        return self.alias is not None and self.alias.is_retired


def find_by_code(db: Session, project_id: uuid.UUID, code: str) -> CodeMatch | None:
    """The requirement a code names in the project, primary or alias, retired aliases included."""
    code = code.strip().upper()
    requirement = db.scalar(select(Requirement).where(Requirement.project_id == project_id, Requirement.unique_code == code))
    if requirement is not None:
        return CodeMatch(requirement, None)
    alias = db.scalar(select(RequirementAlias).where(RequirementAlias.project_id == project_id, RequirementAlias.unique_code == code))
    if alias is None:
        return None
    requirement = db.get(Requirement, alias.requirement_id)
    return CodeMatch(requirement, alias) if requirement is not None else None


def find_many_by_code(db: Session, project_id: uuid.UUID, codes: Sequence[str]) -> dict[str, Requirement]:
    """The requirements the codes name in the project (`{UPPER code: requirement}`), alias codes included, in two
    statements."""
    wanted = sorted({c.strip().upper() for c in codes if c and c.strip()})
    if not wanted:
        return {}
    found: dict[str, Requirement] = {
        r.unique_code: r
        for r in db.scalars(select(Requirement).where(Requirement.project_id == project_id, Requirement.unique_code.in_(wanted)))
    }
    rest = [c for c in wanted if c not in found]
    if rest:
        for alias, requirement in db.execute(
            select(RequirementAlias, Requirement)
            .join(Requirement, Requirement.id == RequirementAlias.requirement_id)
            .where(RequirementAlias.project_id == project_id, RequirementAlias.unique_code.in_(rest))
        ).tuples():
            found[alias.unique_code] = requirement
    return found


# --- writing ----------------------------------------------------------------------------------


def _text(db: Session, pair: PlacementPair) -> str:
    """The pair as `Component / Category`."""
    return placement_text(db, [pair])[0]


def _audit(
    db: Session, project: Project, actor_id: uuid.UUID | None, requirement: Requirement, action: str, detail: dict[str, str],
) -> None:
    """Writes an alias event against the requirement (what its Activity tab reads)."""
    log_event(
        db, entity_type=_REQUIREMENT, entity_id=requirement.id, action=action, actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id, detail=detail,
    )


def _pair_of(alias: RequirementAlias) -> PlacementPair:
    """The alias's pair (an active alias always has both parts)."""
    if alias.component_id is None or alias.category_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That alias no longer has a component and category.")
    return PlacementPair(alias.component_id, alias.category_id)


def _new_code(db: Session, project: Project, pair: PlacementPair) -> str:
    """Numbers an alias code `COMPONENT-CATEGORY-nnn` from the project's one requirement counter."""
    component = db.get(ProjectComponent, pair.component_id)
    category = db.get(ProjectCategory, pair.category_id) if pair.category_id else None
    if component is None or category is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A component and category are required.")
    return generate_unique_code(db, project, component, category)


@dataclass
class AliasChange:
    """What `set_aliases` did: the aliases added and the ones retired."""

    added: list[RequirementAlias] = field(default_factory=list)
    retired: list[RequirementAlias] = field(default_factory=list)


def set_aliases(
    db: Session, *, project: Project, requirement: Requirement, actor_id: uuid.UUID | None, pairs: Sequence[PlacementPair],
) -> AliasChange:
    """Makes the requirement sit in exactly its primary pair plus `pairs`.

    A pair already held keeps its alias and code; a pair no longer wanted retires its alias (the code keeps
    resolving); a new pair gets a fresh code, which needs the project's setting to allow aliases.

    Args:
        db: Active session; rows and audit events are added, not committed.
        project: The requirement's project.
        requirement: The requirement; the caller has authorised the change.
        actor_id: The acting user.
        pairs: The wanted further places (each needs a category and differs from the primary pair).

    Returns:
        The aliases added and retired.

    Raises:
        HTTPException: 422 for an invalid pair, a pair without a category or the primary pair, or too many;
            409 when a new alias is wanted and the project's setting disables them.
    """
    wanted = resolve_pairs(db, project, pairs)
    primary = PlacementPair(requirement.component_id, requirement.category_id)
    for pair in wanted:
        if pair.category_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A requirement is placed in a category, so choose one for each component.")
        if pair == primary:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That is already the requirement's own component and category.")
    if len(wanted) + 1 > MAX_PLACEMENTS_PER_RECORD:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"A record can sit in at most {MAX_PLACEMENTS_PER_RECORD} places."
        )
    current = {_pair_key(a): a for a in active_aliases(db, requirement.id)}
    result = AliasChange()
    for key, alias in current.items():
        if key not in set(wanted):
            retire_alias(db, project, requirement, alias, actor_id)
            result.retired.append(alias)
    new_pairs = [pair for pair in wanted if pair not in current]
    if new_pairs:
        require_allowed(db, project)
    for pair in new_pairs:
        alias = RequirementAlias(
            project_id=project.id, requirement_id=requirement.id, component_id=pair.component_id,
            category_id=pair.category_id, unique_code=_new_code(db, project, pair), created_by=actor_id,
        )
        db.add(alias)
        db.flush()
        _audit(db, project, actor_id, requirement, "alias_added", {"code": alias.unique_code, "place": _text(db, pair)})
        result.added.append(alias)
    return result


def _pair_key(alias: RequirementAlias) -> PlacementPair:
    """An active alias's pair as a hashable key."""
    return _pair_of(alias)


def retire_alias(
    db: Session, project: Project, requirement: Requirement, alias: RequirementAlias, actor_id: uuid.UUID | None,
) -> None:
    """Takes the requirement out of the alias's place and retires the code (never reused; it still resolves)."""
    if alias.is_retired:
        return
    detail = {"code": alias.unique_code}
    if alias.component_id is not None and alias.category_id is not None:
        detail["place"] = _text(db, PlacementPair(alias.component_id, alias.category_id))
    alias.is_retired = True
    alias.retired_at = datetime.now(UTC)
    _audit(db, project, actor_id, requirement, "alias_retired", detail)
    db.flush()


def drop_redundant(db: Session, project: Project, requirement: Requirement, actor_id: uuid.UUID | None) -> None:
    """Retires the alias that names the requirement's own (new) primary place, after the requirement moved there."""
    for alias in active_aliases(db, requirement.id):
        if alias.component_id == requirement.component_id and alias.category_id == requirement.category_id:
            retire_alias(db, project, requirement, alias, actor_id)


def promote_alias(
    db: Session, project: Project, requirement: Requirement, alias: RequirementAlias, actor_id: uuid.UUID | None,
) -> None:
    """Makes the alias's place the requirement's primary one, swapping the two places and their codes.

    Raises:
        HTTPException: 409 when the requirement is approved (moving its own component and category is an edit,
            which an approved requirement takes through a change request) or the alias is retired.
    """
    if alias.is_retired:
        raise HTTPException(status.HTTP_409_CONFLICT, "That alias is retired.")
    version = get_current_version_for_update(db, requirement.id)
    if is_locked(version):
        raise HTTPException(status.HTTP_409_CONFLICT, "This requirement is approved; changes must be made via a change request.")
    pair = _pair_of(alias)
    new_category_id = pair.category_id
    if new_category_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That alias no longer has a category.")
    old_component_id, old_category_id = requirement.component_id, requirement.category_id
    old_code, new_code = requirement.unique_code, alias.unique_code
    requirement.component_id, requirement.category_id = pair.component_id, new_category_id
    requirement.unique_code = new_code
    alias.component_id, alias.category_id = old_component_id, old_category_id
    alias.unique_code = old_code
    db.flush()
    _audit(db, project, actor_id, requirement, "alias_promoted", {
        "code": new_code, "previous_code": old_code, "place": _text(db, pair),
    })


# --- make independent -------------------------------------------------------------------------


@dataclass
class SkippedItem:
    """Something `make_independent` could not copy and why.

    Attributes:
        kind: `link`, `comment` or `attachment`.
        label: What it was (a link's far record and type, a file name).
        reason: Why it was left out.
    """

    kind: Literal["link", "comment", "attachment"]
    label: str
    reason: str


@dataclass
class IndependentResult:
    """The outcome of making an alias independent.

    Attributes:
        requirement: The new requirement (it now holds the alias code).
        original_id: The requirement the alias belonged to.
        links_copied / comments_copied / attachments_copied / tags_copied: How many were carried over.
        related_link_made: Whether the Related to link between the pair was made.
        skipped: Everything not carried over, with the reason.
    """

    requirement: Requirement
    original_id: uuid.UUID
    links_copied: int = 0
    comments_copied: int = 0
    attachments_copied: int = 0
    tags_copied: int = 0
    related_link_made: bool = False
    skipped: list[SkippedItem] = field(default_factory=list)


def default_related_link_type(db: Session, project: Project) -> uuid.UUID | None:
    """The link type to join an independent copy to its original: the first usable symmetric type with no
    traceability flow ("Related to"), or `None` when the organisation has none."""
    for option in usable_options(db, project, _REQUIREMENT, _REQUIREMENT):
        link_type = option.link_type
        if link_type.flow == LinkFlow.NONE and link_type.forward_name == link_type.reverse_name and option.outgoing:
            return link_type.id
    return None


def _copy_links(
    db: Session, *, project: Project, actor: User, original: Requirement, copy: Requirement, note: str,
    result: IndependentResult,
) -> None:
    """Copies the original's links onto the copy as new links, through the same gates the Links panel applies."""
    links = get_links_touching_many(db, {_REQUIREMENT: [original.id]})
    resolver = ArtefactResolver(db, project, actor.id)
    for link in links:
        outgoing = link.source_type == _REQUIREMENT and link.source_id == original.id
        other_type, other_id = (link.target_type, link.target_id) if outgoing else (link.source_type, link.source_id)
        if (other_type, other_id) == (_REQUIREMENT, original.id):
            continue
        resolver.resolve({other_type: {other_id}})
        far = resolver.visible((other_type, other_id))
        label = far.label if far is not None else "a record outside this project"
        far_project_id = link.target_project_id if outgoing else link.source_project_id
        try:
            with db.begin_nested():
                if link.link_type_id is None:
                    copied = create_link(
                        db, source_type=_REQUIREMENT if outgoing else other_type,
                        source_id=copy.id if outgoing else other_id,
                        target_type=other_type if outgoing else _REQUIREMENT,
                        target_id=other_id if outgoing else copy.id,
                        link_type_id=None, created_by=actor.id, project_id=project.id,
                    )
                else:
                    created = create_link_for_artefact(
                        db, project=project, user_id=actor.id, artefact_type=_REQUIREMENT, artefact_id=copy.id,
                        link_type_id=link.link_type_id, outgoing=outgoing, other_type=other_type, other_id=other_id,
                        other_project_id=far_project_id if far_project_id and far_project_id != project.id else None,
                    )
                    copied = created.link
                copied.note = note
                db.flush()
            result.links_copied += 1
        except HTTPException as exc:
            result.skipped.append(SkippedItem("link", label, str(exc.detail)))
        except Exception as exc:  # a rule error from `create_link` for a type pair the copy cannot take
            logger.info("link not copied on make independent: %s", exc)
            result.skipped.append(SkippedItem("link", label, str(exc)))


def _copy_comments(db: Session, *, original: Requirement, copy: Requirement, original_code: str, result: IndependentResult) -> None:
    """Copies the original's discussion as new comments that keep their author and time and say where they came from."""
    comments = db.scalars(
        select(ReviewComment)
        .where(ReviewComment.target_type == ReviewTargetType.REQUIREMENT, ReviewComment.target_id == original.id)
        .order_by(ReviewComment.created_at)
    ).all()
    for comment in comments:
        db.add(ReviewComment(
            target_type=ReviewTargetType.REQUIREMENT, target_id=copy.id, author_id=comment.author_id,
            body=f"*Copied from {original_code}.*\n\n{comment.body}", created_at=comment.created_at,
            updated_at=comment.updated_at, edited_at=comment.edited_at,
        ))
        result.comments_copied += 1


def _copy_attachments(
    db: Session, *, project: Project, actor: User, original: Requirement, copy: Requirement, result: IndependentResult,
) -> None:
    """Attaches the original's files to the copy: a shared organisation resource is linked, a direct upload is
    stored again so removing it from one requirement never removes it from the other."""
    assets = db.scalars(
        select(FileAsset).join(RequirementFile, FileAsset.id == RequirementFile.file_id)
        .where(RequirementFile.requirement_id == original.id)
    ).all()
    for asset in assets:
        if asset.is_org_resource:
            db.add(RequirementFile(requirement_id=copy.id, file_id=asset.id, linked_by=actor.id, created_at=datetime.now(UTC)))
            result.attachments_copied += 1
            continue
        try:
            with db.begin_nested():
                stored = upload_file(
                    db, organization_id=project.organization_id, uploaded_by=actor.id, filename=asset.filename,
                    content_type=asset.content_type, data=read_file(asset),
                )
                db.flush()
                db.add(RequirementFile(requirement_id=copy.id, file_id=stored.id, linked_by=actor.id, created_at=datetime.now(UTC)))
            result.attachments_copied += 1
        except HTTPException as exc:
            result.skipped.append(SkippedItem("attachment", asset.filename, str(exc.detail)))
        except Exception as exc:  # the stored bytes could not be read
            logger.warning("attachment not copied on make independent: %s", exc)
            result.skipped.append(SkippedItem("attachment", asset.filename, "The stored file could not be read."))


def make_independent(
    db: Session, *, project: Project, alias: RequirementAlias, actor: User, related_link_type_id: uuid.UUID | None = None,
) -> IndependentResult:
    """Turns an alias into a requirement of its own.

    The new requirement is a draft (never approved) holding the current version's content, owned by `actor`,
    with the alias code as its own code and the alias's place as its primary pair. The alias is removed from the
    original, and the pair is joined by a Related to link. Links, comments, tags and attachments are copied.

    Args:
        db: Active session; everything is added, not committed.
        project: The requirement's project.
        alias: An active alias; the caller has authorised the actor to edit the requirement and create one.
        actor: The acting user.
        related_link_type_id: The link type joining the copy to the original; the organisation's symmetric
            no-flow type when omitted.

    Returns:
        What was made and what could not be copied.

    Raises:
        HTTPException: 409 when the alias is retired, has lost its place, or no Related to type exists and none was
            chosen; 400 when the chosen link type is not usable.
    """
    if alias.is_retired:
        raise HTTPException(status.HTTP_409_CONFLICT, "That alias is retired.")
    original = db.get(Requirement, alias.requirement_id)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement not found.")
    pair = _pair_of(alias)
    link_type_id = related_link_type_id or default_related_link_type(db, project)
    if link_type_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This organisation has no Related to link type. Choose a link type to join the new requirement to the original.",
        )
    version = get_current_version_for_update(db, original.id)
    component = db.get(ProjectComponent, pair.component_id)
    category = db.get(ProjectCategory, pair.category_id) if pair.category_id else None
    if component is None or category is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That alias no longer has a component and category.")
    author = db.get(User, version.created_by)
    original_code, alias_code = original.unique_code, alias.unique_code
    keywords = get_keywords(db, original.id)
    count = int(db.scalar(select(func.count()).select_from(Requirement).where(Requirement.project_id == project.id)) or 0)
    db.delete(alias)
    db.flush()
    copy = create_requirement(
        db, project, component, category, actor,
        name=version.name, reasoning=version.reasoning, clarification=version.clarification,
        description=version.description, owner=PrincipalRef(type=PrincipalType.USER, id=actor.id), keywords=keywords,
        sort_order=count, target_stage_id=version.target_stage_id, level=version.level,
        custom_fields=dict(version.custom_fields), review_date=version.review_date,
        review_lead_days=version.review_lead_days, unique_code=alias_code,
        change_note=f"Made independent from {original_code}; content authored by {author.display_name if author else 'a former user'}.",
    )
    requirements_created_total.inc()
    result = IndependentResult(requirement=copy, original_id=original.id, tags_copied=len(keywords))
    note = f"Copied from {original_code}"
    _copy_comments(db, original=original, copy=copy, original_code=original_code, result=result)
    _copy_attachments(db, project=project, actor=actor, original=original, copy=copy, result=result)
    _copy_links(db, project=project, actor=actor, original=original, copy=copy, note=note, result=result)
    try:
        with db.begin_nested():
            created = create_link_for_artefact(
                db, project=project, user_id=actor.id, artefact_type=_REQUIREMENT, artefact_id=copy.id,
                link_type_id=link_type_id, outgoing=True, other_type=_REQUIREMENT, other_id=original.id,
            )
            created.link.note = f"Made independent from {original_code}"
        result.related_link_made = True
    except HTTPException as exc:
        result.skipped.append(SkippedItem("link", original_code, str(exc.detail)))
    place = placement_text(db, [pair])[0]
    _audit(db, project, actor.id, original, "alias_made_independent", {
        "code": alias_code, "place": place, "new_requirement_id": str(copy.id),
    })
    log_event(
        db, entity_type=_REQUIREMENT, entity_id=copy.id, action="created", actor_id=actor.id,
        organization_id=project.organization_id, project_id=project.id,
        detail={"via": "make_independent", "original": original_code, "original_id": str(original.id)},
    )
    db.flush()
    return result
