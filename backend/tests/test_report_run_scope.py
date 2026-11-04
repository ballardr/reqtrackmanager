"""Tests for the projects a layout may run for (`run_scope` on the layout tree: `any`, `one`, `one_and_children`): the
setting in the tree, the text view and the field catalogue, and the refusal of every run that does not fit (sync run, queued
run and its repeat, draft preview, catalogue). Each test builds its own organisation.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.database import SessionLocal
from app.models.generated_report import GeneratedReport
from app.services import report_run_jobs
from app.services.report_layout_text import format_tree, parse_text
from app.services.report_layout_tree import empty_tree, validate_tree
from tests.conftest import auth_headers
from tests.link_world import World
from tests.test_custom_report_run import document_tree, make_layout, org_run, project_run, rows_of, sheet_tree


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Single Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def single(tree: dict[str, Any], scope: str = "one") -> dict[str, Any]:
    return {**tree, "run_scope": scope}


def queue_org(world: World, layout: dict, **body: Any):
    return world.client.post(
        f"/api/v1/orgs/{world.org['id']}/custom-reports/{layout['id']}/runs",
        json={"format": "csv", **body}, headers=auth_headers(world.token),
    )


# ---- the setting ------------------------------------------------------------------------------------------------


WORDS = {"any": "anyprojects", "one": "oneproject", "one_and_children": "projecttree"}


@pytest.mark.parametrize("family", ["document", "table"])
@pytest.mark.parametrize("scope", ["any", "one", "one_and_children"])
def test_the_setting_is_a_choice_on_either_family_and_round_trips_through_the_text_view(family, scope):
    tree = {**empty_tree(family), "run_scope": scope}

    assert validate_tree(tree).errors == []
    text = format_tree(tree)
    assert text.splitlines()[0].endswith(WORDS[scope])
    assert parse_text(text).tree == tree


def test_the_setting_must_be_one_of_the_three_values():
    errors = {e.path: e.message for e in validate_tree({**empty_tree("document"), "run_scope": "yes"}).errors}

    assert errors == {"run_scope": "Must be one of: any, one, one_and_children."}


def test_a_layout_without_the_setting_writes_nothing_in_its_text():
    text = format_tree(empty_tree("document"))

    assert not any(word in text for word in WORDS.values())


def test_the_layout_field_catalogue_offers_it_for_both_families(world):
    for family in ("document", "table"):
        url = f"/api/v1/orgs/{world.org['id']}/report-layouts/blocks"
        body = world.client.get(url, params={"family": family}, headers=auth_headers(world.token)).json()
        fields = {f["key"]: f for f in body["layout_fields"]}
        scope = fields["run_scope"]
        assert scope["kind"] == "choice" and scope["choices"] == ["any", "one", "one_and_children"] and scope["help"]


# ---- a synchronous run ------------------------------------------------------------------------------------------


def test_an_organisation_run_needs_exactly_one_project(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    world.requirement(alpha, "Alpha rule")
    world.requirement(beta, "Beta rule")
    layout = make_layout(world, single(sheet_tree("Reqs")), "Sign-off")

    none = org_run(world, layout)
    both = org_run(world, layout, project_ids=f"{alpha['id']},{beta['id']}")
    blank = org_run(world, layout, project_ids="")
    one = org_run(world, layout, project_ids=beta["id"])

    assert [r.status_code for r in (none, both, blank)] == [422, 422, 422]
    assert "single project" in none.json()["detail"] and "2 were chosen" in both.json()["detail"]
    assert one.status_code == 200 and [r[-1] for r in rows_of(one.json())] == ["Beta rule"]
    # The same project named twice is still one project.
    assert org_run(world, layout, project_ids=f"{beta['id']},{beta['id']}").status_code == 200


def test_a_project_the_caller_cannot_report_on_is_still_refused_as_before(world):
    world.project("Alpha")
    layout = make_layout(world, single(sheet_tree("Reqs")), "Sign-off")

    assert org_run(world, layout, project_ids=str(uuid.uuid4())).status_code == 404


def test_a_layout_without_the_setting_still_fans_out(world):
    world.project("Alpha"), world.project("Beta")
    old = make_layout(world, sheet_tree("Reqs"), "Everywhere")
    switched_off = make_layout(world, single(sheet_tree("Reqs"), "any"), "Explicitly off")

    for layout in (old, switched_off):
        assert org_run(world, layout).json()["eligible_projects"] == 2


def test_a_project_run_cannot_add_child_projects(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.requirement(parent, "In parent")
    world.requirement(child, "In child")
    layout = make_layout(world, single(document_tree()), "Charter", project=parent)

    refused = project_run(world, parent, layout, include_children=True)

    assert refused.status_code == 422 and "child projects" in refused.json()["detail"]
    assert project_run(world, parent, layout).json()["metrics"][0]["value"] == 1


def test_a_one_project_organisation_run_reads_like_a_project_run(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    world.requirement(alpha, "Alpha rule")
    world.requirement(beta, "Beta rule")
    layout = make_layout(world, single(sheet_tree("Reqs")), "Sign-off")

    report = org_run(world, layout, project_ids=beta["id"]).json()

    assert report["scope_label"] == "Beta" and report["sections"][0]["columns"] == ["Code", "Title"]


def test_one_project_and_its_children_merge_into_one_report(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.project("Other")
    world.requirement(parent, "In parent")
    world.requirement(child, "In child")
    layout = make_layout(world, single(sheet_tree("Reqs"), "one_and_children"), "Charter")

    alone = org_run(world, layout, project_ids=parent["id"]).json()
    merged = org_run(world, layout, project_ids=parent["id"], include_children="true").json()

    assert sorted(r[-1] for r in rows_of(alone)) == ["In parent"]
    assert sorted(r[-1] for r in rows_of(merged)) == ["In child", "In parent"]
    assert merged["scope_label"] == "Parent" and merged["eligible_projects"] == 2
    # Still exactly one project is named: several are refused whether or not children are included.
    both = f"{parent['id']},{child['id']}"
    assert org_run(world, layout, project_ids=both, include_children="true").status_code == 422
    assert org_run(world, layout, include_children="true").status_code == 422


def test_children_are_only_added_for_what_the_caller_can_read(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.requirement(parent, "In parent")
    world.requirement(child, "In child")
    layout = make_layout(world, single(sheet_tree("Reqs"), "one_and_children"), "Charter")
    from tests.test_custom_report_run import member_in

    only_parent = member_in(world, parent)

    report = org_run(world, layout, token=only_parent, project_ids=parent["id"], include_children="true").json()

    assert [r[-1] for r in rows_of(report)] == ["In parent"] and "In child" not in str(report)


def test_a_project_run_of_a_one_and_children_layout_may_include_children(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.requirement(parent, "In parent")
    world.requirement(child, "In child")
    tree = make_layout(world, single(document_tree(), "one_and_children"), "Charter", project=parent)

    alone = project_run(world, parent, tree).json()["metrics"][0]["value"]
    merged = project_run(world, parent, tree, include_children=True).json()["metrics"][0]["value"]

    assert (alone, merged) == (1, 2)


def test_children_cannot_be_added_to_a_fan_out(world):
    parent = world.project("Parent")
    layout = make_layout(world, sheet_tree("Reqs"), "Everywhere")

    refused = org_run(world, layout, project_ids=parent["id"], include_children="true")

    assert refused.status_code == 422 and "one project and its children" in refused.json()["detail"]


def test_queuing_one_project_and_its_children_carries_the_choice(world):
    parent = world.project("Parent")
    world.project("Child", parent=parent)
    layout = make_layout(world, single(sheet_tree("Reqs"), "one_and_children"), "Charter")

    queued = queue_org(world, layout, project_ids=[parent["id"]], include_children=True)

    assert queued.status_code == 202, queued.text
    while report_run_jobs.run_next():
        pass
    shown = world.client.get(f"/api/v1/report-runs/{queued.json()['id']}", headers=auth_headers(world.token)).json()
    assert shown["status"] == "ready"


def test_the_catalogue_carries_the_run_scope_and_drops_the_multi_selection(world):
    parent = world.project("Parent")
    make_layout(world, single(sheet_tree("Reqs")), "Sign-off")
    make_layout(world, single(document_tree()), "Charter", project=parent)
    make_layout(world, sheet_tree("Reqs"), "Everywhere")
    make_layout(world, single(sheet_tree("Reqs"), "one_and_children"), "Tree")

    org_entries = {
        e["title"]: e for e in world.client.get(
            f"/api/v1/orgs/{world.org['id']}/report-catalogue", headers=auth_headers(world.token),
        ).json() if e["module_key"] == "custom_reports"
    }
    project_entries = {
        e["title"]: e for e in world.client.get(
            f"/api/v1/projects/{parent['id']}/report-catalogue", headers=auth_headers(world.token),
        ).json() if e["module_key"] == "custom_reports"
    }

    assert org_entries["Sign-off"]["run_scope"] == "one"
    assert org_entries["Sign-off"]["supports_project_multi_filter"] is False
    assert org_entries["Everywhere"]["run_scope"] == "any"
    assert org_entries["Everywhere"]["supports_project_multi_filter"] is True
    assert project_entries["Charter"]["run_scope"] == "one"
    assert project_entries["Charter"]["supports_include_children"] is False
    assert [p["name"] for p in org_entries["Sign-off"]["projects"]] == ["Parent"]
    assert org_entries["Tree"]["run_scope"] == "one_and_children" and org_entries["Tree"]["supports_include_children"] is True
    assert org_entries["Tree"]["supports_project_multi_filter"] is False
    assert org_entries["Sign-off"]["supports_include_children"] is False


# ---- the background run -----------------------------------------------------------------------------------------


def test_queuing_is_refused_up_front_for_none_or_several_projects(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    layout = make_layout(world, single(sheet_tree("Reqs")), "Sign-off")

    assert queue_org(world, layout).status_code == 422
    assert queue_org(world, layout, project_ids=[alpha["id"], beta["id"]]).status_code == 422
    assert queue_org(world, layout, project_ids=[alpha["id"]]).status_code == 202


def test_a_queued_run_is_refused_for_child_projects(world):
    parent = world.project("Parent")
    layout = make_layout(world, single(document_tree()), "Charter", project=parent)

    resp = world.client.post(
        f"/api/v1/projects/{parent['id']}/custom-reports/{layout['id']}/runs",
        json={"format": "pdf", "include_children": True}, headers=auth_headers(world.token),
    )

    assert resp.status_code == 422


def test_generating_again_is_refused_when_the_layout_became_single_project(world, db):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    layout = make_layout(world, sheet_tree("Reqs"), "Everywhere")
    run = queue_org(world, layout, project_ids=[alpha["id"], beta["id"]]).json()
    row = db.get(GeneratedReport, uuid.UUID(run["id"]))
    row.status, row.error = "failed", report_run_jobs.FAILURE_OTHER
    db.commit()
    edited = world.client.put(
        f"/api/v1/orgs/{world.org['id']}/report-layouts/{layout['id']}/tree",
        json={"tree": single(sheet_tree("Reqs")), "base_version": layout["current_version"]}, headers=auth_headers(world.token),
    )
    assert edited.status_code == 200, edited.text

    resp = world.client.post(f"/api/v1/report-runs/{run['id']}/again", headers=auth_headers(world.token))

    assert resp.status_code in (409, 422) and "single project" in str(resp.json())


# ---- the draft preview ------------------------------------------------------------------------------------------


def test_the_draft_preview_holds_a_single_project_draft_to_the_same_rule(world):
    alpha, beta = world.project("Alpha"), world.project("Beta")
    url = f"/api/v1/orgs/{world.org['id']}/report-layouts/preview"
    tree = single(sheet_tree("Reqs"))

    refused = world.client.post(url, json={"tree": tree}, headers=auth_headers(world.token))
    two = world.client.post(url, json={"tree": tree, "project_ids": [alpha["id"], beta["id"]]}, headers=auth_headers(world.token))
    one = world.client.post(url, json={"tree": tree, "project_ids": [alpha["id"]]}, headers=auth_headers(world.token))

    assert (refused.status_code, two.status_code, one.status_code) == (422, 422, 200)
