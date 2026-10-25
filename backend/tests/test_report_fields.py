"""Tests for the custom-report field registry (`services.report_fields`, `ModuleDefinition.report_fields`).

Covers the coverage rule (every registered artefact type is reportable or says why not), the
declaration rules (reserved and repeated keys, one label per shared key), that every declared field
runs as SQL, the batch loader's values and bounded query count, and the module boundary. Each test
builds its own organisation, so none depends on state left by another.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models.requirement_action import RequirementAction
from app.modules.registry import (
    REPORT_FIELD_KINDS,
    get_all_registered_artefact_types,
    get_module_registry,
    get_not_reportable_types,
    get_report_field_providers,
)
from app.services import report_fields
from app.services.report_fields import UnknownReportFieldError, field_catalogue, format_value, load_records
from tests.conftest import auth_headers
from tests.link_world import ACTION, REQ, World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Report Fields Org", decisions=True, context_strategy=True)


# --- registry rules ---------------------------------------------------------------------------


def test_every_registered_artefact_type_is_reportable_or_says_why_not():
    providers = get_report_field_providers()
    reasons = get_not_reportable_types()
    for artefact_type in get_all_registered_artefact_types():
        assert artefact_type in providers or reasons.get(artefact_type), f"{artefact_type} has no report fields or reason"
    for artefact_type in providers:
        assert artefact_type not in reasons, f"{artefact_type} is both reportable and declared not reportable"
    assert set(providers) <= get_all_registered_artefact_types(), "a provider is registered for an unknown type"


def test_every_provider_declares_valid_fields():
    for artefact_type, provider in get_report_field_providers().items():
        assert report_fields.validate_provider(artefact_type, provider) == []
        assert {f.kind for f in provider.fields} <= set(REPORT_FIELD_KINDS)


def test_a_field_key_has_one_label_across_types():
    labels: dict[str, set[str]] = {}
    for provider in get_report_field_providers().values():
        for f in provider.fields:
            labels.setdefault(f.key, set()).add(f.label)
    assert {key: found for key, found in labels.items() if len(found) > 1} == {}


def test_validate_provider_reports_each_kind_of_mistake():
    from app.modules.registry import ReportField, ReportFieldProvider
    from app.services.report_fields import validate_provider

    base = get_report_field_providers()["requirement"]
    bad = ReportFieldProvider(
        from_clause=base.from_clause, columns=base.columns,
        fields=(
            ReportField("title", "T", base.columns.title), ReportField("x", "X", base.columns.title),
            ReportField("x", "X", base.columns.title), ReportField("k", "K", base.columns.title, kind="nope"),
            ReportField("p", "P", base.columns.title, kind="principal"), ReportField("e", "E", base.columns.title, kind="enum"),
        ),
    )
    problems = " | ".join(validate_provider("requirement", bad))
    for expected in ("reserved key", "declared twice", "unknown kind", "principal field without id_column", "enum field without labels"):
        assert expected in problems


def test_no_core_report_file_names_a_module():
    root = Path(__file__).resolve().parent.parent / "app" / "services"
    core_files = [root / "report_fields.py", root / "report_fields_core.py", root / "report_traversal.py"]
    for module_key in get_module_registry():
        for path in core_files:
            assert f"modules.{module_key}" not in path.read_text(), f"{path.name} imports module {module_key}"


def test_the_catalogue_lists_reserved_fields_first_and_rejects_an_unknown_type():
    keys = [f.key for f in field_catalogue("requirement")]
    assert keys[:4] == ["code", "title", "status", "tags"]
    assert {"component", "category", "owner", "level"} <= set(keys)
    level = next(f for f in field_catalogue("requirement") if f.key == "level")
    assert level.kind == "enum" and "Requirement" in level.choices
    with pytest.raises(UnknownReportFieldError):
        field_catalogue("no_such_type")


def test_a_personal_data_column_is_not_a_report_field():
    engagement = {f.key for f in get_report_field_providers()["engagement"].fields}
    assert not engagement & {"consent_recorded", "retain_until", "participants", "participant_name"}


# --- every declared field is valid SQL --------------------------------------------------------


def test_every_declared_field_of_every_type_runs_as_sql(world):
    db = SessionLocal()
    try:
        for artefact_type, provider in get_report_field_providers().items():
            keys = [f.key for f in provider.fields]
            # An id that exists nowhere: nothing is returned, but the whole statement is executed.
            assert load_records(db, artefact_type, [uuid.uuid4()], keys, with_tags=True) == {}, artefact_type
    finally:
        db.close()


# --- loader -----------------------------------------------------------------------------------


def _load(artefact_type: str, ids, keys=(), **kwargs):
    db = SessionLocal()
    try:
        return load_records(db, artefact_type, ids, keys, **kwargs)
    finally:
        db.close()


def test_a_requirement_loads_with_names_labels_and_utc_times(world):
    project = world.project("Fields P")
    req = world.requirement(project, "Alpha")

    record = _load(
        REQ, [req],
        ["description", "component", "category", "level", "owner", "review_date", "is_completed", "completed_at", "target_stage"],
        with_tags=True,
    )[req]

    assert record.title == "Alpha" and record.status == "Draft" and record.unique_code.endswith("001")
    assert record.project_id == uuid.UUID(project["id"]) and record.organization_id is None and not record.is_archived
    assert record.updated_at is not None and record.updated_at.tzinfo is not None
    values = record.values
    assert values["component"] and values["category"], "component and category read as names"
    assert values["level"] == "Requirement"
    assert values["owner"], "the owner reads as a name, never an id or an email"
    assert "@" not in values["owner"] and str(world.user_id) not in values["owner"]
    assert values["review_date"] is None and values["is_completed"] is False and values["completed_at"] is None
    assert record.tags == ""


def test_a_requirements_component_and_category_are_the_names_a_person_sees(world):
    project = world.project("Names P")
    req = world.requirement(project)
    headers = auth_headers(world.token)
    components = world.client.get(f"/api/v1/projects/{project['id']}/components", headers=headers).json()
    categories = world.client.get(f"/api/v1/projects/{project['id']}/categories", headers=headers).json()
    values = _load(REQ, [req], ["component", "category"])[req].values
    assert values["component"] == next(c["name"] for c in components if c["id"] == project["component_id"])
    assert values["category"] == next(c["name"] for c in categories if c["id"] == project["category_id"])


def test_an_action_loads_its_type_assignee_and_due_date(world):
    project = world.project("Action P")
    action = world.action(project, "Do it")
    db = SessionLocal()
    try:
        row = db.get(RequirementAction, action)
        row.due_date = date(2026, 3, 1)
        row.assignee_type, row.assignee_id = "user", world.user_id
        db.commit()
    finally:
        db.close()

    record = _load(ACTION, [action], ["action_type", "due_date", "assignee", "completed_at"])[action]

    assert record.title == "Do it"
    assert record.values["action_type"]
    assert record.values["due_date"] == date(2026, 3, 1) and format_value("date", record.values["due_date"]) == "2026-03-01"
    assert record.values["assignee"] and record.values["completed_at"] is None


def test_a_module_record_loads_its_typed_fields(world):
    project = world.project("Module P")
    decision = world.decision(project, "DEC-9")
    pain = world.pain_point(project, "Slow")

    d = _load("decision", [decision], ["decision_type", "owner", "decision_maker", "decision_date", "context"])[decision]
    p = _load("pain_point", [pain], ["priority", "owner", "date_identified", "is_intentional", "description"])[pain]

    assert d.unique_code == "DEC-9" and d.status == "Draft" and d.values["decision_type"] and d.values["owner"]
    assert d.values["decision_maker"] == "" and d.values["decision_date"] is None
    assert p.title == "Slow" and p.values["priority"] and p.values["is_intentional"] is False
    assert isinstance(p.values["date_identified"], date) and p.values["description"] == "Reports are late."


def test_an_unknown_id_is_absent_and_an_unknown_field_or_type_is_refused(world):
    project = world.project("Refuse P")
    req = world.requirement(project)
    missing = uuid.uuid4()

    assert set(_load(REQ, [req, missing])) == {req}
    with pytest.raises(UnknownReportFieldError):
        _load(REQ, [req], ["not_a_field"])
    with pytest.raises(UnknownReportFieldError):
        _load("no_such_type", [req])
    assert _load(REQ, []) == {}


def test_reserved_keys_are_accepted_and_always_present(world):
    project = world.project("Reserved P")
    req = world.requirement(project, "R")
    record = _load(REQ, [req], ["code", "title", "status", "tags"])[req]
    assert record.values == {} and record.title == "R"


def test_tags_load_as_text_when_asked(world):
    project = world.project("Tags P")
    req = world.requirement(project)
    headers = auth_headers(world.token)
    for name in ("beta", "alpha"):
        resp = world.client.post(
            f"/api/v1/projects/{project['id']}/artefacts/{REQ}/{req}/tags", json={"name": name}, headers=headers,
        )
        assert resp.status_code == 201, resp.text
    assert _load(REQ, [req], with_tags=True)[req].tags == "alpha, beta"
    assert _load(REQ, [req])[req].tags == ""


def test_the_number_of_queries_does_not_grow_with_the_number_of_records(world):
    project = world.project("Count P")
    ids = [world.requirement(project, f"R{i}") for i in range(2)]
    fields = ["component", "category", "owner", "level", "description"]

    def statements(record_ids) -> int:
        seen: list[str] = []

        def record(conn, cursor, statement, *args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            _load(REQ, record_ids, fields, with_tags=True)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    small = statements(ids)
    ids += [world.requirement(project, f"More{i}") for i in range(6)]
    assert statements(ids) == small


# --- formatting -------------------------------------------------------------------------------


def test_format_value_by_kind():
    assert format_value("date", date(2026, 1, 5)) == "2026-01-05"
    assert format_value("bool", True) == "Yes" and format_value("bool", False) == "No"
    assert format_value("number", 3.0) == "3" and format_value("number", 2.5) == "2.5" and format_value("number", 7) == "7"
    assert format_value("text", None) == "" and format_value("date", None) == "" and format_value("enum", "") == ""
    assert format_value("enum", "Draft") == "Draft"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        # Past instants stay UTC whatever the zone they were produced in (09:00 at UTC+10 and 23:00 at UTC-8).
        (datetime(2026, 7, 1, 23, 0, tzinfo=UTC), "2026-07-01T23:00:00Z"),
        (datetime(2026, 7, 1, 9, 0), "2026-07-01T09:00:00Z"),
    ],
)
def test_an_instant_is_formatted_in_utc(stored, expected):
    assert format_value("instant", stored) == expected


def test_a_calendar_date_is_not_converted_to_an_instant():
    # A due date means the person's own day: it is a plain date and prints as it was entered.
    assert format_value("date", date(2026, 7, 2)) == "2026-07-02"
