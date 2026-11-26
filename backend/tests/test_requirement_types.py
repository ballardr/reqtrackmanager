"""Requirement types: the two-tier list, the type on a requirement (a versioned field), and every path that carries it.

Pins that a new organisation has the default list, a project overrides, hides and restores entries and inherits a
configured ancestor's list, a requirement's type is set on create and edit (omitted leaves it, null clears it),
an approved requirement is retyped only through a change request, and the type survives a project export and import,
the record table export and import, and the record sub-type lookup the traceability rules use.
"""

from __future__ import annotations

import csv
import io
import uuid

from app.database import SessionLocal
from app.modules.registry import resolve_record_subtypes
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project

DEFAULTS = ["Business Requirement", "Stakeholder Requirement", "Project Requirement"]


def _types(client, token, project_id) -> list[dict]:
    resp = client.get(f"/api/v1/projects/{project_id}/requirement-types", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _type_id(client, token, project_id, name) -> str:
    return next(t["id"] for t in _types(client, token, project_id) if t["name"] == name)


def _requirement(client, token, project_id, component_id, category_id, name="Boot fast", **extra) -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id, **extra},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _put(client, token, project_id, requirement: dict, **changes):
    body = {
        "name": requirement["name"], "component_id": requirement["component_id"], "category_id": requirement["category_id"],
        "owner": {"type": "user", "id": requirement["owner"]["id"]}, **changes,
    }
    return client.put(
        f"/api/v1/projects/{project_id}/requirements/{requirement['id']}", json=body, headers=auth_headers(token),
    )


def _setup(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    return project, component_id, category_id


# --- the list ---------------------------------------------------------------------------------------


def test_a_new_organisation_has_the_default_types_in_order(client, admin_token, org_id):
    org_list = client.get(f"/api/v1/orgs/{org_id}/requirement-types", headers=auth_headers(admin_token))
    assert org_list.status_code == 200, org_list.text
    assert [t["name"] for t in org_list.json()] == DEFAULTS
    project = create_project(client, admin_token, org_id)
    assert [t["name"] for t in _types(client, admin_token, project["id"])] == DEFAULTS


def test_organisation_admin_adds_renames_and_reorders_types(client, admin_token, org_id):
    created = client.post(f"/api/v1/orgs/{org_id}/requirement-types", json={"name": "Regulatory"}, headers=auth_headers(admin_token))
    assert created.status_code == 201, created.text
    moved = client.post(
        f"/api/v1/orgs/{org_id}/requirement-types/{created.json()['id']}/move", json={"direction": "up"}, headers=auth_headers(admin_token),
    )
    assert moved.status_code == 200, moved.text
    renamed = client.patch(
        f"/api/v1/orgs/{org_id}/requirement-types/{created.json()['id']}", json={"name": "Regulation"}, headers=auth_headers(admin_token),
    )
    assert renamed.status_code == 200, renamed.text
    names = [t["name"] for t in client.get(f"/api/v1/orgs/{org_id}/requirement-types", headers=auth_headers(admin_token)).json()]
    assert names == [DEFAULTS[0], DEFAULTS[1], "Regulation", DEFAULTS[2]]


def test_project_overrides_adds_and_hides_then_restores(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    business = _type_id(client, admin_token, pid, "Business Requirement")
    renamed = client.put(f"/api/v1/projects/{pid}/requirement-types/{business}", json={"name": "Enterprise"}, headers=auth_headers(admin_token))
    assert renamed.status_code == 200, renamed.text
    local = client.post(f"/api/v1/projects/{pid}/requirement-types", json={"name": "Interface"}, headers=auth_headers(admin_token))
    assert local.status_code == 201, local.text
    stakeholder = _type_id(client, admin_token, pid, "Stakeholder Requirement")
    hidden = client.delete(f"/api/v1/projects/{pid}/requirement-types/{stakeholder}", headers=auth_headers(admin_token))
    assert hidden.status_code == 204, hidden.text
    assert [t["name"] for t in _types(client, admin_token, pid)] == ["Enterprise", "Project Requirement", "Interface"]

    restored = client.post(f"/api/v1/projects/{pid}/requirement-types/restore", json={}, headers=auth_headers(admin_token))
    assert restored.status_code == 200, restored.text
    assert [t["name"] for t in restored.json()["restored"]] == ["Stakeholder Requirement"]
    assert "Stakeholder Requirement" in [t["name"] for t in _types(client, admin_token, pid)]


def test_a_child_project_shows_the_nearest_configured_ancestors_list(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "Parent", can_be_parent=True)
    business = _type_id(client, admin_token, parent["id"], "Business Requirement")
    client.put(f"/api/v1/projects/{parent['id']}/requirement-types/{business}", json={"name": "Enterprise"}, headers=auth_headers(admin_token))
    child = create_project(client, admin_token, org_id, "Child", parent_project_id=parent["id"])
    assert _types(client, admin_token, child["id"])[0]["name"] == "Enterprise"
    # A child's first change copies the inherited list into the child, leaving the parent's own.
    local = client.post(f"/api/v1/projects/{child['id']}/requirement-types", json={"name": "Leaf"}, headers=auth_headers(admin_token))
    assert local.status_code == 201, local.text
    assert "Leaf" not in [t["name"] for t in _types(client, admin_token, parent["id"])]
    assert [t["name"] for t in _types(client, admin_token, child["id"])][0] == "Enterprise"


def test_a_type_in_use_cannot_be_deleted_from_the_organisation(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    business = _type_id(client, admin_token, project["id"], "Business Requirement")
    _requirement(client, admin_token, project["id"], component_id, category_id, type_id=business)
    org_type = next(
        t for t in client.get(f"/api/v1/orgs/{org_id}/requirement-types", headers=auth_headers(admin_token)).json()
        if t["name"] == "Business Requirement"
    )
    resp = client.delete(f"/api/v1/orgs/{org_id}/requirement-types/{org_type['id']}", headers=auth_headers(admin_token))
    assert resp.status_code == 409, resp.text


# --- the type on a requirement --------------------------------------------------------------------


def test_create_stores_the_type_and_reads_it_back(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    business = _type_id(client, admin_token, pid, "Business Requirement")
    created = _requirement(client, admin_token, pid, component_id, category_id, type_id=business)
    assert created["type_name"] == "Business Requirement" and created["type_id"]
    fetched = client.get(f"/api/v1/projects/{pid}/requirements/{created['id']}", headers=auth_headers(admin_token)).json()
    assert fetched["type_name"] == "Business Requirement"
    untyped = _requirement(client, admin_token, pid, component_id, category_id, name="No type")
    assert untyped["type_id"] is None and untyped["type_name"] is None


def test_edit_sets_leaves_and_clears_the_type(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    requirement = _requirement(client, admin_token, pid, component_id, category_id)
    stakeholder = _type_id(client, admin_token, pid, "Stakeholder Requirement")

    set_ = _put(client, admin_token, pid, requirement, type_id=stakeholder)
    assert set_.status_code == 200, set_.text
    assert set_.json()["type_name"] == "Stakeholder Requirement"
    # Omitted leaves the type as it is.
    left = _put(client, admin_token, pid, set_.json(), name="Renamed")
    assert left.json()["type_name"] == "Stakeholder Requirement"
    cleared = _put(client, admin_token, pid, left.json(), type_id=None)
    assert cleared.json()["type_id"] is None

    history = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}/history", headers=auth_headers(admin_token)).json()
    assert [v["type_name"] for v in history] == [None, "Stakeholder Requirement", "Stakeholder Requirement", None]


def test_an_unknown_or_disabled_type_is_refused(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    bad = client.post(
        f"/api/v1/projects/{pid}/requirements",
        json={"name": "x", "component_id": component_id, "category_id": category_id, "type_id": str(uuid.uuid4())},
        headers=auth_headers(admin_token),
    )
    assert bad.status_code == 422, bad.text
    project_row = _type_id(client, admin_token, pid, "Project Requirement")
    off = client.put(f"/api/v1/projects/{pid}/requirement-types/{project_row}", json={"is_enabled": False}, headers=auth_headers(admin_token))
    assert off.status_code == 200, off.text
    refused = client.post(
        f"/api/v1/projects/{pid}/requirements",
        json={"name": "x", "component_id": component_id, "category_id": category_id, "type_id": off.json()["id"]},
        headers=auth_headers(admin_token),
    )
    assert refused.status_code == 422, refused.text


def test_list_filters_by_type_name_and_sorts_by_the_configured_order(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    business = _type_id(client, admin_token, pid, "Business Requirement")
    project_type = _type_id(client, admin_token, pid, "Project Requirement")
    _requirement(client, admin_token, pid, component_id, category_id, name="P", type_id=project_type)
    _requirement(client, admin_token, pid, component_id, category_id, name="U")
    _requirement(client, admin_token, pid, component_id, category_id, name="B", type_id=business)

    filtered = client.get(
        f"/api/v1/projects/{pid}/requirements", params={"type": ["business requirement"]}, headers=auth_headers(admin_token),
    ).json()
    assert [r["name"] for r in filtered] == ["B"]
    ascending = client.get(f"/api/v1/projects/{pid}/requirements", params={"sort": "type"}, headers=auth_headers(admin_token)).json()
    assert [r["name"] for r in ascending] == ["B", "P", "U"]
    descending = client.get(
        f"/api/v1/projects/{pid}/requirements", params={"sort": "type", "order": "desc"}, headers=auth_headers(admin_token),
    ).json()
    assert [r["name"] for r in descending] == ["U", "P", "B"]


def test_an_approved_requirement_is_retyped_through_a_change_request(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    requirement = _requirement(client, admin_token, pid, component_id, category_id, type_id=_type_id(client, admin_token, pid, "Project Requirement"))
    approved = client.post(f"/api/v1/projects/{pid}/requirements/{requirement['id']}/approve", headers=auth_headers(admin_token))
    assert approved.status_code == 200, approved.text
    direct = _put(client, admin_token, pid, approved.json(), type_id=_type_id(client, admin_token, pid, "Business Requirement"))
    assert direct.status_code == 409

    business = _type_id(client, admin_token, pid, "Business Requirement")
    cr = client.post(
        f"/api/v1/projects/{pid}/change-requests",
        json={"kind": "modify_requirement", "requirement_id": requirement["id"], "changed_fields": ["type_id"],
              "proposed_type_id": business, "reason": "It is a business need"},
        headers=auth_headers(admin_token),
    )
    assert cr.status_code == 201, cr.text
    assert cr.json()["proposed_type_name"] == "Business Requirement"
    client.post(f"/api/v1/projects/{pid}/change-requests/{cr.json()['id']}/submit", headers=auth_headers(admin_token))
    decided = client.post(
        f"/api/v1/projects/{pid}/change-requests/{cr.json()['id']}/decide", json={"approve": True, "note": ""}, headers=auth_headers(admin_token),
    )
    assert decided.status_code == 200, decided.text
    after = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}", headers=auth_headers(admin_token)).json()
    assert after["type_name"] == "Business Requirement"


def test_a_change_request_can_clear_the_type_and_a_new_requirement_request_carries_one(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    requirement = _requirement(client, admin_token, pid, component_id, category_id, type_id=_type_id(client, admin_token, pid, "Project Requirement"))
    client.post(f"/api/v1/projects/{pid}/requirements/{requirement['id']}/approve", headers=auth_headers(admin_token))
    clear = client.post(
        f"/api/v1/projects/{pid}/change-requests",
        json={"kind": "modify_requirement", "requirement_id": requirement["id"], "changed_fields": ["type_id"], "reason": "untyped"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{pid}/change-requests/{clear['id']}/submit", headers=auth_headers(admin_token))
    client.post(f"/api/v1/projects/{pid}/change-requests/{clear['id']}/decide", json={"approve": True, "note": ""}, headers=auth_headers(admin_token))
    assert client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}", headers=auth_headers(admin_token)).json()["type_id"] is None

    new = client.post(
        f"/api/v1/projects/{pid}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "Added", "proposed_component_id": component_id,
              "proposed_category_id": category_id, "proposed_type_id": _type_id(client, admin_token, pid, "Stakeholder Requirement"),
              "reason": "new need"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{pid}/change-requests/{new['id']}/submit", headers=auth_headers(admin_token))
    decided = client.post(
        f"/api/v1/projects/{pid}/change-requests/{new['id']}/decide", json={"approve": True, "note": ""}, headers=auth_headers(admin_token),
    )
    assert decided.status_code == 200, decided.text
    created = client.get(f"/api/v1/projects/{pid}/change-requests/{new['id']}", headers=auth_headers(admin_token)).json()
    added = client.get(f"/api/v1/projects/{pid}/requirements/{created['requirement_id']}", headers=auth_headers(admin_token)).json()
    assert added["type_name"] == "Stakeholder Requirement"


# --- the carriers ------------------------------------------------------------------------------------


def test_project_export_and_import_keep_the_type_by_name(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    local = client.post(f"/api/v1/projects/{pid}/requirement-types", json={"name": "Interface"}, headers=auth_headers(admin_token)).json()
    _requirement(client, admin_token, pid, component_id, category_id, name="A", type_id=_type_id(client, admin_token, pid, "Business Requirement"))
    _requirement(client, admin_token, pid, component_id, category_id, name="B", type_id=local["id"])
    exported = client.get(f"/api/v1/projects/{pid}/export", headers=auth_headers(admin_token))
    assert exported.status_code == 200, exported.text

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    rows = client.get(f"/api/v1/projects/{new_id}/requirements", headers=auth_headers(admin_token)).json()
    assert {r["name"]: r["type_name"] for r in rows} == {"A": "Business Requirement", "B": "Interface"}
    assert "Interface" in [t["name"] for t in _types(client, admin_token, new_id)]


def test_record_table_export_and_import_carry_the_type(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    created = _requirement(client, admin_token, pid, component_id, category_id, type_id=_type_id(client, admin_token, pid, "Business Requirement"))
    base = f"/api/v1/projects/{pid}/records/requirement"
    exported = client.get(f"{base}/export", headers=auth_headers(admin_token))
    assert exported.status_code == 200, exported.text
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["type"] == "Business Requirement"

    rows[0]["type"] = "Stakeholder Requirement"
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    applied = client.post(
        f"{base}/import", params={"dry_run": "false"},
        files={"file": ("records.csv", out.getvalue().encode("utf-8"), "text/csv")}, headers=auth_headers(admin_token),
    )
    assert applied.status_code == 200, applied.text
    after = client.get(f"/api/v1/projects/{pid}/requirements/{created['id']}", headers=auth_headers(admin_token)).json()
    assert after["type_name"] == "Stakeholder Requirement"

    rows[0]["type"] = "Nonsense"
    bad = io.StringIO()
    writer = csv.DictWriter(bad, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    preview = client.post(
        f"{base}/import", params={"dry_run": "true"},
        files={"file": ("records.csv", bad.getvalue().encode("utf-8"), "text/csv")}, headers=auth_headers(admin_token),
    )
    assert preview.status_code == 200, preview.text
    assert "Unknown requirement type" in preview.text


def test_the_type_is_the_requirements_record_sub_type(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    project_type = _type_id(client, admin_token, pid, "Project Requirement")
    typed = _requirement(client, admin_token, pid, component_id, category_id, name="T", type_id=project_type)
    untyped = _requirement(client, admin_token, pid, component_id, category_id, name="U")
    db = SessionLocal()
    try:
        found = resolve_record_subtypes(db, uuid.UUID(pid), "requirement", [uuid.UUID(typed["id"]), uuid.UUID(untyped["id"])])
    finally:
        db.close()
    assert found == {uuid.UUID(typed["id"]): "Project Requirement"}


def test_a_project_made_from_a_template_keeps_the_types_and_each_requirements_type(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    client.post(f"/api/v1/projects/{pid}/requirement-types", json={"name": "Interface"}, headers=auth_headers(admin_token))
    _requirement(client, admin_token, pid, component_id, category_id, name="Typed", type_id=_type_id(client, admin_token, pid, "Interface"))
    marked = client.patch(f"/api/v1/projects/{pid}", json={"is_template": True}, headers=auth_headers(admin_token))
    assert marked.status_code == 200, marked.text
    cloned = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "From template", "summary": "", "template_project_id": pid},
        headers=auth_headers(admin_token),
    )
    assert cloned.status_code == 201, cloned.text
    rows = client.get(f"/api/v1/projects/{cloned.json()['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert [(r["name"], r["type_name"]) for r in rows] == [("Typed", "Interface")]


def test_an_organisation_with_typed_requirements_can_be_deleted(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Typed Org To Delete")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    local = client.post(f"/api/v1/projects/{project['id']}/requirement-types", json={"name": "Interface"}, headers=auth_headers(token)).json()
    _requirement(client, token, project["id"], component_id, category_id, type_id=_type_id(client, token, project["id"], "Business Requirement"))
    _requirement(client, token, project["id"], component_id, category_id, name="Local", type_id=local["id"])
    deleted = client.request(
        "DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]}, headers=auth_headers(admin_token),
    )
    assert deleted.status_code in (200, 204), deleted.text


# --- rank (priority) -----------------------------------------------------------------------------------


def test_default_types_are_ranked_one_to_three_and_a_new_type_is_unranked(client, admin_token, org_id):
    listed = client.get(f"/api/v1/orgs/{org_id}/requirement-types", headers=auth_headers(admin_token)).json()
    assert [(t["name"], t["rank"]) for t in listed] == list(zip(DEFAULTS, [1, 2, 3], strict=True))
    created = client.post(f"/api/v1/orgs/{org_id}/requirement-types", json={"name": "Regulatory"}, headers=auth_headers(admin_token))
    assert created.json()["rank"] is None
    ranked = client.post(f"/api/v1/orgs/{org_id}/requirement-types", json={"name": "Safety", "rank": 2}, headers=auth_headers(admin_token))
    assert ranked.status_code == 201 and ranked.json()["rank"] == 2


def test_a_rank_must_be_a_whole_number_from_one_and_can_be_cleared(client, admin_token, org_id):
    org_type = client.get(f"/api/v1/orgs/{org_id}/requirement-types", headers=auth_headers(admin_token)).json()[0]
    url = f"/api/v1/orgs/{org_id}/requirement-types/{org_type['id']}"
    for bad in (0, -1, 1001):
        assert client.patch(url, json={"rank": bad}, headers=auth_headers(admin_token)).status_code == 422
    assert client.patch(url, json={"rank": 5}, headers=auth_headers(admin_token)).json()["rank"] == 5
    assert client.patch(url, json={"rank": None}, headers=auth_headers(admin_token)).json()["rank"] is None


def test_a_project_can_rank_a_type_differently_and_null_follows_the_organisation(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    project_type = _type_id(client, admin_token, pid, "Project Requirement")
    overridden = client.put(f"/api/v1/projects/{pid}/requirement-types/{project_type}", json={"rank": 1}, headers=auth_headers(admin_token))
    assert overridden.status_code == 200, overridden.text
    ranks = {t["name"]: t["rank"] for t in _types(client, admin_token, pid)}
    assert ranks == {"Business Requirement": 1, "Stakeholder Requirement": 2, "Project Requirement": 1}
    local = client.post(f"/api/v1/projects/{pid}/requirement-types", json={"name": "Interface", "rank": 4}, headers=auth_headers(admin_token))
    assert local.status_code == 201 and local.json()["rank"] == 4
    row = next(t for t in _types(client, admin_token, pid) if t["name"] == "Project Requirement")
    cleared = client.put(f"/api/v1/projects/{pid}/requirement-types/{row['id']}", json={"rank": None}, headers=auth_headers(admin_token))
    assert cleared.status_code == 200
    assert {t["name"]: t["rank"] for t in _types(client, admin_token, pid)}["Project Requirement"] == 3


def test_sort_by_type_follows_the_rank_not_the_list_order(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    business = _type_id(client, admin_token, pid, "Business Requirement")
    project_type = _type_id(client, admin_token, pid, "Project Requirement")
    # Project Requirement becomes the highest priority while it stays last in the list.
    client.put(f"/api/v1/projects/{pid}/requirement-types/{project_type}", json={"rank": 1}, headers=auth_headers(admin_token))
    client.put(f"/api/v1/projects/{pid}/requirement-types/{business}", json={"rank": 3}, headers=auth_headers(admin_token))
    _requirement(client, admin_token, pid, component_id, category_id, name="B", type_id=_type_id(client, admin_token, pid, "Business Requirement"))
    _requirement(client, admin_token, pid, component_id, category_id, name="P", type_id=_type_id(client, admin_token, pid, "Project Requirement"))
    _requirement(client, admin_token, pid, component_id, category_id, name="U")
    rows = client.get(f"/api/v1/projects/{pid}/requirements", params={"sort": "type"}, headers=auth_headers(admin_token)).json()
    assert [r["name"] for r in rows] == ["P", "B", "U"]


def test_rank_travels_in_the_project_and_organisation_bundles(client, admin_token, org_id):
    project, component_id, category_id = _setup(client, admin_token, org_id)
    pid = project["id"]
    client.post(f"/api/v1/projects/{pid}/requirement-types", json={"name": "Interface", "rank": 4}, headers=auth_headers(admin_token))
    business = _type_id(client, admin_token, pid, "Business Requirement")
    client.put(f"/api/v1/projects/{pid}/requirement-types/{business}", json={"rank": 2}, headers=auth_headers(admin_token))
    _requirement(client, admin_token, pid, component_id, category_id, type_id=_type_id(client, admin_token, pid, "Interface"))
    exported = client.get(f"/api/v1/projects/{pid}/export", headers=auth_headers(admin_token))
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    ranks = {t["name"]: t["rank"] for t in _types(client, admin_token, imported.json()["project"]["id"])}
    assert ranks["Interface"] == 4 and ranks["Business Requirement"] == 2


def test_the_rank_is_a_report_field_layouts_can_sort_by():
    from app.services.report_fields import field_catalogue

    field = next(f for f in field_catalogue("requirement") if f.key == "requirement_type_rank")
    assert field.kind == "number"
