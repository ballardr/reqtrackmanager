"""Tests for the scoped link finder:
the bounded global search, narrowing one type by its browse levels, the `link-browse` endpoint, and
the guard that every registered artefact type declares at least one level.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by
another test or run.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.registry import get_all_registered_artefact_types, get_module_registry
from app.services.link_browse import (
    CANDIDATE_LIMIT,
    GLOBAL_MIN_QUERY,
    GLOBAL_PER_TYPE,
    MAX_LEVEL_OPTIONS,
    levels_for,
    parse_selected,
)
from tests.conftest import auth_headers
from tests.link_world import REQ, World

DEC = "decision"
PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Browse Org", decisions=True, context_strategy=True)


def _get(world: World, project: dict, artefact: tuple[str, uuid.UUID], suffix: str, token=None, **params):
    return world.client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/{suffix}", params=params,
        headers=auth_headers(token or world.token),
    )


def _search(world, project, artefact, **params):
    return _get(world, project, artefact, "link-candidates", **params)


def _browse(world, project, artefact, **params):
    return _get(world, project, artefact, "link-browse", **params)


def _items(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


# --- coverage guard --------------------------------------------------------------------------


def test_every_registered_artefact_type_declares_a_browse_level():
    """A new module's type cannot ship search-only by accident."""
    missing = sorted(t for t in get_all_registered_artefact_types() if not levels_for(t))
    assert missing == []


def test_every_level_of_a_module_type_is_narrowable():
    """A level with no `list_options` reads a facet, so the type must be able to narrow by it."""
    for definition in get_module_registry().values():
        for artefact_type, provider in definition.artefact_summary_providers.items():
            keys = [level.key for level in provider.browse_levels]
            assert len(keys) == len(set(keys)), f"{artefact_type} repeats a level key"
            assert provider.browse_levels, artefact_type


def test_the_fifteen_known_types_are_all_covered():
    assert {
        "requirement", "requirement_action", "decision", "pain_point", "strategy", "future_state",
        "guiding_principle", "open_question", "persona", "stakeholder", "stakeholder_need",
        "compliance_requirement", "project_compliance_requirement", "compliance_required_action_assessment",
        "compliance_evidence",
    } <= get_all_registered_artefact_types()


# --- selection parsing -----------------------------------------------------------------------


def test_parse_selected_reads_ordered_pairs_and_rejects_malformed_input():
    assert parse_selected(None) == {}
    assert parse_selected("standard:abc,version:def") == {"standard": "abc", "version": "def"}
    for bad in ("standard", "standard:", ":abc", "standard:a,standard:b"):
        with pytest.raises(Exception) as exc:
            parse_selected(bad)
        assert getattr(exc.value, "status_code", None) == 400


# --- global search ---------------------------------------------------------------------------


def test_global_search_needs_a_query_of_two_characters(world):
    project = world.project()
    page = world.requirement(project, "Page")
    world.requirement(project, "Voltage limit")
    assert GLOBAL_MIN_QUERY == 2
    assert _items(_search(world, project, (REQ, page))) == []
    assert _items(_search(world, project, (REQ, page), q="v")) == []
    assert [i["type"] for i in _items(_search(world, project, (REQ, page), q="vo"))] == [REQ]


def test_global_search_spans_types_and_labels_each_result(world):
    project = world.project()
    page = world.requirement(project, "Page")
    world.requirement(project, "Battery runtime")
    world.pain_point(project, "Battery drains fast")
    world.decision(project, "BAT-1")
    items = _items(_search(world, project, (REQ, page), q="batt"))
    assert {i["type"] for i in items} == {REQ, PAIN}
    assert {i["type_label"] for i in items} == {"Requirement", "Pain point"}
    # A decision whose title does not match is not offered; a matching code would be.
    assert all(i["type"] != DEC for i in items)


def test_global_search_takes_a_few_per_type_so_one_type_cannot_crowd_out_the_rest(world):
    project = world.project()
    page = world.requirement(project, "Page")
    for i in range(GLOBAL_PER_TYPE + 3):
        world.requirement(project, f"Shared needle {i}")
    world.pain_point(project, "Shared needle pain")
    body = _search(world, project, (REQ, page), q="needle").json()
    by_type: dict[str, int] = {}
    for item in body["items"]:
        by_type[item["type"]] = by_type.get(item["type"], 0) + 1
    assert by_type[REQ] == GLOBAL_PER_TYPE
    assert by_type[PAIN] == 1
    assert body["truncated"] is True
    assert len(body["items"]) <= CANDIDATE_LIMIT


def test_global_search_only_covers_types_enabled_in_the_project(client, admin_token):
    plain = World(client, admin_token, "Plain Org")
    project = plain.project()
    page = plain.requirement(project, "Page")
    plain.requirement(project, "Needle req")
    assert {i["type"] for i in _items(_search(plain, project, (REQ, page), q="needle"))} == {REQ}


# --- one type, narrowed by its levels --------------------------------------------------------


def test_requirement_levels_are_component_then_category(world):
    project = world.project()
    page = world.requirement(project, "Page")
    first = _browse(world, project, (REQ, page), other_type=REQ).json()
    assert (first["key"], first["label"]) == ("component", "Component")
    assert [o["label"] for o in first["options"]] == ["Software"]
    component_id = first["options"][0]["id"]
    second = _browse(world, project, (REQ, page), other_type=REQ, selected=f"component:{component_id}").json()
    assert (second["key"], second["label"]) == ("category", "Category")
    assert [o["label"] for o in second["options"]] == ["Performance"]
    category_id = second["options"][0]["id"]
    done = _browse(world, project, (REQ, page), other_type=REQ, selected=f"component:{component_id},category:{category_id}")
    assert done.status_code == 200 and done.json() is None


def test_narrowing_a_requirement_by_component_and_category(world):
    project = world.project()
    page = world.requirement(project, "Page")
    other_component = world.client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": "Hardware", "prefix": "HW"},
        headers=auth_headers(world.token),
    ).json()
    other_category = world.client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": "Thermal", "prefix": "TH", "component_id": other_component["id"]},
        headers=auth_headers(world.token),
    ).json()
    world.requirement(project, "Software one")
    hw = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Hardware one", "component_id": other_component["id"], "category_id": other_category["id"]},
        headers=auth_headers(world.token),
    )
    assert hw.status_code == 201, hw.text
    narrowed = _items(_search(world, project, (REQ, page), other_type=REQ, selected=f"component:{other_component['id']}"))
    assert [i["label"].split(" ", 1)[1] for i in narrowed] == ["Hardware one"]
    both = _items(_search(
        world, project, (REQ, page), other_type=REQ,
        selected=f"component:{other_component['id']},category:{other_category['id']}",
    ))
    assert len(both) == 1
    # The search text narrows within the chosen scope.
    assert _items(_search(world, project, (REQ, page), other_type=REQ, selected=f"component:{other_component['id']}", q="nope")) == []


def test_a_category_cannot_be_chosen_before_its_component_or_under_another_one(world):
    project = world.project()
    page = world.requirement(project, "Page")
    category = _browse(
        world, project, (REQ, page), other_type=REQ,
        selected=f"component:{_browse(world, project, (REQ, page), other_type=REQ).json()['options'][0]['id']}",
    ).json()["options"][0]["id"]
    # Out of order.
    assert _browse(world, project, (REQ, page), other_type=REQ, selected=f"category:{category}").status_code == 400
    assert _search(world, project, (REQ, page), other_type=REQ, selected=f"category:{category}").status_code == 400
    # An option the level never offered (another project's, or invented).
    assert _browse(world, project, (REQ, page), other_type=REQ, selected=f"component:{uuid.uuid4()}").status_code == 400
    # An unknown level key.
    assert _browse(world, project, (REQ, page), other_type=REQ, selected="flavour:x").status_code == 400


def test_a_selection_naming_another_projects_component_is_refused(world):
    project, other = world.project("A"), world.project("B")
    page = world.requirement(project, "Page")
    foreign = _browse(world, other, (REQ, world.requirement(other, "B page")), other_type=REQ).json()["options"][0]["id"]
    assert _browse(world, project, (REQ, page), other_type=REQ, selected=f"component:{foreign}").status_code == 400


def test_a_status_level_narrows_records_by_their_facet(world):
    project = world.project()
    page = world.requirement(project, "Page")
    world.pain_point(project, "Slow reports")
    first = _browse(world, project, (REQ, page), other_type=PAIN).json()
    assert first["key"] == "pain_point_type" and len(first["options"]) == 1
    option = first["options"][0]["id"]
    assert [i["label"] for i in _items(_search(world, project, (REQ, page), other_type=PAIN, selected=f"pain_point_type:{option}"))] == [
        "PP-001 Slow reports"
    ]
    assert _browse(world, project, (REQ, page), other_type=PAIN, selected=f"pain_point_type:{option}").json() is None


def test_a_decision_type_level_lists_the_types_in_use(world):
    project = world.project()
    page = world.requirement(project, "Page")
    world.decision(project, "DEC-1")
    step = _browse(world, project, (REQ, page), other_type=DEC).json()
    assert step["key"] == "decision_type" and step["label"] == "Decision type"
    assert step["options"] and all(o["label"] for o in step["options"])
    assert step["truncated"] is False


def test_level_options_filter_by_text_and_are_capped(world):
    project = world.project()
    page = world.requirement(project, "Page")
    assert [o["label"] for o in _browse(world, project, (REQ, page), other_type=REQ, q="soft").json()["options"]] == ["Software"]
    assert _browse(world, project, (REQ, page), other_type=REQ, q="zzz").json()["options"] == []
    assert MAX_LEVEL_OPTIONS == 200


def test_browse_is_empty_for_a_module_disabled_in_the_project(client, admin_token):
    plain = World(client, admin_token, "No Modules Org")
    project = plain.project()
    page = plain.requirement(project)
    assert _browse(plain, project, (REQ, page), other_type=DEC).json() is None
    assert _items(_search(plain, project, (REQ, page), other_type=DEC)) == []


def test_browse_rejects_unknown_types_unseen_artefacts_and_unrelated_projects(world):
    project, sibling = world.project("A"), world.project("B")
    page = world.requirement(project, "Page")
    assert _browse(world, project, (REQ, page), other_type="not_a_type").status_code == 404
    assert _browse(world, project, (REQ, uuid.uuid4()), other_type=REQ).status_code == 404
    assert _browse(world, project, (REQ, page), other_type=REQ, other_project_id=sibling["id"]).status_code == 404
    assert _browse(world, project, (REQ, page)).status_code == 422  # other_type is required


def test_non_member_is_refused_by_both_reads(world, client, admin_token):
    project = world.project()
    page = world.requirement(project)
    outsider = World(client, admin_token, "Outsider Org")
    assert _browse(world, project, (REQ, page), token=outsider.token, other_type=REQ).status_code == 403
    assert _search(world, project, (REQ, page), token=outsider.token, q="ab").status_code == 403


def test_searching_an_ancestor_project_uses_that_projects_levels(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    page = world.requirement(child, "Child page")
    world.requirement(parent, "Parent need")
    step = _browse(world, child, (REQ, page), other_type=REQ, other_project_id=parent["id"]).json()
    assert step["key"] == "component" and [o["label"] for o in step["options"]] == ["Software"]
    parent_component = step["options"][0]["id"]
    child_component = _browse(world, child, (REQ, page), other_type=REQ).json()["options"][0]["id"]
    assert parent_component != child_component
    # The child's own component is not an option of the parent's level.
    assert _browse(
        world, child, (REQ, page), other_type=REQ, other_project_id=parent["id"], selected=f"component:{child_component}"
    ).status_code == 400
    assert [i["label"].split(" ", 1)[1] for i in _items(_search(
        world, child, (REQ, page), other_type=REQ, other_project_id=parent["id"], selected=f"component:{parent_component}"
    ))] == ["Parent need"]
