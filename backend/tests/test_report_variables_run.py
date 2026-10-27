"""Tests for running a layout with run-time variables against real records: narrowing by chosen values,
`{{var.name}}` text, defaults, refused values, the run form (defaults and options from field value domains),
preview, background queueing, provenance, the organisation fan-out, and the value-domain hook itself. The
declaration, reference and text-view rules are in `test_report_variables.py`. Each test builds its own organisation.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.generated_report import GeneratedReport
from app.modules.registry import get_report_field_providers
from app.services.report_fields import field_domain
from app.services.report_layout_tree import empty_tree
from tests.conftest import auth_headers
from tests.link_world import REQ, World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Vars Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


CATEGORIES = {"name": "categories", "type": "enum", "multiple": True, "label": "Categories", "source": {"record_type": REQ, "field": "category"}}


def layout_tree(*variables: dict[str, Any]) -> dict[str, Any]:
    """Requirements in the chosen categories, one line each, headed by the choice."""
    return {
        **empty_tree("document"),
        "variables": list(variables) or [CATEGORIES],
        "nodes": [
            {"type": "heading", "text": "For {{var.categories}}"},
            {
                "type": "each",
                "source": {
                    "record_type": REQ, "sort": [{"field": "title"}],
                    "where": [{"field": "category", "op": "in", "value": {"var": "categories"}}],
                },
                "children": [{"type": "text", "text": "{{record.title}} [{{record.category}}]"}],
            },
        ],
    }


def make_layout(world: World, tree: dict[str, Any], name: str = "By category", *, project: dict | None = None) -> dict:
    base = f"/api/v1/projects/{project['id']}" if project else f"/api/v1/orgs/{world.org['id']}"
    resp = world.client.post(
        f"{base}/report-layouts", json={"name": name, "description": "d", "family": tree["family"], "tree": tree},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def category(world: World, project: dict, name: str) -> str:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": name, "prefix": name[:4].upper(), "component_id": project["component_id"]}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def requirement_in(world: World, project: dict, name: str, category_id: str) -> None:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": name, "component_id": project["component_id"], "category_id": category_id}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text


@pytest.fixture
def scene(world):
    """A project with requirements in three categories (Security, Usability, Billing)."""
    project = world.project("Alpha")
    ids = {name: category(world, project, name) for name in ("Security", "Usability", "Billing")}
    requirement_in(world, project, "Login must be strong", ids["Security"])
    requirement_in(world, project, "Audit trail", ids["Security"])
    requirement_in(world, project, "Large buttons", ids["Usability"])
    requirement_in(world, project, "Invoice numbering", ids["Billing"])
    return project


def run(world: World, project: dict, layout: dict, variables: dict[str, Any] | None = None, **params: Any):
    if variables is not None:
        params["variables"] = json.dumps(variables)
    return world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params=params, headers=auth_headers(world.token),
    )


def printed(report: dict) -> list[str]:
    return report["notes"]


# ---- narrowing ----------------------------------------------------------------------------------------------------


def test_a_run_shows_only_the_chosen_categories_and_names_them(world, scene):
    layout = make_layout(world, layout_tree(), project=scene)

    resp = run(world, scene, layout, {"categories": ["Security", "Billing"]})

    assert resp.status_code == 200, resp.text
    assert printed(resp.json()) == [
        "For Security, Billing", "Audit trail [Security]", "Invoice numbering [Billing]", "Login must be strong [Security]",
    ]


def test_another_choice_gives_another_report_from_the_same_layout(world, scene):
    layout = make_layout(world, layout_tree(), project=scene)

    only_usability = run(world, scene, layout, {"categories": ["Usability"]}).json()

    assert printed(only_usability) == ["For Usability", "Large buttons [Usability]"]


def test_a_default_is_used_when_nothing_is_supplied(world, scene):
    layout = make_layout(world, layout_tree({**CATEGORIES, "default": ["Billing"]}), project=scene)

    assert printed(run(world, scene, layout).json()) == ["For Billing", "Invoice numbering [Billing]"]


def test_a_value_is_a_literal_and_never_markup_or_a_placeholder(world, scene):
    layout = make_layout(world, layout_tree({"name": "categories", "type": "text", "multiple": True}), project=scene)

    hostile = "# Big {{record.title}} \\( x \\)"
    resp = run(world, scene, layout, {"categories": [hostile]})

    assert resp.status_code == 200
    assert printed(resp.json()) == [f"For {hostile}"]  # still text, not a heading, a placeholder or an equation


def test_a_missing_or_unacceptable_value_is_refused_with_the_problems_listed(world, scene):
    layout = make_layout(world, layout_tree(), project=scene)

    missing = run(world, scene, layout)
    wrong = run(world, scene, layout, {"categories": "Security", "ghost": 1})

    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "variable_values"
    assert missing.json()["detail"]["problems"] == [{"name": "categories", "message": "Needs a value."}]
    names = {p["name"] for p in wrong.json()["detail"]["problems"]}
    assert names == {"categories", "ghost"}


def test_the_variables_parameter_must_be_a_json_object(world, scene):
    layout = make_layout(world, layout_tree(), project=scene)
    for bad in ("not json", "[1]", '"x"'):
        resp = world.client.get(
            f"/api/v1/projects/{scene['id']}/custom-reports/{layout['id']}/run", params={"variables": bad}, headers=auth_headers(world.token),
        )
        assert resp.status_code == 422, bad


def test_a_value_outside_the_current_options_runs_but_is_flagged(world, scene):
    layout = make_layout(world, layout_tree(), project=scene)

    notes = printed(run(world, scene, layout, {"categories": ["Retired"]}).json())

    warnings = [n for n in notes if "not one of its current options" in n]
    assert len(warnings) == 1 and "Retired" not in warnings[0]  # names the variable, not the value
    assert [n for n in notes if n not in warnings] == ["For Retired"]


def test_files_are_produced_with_the_same_values(world, scene):
    layout = make_layout(world, layout_tree(), project=scene)

    resp = run(world, scene, layout, {"categories": ["Usability"]}, format="html")

    assert resp.status_code == 200 and "Large buttons" in resp.text and "Audit trail" not in resp.text


# ---- provenance ---------------------------------------------------------------------------------------------------


def test_the_run_records_the_values_it_used(world, scene, db):
    since = {"name": "since", "type": "date", "default": "today"}
    layout = make_layout(world, layout_tree({**CATEGORIES, "default": ["Billing"]}, since), project=scene)
    layout_id = uuid.UUID(layout["id"])

    assert run(world, scene, layout, {"categories": ["Security"]}).status_code == 200

    row = db.scalars(select(GeneratedReport).where(GeneratedReport.layout_id == layout_id)).one()
    assert row.params["variables"]["categories"] == ["Security"]
    assert len(row.params["variables"]["since"]) == 10  # today became the day it was run


def test_a_refused_run_leaves_no_provenance_row(world, scene, db):
    layout = make_layout(world, layout_tree(), project=scene)

    assert run(world, scene, layout).status_code == 422

    assert db.scalars(select(GeneratedReport).where(GeneratedReport.layout_id == uuid.UUID(layout["id"]))).first() is None


# ---- the run form ---------------------------------------------------------------------------------------------------


def test_the_run_form_offers_the_current_values_of_the_source_field(world, scene):
    layout = make_layout(world, layout_tree({**CATEGORIES, "default": ["Billing"]}), project=scene)

    resp = world.client.get(
        f"/api/v1/projects/{scene['id']}/custom-reports/{layout['id']}/variables", headers=auth_headers(world.token),
    )

    assert resp.status_code == 200, resp.text
    [form] = resp.json()["variables"]
    assert form["name"] == "categories" and form["label"] == "Categories" and form["multiple"] is True
    assert form["default"] == ["Billing"] and form["source"] == {"record_type": REQ, "field": "category"}
    assert {"Security", "Usability", "Billing"} <= set(form["options"])


def test_the_run_form_resolves_a_date_default_to_the_callers_day_and_enum_labels(world, scene):
    tree = layout_tree(
        CATEGORIES, {"name": "since", "type": "date", "default": "today"},
        {"name": "level", "type": "enum", "source": {"record_type": REQ, "field": "level"}},
        {"name": "free", "type": "text"},
    )
    layout = make_layout(world, tree, project=scene)

    resp = world.client.get(
        f"/api/v1/projects/{scene['id']}/custom-reports/{layout['id']}/variables",
        headers={**auth_headers(world.token), "X-Client-Date": "2026-10-27"},
    )
    forms = {v["name"]: v for v in resp.json()["variables"]}

    assert forms["since"]["default"] in {"2026-10-26", "2026-10-27", "2026-10-28"} and forms["since"]["options"] is None
    assert forms["level"]["options"] == ["Requirement", "Recommended", "Optional"]
    assert forms["free"]["options"] is None and forms["free"]["default"] is None and forms["free"]["label"] == "free"


def test_the_catalogue_entry_carries_the_run_form(world, scene):
    with_form = make_layout(world, layout_tree({**CATEGORIES, "default": ["Billing"]}), "With form", project=scene)
    without = make_layout(world, {**empty_tree("document"), "nodes": [{"type": "text", "text": "x"}]}, "Without", project=scene)

    catalogue = world.client.get(f"/api/v1/projects/{scene['id']}/report-catalogue", headers=auth_headers(world.token)).json()
    by_title = {e["title"]: e for e in catalogue if e["module_key"] == "custom_reports"}

    [form] = by_title["With form"]["variables"]
    assert form["name"] == "categories" and form["default"] == ["Billing"] and "Security" in form["options"]
    assert by_title["Without"]["variables"] == []
    assert with_form["id"] in by_title["With form"]["path"] and without["id"] in by_title["Without"]["path"]


def test_a_layout_without_variables_has_an_empty_form(world, scene):
    layout = make_layout(world, {**empty_tree("document"), "nodes": [{"type": "text", "text": "x"}]}, project=scene)

    resp = world.client.get(
        f"/api/v1/projects/{scene['id']}/custom-reports/{layout['id']}/variables", headers=auth_headers(world.token),
    )

    assert resp.json() == {"variables": []}


def test_the_run_form_of_a_draft_for_the_designer(world, scene):
    resp = world.client.post(
        f"/api/v1/projects/{scene['id']}/report-layouts/variables", json={"tree": layout_tree()}, headers=auth_headers(world.token),
    )
    bad = world.client.post(
        f"/api/v1/projects/{scene['id']}/report-layouts/variables", json={"text": "@layout document\n@var a colour\n"},
        headers=auth_headers(world.token),
    )

    assert resp.status_code == 200 and resp.json()["ok"] is True
    assert {"Security", "Billing"} <= set(resp.json()["variables"][0]["options"])
    assert bad.status_code == 200 and bad.json()["ok"] is False and bad.json()["errors"][0]["line"] == 2


# ---- preview and background -----------------------------------------------------------------------------------------


def test_a_preview_takes_values_for_its_draft(world, scene):
    resp = world.client.post(
        f"/api/v1/projects/{scene['id']}/report-layouts/preview",
        json={"tree": layout_tree(), "variables": {"categories": ["Usability"]}}, headers=auth_headers(world.token),
    )
    refused = world.client.post(
        f"/api/v1/projects/{scene['id']}/report-layouts/preview", json={"tree": layout_tree()}, headers=auth_headers(world.token),
    )

    assert resp.status_code == 200 and "Large buttons" in resp.json()["html"] and "Audit trail" not in resp.json()["html"]
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "variable_values"


def test_a_background_run_is_queued_with_checked_values_and_keeps_them(world, scene, db):
    layout = make_layout(world, layout_tree(), project=scene)
    url = f"/api/v1/projects/{scene['id']}/custom-reports/{layout['id']}/runs"

    bad = world.client.post(url, json={"format": "pdf"}, headers=auth_headers(world.token))
    queued = world.client.post(url, json={"format": "pdf", "variables": {"categories": ["Security"]}}, headers=auth_headers(world.token))

    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "variable_values"
    assert queued.status_code == 202, queued.text
    row = db.get(GeneratedReport, uuid.UUID(queued.json()["id"]))
    assert row.params["variables"] == {"categories": ["Security"]}


# ---- the organisation fan-out ---------------------------------------------------------------------------------------


def test_an_organisation_run_applies_the_same_values_to_every_project(world, scene):
    second = world.project("Beta")
    sec = category(world, second, "Security")
    requirement_in(world, second, "Beta security rule", sec)
    requirement_in(world, second, "Beta other", category(world, second, "Other"))
    layout = make_layout(world, layout_tree())

    resp = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/custom-reports/{layout['id']}/run",
        params={"variables": json.dumps({"categories": ["Security"]})}, headers=auth_headers(world.token),
    )
    form = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/custom-reports/{layout['id']}/variables", headers=auth_headers(world.token),
    )

    assert resp.status_code == 200, resp.text
    notes = printed(resp.json())
    assert "Audit trail [Security]" in notes and "Beta security rule [Security]" in notes
    assert not any("Other" in n or "Usability" in n for n in notes)
    assert {"Security", "Usability", "Billing", "Other"} <= set(form.json()["variables"][0]["options"])


def test_an_organisation_run_form_cannot_name_a_project_the_caller_cannot_report_on(world, scene):
    layout = make_layout(world, layout_tree())

    resp = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/custom-reports/{layout['id']}/variables",
        params={"project_ids": str(uuid.uuid4())}, headers=auth_headers(world.token),
    )

    assert resp.status_code == 404


# ---- the value-domain hook ------------------------------------------------------------------------------------------


def test_a_project_defined_vocabulary_offers_its_names_including_an_ancestors(world, db):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    category(world, parent, "Parent only")
    category(world, child, "Child only")

    from_child = field_domain(db, REQ, "category", [uuid.UUID(child["id"])])
    from_parent = field_domain(db, REQ, "category", [uuid.UUID(parent["id"])])

    assert {"Parent only", "Child only"} <= set(from_child or [])
    assert "Child only" not in (from_parent or [])


def test_enum_and_status_fields_offer_their_labels_and_other_fields_take_free_input(world, db):
    project = uuid.UUID(world.project("D")["id"])

    assert field_domain(db, REQ, "level", [project]) == ["Requirement", "Recommended", "Optional"]
    assert field_domain(db, REQ, "status", [project])
    assert field_domain(db, REQ, "title", [project]) is None
    assert field_domain(db, REQ, "review_date", [project]) is None


def test_the_fields_that_name_a_project_defined_row_declare_their_value_domain():
    """Without a domain a variable over the project's own names (component, category, stage, action or decision type)
    would be free text where the person expects a list."""
    providers = get_report_field_providers()
    lookups = {
        "requirement": ("component", "category", "target_stage"),
        "requirement_action": ("action_type",),
        "decision": ("decision_type",),
    }
    for artefact_type, keys in lookups.items():
        by_key = {f.key: f for f in providers[artefact_type].fields}
        for key in keys:
            assert by_key[key].domain is not None, f"{artefact_type}.{key}"
