"""
Module: services.search_core

The global search's `ArtefactSearchProvider`s for the three core artefact types
(requirements, actions, change requests), plus the shared building blocks module
providers use.

Responsibilities:
- Declare, per core type, what the search reads (code, title, status, owning project)
  and which extra columns are searchable (description, reasoning, ...).
- Offer `versioned_provider` and `humanise_labels`, so a module registers a type in a
  few lines without writing SQL conventions of its own.

Design decisions:
- Core types register through the same `ArtefactSearchProvider` mechanism as module
  types, in core code because core owns these three types (the module-boundary rule: a
  module's types are registered by the module, never listed here).
- A versioned record (requirement) is searched through its current version
  (`valid_to IS NULL`); its change time is the later of the record's and the version's.
- A change request has no title of its own: it is titled by its latest version's proposed
  name, else the requirement it targets, exactly as `change_request_titles` does, but as
  correlated SQL so the search can match and sort on it.

Dependencies: the core models and `modules.registry` (the provider shapes).
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Boolean, func, literal, select

from app.models.change_request import ChangeRequest, ChangeRequestVersion, ReviewComment
from app.models.enums import ChangeRequestStatus, RequirementActionOutcome, RequirementStatus, ReviewTargetType
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.modules.registry import ArtefactSearchProvider, SearchColumns, SearchComments, SearchField

_CHANGE_REQUEST_FALLBACK_TITLE = "Change request"


def humanise_labels(enum_class: type[enum.Enum]) -> dict[str, str]:
    """`{value: label}` for an enum's members, the label being the value with underscores
    as spaces and the first letter capitalised (`in_review` -> `In review`).

    Args:
        enum_class: A `str`-valued enum.

    Returns:
        The label map for `ArtefactSearchProvider.status_labels`.
    """
    return {str(m.value): str(m.value).replace("_", " ").capitalize() for m in enum_class}


def versioned_provider(
    model: Any,
    version_model: Any,
    fk_name: str,
    *,
    title: Any,
    code: Any | None = None,
    status: Any | None = None,
    fields: tuple[SearchField, ...] = (),
    status_labels: Mapping[str, str] | None = None,
    organization_owned: bool = False,
    organization_subcomponent: str | None = None,
    is_archived: Any | None = None,
    comments: SearchComments | None = None,
) -> ArtefactSearchProvider:
    """Provider for a record whose content lives in versions (`valid_to IS NULL` is current).

    Args:
        model: The record model (`id`, `project_id`, `unique_code`, `is_archived`, `updated_at`;
            `organization_id` when `organization_owned`).
        version_model: Its version model (`valid_to`, `status`).
        fk_name: The version model's foreign-key attribute to the record.
        title: The version column holding the display title.
        code: Override for the code column (default `model.unique_code`).
        status: Override for the status column (default `version_model.status`).
        fields: The extra searchable fields, columns of either model.
        status_labels: `{status value: label}` for the status values.
        organization_owned: Whether the record may be owned by the organisation and shown through
            projects (with per-project hiding).
        organization_subcomponent: Whether it may be owned by the organisation and has an organisation-level
            surface instead (`ArtefactSearchProvider.organization_subcomponent`).
        is_archived: Override for the archived expression (default `model.is_archived`).
        comments: Where the type's comments live, if it has any.

    Returns:
        The provider.
    """
    return ArtefactSearchProvider(
        from_clause=model.__table__.join(version_model.__table__, getattr(version_model, fk_name) == model.id),
        where=(version_model.valid_to.is_(None),),
        columns=SearchColumns(
            id=model.id,
            project_id=model.project_id,
            code=code if code is not None else model.unique_code,
            title=title,
            status=status if status is not None else version_model.status,
            is_archived=is_archived if is_archived is not None else model.is_archived,
            updated_at=func.greatest(model.updated_at, getattr(version_model, "created_at", model.updated_at)),
            organization_id=model.organization_id if (organization_owned or organization_subcomponent) else None,
            version=version_model.version_number,
        ),
        fields=fields,
        status_labels=status_labels or {},
        organization_owned=organization_owned,
        organization_subcomponent=organization_subcomponent,
        comments=comments,
    )


def comments_of(comment_model: Any, record_id_column: Any) -> SearchComments:
    """`SearchComments` for a per-type comment table with a `body` column and `created_at` timestamp.

    Args:
        comment_model: The ORM model of the type's own comment table.
        record_id_column: Its column holding the commented record's id.
    """
    return SearchComments(comment_model, record_id_column, comment_model.body, comment_model.created_at)


def _review_comments(target: ReviewTargetType) -> SearchComments:
    """Requirements, actions and change requests share one comment table, told apart by `target_type`."""
    return SearchComments(
        ReviewComment, ReviewComment.target_id, ReviewComment.body, ReviewComment.created_at,
        where=(ReviewComment.target_type == target,),
    )


def _change_request_provider() -> ArtefactSearchProvider:
    """A change request's title and text come from its latest version, via correlated subqueries."""

    def latest(column: Any) -> Any:
        return (
            select(column)
            .where(ChangeRequestVersion.change_request_id == ChangeRequest.id)
            .order_by(ChangeRequestVersion.version_number.desc())
            .limit(1)
            .correlate(ChangeRequest)
            .scalar_subquery()
        )

    targeted_name = (
        select(RequirementVersion.name)
        .where(RequirementVersion.requirement_id == ChangeRequest.requirement_id, RequirementVersion.valid_to.is_(None))
        .limit(1)
        .correlate(ChangeRequest)
        .scalar_subquery()
    )
    title = func.coalesce(func.nullif(latest(ChangeRequestVersion.proposed_name), ""), targeted_name, _CHANGE_REQUEST_FALLBACK_TITLE)
    return ArtefactSearchProvider(
        from_clause=ChangeRequest.__table__,
        columns=SearchColumns(
            id=ChangeRequest.id,
            project_id=ChangeRequest.project_id,
            code=ChangeRequest.unique_code,
            title=title,
            status=ChangeRequest.status,
            is_archived=literal(False, type_=Boolean),
            updated_at=ChangeRequest.updated_at,
            version=latest(ChangeRequestVersion.version_number),
        ),
        fields=(
            SearchField("reason", "Reason", latest(ChangeRequestVersion.reason)),
            SearchField("description", "Description", latest(ChangeRequestVersion.proposed_description)),
            SearchField("decision_note", "Decision note", ChangeRequest.decision_note),
        ),
        status_labels=humanise_labels(ChangeRequestStatus),
        comments=_review_comments(ReviewTargetType.CHANGE_REQUEST),
    )


CORE_SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    "requirement": versioned_provider(
        Requirement,
        RequirementVersion,
        "requirement_id",
        title=RequirementVersion.name,
        fields=(
            SearchField("description", "Description", RequirementVersion.description),
            SearchField("reasoning", "Reasoning", RequirementVersion.reasoning),
            SearchField("clarification", "Clarification", RequirementVersion.clarification),
        ),
        status_labels=humanise_labels(RequirementStatus),
        comments=_review_comments(ReviewTargetType.REQUIREMENT),
    ),
    "requirement_action": ArtefactSearchProvider(
        from_clause=RequirementAction.__table__,
        columns=SearchColumns(
            id=RequirementAction.id,
            project_id=RequirementAction.project_id,
            code=RequirementAction.unique_code,
            title=RequirementAction.title,
            status=RequirementAction.outcome_status,
            is_archived=RequirementAction.is_archived,
            updated_at=RequirementAction.updated_at,
        ),
        fields=(SearchField("description", "Description", RequirementAction.description),),
        status_labels=humanise_labels(RequirementActionOutcome),
        comments=_review_comments(ReviewTargetType.ACTION),
    ),
    "change_request": _change_request_provider(),
}

__all__ = ["CORE_SEARCH_PROVIDERS", "humanise_labels", "versioned_provider"]
