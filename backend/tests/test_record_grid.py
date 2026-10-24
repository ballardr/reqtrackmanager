"""Tests for the bulk edit grid engine (`services.record_tables.build_grid` / `update_row`, the `.../grid` and
`.../rows/{code}` routes) over the core record types: Requirements and Actions.

The grid is generic, so what it guarantees is checked here against types that are not Pain Points: the cells and
the columns it may edit, a save through the type's own edit path (a new version, its refusal of an approved
requirement), the stale-cell check, the rows of a related project being read-only, and the column rules every
provider must keep for the grid to be safe. Pain Point scores have their own file in the Context & Strategy module.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by another test.
"""

from __future__ import annotations

import uuid

import pytest

from app.database import SessionLocal
from app.models.enums import RequirementStatus
from app.models.project import Project
from app.models.requirement import RequirementVersion
from app.modules.registry import get_record_table_providers
from app.services.record_tables import GRID_KINDS, grid_editable
from tests.conftest import auth_headers
from tests.link_world import ACTION, REQ, World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Grid Org", context_strategy=True)


def _base(project: dict, record_type: str) -> str:
    return f"/api/v1/projects/{project['id']}/records/{record_type}"


def _grid(world: World, project: dict, record_type: str = REQ, **params):
    resp = world.client.get(f"{_base(project, record_type)}/grid", params=params, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _save(world: World, project: dict, code: str, cells: dict, expected: dict | None = None, record_type: str = REQ):
    return world.client.patch(
        f"{_base(project, record_type)}/rows/{code}", json={"cells": cells, "expected": expected or {}}, headers=auth_headers(world.token),
    )


def _versions(requirement_id: uuid.UUID) -> int:
    with SessionLocal() as db:
        return db.query(RequirementVersion).filter(RequirementVersion.requirement_id == requirement_id).count()


def test_a_requirements_grid_offers_its_closed_value_columns_and_leaves_free_text_to_the_form(world):
    project = world.project()
    world.requirement(project, "Alpha")
    grid = _grid(world, project)
    editable = {c["key"] for c in grid["columns"] if c["editable"]}
    assert "level" in editable and grid["can_edit"] is True
    assert not editable & {"name", "description", "reasoning", "clarification"}, "free text is edited in the form"
    level = next(c for c in grid["columns"] if c["key"] == "level")
    assert level["kind"] == "enum" and level["choices"]


def test_saving_an_enum_cell_writes_a_new_version_through_the_requirements_own_edit(world):
    project = world.project()
    rid = world.requirement(project, "Alpha")
    row = _grid(world, project)["rows"][0]
    level_choices = next(c for c in _grid(world, project)["columns"] if c["key"] == "level")["choices"]
    current = row["cells"]["level"]
    other = next(c for c in level_choices if c != current)

    resp = _save(world, project, row["code"], {"level": other}, {"level": current})
    assert resp.status_code == 200, resp.text
    assert resp.json()["cells"]["level"] == other and resp.json()["id"] == row["id"]
    assert _versions(rid) == 2
    assert _save(world, project, row["code"], {"level": other}, {"level": other}).status_code == 200
    assert _versions(rid) == 2, "an unchanged cell writes nothing"


def test_a_stale_cell_is_refused_with_the_current_value(world):
    project = world.project()
    rid = world.requirement(project, "Alpha")
    row = _grid(world, project)["rows"][0]
    choices = next(c for c in _grid(world, project)["columns"] if c["key"] == "level")["choices"]
    first, second = [c for c in choices if c != row["cells"]["level"]][:2]
    assert _save(world, project, row["code"], {"level": first}, {"level": row["cells"]["level"]}).status_code == 200
    stale = _save(world, project, row["code"], {"level": second}, {"level": row["cells"]["level"]})
    assert stale.status_code == 409 and f"'{first}'" in stale.json()["detail"]
    assert _versions(rid) == 2


def test_an_approved_requirement_is_a_read_only_row_and_a_save_is_refused_with_the_same_reason(world):
    project = world.project()
    rid = world.requirement(project, "Locked one")
    with SessionLocal() as db:
        version = db.query(RequirementVersion).filter(
            RequirementVersion.requirement_id == rid, RequirementVersion.valid_to.is_(None),
        ).one()
        version.status = RequirementStatus.APPROVED
        db.commit()
    row = _grid(world, project)["rows"][0]
    assert row["read_only"] and "change request" in row["read_only"]
    resp = _save(world, project, row["code"], {"level": "Goal"})
    assert resp.status_code == 409 and "change request" in resp.json()["detail"]
    assert _versions(rid) == 1


def test_an_actions_date_and_outcome_cells_save_through_its_edit_and_a_bad_date_is_refused(world):
    project = world.project()
    world.action(project, "Review spec")
    grid = _grid(world, project, ACTION)
    editable = {c["key"] for c in grid["columns"] if c["editable"]}
    assert {"outcome", "due_date"} <= editable
    code = grid["rows"][0]["code"]
    resp = _save(world, project, code, {"due_date": "2027-03-05"}, {"due_date": ""}, ACTION)
    assert resp.status_code == 200, resp.text
    assert resp.json()["cells"]["due_date"] == "2027-03-05"
    assert _save(world, project, code, {"due_date": "05/03/2027"}, record_type=ACTION).status_code == 422
    assert _save(world, project, code, {"title": "Renamed"}, record_type=ACTION).status_code == 422


def test_a_widened_scope_lists_a_related_projects_rows_read_only_and_they_cannot_be_saved_here(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.requirement(parent, "Parent record")
    world.requirement(child, "Child record")
    grid = _grid(world, parent, project_scope="children")
    rows = {r["cells"]["name"]: r for r in grid["rows"]}
    assert rows["Parent record"]["read_only"] is None
    assert child["code"] in rows["Child record"]["read_only"]
    resp = _save(world, parent, rows["Child record"]["code"], {"level": "Goal"})
    assert resp.status_code == 404


def test_the_grid_takes_the_exports_filters_and_refuses_an_unknown_one(world):
    project = world.project()
    world.requirement(project, "Alpha")
    world.requirement(project, "Beta")
    assert _grid(world, project, search="Alp")["total"] == 1
    bad = world.client.get(f"{_base(project, REQ)}/grid", params={"colour": "red"}, headers=auth_headers(world.token))
    assert bad.status_code == 422


def test_a_type_that_cannot_be_updated_has_no_edit_in_its_grid(world):
    project = world.project()
    grid = _grid(world, project, "change_request")
    assert grid["can_edit"] is False
    resp = _save(world, project, "CR-1", {"anything": "x"}, record_type="change_request")
    assert resp.status_code == 422


def test_every_grid_editable_column_can_be_written_and_is_a_closed_value_kind(world):
    project = world.project()
    with SessionLocal() as db:
        row = db.get(Project, uuid.UUID(project["id"]))
        for artefact_type, provider in get_record_table_providers().items():
            for column in provider.columns(db, row):
                if not grid_editable(column):
                    continue
                assert column.parse is not None and column.kind in GRID_KINDS, (artefact_type, column.key)
                assert provider.update is not None, f"{artefact_type}.{column.key} is grid-editable but the type cannot be updated"
