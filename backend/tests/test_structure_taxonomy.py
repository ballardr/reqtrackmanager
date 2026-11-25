"""The component and category tree's shared rules: the prefix suggestion, the prefix and name checks, moving a category
under another component, the structure counts and the list filter over several components and categories.

The suggestion is one server function (`services.taxonomy.suggest_prefix`) that the screen, the API and MCP all use, so
it is pinned here on its own and through each way it is reached.
"""
import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.services.taxonomy import MAX_PREFIX_LENGTH, base_prefix, clean_prefix, free_prefix
from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login
from tests.db_helpers import audit_detail


def _outsider_token(client, admin_token, org_id):
    """An organisation member who holds no role in the project."""
    create_org_user(client, admin_token, org_id, "outsider@example.com")
    return login(client, "outsider@example.com", "Password123!")


def _component(client, token, project_id, name, prefix=None):
    body = {"name": name} if prefix is None else {"name": name, "prefix": prefix}
    return client.post(f"/api/v1/projects/{project_id}/components", json=body, headers=auth_headers(token))


def _category(client, token, project_id, component_id, name, prefix=None):
    body = {"name": name, "component_id": component_id}
    if prefix is not None:
        body["prefix"] = prefix
    return client.post(f"/api/v1/projects/{project_id}/categories", json=body, headers=auth_headers(token))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Software", "SOFTWA"),
        ("Power Supply", "PS"),
        ("Power  supply unit", "PSU"),
        ("Électronique générale", "EG"),
        ("Sécurité", "SECURI"),
        ("Fire & Life-Safety", "FLS"),
        ("  hardware  ", "HARDWA"),
        ("A", "A"),
        ("Stage 2 Works", "S2W"),
        ("Alpha Beta Gamma Delta Epsilon Zeta Eta", "ABGDEZ"),
        ("日本語", ""),
        ("---", ""),
        ("", ""),
    ],
)
def test_base_prefix_rule(name, expected):
    """Initials of several words, the first letters of one word, ASCII only, at most six characters."""
    assert base_prefix(name) == expected


def test_base_prefix_is_stable_for_the_same_input():
    assert {base_prefix("Power Supply") for _ in range(5)} == {"PS"}


def test_free_prefix_numbers_a_collision_within_the_length_limit():
    assert free_prefix("PS", {"PS"}) == "PS2"
    assert free_prefix("PS", {"PS", "PS2", "ps3"}) == "PS4"
    assert free_prefix("ps", {"PS"}) == "ps2"
    long = "X" * MAX_PREFIX_LENGTH
    attempt = free_prefix(long, {long})
    assert attempt.endswith("2") and len(attempt) == MAX_PREFIX_LENGTH
    assert free_prefix("", {"PS"}) == ""
    assert free_prefix("PS", set()) == "PS"


def test_clean_prefix_trims_and_refuses_blank_or_too_long():
    assert clean_prefix("  SW ") == "SW"
    with pytest.raises(ValueError):
        clean_prefix("   ")
    with pytest.raises(ValueError):
        clean_prefix("X" * (MAX_PREFIX_LENGTH + 1))


def test_component_suggestion_endpoint_numbers_a_collision(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    headers = auth_headers(admin_token)
    url = f"/api/v1/projects/{pid}/components/suggest-prefix"
    assert client.get(url, params={"name": "Power Supply"}, headers=headers).json() == {"prefix": "PS"}
    assert _component(client, admin_token, pid, "Power Supply", "PS").status_code == 201
    assert client.get(url, params={"name": "Pressure Sensors"}, headers=headers).json() == {"prefix": "PS2"}
    # A name with no letter leaves the field empty, so the person must type one.
    assert client.get(url, params={"name": "!!!"}, headers=headers).json() == {"prefix": ""}


def test_renaming_does_not_collide_with_its_own_prefix(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    component = _component(client, admin_token, pid, "Power Supply", "PS").json()
    suggestion = client.get(
        f"/api/v1/projects/{pid}/components/suggest-prefix", params={"name": "Power Supply", "ignore": component["id"]},
        headers=auth_headers(admin_token),
    )
    assert suggestion.json() == {"prefix": "PS"}


def test_category_suggestion_is_per_component(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    headers = auth_headers(admin_token)
    core = _component(client, admin_token, pid, "Core", "CORE").json()
    other = _component(client, admin_token, pid, "Other", "OTH").json()
    assert _category(client, admin_token, pid, core["id"], "Performance", "PERF").status_code == 201
    url = f"/api/v1/projects/{pid}/categories/suggest-prefix"
    assert client.get(url, params={"name": "Performance", "component_id": core["id"]}, headers=headers).json() == {"prefix": "PERFOR"}
    assert client.get(url, params={"name": "Perf", "component_id": core["id"]}, headers=headers).json() == {"prefix": "PERF2"}
    assert client.get(url, params={"name": "Perf", "component_id": other["id"]}, headers=headers).json() == {"prefix": "PERF"}
    assert client.get(url, params={"name": "x", "component_id": str(uuid.uuid4())}, headers=headers).status_code == 404


def test_suggestion_needs_the_manage_role(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    outsider = auth_headers(_outsider_token(client, admin_token, org_id))
    resp = client.get(
        f"/api/v1/projects/{project['id']}/components/suggest-prefix", params={"name": "Power"}, headers=outsider
    )
    assert resp.status_code in (403, 404)


def test_a_create_without_a_prefix_uses_the_same_suggestion(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    first = _component(client, admin_token, pid, "Power Supply")
    second = _component(client, admin_token, pid, "Pressure Sensors")
    assert (first.status_code, first.json()["prefix"]) == (201, "PS")
    assert (second.status_code, second.json()["prefix"]) == (201, "PS2")
    category = _category(client, admin_token, pid, first.json()["id"], "Fuse Block")
    assert (category.status_code, category.json()["prefix"]) == (201, "FB")
    again = _category(client, admin_token, pid, first.json()["id"], "Fan Bay")
    assert again.json()["prefix"] == "FB2"


def test_a_create_whose_name_has_no_letter_needs_a_typed_prefix(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    resp = _component(client, admin_token, project["id"], "###")
    assert resp.status_code == 422
    assert _component(client, admin_token, project["id"], "###", "HASH").status_code == 201


def test_a_typed_prefix_is_never_replaced_by_the_suggestion(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component = _component(client, admin_token, project["id"], "Power Supply", "ZZ")
    assert component.json()["prefix"] == "ZZ"


@pytest.mark.parametrize("prefix", ["", "   ", "X" * (MAX_PREFIX_LENGTH + 1)])
def test_a_blank_or_too_long_prefix_is_refused_not_stored_or_a_500(client, admin_token, org_id, prefix):
    project = create_project(client, admin_token, org_id)
    assert _component(client, admin_token, project["id"], "Core", prefix).status_code == 422


def test_a_blank_or_too_long_name_is_refused(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    assert _component(client, admin_token, project["id"], "   ", "A").status_code == 422
    assert _component(client, admin_token, project["id"], "N" * 256, "A").status_code == 422


def test_an_update_without_a_prefix_keeps_the_current_one(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    component = _component(client, admin_token, pid, "Core", "CORE").json()
    resp = client.patch(
        f"/api/v1/projects/{pid}/components/{component['id']}", json={"name": "Core platform"}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200 and resp.json()["prefix"] == "CORE" and resp.json()["name"] == "Core platform"


def test_a_duplicate_prefix_is_still_a_400_with_the_existing_message(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    _component(client, admin_token, pid, "Core", "CORE")
    dup = _component(client, admin_token, pid, "Core again", "CORE")
    assert dup.status_code == 400 and "already exists" in dup.json()["detail"]


def test_a_concurrent_duplicate_returns_the_same_400(client, admin_token, org_id, monkeypatch):
    """The duplicate check can pass for two requests at once; the unique constraint then decides, and the answer is
    the check's 400, never a 500."""
    from app.routers.projects import taxonomy as router

    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    headers = auth_headers(admin_token)
    component = _component(client, admin_token, pid, "Core", "CORE").json()
    category = _category(client, admin_token, pid, component["id"], "General", "GEN")
    assert category.status_code == 201
    # Blind the check to the existing rows, as a request that read before the other committed would be.
    monkeypatch.setattr(router, "_component_prefix_taken", lambda *a, **k: False)
    monkeypatch.setattr(router, "_category_prefix_taken", lambda *a, **k: False)

    created = _component(client, admin_token, pid, "Core race", "CORE")
    assert created.status_code == 400 and "already exists" in created.json()["detail"]
    other = _component(client, admin_token, pid, "Other", "OTH").json()
    renamed = client.patch(
        f"/api/v1/projects/{pid}/components/{other['id']}", json={"name": "Other", "prefix": "CORE"}, headers=headers
    )
    assert renamed.status_code == 400 and "already exists" in renamed.json()["detail"]
    duplicate = _category(client, admin_token, pid, component["id"], "General race", "GEN")
    assert duplicate.status_code == 400 and "already exists" in duplicate.json()["detail"]
    second = _category(client, admin_token, pid, component["id"], "Second", "SEC").json()
    renamed_category = client.patch(
        f"/api/v1/projects/{pid}/categories/{second['id']}", json={"name": "Second", "prefix": "GEN"}, headers=headers
    )
    assert renamed_category.status_code == 400 and "already exists" in renamed_category.json()["detail"]
    # The failed attempts left the first rows alone and the session usable.
    rows = client.get(f"/api/v1/projects/{pid}/components", headers=headers).json()
    assert sorted(c["prefix"] for c in rows) == ["CORE", "OTH"]


def test_structure_counts(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    headers = auth_headers(admin_token)
    component_id, category_id = create_component_and_category(client, admin_token, pid)
    empty = _component(client, admin_token, pid, "Empty", "EMP").json()
    for name in ("One", "Two"):
        resp = client.post(
            f"/api/v1/projects/{pid}/requirements",
            json={"name": name, "component_id": component_id, "category_id": category_id}, headers=headers,
        )
        assert resp.status_code == 201, resp.text
    counts = client.get(f"/api/v1/projects/{pid}/structure-counts", headers=headers).json()
    assert counts["components"][component_id] == {"categories": 1, "requirements": 2}
    assert counts["components"][empty["id"]] == {"categories": 0, "requirements": 0}
    assert counts["categories"][category_id] == 2


def _requirement(client, token, pid, component_id, category_id, name="Req"):
    resp = client.post(
        f"/api/v1/projects/{pid}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_moving_a_category_carries_its_requirements_and_keeps_their_codes(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    headers = auth_headers(admin_token)
    component_id, category_id = create_component_and_category(client, admin_token, pid)
    target = _component(client, admin_token, pid, "Hardware", "HW").json()
    requirement = _requirement(client, admin_token, pid, component_id, category_id)
    assert requirement["unique_code"].startswith("SW-PERF-")

    moved = client.post(
        f"/api/v1/projects/{pid}/categories/{category_id}/move-to", json={"component_id": target["id"]}, headers=headers
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["component_id"] == target["id"]

    after = client.get(f"/api/v1/projects/{pid}/requirements/{requirement['id']}", headers=headers).json()
    assert after["component_id"] == target["id"] and after["category_id"] == category_id
    assert after["unique_code"] == requirement["unique_code"]  # a code is never rewritten
    created_later = _requirement(client, admin_token, pid, target["id"], category_id, "Later")
    assert created_later["unique_code"].startswith("HW-PERF-")
    assert created_later["unique_code"] != requirement["unique_code"]


def test_moving_a_category_goes_last_and_is_audited(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    headers = auth_headers(admin_token)
    component_id, category_id = create_component_and_category(client, admin_token, pid)
    target = _component(client, admin_token, pid, "Hardware", "HW").json()
    _category(client, admin_token, pid, target["id"], "Thermal", "THM")
    resp = client.post(
        f"/api/v1/projects/{pid}/categories/{category_id}/move-to", json={"component_id": target["id"]}, headers=headers
    )
    assert resp.json()["sort_order"] == 1
    categories = client.get(f"/api/v1/projects/{pid}/categories", headers=headers).json()
    assert [c["prefix"] for c in categories if c["component_id"] == target["id"]] == ["THM", "PERF"]
    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == category_id, AuditEvent.action == "moved")
        ).one()
        assert audit_detail(event) == {
            "from_component_id": component_id, "to_component_id": target["id"], "records_moved": "0",
        }
        assert str(event.project_id) == pid


def test_a_move_is_refused_for_the_same_component_a_clash_or_another_project(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id, "Other")
    pid = project["id"]
    headers = auth_headers(admin_token)
    component_id, category_id = create_component_and_category(client, admin_token, pid)
    target = _component(client, admin_token, pid, "Hardware", "HW").json()
    _category(client, admin_token, pid, target["id"], "Performance again", "PERF")
    foreign = _component(client, admin_token, other_project["id"], "Foreign", "FOR").json()
    url = f"/api/v1/projects/{pid}/categories/{category_id}/move-to"
    assert client.post(url, json={"component_id": component_id}, headers=headers).status_code == 400
    clash = client.post(url, json={"component_id": target["id"]}, headers=headers)
    assert clash.status_code == 400 and "prefix already exists" in clash.json()["detail"]
    assert client.post(url, json={"component_id": foreign["id"]}, headers=headers).status_code == 400
    assert client.post(url, json={"component_id": str(uuid.uuid4())}, headers=headers).status_code == 400
    missing = client.post(
        f"/api/v1/projects/{pid}/categories/{uuid.uuid4()}/move-to", json={"component_id": target["id"]}, headers=headers
    )
    assert missing.status_code == 404


def test_a_move_needs_the_manage_role(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    _, category_id = create_component_and_category(client, admin_token, pid)
    target = _component(client, admin_token, pid, "Hardware", "HW").json()
    resp = client.post(
        f"/api/v1/projects/{pid}/categories/{category_id}/move-to", json={"component_id": target["id"]},
        headers=auth_headers(_outsider_token(client, admin_token, org_id)),
    )
    assert resp.status_code in (403, 404)


def test_the_requirement_list_filters_by_several_components_and_categories(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    headers = auth_headers(admin_token)
    sw_id, perf_id = create_component_and_category(client, admin_token, pid)
    hw = _component(client, admin_token, pid, "Hardware", "HW").json()
    thermal = _category(client, admin_token, pid, hw["id"], "Thermal", "THM").json()
    ops = _component(client, admin_token, pid, "Operations", "OPS").json()
    ops_cat = _category(client, admin_token, pid, ops["id"], "Runbooks", "RUN").json()
    a = _requirement(client, admin_token, pid, sw_id, perf_id, "A")
    b = _requirement(client, admin_token, pid, hw["id"], thermal["id"], "B")
    c = _requirement(client, admin_token, pid, ops["id"], ops_cat["id"], "C")

    def ids(params):
        resp = client.get(f"/api/v1/projects/{pid}/requirements", params=params, headers=headers)
        assert resp.status_code == 200, resp.text
        return {r["id"] for r in resp.json()}

    assert ids({"component_id": [sw_id]}) == {a["id"]}
    assert ids({"component_id": [sw_id, hw["id"]]}) == {a["id"], b["id"]}
    assert ids({"category_id": [ops_cat["id"]]}) == {c["id"]}
    # Any listed component or any listed category, as every other record list reads the filter.
    assert ids({"component_id": [sw_id], "category_id": [ops_cat["id"]]}) == {a["id"], c["id"]}
    assert ids({}) == {a["id"], b["id"], c["id"]}


def test_the_requirement_export_takes_several_components(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    headers = auth_headers(admin_token)
    sw_id, perf_id = create_component_and_category(client, admin_token, pid)
    hw = _component(client, admin_token, pid, "Hardware", "HW").json()
    thermal = _category(client, admin_token, pid, hw["id"], "Thermal", "THM").json()
    _requirement(client, admin_token, pid, sw_id, perf_id, "Alpha")
    _requirement(client, admin_token, pid, hw["id"], thermal["id"], "Bravo")
    resp = client.get(
        f"/api/v1/projects/{pid}/records/requirement/export",
        params={"format": "csv", "component_id": [sw_id, hw["id"]]}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "Alpha" in resp.text and "Bravo" in resp.text
    only = client.get(
        f"/api/v1/projects/{pid}/records/requirement/export", params={"format": "csv", "component_id": [sw_id]}, headers=headers
    )
    assert "Alpha" in only.text and "Bravo" not in only.text
