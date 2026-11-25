"""Tests for the one list sort (`services.list_sort`): a Sort by key and an Order that every record list's export,
grid and record-list report follow, the default of code ascending, the numeric reading of a code (`DEC-2` before
`DEC-10`), a key the list does not offer being ignored, and the two paged lists (requirements, change requests)
accepting the same four keys.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime

import pytest

from app.database import SessionLocal
from app.models.project import Project
from app.modules.registry import get_record_table_providers
from app.services.list_sort import (
    COMMON_KEYS,
    ListSort,
    canonical_key,
    code_order_columns,
    natural_key,
    order_records,
)
from tests.conftest import auth_headers
from tests.link_world import World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Sort Org", context_strategy=True)


class _Row:
    def __init__(self, id_: int, value) -> None:
        self.id, self.value = id_, value


def _ids(rows) -> list[int]:
    return [r.id for r in rows]


# --- the ordering rules --------------------------------------------------------------------------------------------


def test_text_orders_case_insensitively_and_digit_runs_by_value():
    texts = ["REQ-10", "req-2", "REQ-1", "Req-9"]
    assert sorted(texts, key=natural_key) == ["REQ-1", "req-2", "Req-9", "REQ-10"]
    assert sorted(["b", "A", "a1", "a"], key=natural_key) == ["A", "a", "a1", "b"]


def test_a_missing_value_sorts_last_ascending_and_first_descending():
    rows = [_Row(1, "b"), _Row(2, None), _Row(3, "a"), _Row(4, "")]
    assert _ids(order_records(rows, lambda r: r.value)) == [3, 1, 2, 4]
    assert _ids(order_records(rows, lambda r: r.value, descending=True)) == [2, 4, 1, 3]


def test_equal_values_keep_a_fixed_order_so_a_page_never_repeats_or_skips_a_row():
    rows = [_Row(5, "x"), _Row(3, "x"), _Row(4, "x"), _Row(1, "x")]
    assert _ids(order_records(rows, lambda r: r.value)) == [1, 3, 4, 5]
    # Descending reverses the values, not the ties: equal rows still read in their own order.
    assert _ids(order_records(rows, lambda r: r.value, descending=True)) == [1, 3, 4, 5]
    mixed = [_Row(1, "b"), _Row(2, "a"), _Row(3, "b"), _Row(4, "a")]
    assert _ids(order_records(mixed, lambda r: r.value, descending=True)) == [1, 3, 2, 4]
    # A tie order of the caller's own (a code) comes before the id.
    assert _ids(order_records(mixed, lambda r: "same", tie_of=lambda r: -r.id)) == [4, 3, 2, 1]


def test_numbers_and_instants_order_by_value_not_as_text():
    rows = [_Row(1, 10), _Row(2, 9), _Row(3, 100)]
    assert _ids(order_records(rows, lambda r: r.value)) == [2, 1, 3]
    early, late = datetime(2026, 1, 1, tzinfo=UTC).timestamp(), datetime(2026, 11, 1, tzinfo=UTC).timestamp()
    assert _ids(order_records([_Row(1, late), _Row(2, early)], lambda r: r.value)) == [2, 1]


def test_the_sort_parameters_are_read_leniently():
    assert ListSort.read("code", "desc") == ListSort(key="code", descending=True)
    assert ListSort.read("unique_code", "asc") == ListSort(key="code", descending=False)
    assert ListSort.read("created_at", "sideways") == ListSort(key="created", descending=False)
    assert ListSort.read(None, "desc") == ListSort(key=None, descending=True)
    assert ListSort.read("x" * 200, "asc").key is None
    assert canonical_key("updated_at") == "modified"


# --- the database order of a code ---------------------------------------------------------------------------------


def test_the_database_orders_a_code_by_prefix_then_number():
    from sqlalchemy import String as SaString
    from sqlalchemy import column as sa_column
    from sqlalchemy import select, values

    codes = ["DEC-10", "DEC-2", "ADR-3", "dec-1", "NOPE"]
    table = values(sa_column("code", SaString), name="t").data([(c,) for c in codes])
    db = SessionLocal()
    try:
        ordered = list(db.scalars(select(table.c.code).order_by(*code_order_columns(table.c.code))))
    finally:
        db.close()
    assert ordered == ["ADR-3", "dec-1", "DEC-2", "DEC-10", "NOPE"]


# --- the export, grid and report of a list follow the sort -------------------------------------------------------------


def _decision_codes(world: World, project: dict, **params) -> list[str]:
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/records/decision/export", params=params, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return [row["code"] for row in csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")))]


def _decisions(world: World) -> dict:
    world.enable("decisions")
    project = world.project()
    for code in ("DEC-10", "DEC-2", "DEC-1"):
        world.decision(project, code)
    return project


def test_the_default_order_is_code_ascending_with_numbers_by_value(world):
    project = _decisions(world)
    assert _decision_codes(world, project) == ["DEC-1", "DEC-2", "DEC-10"]


def test_code_descending_reverses_it(world):
    project = _decisions(world)
    assert _decision_codes(world, project, sort="code", order="desc") == ["DEC-10", "DEC-2", "DEC-1"]


def test_title_sorts_by_the_titles_column_and_a_column_key_by_its_cell_text(world):
    project = _decisions(world)
    assert _decision_codes(world, project, sort="title", order="desc") == ["DEC-10", "DEC-2", "DEC-1"]
    assert _decision_codes(world, project, sort="status") == ["DEC-1", "DEC-2", "DEC-10"]  # one status: the code breaks ties by id order


def test_created_and_modified_follow_the_time_the_row_was_written(world):
    project = _decisions(world)
    db = SessionLocal()
    try:
        from app.modules.decisions.models import Decision

        rows = {d.unique_code: d for d in db.query(Decision).filter(Decision.project_id == project["id"])}
        rows["DEC-2"].created_at = datetime(2020, 1, 1, tzinfo=UTC)
        rows["DEC-10"].created_at = datetime(2021, 1, 1, tzinfo=UTC)
        rows["DEC-1"].created_at = datetime(2022, 1, 1, tzinfo=UTC)
        rows["DEC-1"].updated_at = datetime(2020, 6, 1, tzinfo=UTC)
        rows["DEC-2"].updated_at = datetime(2021, 6, 1, tzinfo=UTC)
        rows["DEC-10"].updated_at = datetime(2022, 6, 1, tzinfo=UTC)
        db.commit()
    finally:
        db.close()
    assert _decision_codes(world, project, sort="created") == ["DEC-2", "DEC-10", "DEC-1"]
    assert _decision_codes(world, project, sort="created", order="desc") == ["DEC-1", "DEC-10", "DEC-2"]
    assert _decision_codes(world, project, sort="modified") == ["DEC-1", "DEC-2", "DEC-10"]
    assert _decision_codes(world, project, sort="updated_at", order="desc") == ["DEC-10", "DEC-2", "DEC-1"]


def test_an_unknown_key_or_order_is_ignored_and_the_default_applies(world):
    project = _decisions(world)
    assert _decision_codes(world, project, sort="nonsense", order="desc") == ["DEC-1", "DEC-2", "DEC-10"]
    assert _decision_codes(world, project, sort="code", order="sideways") == ["DEC-1", "DEC-2", "DEC-10"]


def test_the_grid_lists_its_rows_in_the_requested_order(world):
    project = _decisions(world)
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/records/decision/grid", params={"sort": "code", "order": "desc"},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    assert [r["code"] for r in resp.json()["rows"]] == ["DEC-10", "DEC-2", "DEC-1"]


def test_the_record_list_report_follows_the_lists_sort(world):
    project = _decisions(world)
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/reports/record-list",
        params={"record_type": "decision", "format": "csv", "sort": "code", "order": "desc"}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    codes = [row["code"] for row in csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")))]
    assert codes == ["DEC-10", "DEC-2", "DEC-1"]


# --- every registered type offers the four keys -----------------------------------------------------------------------


def test_every_record_type_offers_code_title_created_and_modified(world):
    """A provider's title column exists, and a type whose rows are not plain records gives its own times."""
    project = world.project()
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        for artefact_type, provider in get_record_table_providers().items():
            keys = {c.key for c in provider.columns(db, row)}
            assert provider.title_column in keys, f"{artefact_type}: no column {provider.title_column!r} for the Title sort"
            unknown = set(provider.sort_keys) - set(COMMON_KEYS) - keys
            assert not unknown, f"{artefact_type}: sort_keys names {sorted(unknown)}, which are neither common keys nor columns"
    finally:
        db.close()


def test_every_record_model_with_a_code_has_the_times_the_created_and_modified_sorts_read():
    """Created and Modified read the record's own `created_at` and `updated_at`: every model that carries a human-readable
    `unique_code` has both, or its provider supplies the keys itself."""
    from app.database import Base

    # A requirement alias is shown inside its requirement's row, never as a list of its own.
    not_listed = {"RequirementAlias"}
    missing = []
    for mapper in Base.registry.mappers:
        columns = set(mapper.columns.keys())
        if mapper.class_.__name__ not in not_listed and "unique_code" in columns and {"created_at", "updated_at"} - columns:
            missing.append(mapper.class_.__name__)
    assert missing == [], f"no created_at/updated_at on: {missing}"


# --- the paged lists ---------------------------------------------------------------------------------------------------


def _names(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [r["name"] for r in resp.json()]


def test_requirements_accept_the_four_keys_both_ways(world):
    project = world.project()
    for name in ("Charlie", "Alpha", "Bravo"):
        world.requirement(project, name)
    url = f"/api/v1/projects/{project['id']}/requirements"
    headers = auth_headers(world.token)
    assert _names(world.client.get(url, params={"sort": "title"}, headers=headers)) == ["Alpha", "Bravo", "Charlie"]
    assert _names(world.client.get(url, params={"sort": "title", "order": "desc"}, headers=headers)) == ["Charlie", "Bravo", "Alpha"]
    assert _names(world.client.get(url, params={"sort": "code"}, headers=headers)) == ["Charlie", "Alpha", "Bravo"]
    assert _names(world.client.get(url, params={"sort": "created", "order": "desc"}, headers=headers)) == ["Bravo", "Alpha", "Charlie"]
    assert _names(world.client.get(url, params={"sort": "modified", "order": "desc"}, headers=headers)) == ["Bravo", "Alpha", "Charlie"]
    assert world.client.get(url, params={"sort": "nonsense"}, headers=headers).status_code == 422


def test_a_requirement_edit_moves_it_to_the_top_of_a_modified_newest_first_list(world):
    project = world.project()
    ids = [world.requirement(project, name) for name in ("One", "Two", "Three")]
    headers = auth_headers(world.token)
    url = f"/api/v1/projects/{project['id']}/requirements"
    current = world.client.get(f"{url}/{ids[0]}", headers=headers).json()
    edited = world.client.put(
        f"{url}/{ids[0]}",
        json={
            "name": "One edited", "component_id": current["component_id"], "category_id": current["category_id"],
            "owner": current["owner"],
        },
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    assert _names(world.client.get(url, params={"sort": "modified", "order": "desc"}, headers=headers))[0] == "One edited"


def test_a_widened_scope_orders_every_projects_rows_together(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.requirement(parent, "Mango")
    world.requirement(child, "Apple")
    world.requirement(child, "Zebra")
    resp = world.client.get(
        f"/api/v1/projects/{parent['id']}/requirements", params={"sort": "title", "project_scope": "children"},
        headers=auth_headers(world.token),
    )
    assert _names(resp) == ["Apple", "Mango", "Zebra"]


def test_change_requests_accept_the_four_keys(world):
    project = world.project()
    headers = auth_headers(world.token)
    for name in ("Zebra change", "Alpha change", "Mid change"):
        created = world.client.post(
            f"/api/v1/projects/{project['id']}/change-requests",
            json={"kind": "new_requirement", "proposed_name": name, "reason": "because"}, headers=headers,
        )
        assert created.status_code == 201, created.text
    url = f"/api/v1/projects/{project['id']}/change-requests"

    def titles(**params) -> list[str]:
        resp = world.client.get(url, params=params, headers=headers)
        assert resp.status_code == 200, resp.text
        return [r["proposed_name"] for r in resp.json()]

    assert titles(sort="title") == ["Alpha change", "Mid change", "Zebra change"]
    assert titles(sort="code") == ["Zebra change", "Alpha change", "Mid change"]
    assert titles(sort="created", order="desc") == ["Mid change", "Alpha change", "Zebra change"]
    assert titles(sort="modified", order="desc") == ["Mid change", "Alpha change", "Zebra change"]
    assert world.client.get(url, params={"sort": "nonsense"}, headers=headers).status_code == 422
