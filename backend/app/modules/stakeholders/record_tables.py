"""
Module: modules.stakeholders.record_tables

The `RecordTableProvider`s of the Stakeholders & Personas module's six record types (Persona, Stakeholder,
Stakeholder Group, Stakeholder Need, Engagement, Research Finding): each list as a table that exports to CSV,
PDF and Word and imports from the same CSV (a row with a code updates that record, a blank code creates one).

Responsibilities:
- Declare, per type, the columns (key, label, cell text, parser, editable flag, personal-data sensitivity) and
  how a row is created or updated.
- Share the list query with the list endpoint and the create / edit logic with the edit endpoint
  (`stage_*` in the `_*_shared` modules, which the endpoints commit and the import wraps in a savepoint), so a
  filter, validation or audit event added there reaches the file too.

Design decisions:
- A create or update is built as the endpoint's own request payload (`PersonaCreate`, `StakeholderUpdate`, ...),
  so its length limits, principal tenancy checks and type rules apply unchanged; a payload the model refuses is
  that row's error.
- Personal data is tagged where it is declared, so the organisation's policy decides what leaves the
  application: a stakeholder's name, role and group are `personal`, its contact details and availability are
  `contact`, and the free text about a named person (description, interests, notes of an engagement) is
  `free_text_people`. A persona is a fictional archetype and is untagged. An excluded column is absent from the
  file; a create without a required column that the policy removed fails with the payload's own message.
- `status` is export-only: a Persona, Stakeholder and Need move through draft / active / retired by their
  lifecycle actions and a file never does. A created record starts as the form starts it (draft).
- The project's list also shows the organisation's personas, stakeholders and groups. They are exported with the
  organisation-qualified code and never matched by an import here (an import into a project only updates the
  project's own records); `organization_owned` marks them. The organisation's own lists have their own
  `OrganizationRecordTable` (same columns, the organisation endpoints' create / update path, the organisation's
  type vocabulary).
- Participants, covered personas, audience groups and group members are links, managed on the record; they are
  not columns. A group's parent is exported as a path and set in the group tree.
- A research finding belongs to an engagement: the `engagement` column (its code) is required to create and
  cannot be changed by an update.
- `Tags` is export-only (tag authority and vocabulary are not a column's business).

Dependencies: this module's models, enums, labels, schemas and `_*_shared` write paths;
`services.record_tables` / `record_tables_core` (cell helpers), `services.tags`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.scoring import ScoringLevel
from app.models.user import User
from app.modules.registry import (
    OrganizationRecordTable,
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
)
from app.modules.stakeholders import _engagement_shared as engagement_shared
from app.modules.stakeholders import _group_shared as group_shared
from app.modules.stakeholders import _need_shared as need_shared
from app.modules.stakeholders import _research_shared as research_shared
from app.modules.stakeholders import _shared as persona_shared
from app.modules.stakeholders import _stakeholder_shared as stakeholder_shared
from app.modules.stakeholders import groups as grp
from app.modules.stakeholders.engagements import ENGAGEMENT_ARTEFACT_TYPE, FINDING_ARTEFACT_TYPE, RESEARCH_SUBCOMPONENT
from app.modules.stakeholders.enums import (
    EngagementChannel,
    NeedStatus,
    PersonaScope,
    PersonaStatus,
    StakeholderScope,
    StakeholderStatus,
    TargetCadence,
)
from app.modules.stakeholders.groups import GROUP_ARTEFACT_TYPE
from app.modules.stakeholders.labels import ENGAGEMENT_CHANNEL_LABEL, RECORD_STATUS_LABEL, RECORD_STATUS_TONE
from app.modules.stakeholders.models import (
    Engagement,
    EngagementFacilitator,
    Persona,
    PersonaVersion,
    ResearchFinding,
    Stakeholder,
    StakeholderGroup,
    StakeholderGroupMember,
    StakeholderNeed,
    StakeholderNeedVersion,
    StakeholderVersion,
)
from app.modules.stakeholders.schemas import (
    EngagementCreate,
    EngagementUpdate,
    FindingCreate,
    FindingUpdate,
    NeedCreate,
    NeedUpdate,
    PersonaCreate,
    PersonaUpdate,
    StakeholderCreate,
    StakeholderGroupCreate,
    StakeholderGroupUpdate,
    StakeholderUpdate,
)
from app.modules.stakeholders.service import (
    NEED_ARTEFACT_TYPE,
    PERSONA_ARTEFACT_TYPE,
    PERSONA_TYPES,
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDER_TYPES,
    list_project_needs,
    organization_personas,
    organization_stakeholders,
    project_personas,
    project_stakeholders,
)
from app.schemas.principal import PrincipalRef
from app.services import tags as tag_service
from app.services.principals import principal_ref
from app.services.record_tables import PrincipalCells, find_many_by_code, parse_principal_cell
from app.services.record_tables_core import (
    bool_cell,
    bool_parser,
    cached_lookup,
    count_rows,
    date_parser,
    enum_filter,
    enum_parser,
    label_map,
    list_cell,
    person_parser,
    text_parser,
)

MODULE_KEY = "stakeholders"
LIST_FILTERS = frozenset({"search"})
PEOPLE_FILTERS = frozenset({"search", "status", "type", "include_archived", "include_org", "include_hidden"})


# --- building blocks --------------------------------------------------------------------------------------------


def payload_of(model: type[BaseModel], values: Mapping[str, Any]) -> BaseModel:
    """Builds the endpoint's request payload from the parsed cells.

    Raises:
        RecordCellError: The model refuses a value (length, required); the message names the field.
    """
    try:
        return model(**values)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"]) or "value"
        raise RecordCellError(f"{field}: {first['msg']}") from None


def _allowed(check: Callable[..., None], *args: Any, **kwargs: Any) -> bool:
    """Whether a raising role gate passes (`HTTPException` means no)."""
    try:
        check(*args, **kwargs)
    except HTTPException:
        return False
    return True


def _project(db: Session, project_id: uuid.UUID) -> Project:
    return db.get(Project, project_id)


def _search_hit(filters: RecordFilters, *parts: str) -> bool:
    """The page's search box: the code or the main text contains it, ignoring case."""
    needle = filters.one("search")
    return needle is None or needle.casefold() in " ".join(parts).casefold()


def _version_map(db: Session, model: Any, fk: str, records: list[Any]) -> dict[uuid.UUID, Any]:
    """The current version of each record, by the record's id."""
    if not records:
        return {}
    column = getattr(model, fk)
    return {getattr(v, fk): v for v in db.scalars(select(model).where(column.in_([r.id for r in records]), model.valid_to.is_(None)))}


class _Prepared:
    """Lookups handed to every column's `get`: current versions, people cells, tags, type names, counts."""

    def __init__(self, db: Session, records: list[Any], artefact_type: str, *, version_model: Any = None, version_fk: str = "") -> None:
        self.db = db
        ids = [r.id for r in records]
        self.versions: dict[uuid.UUID, Any] = _version_map(db, version_model, version_fk, records) if version_model is not None else {}
        holders = list(self.versions.values()) or records
        refs = [principal_ref(getattr(h, "owner_type", None), getattr(h, "owner_id", None)) for h in holders]
        refs += [principal_ref(getattr(h, "champion_type", None), getattr(h, "champion_id", None)) for h in holders]
        self.people = PrincipalCells.load(db, refs)
        self.tags = tag_service.tag_names_for_records(db, artefact_type, ids) if ids else {}
        self.extra: dict[str, Any] = {}


def _tags_column() -> RecordColumn:
    return RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list")


def _text(
    key: str, label: str, getter: Callable[[Any, Any], str], *, required: bool = False, sensitivity: str = "none", editable: bool = True,
) -> RecordColumn:
    return RecordColumn(key, label, getter, text_parser, editable=editable, required=required, sensitivity=sensitivity)


def _principal(key: str, label: str, type_attr: str, id_attr: str, source: Callable[[Any, Any], Any]) -> RecordColumn:
    return RecordColumn(
        key, label, lambda t, r: t.people.text(getattr(source(t, r), type_attr), getattr(source(t, r), id_attr)),
        person_parser(key), kind="principal",
    )


def _scope_column(organization_owned: Callable[[Any], bool]) -> RecordColumn:
    return RecordColumn("scope", "Scope", lambda t, r: "Organisation" if organization_owned(r) else "Project", kind="enum")


def _status_column(source: Callable[[Any, Any], Any]) -> RecordColumn:
    return RecordColumn(
        "status", "Status", lambda t, r: RECORD_STATUS_LABEL[source(t, r).status.value], kind="enum",
        tones={RECORD_STATUS_LABEL[v]: tone for v, tone in RECORD_STATUS_TONE.items()},
    )


def _changed(values: Mapping[str, Any], mapping: Mapping[str, str]) -> dict[str, Any]:
    """The changed cells named as the update payload names them (`mapping`: column key -> payload field)."""
    return {field: values[key] for key, field in mapping.items() if key in values}


def _type_ref(vocabulary: Any, kind: str) -> Callable[[RecordImportContext, str], uuid.UUID | None]:
    """A parser for a type name of this project (or organisation default), or of the organisation itself at the
    organisation tier; blank means no type."""

    def parse(ctx: RecordImportContext, text: str) -> uuid.UUID | None:
        if not text:
            return None

        def load() -> dict[str, uuid.UUID]:
            if ctx.project is None:
                return {t.name.casefold(): t.id for t in reversed(vocabulary.active_org_types(ctx.db, ctx.organization.id))}
            return {
                t.name.casefold(): t.id for t in reversed(vocabulary.resolve_effective(ctx.db, ctx.project.id, ctx.project.organization_id))
            }

        found = cached_lookup(ctx, f"{kind}:types", load).get(text.casefold())
        if found is None:
            raise RecordCellError(f"Unknown {vocabulary.label.lower()} '{text}'.")
        return found

    return parse


def _type_choices(vocabulary: Any, db: Session, project: Project) -> tuple[str, ...]:
    return tuple(t.name for t in vocabulary.resolve_effective(db, project.id, project.organization_id) if t.is_enabled)


def _org_type_choices(vocabulary: Any, db: Session, organization: Organization) -> tuple[str, ...]:
    return tuple(t.name for t in vocabulary.active_org_types(db, organization.id))


# --- Persona ------------------------------------------------------------------------------------------------------

_PERSONA_TEXT = {
    "description": "description", "role_title": "role_title", "goals": "goals", "needs": "needs", "behaviours": "behaviours",
    "context_environment": "context_environment", "skills_proficiency": "skills_proficiency",
    "frequency_of_use": "frequency_of_use", "constraints": "constraints",
}


def _persona_owned_by_org(persona: Persona) -> bool:
    return persona.scope == PersonaScope.ORGANIZATION


def _prepare_personas(db: Session, project: Project, records: list[Persona]) -> _Prepared:
    prepared = _Prepared(db, records, PERSONA_ARTEFACT_TYPE, version_model=PersonaVersion, version_fk="persona_id")
    names = PERSONA_TYPES.display_names(db, [(v.org_type_id, v.project_type_id) for v in prepared.versions.values()])
    prepared.extra["types"] = {key: name or "" for key, name in names.items()}
    return prepared


def _filter_personas(db: Session, records: list[Persona], filters: RecordFilters) -> list[Persona]:
    status, type_name = enum_filter(filters, "status", PersonaStatus), filters.one("type")
    versions = _version_map(db, PersonaVersion, "persona_id", records)
    names = PERSONA_TYPES.display_names(db, [(v.org_type_id, v.project_type_id) for v in versions.values()]) if type_name else {}
    out = []
    for p in records:
        v = versions[p.id]
        name = names.get((v.org_type_id, v.project_type_id))
        if (status is None or v.status == status) and (type_name is None or name == type_name) and _search_hit(
            filters, p.unique_code, v.name, v.role_title
        ):
            out.append(p)
    return out


def _list_personas(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[Persona]:
    project = _project(db, project_id)
    records = project_personas(
        db, project, include_archived=bool(filters.flag("include_archived")),
        include_org=filters.flag("include_org") is not False, include_hidden=bool(filters.flag("include_hidden")),
    )
    return _filter_personas(db, records, filters)


def _list_org_personas(db: Session, user: User, organization: Organization, filters: RecordFilters) -> list[Persona]:
    return _filter_personas(db, organization_personas(db, organization.id, include_archived=bool(filters.flag("include_archived"))), filters)


def _persona_columns(db: Session, project: Project) -> list[RecordColumn]:
    return _persona_columns_for(_type_choices(PERSONA_TYPES, db, project))


def _persona_columns_for(type_choices: tuple[str, ...]) -> list[RecordColumn]:
    def version(t: _Prepared, r: Persona) -> PersonaVersion:
        return t.versions[r.id]

    columns = [
        _text("name", "Name", lambda t, r: version(t, r).name, required=True),
        RecordColumn(
            "type", "Type", lambda t, r: t.extra["types"].get((version(t, r).org_type_id, version(t, r).project_type_id), ""),
            _type_ref(PERSONA_TYPES, "persona"), kind="enum", editable=True, choices=type_choices,
        ),
        _text("description", "Description", lambda t, r: version(t, r).description),
        _text("role_title", "Role title", lambda t, r: version(t, r).role_title),
        _text("goals", "Goals", lambda t, r: version(t, r).goals),
        _text("needs", "Needs", lambda t, r: version(t, r).needs),
        _text("behaviours", "Behaviours", lambda t, r: version(t, r).behaviours),
        _text("context_environment", "Context and environment", lambda t, r: version(t, r).context_environment),
        _text("skills_proficiency", "Skills and proficiency", lambda t, r: version(t, r).skills_proficiency),
        _text("frequency_of_use", "Frequency of use", lambda t, r: version(t, r).frequency_of_use),
        _text("constraints", "Constraints", lambda t, r: version(t, r).constraints),
        RecordColumn(
            "weight", "Weight", lambda t, r: "" if version(t, r).weight is None else f"{version(t, r).weight:g}",
            _weight_parser, kind="number", editable=True,
        ),
        _principal("owner", "Owner", "owner_type", "owner_id", version),
        _principal("champion", "Champion", "champion_type", "champion_id", version),
        _scope_column(_persona_owned_by_org),
        _tags_column(),
        _status_column(version),
    ]
    return columns


def _weight_parser(ctx: RecordImportContext, text: str) -> float | None:
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise RecordCellError(f"Weight '{text}' is not a number.") from None


def _persona_values(values: Mapping[str, Any]) -> dict[str, Any]:
    fields = _changed(values, {**_PERSONA_TEXT, "name": "name", "weight": "weight", "owner": "owner", "champion": "champion",
                               "type": "persona_type_id"})
    return fields


def _create_persona(ctx: RecordImportContext, values: Mapping[str, Any]) -> Persona:
    payload = payload_of(PersonaCreate, _persona_values(values))
    return persona_shared.stage_persona(
        ctx.db, PersonaScope.PROJECT, payload, ctx.user, organization_id=ctx.project.organization_id, project_id=ctx.project.id,
    )


def _update_persona(ctx: RecordImportContext, persona: Persona, values: Mapping[str, Any]) -> None:
    payload = payload_of(PersonaUpdate, {**_persona_values(values), "change_note": "Edited by record import."})
    persona_shared.stage_persona_update(
        ctx.db, persona, payload, ctx.user, organization_id=ctx.project.organization_id, project_id=ctx.project.id,
    )


def _find_persona(db: Session, project: Project, code: str) -> Persona | None:
    return db.scalar(select(Persona).where(
        Persona.project_id == project.id, Persona.scope == PersonaScope.PROJECT, Persona.unique_code == code.upper()
    ))


def _may_manage_personas(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return _allowed(
        persona_shared.require_persona_manage, db, user, PersonaScope.PROJECT,
        organization_id=_project(db, project_id).organization_id, project_id=project_id,
    )


def _create_org_persona(ctx: RecordImportContext, values: Mapping[str, Any]) -> Persona:
    payload = payload_of(PersonaCreate, _persona_values(values))
    return persona_shared.stage_persona(
        ctx.db, PersonaScope.ORGANIZATION, payload, ctx.user, organization_id=ctx.organization.id, project_id=None,
    )


def _update_org_persona(ctx: RecordImportContext, persona: Persona, values: Mapping[str, Any]) -> None:
    payload = payload_of(PersonaUpdate, {**_persona_values(values), "change_note": "Edited by record import."})
    persona_shared.stage_persona_update(ctx.db, persona, payload, ctx.user, organization_id=ctx.organization.id, project_id=None)


def _find_org_persona(db: Session, organization: Organization, code: str) -> Persona | None:
    return db.scalar(select(Persona).where(
        Persona.organization_id == organization.id, Persona.scope == PersonaScope.ORGANIZATION, Persona.unique_code == code.upper()
    ))


def _may_manage_org_personas(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    return _allowed(
        persona_shared.require_persona_manage, db, user, PersonaScope.ORGANIZATION, organization_id=organization_id, project_id=None,
    )


PERSONA_TABLE = RecordTableProvider(
    label="Personas",
    columns=_persona_columns,
    list_records=_list_personas,
    find=_find_persona,
    find_many=find_many_by_code(Persona, "project_id", Persona.scope == PersonaScope.PROJECT),
    prepare=_prepare_personas,
    create=_create_persona,
    update=_update_persona,
    filter_params=PEOPLE_FILTERS,
    gate=(MODULE_KEY, "persona"),
    can_create=_may_manage_personas,
    can_update=_may_manage_personas,
    organization_owned=_persona_owned_by_org,
    organization=OrganizationRecordTable(
        subcomponent="persona",
        columns=lambda db, organization: _persona_columns_for(_org_type_choices(PERSONA_TYPES, db, organization)),
        list_records=_list_org_personas,
        find=_find_org_persona,
        find_many=find_many_by_code(Persona, "organization_id", Persona.scope == PersonaScope.ORGANIZATION),
        prepare=lambda db, organization, records: _prepare_personas(db, None, records),
        create=_create_org_persona,
        update=_update_org_persona,
        filter_params=frozenset({"search", "status", "type", "include_archived"}),
        can_create=_may_manage_org_personas,
        can_update=_may_manage_org_personas,
    ),
    count=lambda db, user, project_id: count_rows(db, Persona, project_id, live_only=True),
)


# --- Stakeholder --------------------------------------------------------------------------------------------------

_STAKEHOLDER_TEXT = {
    "description": "description", "interests": "interests", "responsibilities": "responsibilities", "goals_needs": "goals_needs",
    "priorities": "priorities", "constraints": "constraints", "workflows_scenarios": "workflows_scenarios",
}
_CADENCE_LABELS = label_map(TargetCadence)


def _stakeholder_owned_by_org(stakeholder: Stakeholder) -> bool:
    return stakeholder.scope == StakeholderScope.ORGANIZATION


def _prepare_stakeholders(db: Session, project: Project, records: list[Stakeholder]) -> _Prepared:
    prepared = _Prepared(db, records, STAKEHOLDER_ARTEFACT_TYPE, version_model=StakeholderVersion, version_fk="stakeholder_id")
    names = STAKEHOLDER_TYPES.display_names(db, [(v.org_type_id, v.project_type_id) for v in prepared.versions.values()])
    prepared.extra["types"] = {key: name or "" for key, name in names.items()}
    level_ids = {i for v in prepared.versions.values() for i in (v.influence_level_id, v.interest_level_id) if i}
    prepared.extra["levels"] = {
        level.id: level.name for level in db.scalars(select(ScoringLevel).where(ScoringLevel.id.in_(level_ids)))
    } if level_ids else {}
    return prepared


def _filter_stakeholders(
    db: Session, records: list[Stakeholder], filters: RecordFilters, organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> list[Stakeholder]:
    status, type_name = enum_filter(filters, "status", StakeholderStatus), filters.one("type")
    group_raw = filters.one("group_id")
    if group_raw is not None:
        try:
            group_id = uuid.UUID(group_raw)
        except ValueError:
            raise HTTPException(422, "group_id must be an id.") from None
        records = group_shared.filter_and_sort_stakeholders(
            db, records, grp.load_groups(db, organization_id, project_id), group_id=group_id,
            direct_only=bool(filters.flag("direct_only")), group_by=None,
        )
    versions = _version_map(db, StakeholderVersion, "stakeholder_id", records)
    names = STAKEHOLDER_TYPES.display_names(db, [(v.org_type_id, v.project_type_id) for v in versions.values()]) if type_name else {}
    out = []
    for s in records:
        v = versions[s.id]
        name = names.get((v.org_type_id, v.project_type_id))
        if (status is None or v.status == status) and (type_name is None or name == type_name) and _search_hit(
            filters, s.unique_code, v.name, v.role, v.organisation_group
        ):
            out.append(s)
    return out


def _list_stakeholders(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[Stakeholder]:
    project = _project(db, project_id)
    records = project_stakeholders(
        db, project, include_archived=bool(filters.flag("include_archived")),
        include_org=filters.flag("include_org") is not False, include_hidden=bool(filters.flag("include_hidden")),
    )
    return _filter_stakeholders(db, records, filters, project.organization_id, project.id)


def _list_org_stakeholders(db: Session, user: User, organization: Organization, filters: RecordFilters) -> list[Stakeholder]:
    records = organization_stakeholders(db, organization.id, include_archived=bool(filters.flag("include_archived")))
    return _filter_stakeholders(db, records, filters, organization.id, None)


def _stakeholder_columns(db: Session, project: Project) -> list[RecordColumn]:
    return _stakeholder_columns_for(_type_choices(STAKEHOLDER_TYPES, db, project))


def _stakeholder_columns_for(type_choices: tuple[str, ...]) -> list[RecordColumn]:
    def version(t: _Prepared, r: Stakeholder) -> StakeholderVersion:
        return t.versions[r.id]

    free = "free_text_people"
    return [
        _text("name", "Name", lambda t, r: version(t, r).name, required=True, sensitivity="personal"),
        RecordColumn(
            "type", "Type", lambda t, r: t.extra["types"].get((version(t, r).org_type_id, version(t, r).project_type_id), ""),
            _type_ref(STAKEHOLDER_TYPES, "stakeholder"), kind="enum", editable=True, choices=type_choices,
        ),
        _text("role", "Role", lambda t, r: version(t, r).role, sensitivity="personal"),
        _text("organisation_group", "Organisation or group", lambda t, r: version(t, r).organisation_group, sensitivity="personal"),
        _text("description", "Description", lambda t, r: version(t, r).description, sensitivity=free),
        _text("interests", "Interests", lambda t, r: version(t, r).interests, sensitivity=free),
        _text("responsibilities", "Responsibilities", lambda t, r: version(t, r).responsibilities, sensitivity=free),
        _text("goals_needs", "Goals and needs", lambda t, r: version(t, r).goals_needs, sensitivity=free),
        _text("priorities", "Priorities", lambda t, r: version(t, r).priorities, sensitivity=free),
        _text("constraints", "Constraints", lambda t, r: version(t, r).constraints, sensitivity=free),
        _text("workflows_scenarios", "Workflows and scenarios", lambda t, r: version(t, r).workflows_scenarios, sensitivity=free),
        _text("contact_info", "Contact details", lambda t, r: version(t, r).contact_info, sensitivity="contact"),
        RecordColumn(
            "target_cadence", "Target cadence",
            lambda t, r: _CADENCE_LABELS[version(t, r).target_cadence.value] if version(t, r).target_cadence else "",
            enum_parser(TargetCadence, "Target cadence"), kind="enum", editable=True, choices=tuple(_CADENCE_LABELS.values()),
        ),
        _text("availability_constraints", "Availability", lambda t, r: version(t, r).availability_constraints, sensitivity="contact"),
        RecordColumn("influence", "Influence", lambda t, r: t.extra["levels"].get(version(t, r).influence_level_id, ""), kind="enum"),
        RecordColumn("interest", "Interest", lambda t, r: t.extra["levels"].get(version(t, r).interest_level_id, ""), kind="enum"),
        _principal("owner", "Owner", "owner_type", "owner_id", version),
        _scope_column(_stakeholder_owned_by_org),
        _tags_column(),
        _status_column(version),
    ]


def _stakeholder_values(values: Mapping[str, Any]) -> dict[str, Any]:
    return _changed(values, {
        **_STAKEHOLDER_TEXT, "name": "name", "role": "role", "organisation_group": "organisation_group", "contact_info": "contact_info",
        "target_cadence": "target_cadence", "availability_constraints": "availability_constraints", "owner": "owner",
        "type": "stakeholder_type_id",
    })


def _create_stakeholder(ctx: RecordImportContext, values: Mapping[str, Any]) -> Stakeholder:
    payload = payload_of(StakeholderCreate, _stakeholder_values(values))
    return stakeholder_shared.stage_stakeholder(
        ctx.db, StakeholderScope.PROJECT, payload, ctx.user, organization_id=ctx.project.organization_id, project_id=ctx.project.id,
    )


def _update_stakeholder(ctx: RecordImportContext, stakeholder: Stakeholder, values: Mapping[str, Any]) -> None:
    payload = payload_of(StakeholderUpdate, {**_stakeholder_values(values), "change_note": "Edited by record import."})
    stakeholder_shared.stage_stakeholder_update(
        ctx.db, stakeholder, payload, ctx.user, organization_id=ctx.project.organization_id, project_id=ctx.project.id,
    )


def _find_stakeholder(db: Session, project: Project, code: str) -> Stakeholder | None:
    return db.scalar(select(Stakeholder).where(
        Stakeholder.project_id == project.id, Stakeholder.scope == StakeholderScope.PROJECT, Stakeholder.unique_code == code.upper()
    ))


def _may_manage_stakeholders(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return _allowed(
        stakeholder_shared.require_stakeholder_manage, db, user, StakeholderScope.PROJECT,
        organization_id=_project(db, project_id).organization_id, project_id=project_id,
    )


def _create_org_stakeholder(ctx: RecordImportContext, values: Mapping[str, Any]) -> Stakeholder:
    payload = payload_of(StakeholderCreate, _stakeholder_values(values))
    return stakeholder_shared.stage_stakeholder(
        ctx.db, StakeholderScope.ORGANIZATION, payload, ctx.user, organization_id=ctx.organization.id, project_id=None,
    )


def _update_org_stakeholder(ctx: RecordImportContext, stakeholder: Stakeholder, values: Mapping[str, Any]) -> None:
    payload = payload_of(StakeholderUpdate, {**_stakeholder_values(values), "change_note": "Edited by record import."})
    stakeholder_shared.stage_stakeholder_update(
        ctx.db, stakeholder, payload, ctx.user, organization_id=ctx.organization.id, project_id=None,
    )


def _find_org_stakeholder(db: Session, organization: Organization, code: str) -> Stakeholder | None:
    return db.scalar(select(Stakeholder).where(
        Stakeholder.organization_id == organization.id, Stakeholder.scope == StakeholderScope.ORGANIZATION,
        Stakeholder.unique_code == code.upper(),
    ))


def _may_manage_org_stakeholders(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    return _allowed(
        stakeholder_shared.require_stakeholder_manage, db, user, StakeholderScope.ORGANIZATION,
        organization_id=organization_id, project_id=None,
    )


STAKEHOLDER_TABLE = RecordTableProvider(
    label="Stakeholders",
    columns=_stakeholder_columns,
    list_records=_list_stakeholders,
    find=_find_stakeholder,
    find_many=find_many_by_code(Stakeholder, "project_id", Stakeholder.scope == StakeholderScope.PROJECT),
    prepare=_prepare_stakeholders,
    create=_create_stakeholder,
    update=_update_stakeholder,
    filter_params=PEOPLE_FILTERS | {"group_id", "direct_only"},
    gate=(MODULE_KEY, "stakeholder"),
    can_create=_may_manage_stakeholders,
    can_update=_may_manage_stakeholders,
    organization_owned=_stakeholder_owned_by_org,
    organization=OrganizationRecordTable(
        subcomponent="stakeholder",
        columns=lambda db, organization: _stakeholder_columns_for(_org_type_choices(STAKEHOLDER_TYPES, db, organization)),
        list_records=_list_org_stakeholders,
        find=_find_org_stakeholder,
        find_many=find_many_by_code(Stakeholder, "organization_id", Stakeholder.scope == StakeholderScope.ORGANIZATION),
        prepare=lambda db, organization, records: _prepare_stakeholders(db, None, records),
        create=_create_org_stakeholder,
        update=_update_org_stakeholder,
        filter_params=frozenset({"search", "status", "type", "include_archived", "group_id", "direct_only"}),
        can_create=_may_manage_org_stakeholders,
        can_update=_may_manage_org_stakeholders,
    ),
    count=lambda db, user, project_id: count_rows(db, Stakeholder, project_id, live_only=True),
)


# --- Stakeholder Group --------------------------------------------------------------------------------------------


def _group_owned_by_org(group: StakeholderGroup) -> bool:
    return group.scope == StakeholderScope.ORGANIZATION


def _group_context(db: Session, project_id: uuid.UUID) -> group_shared.GroupContext:
    project = _project(db, project_id)
    return group_shared.GroupContext(organization_id=project.organization_id, project=project)


def _prepare_groups(db: Session, project: Project | None, records: list[StakeholderGroup], organization_id: uuid.UUID | None = None) -> _Prepared:
    prepared = _Prepared(db, records, GROUP_ARTEFACT_TYPE)
    universe = grp.load_groups(db, project.organization_id if project else organization_id, project.id if project else None)

    def path(group: StakeholderGroup) -> str:
        names, seen, current = [], set(), group
        while current is not None and current.id not in seen:
            seen.add(current.id)
            names.append(current.name)
            current = universe.get(current.parent_group_id) if current.parent_group_id else None
        return " > ".join(reversed(names))

    ids = [g.id for g in records]
    member_group = StakeholderGroupMember.group_id
    counts = dict(db.execute(select(member_group, func.count()).where(member_group.in_(ids)).group_by(member_group)).all()) if ids else {}
    prepared.extra["paths"] = {g.id: path(g) for g in records}
    prepared.extra["members"] = counts
    return prepared


def _list_groups(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[StakeholderGroup]:
    groups = group_shared.visible_groups(db, _group_context(db, project_id))
    if filters.flag("include_org") is False:
        groups = [g for g in groups if g.scope == StakeholderScope.PROJECT]
    return [g for g in groups if _search_hit(filters, g.unique_code, g.name)]


def _list_org_groups(db: Session, user: User, organization: Organization, filters: RecordFilters) -> list[StakeholderGroup]:
    groups = group_shared.visible_groups(db, group_shared.GroupContext(organization_id=organization.id))
    return [g for g in groups if _search_hit(filters, g.unique_code, g.name)]


def _group_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        _text("name", "Name", lambda t, r: r.name, required=True),
        _text("description", "Description", lambda t, r: r.description),
        RecordColumn(
            "exclusive_children", "Members belong to one subgroup", lambda t, r: bool_cell(r.exclusive_children),
            bool_parser("Members belong to one subgroup"), kind="bool", editable=True,
        ),
        RecordColumn("parent", "Parent group", lambda t, r: t.extra["paths"][r.id].rpartition(" > ")[0], kind="text"),
        RecordColumn("members", "Members", lambda t, r: str(t.extra["members"].get(r.id, 0)), kind="number"),
        _scope_column(_group_owned_by_org),
        _tags_column(),
    ]


_GROUP_FIELDS = {"name": "name", "description": "description", "exclusive_children": "exclusive_children"}


def _import_group_context(ctx: RecordImportContext) -> group_shared.GroupContext:
    """The tier an import writes groups to: the project's, or (without one) the organisation's."""
    return group_shared.GroupContext(organization_id=ctx.organization_id, project=ctx.project)


def _create_group(ctx: RecordImportContext, values: Mapping[str, Any]) -> StakeholderGroup:
    payload = payload_of(StakeholderGroupCreate, _changed(values, _GROUP_FIELDS))
    return group_shared.stage_group(ctx.db, _import_group_context(ctx), payload, ctx.user)


def _update_group(ctx: RecordImportContext, group: StakeholderGroup, values: Mapping[str, Any]) -> None:
    payload = payload_of(StakeholderGroupUpdate, _changed(values, _GROUP_FIELDS))
    group_shared.stage_group_update(ctx.db, _import_group_context(ctx), group, payload, ctx.user)


def _find_group(db: Session, project: Project, code: str) -> StakeholderGroup | None:
    return db.scalar(select(StakeholderGroup).where(
        StakeholderGroup.project_id == project.id, StakeholderGroup.scope == StakeholderScope.PROJECT,
        StakeholderGroup.unique_code == code.upper(),
    ))


def _may_manage_groups(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return _allowed(group_shared.require_group_manage, db, user, _group_context(db, project_id))


def _find_org_group(db: Session, organization: Organization, code: str) -> StakeholderGroup | None:
    return db.scalar(select(StakeholderGroup).where(
        StakeholderGroup.organization_id == organization.id, StakeholderGroup.scope == StakeholderScope.ORGANIZATION,
        StakeholderGroup.unique_code == code.upper(),
    ))


def _may_manage_org_groups(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    return _allowed(group_shared.require_group_manage, db, user, group_shared.GroupContext(organization_id=organization_id))


GROUP_TABLE = RecordTableProvider(
    label="Stakeholder groups",
    columns=_group_columns,
    list_records=_list_groups,
    find=_find_group,
    find_many=find_many_by_code(StakeholderGroup, "project_id", StakeholderGroup.scope == StakeholderScope.PROJECT),
    prepare=_prepare_groups,
    create=_create_group,
    update=_update_group,
    filter_params=frozenset({"search", "include_org"}),
    gate=(MODULE_KEY, "stakeholder"),
    can_create=_may_manage_groups,
    can_update=_may_manage_groups,
    organization_owned=_group_owned_by_org,
    organization=OrganizationRecordTable(
        subcomponent="stakeholder",
        columns=lambda db, organization: _group_columns(db, None),
        list_records=_list_org_groups,
        find=_find_org_group,
        find_many=find_many_by_code(StakeholderGroup, "organization_id", StakeholderGroup.scope == StakeholderScope.ORGANIZATION),
        prepare=lambda db, organization, records: _prepare_groups(db, None, records, organization.id),
        create=_create_group,
        update=_update_group,
        filter_params=frozenset({"search"}),
        can_create=_may_manage_org_groups,
        can_update=_may_manage_org_groups,
    ),
    count=lambda db, user, project_id: count_rows(db, StakeholderGroup, project_id, live_only=False),
)


# --- Stakeholder Need ---------------------------------------------------------------------------------------------


def _list_needs(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[StakeholderNeed]:
    records = list_project_needs(db, project_id, include_archived=bool(filters.flag("include_archived")))
    status = enum_filter(filters, "status", NeedStatus)
    versions = _version_map(db, StakeholderNeedVersion, "need_id", records)
    return [
        n for n in records
        if (status is None or versions[n.id].status == status)
        and _search_hit(filters, n.unique_code, versions[n.id].name, versions[n.id].description)
    ]


def _need_columns(db: Session, project: Project) -> list[RecordColumn]:
    def version(t: _Prepared, r: StakeholderNeed) -> StakeholderNeedVersion:
        return t.versions[r.id]

    return [
        _text("name", "Name", lambda t, r: version(t, r).name, required=True),
        _text("description", "Description", lambda t, r: version(t, r).description),
        _text("rationale", "Rationale", lambda t, r: version(t, r).rationale),
        _principal("owner", "Owner", "owner_type", "owner_id", version),
        _tags_column(),
        _status_column(version),
    ]


_NEED_FIELDS = {"name": "name", "description": "description", "rationale": "rationale", "owner": "owner"}


def _create_need(ctx: RecordImportContext, values: Mapping[str, Any]) -> StakeholderNeed:
    return need_shared.stage_need(ctx.db, payload_of(NeedCreate, _changed(values, _NEED_FIELDS)), ctx.user, ctx.project)


def _update_need(ctx: RecordImportContext, need: StakeholderNeed, values: Mapping[str, Any]) -> None:
    payload = payload_of(NeedUpdate, {**_changed(values, _NEED_FIELDS), "change_note": "Edited by record import."})
    need_shared.stage_need_update(ctx.db, need, payload, ctx.user, ctx.project)


def _find_need(db: Session, project: Project, code: str) -> StakeholderNeed | None:
    return db.scalar(select(StakeholderNeed).where(StakeholderNeed.project_id == project.id, StakeholderNeed.unique_code == code.upper()))


def _may_manage_needs(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return _allowed(need_shared.require_need_manage, db, user, _project(db, project_id))


NEED_TABLE = RecordTableProvider(
    label="Stakeholder needs",
    columns=_need_columns,
    list_records=_list_needs,
    find=_find_need,
    find_many=find_many_by_code(StakeholderNeed, "project_id"),
    prepare=lambda db, project, records: _Prepared(db, records, NEED_ARTEFACT_TYPE, version_model=StakeholderNeedVersion, version_fk="need_id"),
    create=_create_need,
    update=_update_need,
    filter_params=frozenset({"search", "status", "include_archived"}),
    gate=(MODULE_KEY, "stakeholder_need"),
    can_create=_may_manage_needs,
    can_update=_may_manage_needs,
    count=lambda db, user, project_id: count_rows(db, StakeholderNeed, project_id, live_only=True),
)


# --- Engagement ---------------------------------------------------------------------------------------------------

_CHANNEL_LABELS = label_map(EngagementChannel)


def _channel_filter(filters: RecordFilters) -> str | None:
    """The `type` filter (the page filters by channel label) or `channel` (the stored value), as a stored value."""
    raw = filters.one("type") or filters.one("channel")
    if raw is None:
        return None
    for member in EngagementChannel:
        if raw.casefold() in {member.value.casefold(), ENGAGEMENT_CHANNEL_LABEL[member.value].casefold(), _CHANNEL_LABELS[member.value].casefold()}:
            return member.value
    raise HTTPException(422, "type is not a known channel.")


def _list_engagements(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[Engagement]:
    from datetime import date

    def day(key: str) -> date | None:
        raw = filters.one(key)
        try:
            return date.fromisoformat(raw) if raw else None
        except ValueError:
            raise HTTPException(422, f"{key} must be a date (YYYY-MM-DD).") from None

    def one_id(key: str) -> uuid.UUID | None:
        raw = filters.one(key)
        try:
            return uuid.UUID(raw) if raw else None
        except ValueError:
            raise HTTPException(422, f"{key} must be an id.") from None

    rows = engagement_shared.filter_engagements(
        db, _project(db, project_id), channel=_channel_filter(filters), stakeholder_id=one_id("stakeholder_id"),
        persona_id=one_id("persona_id"), date_from=day("date_from"), date_to=day("date_to"), retention_due=filters.flag("retention_due"),
    )
    return [e for e in rows if _search_hit(filters, e.unique_code, e.title, e.summary)]


def _prepare_engagements(db: Session, project: Project, records: list[Engagement]) -> _Prepared:
    prepared = _Prepared(db, records, ENGAGEMENT_ARTEFACT_TYPE)
    ids = [e.id for e in records]
    facilitators: dict[uuid.UUID, list[EngagementFacilitator]] = {}
    if ids:
        for row in db.scalars(
            select(EngagementFacilitator).where(EngagementFacilitator.engagement_id.in_(ids)).order_by(EngagementFacilitator.sort_order)
        ):
            facilitators.setdefault(row.engagement_id, []).append(row)
    prepared.people = PrincipalCells.load(
        db, [principal_ref(f.facilitator_type, f.facilitator_id) for rows in facilitators.values() for f in rows]
    )
    prepared.extra["facilitators"] = facilitators
    return prepared


def _facilitators_parser(ctx: RecordImportContext, text: str) -> list[PrincipalRef]:
    refs = []
    for part in (p.strip() for p in text.split(";")):
        if part:
            ref = parse_principal_cell(ctx, part, field_name="facilitators")
            if ref is not None:
                refs.append(ref)
    return refs


def _engagement_columns(db: Session, project: Project) -> list[RecordColumn]:
    free = "free_text_people"
    return [
        _text("title", "Title", lambda t, r: r.title, required=True),
        RecordColumn(
            "channel", "Channel", lambda t, r: ENGAGEMENT_CHANNEL_LABEL[r.channel.value], enum_parser(EngagementChannel, "Channel"),
            kind="enum", editable=True, required=True, choices=tuple(ENGAGEMENT_CHANNEL_LABEL.values()),
        ),
        RecordColumn(
            "engagement_date", "Date", lambda t, r: r.engagement_date.isoformat(), date_parser("Date"), kind="date", editable=True,
            required=True,
        ),
        RecordColumn(
            "facilitators", "Facilitators",
            lambda t, r: list_cell([t.people.text(f.facilitator_type, f.facilitator_id) for f in t.extra["facilitators"].get(r.id, [])]),
            _facilitators_parser, kind="list",
        ),
        _text("purpose", "Purpose", lambda t, r: r.purpose),
        _text("summary", "Summary", lambda t, r: r.summary, sensitivity=free),
        _text("notes", "Notes", lambda t, r: r.notes, sensitivity=free),
        RecordColumn(
            "consent_recorded", "Consent recorded", lambda t, r: bool_cell(r.consent_recorded), bool_parser("Consent recorded"),
            kind="bool", editable=True,
        ),
        RecordColumn(
            "retain_until", "Retain until", lambda t, r: r.retain_until.isoformat() if r.retain_until else "",
            date_parser("Retain until"), kind="date",
        ),
        _tags_column(),
    ]


_ENGAGEMENT_FIELDS = {
    "title": "title", "channel": "channel", "engagement_date": "engagement_date", "facilitators": "facilitators",
    "purpose": "purpose", "summary": "summary", "notes": "notes", "consent_recorded": "consent_recorded", "retain_until": "retain_until",
}


def _create_engagement(ctx: RecordImportContext, values: Mapping[str, Any]) -> Engagement:
    return engagement_shared.stage_engagement(ctx.db, payload_of(EngagementCreate, _changed(values, _ENGAGEMENT_FIELDS)), ctx.user, ctx.project)


def _update_engagement(ctx: RecordImportContext, engagement: Engagement, values: Mapping[str, Any]) -> None:
    engagement_shared.stage_engagement_update(
        ctx.db, engagement, payload_of(EngagementUpdate, _changed(values, _ENGAGEMENT_FIELDS)), ctx.user, ctx.project,
    )


def _find_engagement(db: Session, project: Project, code: str) -> Engagement | None:
    return db.scalar(select(Engagement).where(Engagement.project_id == project.id, Engagement.unique_code == code.upper()))


def _may_manage_engagements(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return _allowed(engagement_shared.require_engagement_manage, db, user, _project(db, project_id))


ENGAGEMENT_TABLE = RecordTableProvider(
    label="Engagements",
    columns=_engagement_columns,
    list_records=_list_engagements,
    find=_find_engagement,
    find_many=find_many_by_code(Engagement, "project_id"),
    prepare=_prepare_engagements,
    create=_create_engagement,
    update=_update_engagement,
    filter_params=frozenset({"search", "type", "channel", "stakeholder_id", "persona_id", "date_from", "date_to", "retention_due"}),
    gate=(MODULE_KEY, None),
    can_create=_may_manage_engagements,
    can_update=_may_manage_engagements,
    count=lambda db, user, project_id: count_rows(db, Engagement, project_id, live_only=False),
)


# --- Research Finding ---------------------------------------------------------------------------------------------


def _list_findings(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[ResearchFinding]:
    rows = db.scalars(
        select(ResearchFinding).where(ResearchFinding.project_id == project_id).order_by(ResearchFinding.created_at.desc())
    ).all()
    return [f for f in rows if _search_hit(filters, f.unique_code, f.title, f.description)]


def _prepare_findings(db: Session, project: Project, records: list[ResearchFinding]) -> _Prepared:
    prepared = _Prepared(db, records, FINDING_ARTEFACT_TYPE)
    ids = {f.engagement_id for f in records}
    prepared.extra["engagements"] = {
        e.id: e.unique_code for e in db.scalars(select(Engagement).where(Engagement.id.in_(ids)))
    } if ids else {}
    return prepared


def _engagement_of(ctx: RecordImportContext, code: str) -> Engagement:
    found = _find_engagement(ctx.db, ctx.project, code)
    if found is None:
        raise RecordCellError(f"No engagement with the code {code} in this project.")
    return found


def _finding_columns(db: Session, project: Project) -> list[RecordColumn]:
    return [
        _text("title", "Title", lambda t, r: r.title, required=True),
        _text("description", "Description", lambda t, r: r.description),
        RecordColumn(
            "engagement", "Engagement", lambda t, r: t.extra["engagements"].get(r.engagement_id, ""), text_parser, required=True,
        ),
        _tags_column(),
    ]


def _create_finding(ctx: RecordImportContext, values: Mapping[str, Any]) -> ResearchFinding:
    engagement = _engagement_of(ctx, values["engagement"])
    payload = payload_of(FindingCreate, _changed(values, {"title": "title", "description": "description"}))
    return research_shared.stage_finding(ctx.db, engagement, payload, ctx.user, ctx.project)


def _update_finding(ctx: RecordImportContext, finding: ResearchFinding, values: Mapping[str, Any]) -> None:
    if "engagement" in values and _engagement_of(ctx, values["engagement"]).id != finding.engagement_id:
        raise RecordCellError("A finding cannot be moved to another engagement.")
    payload = payload_of(FindingUpdate, _changed(values, {"title": "title", "description": "description"}))
    research_shared.stage_finding_update(ctx.db, finding, payload, ctx.user, ctx.project)


def _find_finding(db: Session, project: Project, code: str) -> ResearchFinding | None:
    return db.scalar(select(ResearchFinding).where(ResearchFinding.project_id == project.id, ResearchFinding.unique_code == code.upper()))


def _may_manage_findings(db: Session, user: User, project_id: uuid.UUID) -> bool:
    return _allowed(engagement_shared.require_finding_manage, db, user, _project(db, project_id))


FINDING_TABLE = RecordTableProvider(
    label="Research findings",
    columns=_finding_columns,
    list_records=_list_findings,
    find=_find_finding,
    find_many=find_many_by_code(ResearchFinding, "project_id"),
    prepare=_prepare_findings,
    create=_create_finding,
    update=_update_finding,
    filter_params=LIST_FILTERS,
    gate=(MODULE_KEY, RESEARCH_SUBCOMPONENT),
    can_create=_may_manage_findings,
    can_update=_may_manage_findings,
    count=lambda db, user, project_id: count_rows(db, ResearchFinding, project_id, live_only=False),
)


RECORD_TABLES: dict[str, RecordTableProvider] = {
    PERSONA_ARTEFACT_TYPE: PERSONA_TABLE,
    STAKEHOLDER_ARTEFACT_TYPE: STAKEHOLDER_TABLE,
    GROUP_ARTEFACT_TYPE: GROUP_TABLE,
    NEED_ARTEFACT_TYPE: NEED_TABLE,
    ENGAGEMENT_ARTEFACT_TYPE: ENGAGEMENT_TABLE,
    FINDING_ARTEFACT_TYPE: FINDING_TABLE,
}
