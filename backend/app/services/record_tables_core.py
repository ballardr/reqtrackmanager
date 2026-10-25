"""
Module: services.record_tables_core

The `RecordTableProvider`s for the core artefact types (requirements, actions and change requests), plus the building blocks
module providers use to declare a type in a few lines.

Responsibilities:
- Declare, per core type, the columns of its table (export, import, grid) and how a row is created or updated.
- Share the list query with the type's list endpoint (`services.requirements.filter_requirements`,
  `services.actions.list_actions_filtered`) and the create/update logic with its edit endpoints
  (`create_requirement`, `edit_requirement`, `create_action`, `edit_action`), so a filter, rule or audit event
  added there reaches the file too.
- Offer `text_parser`, `date_parser`, `int_parser`, `bool_parser`, `enum_parser`, `person_parser`, `list_parser`, `label_map`,
  `list_cell`, `bool_cell`, `cached_lookup` and the filter readers (`enum_filter`, `uuid_filter`), so a module's provider is
  declarations only.

Design decisions:
- Core owns these types, so they register here (the module-boundary rule: a module's types are registered by
  the module, never listed here).
- `status` of a requirement is export-only: it has an approval gate, and a file must not bypass it. An import
  creates drafts and edits content; an approved requirement refuses the edit (it changes through a change
  request), reported as that row's error.
- A change request is export-only (`CORE_NOT_IMPORTABLE` gives the reason): its content depends on its kind
  and it moves through submit and approval, which a file cannot author.
- A person column is one cell: an email for a user, `Name (Org group)` / `Name (Project group)` for a group.
- A project's custom fields are columns named `cf_<name>`, built per project.

Dependencies: `modules.registry` (provider shapes), `services.record_tables` (cell helpers, people),
`services.requirements`, `services.actions`, `services.change_request_list`, `services.audit`.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metrics import requirements_created_total, requirements_updated_total
from app.models.action_type import ActionTypeDefinition
from app.models.change_request import ChangeRequest, ChangeRequestVersion
from app.models.custom_field import CustomFieldDefinition, CustomFieldEntityKind, CustomFieldType
from app.models.enums import (
    ChangeRequestKind,
    ChangeRequestStatus,
    ProjectRole,
    RequirementActionOutcome,
    RequirementLevel,
    RequirementStatus,
)
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.modules.registry import (
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
)
from app.schemas.principal import PrincipalRef
from app.services import actions as action_service
from app.services import change_request_list as change_request_service
from app.services import requirements as requirement_service
from app.services import tags as tag_service
from app.services.audit import log_event
from app.services.custom_fields import validate_custom_field_values
from app.services.labels import CHANGE_REQUEST_STATUS_TONE, REQUIREMENT_STATUS_TONE
from app.services.principals import principal_ref, validate_principal
from app.services.project_hierarchy import resolve_effective_action_types
from app.services.rbac import get_effective_project_roles
from app.services.record_tables import PrincipalCells, parse_principal_cell
from app.services.search_core import humanise_labels

CAN_EDIT_ROLES = (ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.STAKEHOLDER)
LIST_SEPARATOR = ";"
CUSTOM_FIELD_PREFIX = "cf_"


# --- building blocks -------------------------------------------------------------------------------


def label_map(enum_class: type[enum.Enum]) -> dict[str, str]:
    """`{value: label}` for an enum, the label being what the UI shows (`in_review` -> `In review`)."""
    return humanise_labels(enum_class)


def text_parser(ctx: RecordImportContext, text: str) -> str:
    """A text cell as it is (already trimmed)."""
    return text


def date_parser(field_name: str) -> Callable[[RecordImportContext, str], date | None]:
    """A parser for a calendar date cell (`YYYY-MM-DD`); an empty cell clears the date.

    A calendar date is a person's own day, so there is no time zone to apply.
    """

    def parse(ctx: RecordImportContext, text: str) -> date | None:
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise RecordCellError(f"{field_name} '{text}' is not a date (expected YYYY-MM-DD).") from None

    return parse


def int_parser(field_name: str) -> Callable[[RecordImportContext, str], int | None]:
    """A parser for a whole-number cell; an empty cell clears the value."""

    def parse(ctx: RecordImportContext, text: str) -> int | None:
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            raise RecordCellError(f"{field_name} '{text}' is not a whole number.") from None

    return parse


def bool_cell(value: bool) -> str:
    """A yes/no value as a cell (`true` / `false`, as a custom checkbox writes it)."""
    return "true" if value else "false"


def bool_parser(field_name: str) -> Callable[[RecordImportContext, str], bool | None]:
    """A parser for a yes/no cell (`true`/`false`/`yes`/`no`/`1`/`0`); an empty cell means no."""

    def parse(ctx: RecordImportContext, text: str) -> bool:
        if not text:
            return False
        lowered = text.casefold()
        if lowered in {"true", "yes", "1", "y"}:
            return True
        if lowered in {"false", "no", "0", "n"}:
            return False
        raise RecordCellError(f"{field_name} '{text}' is not true or false.")

    return parse


def enum_parser(enum_class: type[enum.Enum], field_name: str, *, blank: Any = None) -> Callable[[RecordImportContext, str], Any]:
    """A parser for an enum cell written by its label (`In review`); the raw value is accepted too.

    Args:
        enum_class: The enum.
        field_name: The field's name, for the message.
        blank: What an empty cell means (default `None`, i.e. leave the type's own default).
    """
    labels = {label.casefold(): member for member in enum_class for label in (humanise_labels(enum_class)[str(member.value)], str(member.value))}

    def parse(ctx: RecordImportContext, text: str) -> Any:
        if not text:
            return blank
        found = labels.get(text.casefold())
        if found is None:
            options = ", ".join(humanise_labels(enum_class).values())
            raise RecordCellError(f"{field_name} '{text}' is not one of: {options}.")
        return found

    return parse


def list_cell(values: list[str] | tuple[str, ...]) -> str:
    """A list as one cell, `;`-separated."""
    return LIST_SEPARATOR.join(values)


def list_parser(ctx: RecordImportContext, text: str) -> list[str]:
    """A `;`-separated cell as a list (blank entries dropped)."""
    return [part.strip() for part in text.split(LIST_SEPARATOR) if part.strip()]


def person_parser(field_name: str) -> Callable[[RecordImportContext, str], PrincipalRef | None]:
    """A parser for a person cell: an email (user) or `Name (Org group)` (group); empty means nobody."""

    def parse(ctx: RecordImportContext, text: str) -> PrincipalRef | None:
        return parse_principal_cell(ctx, text, field_name=field_name)

    return parse


def cached_lookup(ctx: RecordImportContext, key: str, load: Callable[[], Any]) -> Any:
    """`load()` once per import, kept in the context's cache."""
    if key not in ctx.cache:
        ctx.cache[key] = load()
    return ctx.cache[key]


def uuid_filter(filters: RecordFilters, key: str) -> uuid.UUID | None:
    """A UUID filter, or a 422 naming the parameter."""
    raw = filters.one(key)
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(422, f"{key} must be an id.") from None


def enum_filter(filters: RecordFilters, key: str, enum_class: type[enum.Enum]) -> Any:
    """An enum filter by its stored value, or a 422 naming the parameter."""
    raw = filters.one(key)
    if raw is None:
        return None
    try:
        return enum_class(raw)
    except ValueError:
        raise HTTPException(422, f"{key} is not a valid value.") from None


def _may_edit(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """The check the core create/edit endpoints make: a stakeholder, administrator or manager of the project."""
    return bool(get_effective_project_roles(db, user.id, project_id) & set(CAN_EDIT_ROLES))


# --- requirements ----------------------------------------------------------------------------------


class _RequirementTable:
    """Lookups handed to every requirement column's `get`: the current versions, components, categories,
    stages and people of the rows being written."""

    def __init__(self, db: Session, project: Project, requirements: list[Requirement]) -> None:
        ids = [r.id for r in requirements]
        self.versions: dict[uuid.UUID, RequirementVersion] = {}
        if ids:
            self.versions = {
                v.requirement_id: v for v in db.scalars(
                    select(RequirementVersion).where(RequirementVersion.requirement_id.in_(ids), RequirementVersion.valid_to.is_(None))
                )
            }
        self.components = {
            c.id: c for c in db.scalars(select(ProjectComponent).where(ProjectComponent.id.in_({r.component_id for r in requirements})))
        } if requirements else {}
        self.categories = {
            c.id: c for c in db.scalars(select(ProjectCategory).where(ProjectCategory.id.in_({r.category_id for r in requirements})))
        } if requirements else {}
        stage_ids = {v.target_stage_id for v in self.versions.values() if v.target_stage_id}
        self.stages = {s.id: s for s in db.scalars(select(ProjectStage).where(ProjectStage.id.in_(stage_ids)))} if stage_ids else {}
        refs = [principal_ref(v.owner_type, v.owner_id) for v in self.versions.values()]
        refs += [principal_ref(v.reviewer_type, v.reviewer_id) for v in self.versions.values()]
        self.people = PrincipalCells.load(db, refs)
        self.keywords = tag_service.keywords_for_requirements(db, ids) if ids else {}


def _prepare_requirements(db: Session, project: Project, records: list[Any]) -> _RequirementTable:
    return _RequirementTable(db, project, records)


def _list_requirements(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[Requirement]:
    found = requirement_service.filter_requirements(
        db, project_id, user.id,
        requirement_service.RequirementFilters(
            include_archived=bool(filters.flag("include_archived")), is_completed=filters.flag("is_completed"),
            component_id=uuid_filter(filters, "component_id"), category_id=uuid_filter(filters, "category_id"),
            keyword=filters.one("keyword"), search=filters.one("search"),
            status=enum_filter(filters, "status", RequirementStatus), target_stage_id=uuid_filter(filters, "target_stage_id"),
            has_comments=filters.flag("has_comments"), only_watched=filters.flag("only_watched"),
        ),
        structural_order=True, prefetch=False,
    )
    return found.requirements


def _find_requirement(db: Session, project: Project, code: str) -> Requirement | None:
    return db.scalar(select(Requirement).where(Requirement.project_id == project.id, Requirement.unique_code == code.upper()))


def _requirement_columns(db: Session, project: Project) -> list[RecordColumn]:
    levels, statuses = label_map(RequirementLevel), label_map(RequirementStatus)
    components = db.scalars(select(ProjectComponent).where(ProjectComponent.project_id == project.id).order_by(ProjectComponent.sort_order)).all()
    category_prefixes = sorted({
        c.prefix for c in db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == project.id))
    })
    stages = db.scalars(select(ProjectStage).where(ProjectStage.project_id == project.id).order_by(ProjectStage.sort_order)).all()

    def version(t: _RequirementTable, r: Requirement) -> RequirementVersion:
        return t.versions[r.id]

    columns = [
        RecordColumn("name", "Name", lambda t, r: version(t, r).name, text_parser, editable=True, required=True),
        RecordColumn(
            "component", "Component", lambda t, r: t.components[r.component_id].prefix, text_parser, kind="enum", required=True,
            choices=tuple(c.prefix for c in components),
        ),
        RecordColumn(
            "category", "Category", lambda t, r: t.categories[r.category_id].prefix, text_parser, kind="enum", required=True,
            choices=tuple(category_prefixes),
        ),
        RecordColumn("reasoning", "Reasoning", lambda t, r: version(t, r).reasoning, text_parser, editable=True),
        RecordColumn("clarification", "Clarification", lambda t, r: version(t, r).clarification, text_parser, editable=True),
        RecordColumn("description", "Description", lambda t, r: version(t, r).description, text_parser, editable=True),
        RecordColumn(
            "level", "Level", lambda t, r: levels[version(t, r).level.value],
            enum_parser(RequirementLevel, "Level", blank=RequirementLevel.REQUIREMENT), kind="enum", editable=True,
            choices=tuple(levels.values()),
        ),
        RecordColumn(
            "target_version", "Target version",
            lambda t, r: t.stages[version(t, r).target_stage_id].name if version(t, r).target_stage_id in t.stages else "",
            text_parser, kind="enum", choices=tuple(s.name for s in stages),
        ),
        RecordColumn(
            "owner", "Owner", lambda t, r: t.people.text(version(t, r).owner_type, version(t, r).owner_id),
            person_parser("owner"), kind="principal",
        ),
        RecordColumn(
            "reviewer", "Reviewer", lambda t, r: t.people.text(version(t, r).reviewer_type, version(t, r).reviewer_id),
            person_parser("reviewer"), kind="principal",
        ),
        RecordColumn("keywords", "Tags", lambda t, r: list_cell(t.keywords.get(r.id, [])), list_parser, kind="list"),
        RecordColumn(
            "review_date", "Review date", lambda t, r: version(t, r).review_date.isoformat() if version(t, r).review_date else "",
            date_parser("Review date"), kind="date",
        ),
        RecordColumn(
            "review_lead_days", "Review lead days", lambda t, r: str(version(t, r).review_lead_days or "") ,
            int_parser("Review lead days"), kind="number",
        ),
    ]
    for definition in _custom_field_definitions(db, project.id):
        columns.append(_custom_field_column(definition))
    columns.append(RecordColumn(
        "status", "Status", lambda t, r: statuses[version(t, r).status.value], kind="enum",
        tones={statuses[value]: tone for value, tone in REQUIREMENT_STATUS_TONE.items() if value in statuses},
    ))
    return columns


def _custom_field_definitions(db: Session, project_id: uuid.UUID) -> list[CustomFieldDefinition]:
    return list(db.scalars(
        select(CustomFieldDefinition)
        .where(CustomFieldDefinition.project_id == project_id, CustomFieldDefinition.entity_kind == CustomFieldEntityKind.REQUIREMENT)
        .order_by(CustomFieldDefinition.sort_order)
    ).all())


def _custom_field_column(definition: CustomFieldDefinition) -> RecordColumn:
    """The `cf_<name>` column of one custom field: text, a checkbox (`true`/`false`) or a list option."""
    field_id = str(definition.id)

    def get(t: _RequirementTable, r: Requirement) -> str:
        value = t.versions[r.id].custom_fields.get(field_id)
        if value is None:
            return ""
        return ("true" if value else "false") if definition.field_type == CustomFieldType.CHECKBOX else str(value)

    def parse(ctx: RecordImportContext, text: str) -> Any:
        if definition.field_type == CustomFieldType.CHECKBOX:
            return text.lower() in {"true", "1", "yes", "x"}
        return text if text else None

    return RecordColumn(
        f"{CUSTOM_FIELD_PREFIX}{definition.name}", definition.name, get, parse,
        kind="bool" if definition.field_type == CustomFieldType.CHECKBOX else "text",
        editable=True, required=definition.required,
    )


def _requirement_lookups(
    ctx: RecordImportContext,
) -> tuple[dict[str, ProjectComponent], dict[tuple[uuid.UUID, str], ProjectCategory], dict[str, ProjectStage]]:
    """The project's components by prefix, categories by (component, prefix) and stages by name, loaded once per import."""
    components = cached_lookup(ctx, "req:components", lambda: {
        c.prefix: c for c in ctx.db.scalars(select(ProjectComponent).where(ProjectComponent.project_id == ctx.project.id))
    })
    categories = cached_lookup(ctx, "req:categories", lambda: {
        (c.component_id, c.prefix): c for c in ctx.db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == ctx.project.id))
    })
    stages = cached_lookup(ctx, "req:stages", lambda: {
        s.name: s for s in ctx.db.scalars(select(ProjectStage).where(ProjectStage.project_id == ctx.project.id))
    })
    return components, categories, stages


def _component_and_category(ctx: RecordImportContext, component_prefix: str, category_prefix: str) -> tuple[ProjectComponent, ProjectCategory]:
    components, categories, _ = _requirement_lookups(ctx)
    component = components.get(component_prefix)
    if component is None:
        raise RecordCellError(f"Unknown component '{component_prefix}'.")
    category = categories.get((component.id, category_prefix))
    if category is None:
        raise RecordCellError(f"Unknown category '{category_prefix}' for component '{component_prefix}'.")
    return component, category


def _stage(ctx: RecordImportContext, name: str) -> ProjectStage:
    stage = _requirement_lookups(ctx)[2].get(name)
    if stage is None:
        raise RecordCellError(f"Unknown target version '{name}'.")
    return stage


def _custom_values_in(ctx: RecordImportContext, values: Mapping[str, Any]) -> dict[str, Any]:
    """The custom field values in `values`, keyed by definition id (blank text and list cells are absent)."""
    definitions = {
        f"{CUSTOM_FIELD_PREFIX}{d.name}": d for d in cached_lookup(ctx, "req:cf", lambda: _custom_field_definitions(ctx.db, ctx.project.id))
    }
    return {str(definitions[key].id): value for key, value in values.items() if key in definitions and value is not None}


def _create_requirement(ctx: RecordImportContext, values: Mapping[str, Any]) -> Requirement:
    component, category = _component_and_category(ctx, values["component"], values["category"])
    _, _, stages = _requirement_lookups(ctx)
    if "target_version" in values and values["target_version"]:
        target_stage_id = _stage(ctx, values["target_version"]).id
    elif stages:
        target_stage_id = min(stages.values(), key=lambda s: s.sort_order).id
    else:
        raise RecordCellError("This project has no stages; a requirement needs a target version.")
    custom_fields = validate_custom_field_values(
        ctx.db, ctx.project.id, CustomFieldEntityKind.REQUIREMENT, _custom_values_in(ctx, values)
    )
    for person_field in ("owner", "reviewer"):
        ref = values.get(person_field)
        if ref is not None:
            validate_principal(ctx.db, ref, organization_id=ctx.project.organization_id, project_id=ctx.project.id, field=person_field)
    count = len(ctx.db.scalars(select(Requirement.id).where(Requirement.project_id == ctx.project.id)).all())
    requirement = requirement_service.create_requirement(
        ctx.db, ctx.project, component, category, ctx.user,
        name=values["name"], reasoning=values.get("reasoning", ""), clarification=values.get("clarification", ""),
        description=values.get("description", ""), owner=values.get("owner"), keywords=values.get("keywords", []),
        sort_order=count, target_stage_id=target_stage_id, level=values.get("level") or RequirementLevel.REQUIREMENT,
        custom_fields=custom_fields, review_date=values.get("review_date"), review_lead_days=values.get("review_lead_days"),
        reviewer=values.get("reviewer"),
    )
    log_event(ctx.db, entity_type="requirement", entity_id=requirement.id, action="created", actor_id=ctx.user.id,
              project_id=ctx.project.id, detail={"via": "record_import"})
    requirements_created_total.inc()
    return requirement


def _update_requirement(ctx: RecordImportContext, requirement: Requirement, values: Mapping[str, Any]) -> None:
    if "owner" in values and values["owner"] is None:
        raise RecordCellError("A requirement must have an owner.")
    component_id = category_id = None
    if "component" in values or "category" in values:
        current = ctx.db.get(ProjectComponent, requirement.component_id)
        current_category = ctx.db.get(ProjectCategory, requirement.category_id)
        component, category = _component_and_category(
            ctx,
            values.get("component", current.prefix if current else ""),
            values.get("category", current_category.prefix if current_category else ""),
        )
        component_id, category_id = component.id, category.id
    target_stage_id = None
    if "target_version" in values:
        if not values["target_version"]:
            raise RecordCellError("A requirement must have a target version.")
        target_stage_id = _stage(ctx, values["target_version"]).id
    custom_fields = None
    changed_custom = _custom_values_in(ctx, values)
    cleared = {
        str(d.id) for d in cached_lookup(ctx, "req:cf", lambda: _custom_field_definitions(ctx.db, ctx.project.id))
        if f"{CUSTOM_FIELD_PREFIX}{d.name}" in values and values[f"{CUSTOM_FIELD_PREFIX}{d.name}"] is None
    }
    if changed_custom or cleared:
        current_version = requirement_service.get_current_version(ctx.db, requirement.id)
        custom_fields = {k: v for k, v in current_version.custom_fields.items() if k not in cleared}
        custom_fields.update(changed_custom)
    requirement_service.edit_requirement(
        ctx.db, ctx.project, requirement, ctx.user,
        name=values.get("name"), reasoning=values.get("reasoning"), clarification=values.get("clarification"),
        description=values.get("description"), owner=values.get("owner"), target_stage_id=target_stage_id,
        level=values.get("level"), change_note="Edited by record import.", custom_fields=custom_fields,
        review_date=values.get("review_date"), review_date_explicitly_set="review_date" in values,
        review_lead_days=values.get("review_lead_days"), review_lead_days_explicitly_set="review_lead_days" in values,
        reviewer=values.get("reviewer"), reviewer_explicitly_set="reviewer" in values,
        component_id=component_id, category_id=category_id, keywords=values.get("keywords"),
    )
    log_event(ctx.db, entity_type="requirement", entity_id=requirement.id, action="updated", actor_id=ctx.user.id,
              project_id=ctx.project.id, detail={"via": "record_import"})
    requirements_updated_total.inc()


def _count_rows(db: Session, model: Any, project_id: uuid.UUID, *, live_only: bool) -> int:
    """How many rows of `model` the project holds (archived ones left out when `live_only`): the overview's count."""
    query = select(func.count()).select_from(model).where(model.project_id == project_id)
    if live_only:
        query = query.where(model.is_archived.is_(False))
    return int(db.scalar(query) or 0)


REQUIREMENT_TABLE = RecordTableProvider(
    label="Requirements",
    columns=_requirement_columns,
    list_records=_list_requirements,
    find=_find_requirement,
    prepare=_prepare_requirements,
    create=_create_requirement,
    update=_update_requirement,
    filter_params=frozenset({
        "include_archived", "is_completed", "component_id", "category_id", "keyword", "search", "status",
        "target_stage_id", "has_comments", "only_watched",
    }),
    can_create=_may_edit,
    can_update=_may_edit,
    count=lambda db, user, project_id: _count_rows(db, Requirement, project_id, live_only=True),
    approval_gated=True,
    read_only_reason=lambda t, r: (
        "This requirement is approved; changes must be made via a change request."
        if r.id in t.versions and requirement_service.is_locked(t.versions[r.id]) else None
    ),
)


# --- actions ---------------------------------------------------------------------------------------


class _ActionTable:
    """Lookups handed to every action column's `get`: action type names and people."""

    def __init__(self, db: Session, project: Project, actions: list[RequirementAction]) -> None:
        type_ids = {a.action_type_id for a in actions}
        self.types = {t.id: t.name for t in db.scalars(select(ActionTypeDefinition).where(ActionTypeDefinition.id.in_(type_ids)))} if type_ids else {}
        self.people = PrincipalCells.load(db, [principal_ref(a.assignee_type, a.assignee_id) for a in actions])


def _list_actions(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[RequirementAction]:
    return action_service.list_actions_filtered(
        db, project_id, outcome_status=enum_filter(filters, "outcome_status", RequirementActionOutcome),
        action_type_id=uuid_filter(filters, "action_type_id"), include_archived=bool(filters.flag("include_archived")),
    )


def _action_type(ctx: RecordImportContext, name: str) -> uuid.UUID:
    types = cached_lookup(ctx, "act:types", lambda: {t.name.casefold(): t.id for t in resolve_effective_action_types(ctx.db, ctx.project.id)})
    found = types.get(name.casefold())
    if found is None:
        raise RecordCellError(f"Unknown action type '{name}'.")
    return found


def _action_columns(db: Session, project: Project) -> list[RecordColumn]:
    outcomes = label_map(RequirementActionOutcome)
    type_names = tuple(t.name for t in resolve_effective_action_types(db, project.id))
    return [
        RecordColumn("title", "Title", lambda t, a: a.title, text_parser, editable=True, required=True),
        RecordColumn("description", "Description", lambda t, a: a.description, text_parser, editable=True),
        RecordColumn(
            "action_type", "Action type", lambda t, a: t.types.get(a.action_type_id, ""), text_parser, kind="enum", required=True,
            choices=type_names,
        ),
        RecordColumn(
            "outcome", "Outcome", lambda t, a: outcomes[a.outcome_status.value],
            enum_parser(RequirementActionOutcome, "Outcome", blank=RequirementActionOutcome.PENDING), kind="enum", editable=True,
            choices=tuple(outcomes.values()),
        ),
        RecordColumn(
            "assignee", "Assignee", lambda t, a: t.people.text(a.assignee_type, a.assignee_id), person_parser("assignee"), kind="principal",
        ),
        RecordColumn(
            "due_date", "Due date", lambda t, a: a.due_date.isoformat() if a.due_date else "", date_parser("Due date"), kind="date",
            editable=True,
        ),
        RecordColumn(
            "completed_at", "Completed at", lambda t, a: a.completed_at.isoformat() if a.completed_at else "", kind="instant",
        ),
    ]


def _create_action(ctx: RecordImportContext, values: Mapping[str, Any]) -> RequirementAction:
    action = action_service.create_action(
        ctx.db, ctx.project, ctx.user, title=values["title"], description=values.get("description", ""),
        action_type_id=_action_type(ctx, values["action_type"]), assignee=values.get("assignee"), due_date=values.get("due_date"),
    )
    outcome = values.get("outcome")
    if outcome is not None and outcome != RequirementActionOutcome.PENDING:
        action_service.apply_outcome_transition(action, outcome, ctx.user)
    return action


def _update_action(ctx: RecordImportContext, action: RequirementAction, values: Mapping[str, Any]) -> None:
    action_service.edit_action(
        ctx.db, ctx.project, ctx.user, action, title=values.get("title"), description=values.get("description"),
        action_type_id=_action_type(ctx, values["action_type"]) if "action_type" in values else None,
        assignee=values["assignee"] if "assignee" in values else action_service.UNSET,
        due_date=values["due_date"] if "due_date" in values else action_service.UNSET,
        outcome_status=values.get("outcome"),
    )


def _find_action(db: Session, project: Project, code: str) -> RequirementAction | None:
    return db.scalar(select(RequirementAction).where(RequirementAction.project_id == project.id, RequirementAction.unique_code == code.upper()))


ACTION_TABLE = RecordTableProvider(
    label="Actions",
    columns=_action_columns,
    list_records=_list_actions,
    find=_find_action,
    prepare=lambda db, project, records: _ActionTable(db, project, records),
    create=_create_action,
    update=_update_action,
    filter_params=frozenset({"include_archived", "outcome_status", "action_type_id"}),
    can_create=_may_edit,
    can_update=_may_edit,
    count=lambda db, user, project_id: _count_rows(db, RequirementAction, project_id, live_only=True),
)


# --- change requests -------------------------------------------------------------------------------

#: Field names a change request lists as changed, by the label the form shows (`target_stage_id` -> `Target version`).
CHANGED_FIELD_LABEL = {
    "name": "Name", "reasoning": "Reasoning", "clarification": "Clarification", "description": "Description",
    "target_stage_id": "Target version", "level": "Level", "review_date": "Review date",
    "review_lead_days": "Reminder lead time", "reviewer_id": "Assigned reviewer", "custom_fields": "Custom fields",
    "attachments": "Attachments",
}


class _ChangeRequestTable:
    """Lookups handed to every change request column's `get`: latest versions, target requirements, stages, people, tags."""

    def __init__(self, db: Session, project: Project, change_requests: list[ChangeRequest]) -> None:
        ids = [cr.id for cr in change_requests]
        self.versions: dict[uuid.UUID, ChangeRequestVersion] = change_request_service.latest_versions(db, change_requests)
        requirement_ids = {cr.requirement_id for cr in change_requests if cr.requirement_id}
        self.requirements: dict[uuid.UUID, tuple[str, str]] = {}
        if requirement_ids:
            self.requirements = {
                requirement_id: (code, name) for requirement_id, code, name in db.execute(
                    select(Requirement.id, Requirement.unique_code, RequirementVersion.name)
                    .join(RequirementVersion, RequirementVersion.requirement_id == Requirement.id)
                    .where(Requirement.id.in_(requirement_ids), RequirementVersion.valid_to.is_(None))
                ).all()
            }
        stage_ids = {v.proposed_target_stage_id for v in self.versions.values() if v.proposed_target_stage_id}
        self.stages = {s.id: s.name for s in db.scalars(select(ProjectStage).where(ProjectStage.id.in_(stage_ids)))} if stage_ids else {}
        refs = [principal_ref("user", cr.creator_id) for cr in change_requests]
        refs += [principal_ref("user", cr.decided_by) for cr in change_requests if cr.decided_by]
        refs += [principal_ref(v.proposed_reviewer_type, v.proposed_reviewer_id) for v in self.versions.values()]
        self.people = PrincipalCells.load(db, refs)
        self.tags = tag_service.tag_names_for_records(db, "change_request", ids) if ids else {}

    def version(self, cr: ChangeRequest) -> ChangeRequestVersion:
        return self.versions[cr.id]


def _list_change_requests(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[ChangeRequest]:
    found = change_request_service.query_change_requests(
        db, project_id, cr_status=enum_filter(filters, "cr_status", ChangeRequestStatus), active_only=bool(filters.flag("active_only")),
    )
    return [cr for cr, _ in change_request_service.narrow_change_requests(
        db, found, target_stage_id=uuid_filter(filters, "target_stage_id"), search=filters.one("search"),
    )]


def _find_change_request(db: Session, project: Project, code: str) -> ChangeRequest | None:
    return db.scalar(select(ChangeRequest).where(ChangeRequest.project_id == project.id, ChangeRequest.unique_code == code.upper()))


def instant_cell(value: datetime | None) -> str:
    """A past instant as UTC ISO 8601 (empty for none)."""
    return value.astimezone(UTC).isoformat() if value else ""


def _change_request_custom_column(definition: CustomFieldDefinition) -> RecordColumn:
    """An export-only `cf_<name>` column: the value this request proposes for one custom field."""
    field_id = str(definition.id)

    def get(t: _ChangeRequestTable, cr: ChangeRequest) -> str:
        value = t.version(cr).custom_fields.get(field_id)
        if value is None:
            return ""
        return ("true" if value else "false") if definition.field_type == CustomFieldType.CHECKBOX else str(value)

    return RecordColumn(
        f"{CUSTOM_FIELD_PREFIX}{definition.name}", definition.name, get, kind="bool" if definition.field_type == CustomFieldType.CHECKBOX else "text",
    )


def _change_request_columns(db: Session, project: Project) -> list[RecordColumn]:
    kinds, statuses, levels = label_map(ChangeRequestKind), label_map(ChangeRequestStatus), label_map(RequirementLevel)

    def target(t: _ChangeRequestTable, cr: ChangeRequest) -> tuple[str, str]:
        return t.requirements.get(cr.requirement_id, ("", "")) if cr.requirement_id else ("", "")

    columns = [
        RecordColumn("title", "Title", lambda t, cr: t.version(cr).proposed_name or target(t, cr)[1]),
        RecordColumn("kind", "Kind", lambda t, cr: kinds[cr.kind.value], kind="enum"),
        RecordColumn(
            "status", "Status", lambda t, cr: statuses[cr.status.value], kind="enum",
            tones={statuses[value]: tone for value, tone in CHANGE_REQUEST_STATUS_TONE.items() if value in statuses},
        ),
        RecordColumn("requirement", "Requirement", lambda t, cr: target(t, cr)[0]),
        RecordColumn("reason", "Reason", lambda t, cr: t.version(cr).reason),
        RecordColumn(
            "changed_fields", "Changed fields",
            lambda t, cr: list_cell([CHANGED_FIELD_LABEL.get(f, f) for f in t.version(cr).changed_fields]), kind="list",
        ),
        RecordColumn("proposed_reasoning", "Proposed reasoning", lambda t, cr: t.version(cr).proposed_reasoning or ""),
        RecordColumn("proposed_clarification", "Proposed clarification", lambda t, cr: t.version(cr).proposed_clarification or ""),
        RecordColumn("proposed_description", "Proposed description", lambda t, cr: t.version(cr).proposed_description or ""),
        RecordColumn(
            "proposed_level", "Proposed level", lambda t, cr: levels[t.version(cr).proposed_level.value] if t.version(cr).proposed_level else "",
            kind="enum",
        ),
        RecordColumn(
            "proposed_target_version", "Proposed target version", lambda t, cr: t.stages.get(t.version(cr).proposed_target_stage_id, ""), kind="enum",
        ),
        RecordColumn(
            "proposed_reviewer", "Proposed reviewer",
            lambda t, cr: t.people.text(t.version(cr).proposed_reviewer_type, t.version(cr).proposed_reviewer_id), kind="principal",
        ),
        RecordColumn(
            "proposed_review_date", "Proposed review date",
            lambda t, cr: t.version(cr).proposed_review_date.isoformat() if t.version(cr).proposed_review_date else "", kind="date",
        ),
        RecordColumn(
            "proposed_review_lead_days", "Proposed review lead days",
            lambda t, cr: str(t.version(cr).proposed_review_lead_days) if t.version(cr).proposed_review_lead_days is not None else "", kind="number",
        ),
        RecordColumn("creator", "Created by", lambda t, cr: t.people.text("user", cr.creator_id), kind="principal"),
        RecordColumn("keywords", "Tags", lambda t, cr: list_cell(t.tags.get(cr.id, [])), kind="list"),
        RecordColumn("created_at", "Created at", lambda t, cr: instant_cell(cr.created_at), kind="instant"),
        RecordColumn("submitted_at", "Submitted at", lambda t, cr: instant_cell(cr.submitted_at), kind="instant"),
        RecordColumn("decided_at", "Decided at", lambda t, cr: instant_cell(cr.decided_at), kind="instant"),
        RecordColumn("decided_by", "Decided by", lambda t, cr: t.people.text("user", cr.decided_by) if cr.decided_by else "", kind="principal"),
        RecordColumn("decision_note", "Decision note", lambda t, cr: cr.decision_note),
    ]
    columns.extend(_change_request_custom_column(d) for d in _custom_field_definitions(db, project.id))
    return columns


CHANGE_REQUEST_TABLE = RecordTableProvider(
    label="Change requests",
    columns=_change_request_columns,
    list_records=_list_change_requests,
    find=_find_change_request,
    prepare=lambda db, project, records: _ChangeRequestTable(db, project, records),
    filter_params=frozenset({"cr_status", "active_only", "target_stage_id", "search"}),
    count=lambda db, user, project_id: _count_rows(db, ChangeRequest, project_id, live_only=False),
    approval_gated=True,
)


CORE_RECORD_TABLES: dict[str, RecordTableProvider] = {
    "requirement": REQUIREMENT_TABLE,
    "requirement_action": ACTION_TABLE,
    "change_request": CHANGE_REQUEST_TABLE,
}

#: `{core artefact type: reason}` for a core type whose table is export-only (a module gives its reason in
#: `ModuleDefinition.not_importable`).
CORE_NOT_IMPORTABLE: dict[str, str] = {
    "change_request": (
        "A change request is a proposal whose content depends on its kind (which requirement fields change, proposed "
        "links, attachments, an action to add or remove) and it moves through submit and approval, so it is authored "
        "in its form, not in a file."
    ),
}

__all__ = [
    "CORE_NOT_IMPORTABLE", "CORE_RECORD_TABLES", "bool_cell", "bool_parser", "cached_lookup", "date_parser", "enum_filter",
    "enum_parser", "instant_cell", "int_parser", "label_map", "list_cell", "list_parser", "person_parser", "text_parser",
    "uuid_filter",
]
