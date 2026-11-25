"""
Module: modules.decisions.edits

The list query and the create/edit paths of a Decision, shared by the HTTP
endpoints and the record-table export and import so a rule added here reaches both.
- Nothing commits or checks the role: the caller owns both.
- Text fields except the title are Markdown (`MARKDOWN_LIMITS`).
- A refusal is an `HTTPException` (409 locked, 400 unusable type or person).
- An edit changes only the fields supplied.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PrincipalType
from app.models.project import Project
from app.models.user import User
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.models import Decision
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE, DECISION_CODE_PREFIX, resolve_effective_decision_types
from app.schemas.principal import PrincipalRef
from app.services.audit import log_event
from app.services.markdown_text import MarkdownLimitError, validate_markdown
from app.services.principals import principal_filter_clause, validate_principal
from app.services.rbac import user_satisfies_module_role
from app.services.sequences import generate_unique_code

#: A Decision's content becomes immutable once it reaches either of these statuses.
LOCKED_STATUSES = frozenset({DecisionStatus.APPROVED, DecisionStatus.SUPERSEDED})

#: The free-text content fields of a Decision (everything an edit may change except type, date and people).
TEXT_FIELDS = (
    "title", "decision_statement", "context", "options_considered", "chosen_option", "rationale", "consequences",
    "assumptions", "constraints", "document",
)

#: The size limit, in characters, of each field written in Markdown (every text field but the title). The document is
#: the long-form field, so it has the larger limit.
MARKDOWN_LIMITS: dict[str, int] = {
    **{field: 50_000 for field in TEXT_FIELDS if field not in ("title", "document")}, "document": 200_000,
}


def check_markdown_limits(values: Mapping[str, Any]) -> None:
    """Refuses Markdown text over its limits (size, nesting, diagram count and size) with a 422 naming the field.
    Every write path (the endpoints, an import and the record table) goes through the stage functions below, so one
    check covers them all.

    Args:
        values: Field names mapped to the submitted text (a key that is not a Markdown field, or a blank value, is
            skipped).

    Raises:
        HTTPException: 422 when a field breaks a limit.
    """
    for field, limit in MARKDOWN_LIMITS.items():
        text = values.get(field)
        if not text:
            continue
        try:
            validate_markdown(text, max_chars=limit, field=field.replace("_", " ").capitalize())
        except MarkdownLimitError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def user_is_decision_owner(db: Session, user: User, project: Project) -> bool:
    """Whether `user` holds the Decision Owner role on the project (composing with admin and project manager): the
    edit endpoints' gate."""
    return user_satisfies_module_role(
        db, user, "decisions", "decision_owner", organization_id=project.organization_id, project_id=project.id,
    )


def is_locked(decision: Decision) -> bool:
    """Whether the Decision's content can no longer be edited in place (approved or superseded)."""
    return decision.status in LOCKED_STATUSES


def filter_decisions(
    db: Session, user: User, project_id: uuid.UUID, *, include_archived: bool = False, decision_type_id: uuid.UUID | None = None,
    status_filter: DecisionStatus | None = None, owner_type: PrincipalType = PrincipalType.USER, owner_id: uuid.UUID | None = None,
    owner_mine: bool = False, decision_maker_type: PrincipalType = PrincipalType.USER,
    decision_maker_id: uuid.UUID | None = None, decision_maker_mine: bool = False,
) -> list[Decision]:
    """The project's Decisions the list endpoint's filters keep (type, status, one owner or decision maker, or the
    caller's own and their groups'), oldest first. The tag filter and the search box are applied by the caller."""
    query = select(Decision).where(Decision.project_id == project_id)
    if not include_archived:
        query = query.where(Decision.is_archived.is_(False))
    if decision_type_id:
        query = query.where(Decision.decision_type_id == decision_type_id)
    if status_filter:
        query = query.where(Decision.status == status_filter)
    if owner_id:
        query = query.where(Decision.owner_type == owner_type.value, Decision.owner_id == owner_id)
    if owner_mine:
        query = query.where(principal_filter_clause(db, user.id, Decision.owner_type, Decision.owner_id, project_id=project_id))
    if decision_maker_id:
        query = query.where(Decision.decision_maker_type == decision_maker_type.value, Decision.decision_maker_id == decision_maker_id)
    if decision_maker_mine:
        query = query.where(principal_filter_clause(
            db, user.id, Decision.decision_maker_type, Decision.decision_maker_id, project_id=project_id,
        ))
    return list(db.scalars(query.order_by(Decision.created_at)).all())


def search_decisions(decisions: list[Decision], search: str | None) -> list[Decision]:
    """The Decisions whose title, statement or code contains `search` (ignoring case); all of them when blank."""
    if not search:
        return decisions
    needle = search.lower()
    return [
        d for d in decisions
        if needle in d.title.lower() or needle in d.decision_statement.lower() or needle in d.unique_code.lower()
    ]


def validate_effective_decision_type(db: Session, project_id: uuid.UUID, decision_type_id: uuid.UUID) -> None:
    """400s unless `decision_type_id` is one of the project's *effective* decision types: its own, or (nested
    projects, always on) a fallback inherited from its nearest ancestor (`service.resolve_effective_decision_types`).
    Used for `Decision.decision_type_id` validation only; rename / move / delete stay scoped to rows the project owns."""
    effective_ids = {t.id for t in resolve_effective_decision_types(db, project_id)}
    if decision_type_id not in effective_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "decision_type_id must be a decision type defined in this project, or inherited from a parent project.",
        )


def validate_people(db: Session, project: Project, owner: PrincipalRef | None, decision_maker: PrincipalRef | None) -> None:
    """400s unless the owner and decision maker (each optional here) are valid principals for this project: a
    member of its organisation, a group of the organisation, or a group of this project. A Decision Maker
    overseeing several projects need not hold a formal `ProjectRole` on this specific one."""
    for ref, field in ((owner, "owner"), (decision_maker, "decision_maker")):
        validate_principal(db, ref, organization_id=project.organization_id, project_id=project.id, field=field)


def _maker_columns(decision_maker: PrincipalRef | None) -> dict[str, Any]:
    return {
        "decision_maker_type": decision_maker.type.value if decision_maker else None,
        "decision_maker_id": decision_maker.id if decision_maker else None,
    }


def stage_decision(
    db: Session, project: Project, creator: User, *, title: str, decision_statement: str, decision_type_id: uuid.UUID,
    decision_date: Any = None, decision_maker: PrincipalRef | None = None, owner: PrincipalRef | None = None,
    **text: str | None,
) -> Decision:
    """Creates a `DRAFT` Decision (the owner defaults to `creator`) and records the `created` event. Does not commit.

    Args:
        project: The owning project.
        creator: The acting user.
        title / decision_statement / decision_type_id: The required content.
        decision_date / decision_maker / owner: Optional; `owner` falls back to the creator.
        **text: Any of `TEXT_FIELDS` beyond the two required ones (`context`, `rationale`, ...).

    Raises:
        HTTPException: 400 for a type or person the project cannot use.
    """
    validate_effective_decision_type(db, project.id, decision_type_id)
    check_markdown_limits({"decision_statement": decision_statement, **text})
    owner = owner or PrincipalRef(type=PrincipalType.USER, id=creator.id)
    validate_people(db, project, owner, decision_maker)
    decision = Decision(
        project_id=project.id, unique_code=generate_unique_code(db, project, DECISION_ARTEFACT_TYPE, DECISION_CODE_PREFIX),
        title=title, decision_statement=decision_statement, decision_type_id=decision_type_id,
        status=DecisionStatus.DRAFT, decision_date=decision_date, owner_type=owner.type.value, owner_id=owner.id,
        creator_id=creator.id, **_maker_columns(decision_maker), **{k: v for k, v in text.items() if k in TEXT_FIELDS},
    )
    db.add(decision)
    db.flush()
    log_event(
        db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="created", actor_id=creator.id,
        project_id=project.id, detail={"title": decision.title},
    )
    return decision


def stage_decision_update(
    db: Session, project: Project, decision: Decision, actor: User, changes: Mapping[str, Any],
) -> None:
    """Applies `changes` (any of `TEXT_FIELDS`, `decision_type_id`, `decision_date`, `owner`, `decision_maker`;
    a key absent is kept) and records the `updated` event. Does not commit.

    Raises:
        HTTPException: 409 once the Decision is approved or superseded; 400 for a type or person the project cannot use.
    """
    if is_locked(decision):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Decision is approved or superseded; its content can no longer be edited in place.",
        )
    if "decision_type_id" in changes:
        validate_effective_decision_type(db, project.id, changes["decision_type_id"])
    check_markdown_limits(changes)
    owner = changes.get("owner")
    if "owner" in changes and owner is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A Decision needs an owner.")
    validate_people(db, project, owner, changes.get("decision_maker"))
    for key in (*TEXT_FIELDS, "decision_type_id", "decision_date"):
        if key in changes:
            setattr(decision, key, changes[key])
    if "decision_maker" in changes:
        for column, value in _maker_columns(changes["decision_maker"]).items():
            setattr(decision, column, value)
    if owner is not None:
        decision.owner_type, decision.owner_id = owner.type.value, owner.id
    log_event(
        db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action="updated", actor_id=actor.id, project_id=project.id,
    )
