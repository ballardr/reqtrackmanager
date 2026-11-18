"""Tests for the domain vocabulary (Software, Hardware and the organisation's or a project's own): seeding, both tiers,
hiding and restoring, the nested-project fallback and its copy, types in several domains or none, the in-use refusal,
toggle rules that name domains, the bundles (with an older bundle that named one value), the template copy and migration
0199. Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import text

from alembic import command
from app.database import engine
from app.modules.architecture.export import HIDDEN_DOMAINS_KEY, ORG_DOMAINS_KEY, PROJECT_DOMAINS_KEY, PROJECT_KEYS
from app.modules.architecture.service import DEFAULT_CONNECTION_TYPES, DEFAULT_DOMAINS, DOMAINS
from app.modules.architecture.tests._helpers import (
    domains,
    element_types,
    enable_module,
    make_diagram,
    make_element,
    org_base,
    place_all,
    project_base,
    save_toggles,
    setup,
    view,
)
from tests.conftest import auth_headers, build_alembic_config, create_org_admin_in, create_project

# --- Helpers -----------------------------------------------------------------------------------------------------------------


def _org_rows(client, token, org_id, path="domains") -> dict[str, dict]:
    resp = client.get(f"{org_base(org_id)}/{path}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {r["name"]: r for r in resp.json()}


def _project_rows(client, token, project_id, path="domains") -> dict[str, dict]:
    resp = client.get(f"{project_base(project_id)}/{path}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {r["name"]: r for r in resp.json()}


def _post(client, token, url, expect=201, **body) -> dict:
    resp = client.post(url, json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _patch(client, token, url, expect=200, **body) -> dict:
    resp = client.patch(url, json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _bundle(client, token, project_id) -> tuple[zipfile.ZipFile, dict]:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    source = zipfile.ZipFile(io.BytesIO(resp.content))
    return source, json.loads(source.read("project.json"))


def _import(client, token, org_id, source, data, name) -> str:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item.filename, json.dumps(data) if item.filename == "project.json" else source.read(item.filename))
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["project"]["id"]


# --- Seeding and the organisation tier ---------------------------------------------------------------------------------------


def test_a_new_organisation_is_seeded_with_software_and_hardware_and_the_seeded_types_are_in_them(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch domain seed")
    enable_module(client, token, org["id"])
    rows = _org_rows(client, token, org["id"])
    assert list(rows) == [name for _key, name in DEFAULT_DOMAINS] == ["Software", "Hardware"]
    assert all(r["organization_id"] == org["id"] and r["project_id"] is None for r in rows.values())
    connections = _org_rows(client, token, org["id"], "connection-types")
    expected = {name: key for name, key, _directional in DEFAULT_CONNECTION_TYPES}
    by_id = {r["id"]: r["name"] for r in rows.values()}
    for name, key in expected.items():
        want = {"software": ["Software"], "hardware": ["Hardware"], "any": []}[key]
        assert [by_id[d] for d in connections[name]["domain_ids"]] == want, name
    assert all(r["domain_ids"] == [] for r in _org_rows(client, token, org["id"], "element-types").values())


def test_the_organisation_admin_manages_domains(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch domain org crud", domain_types=False)
    base = f"{org_base(org['id'])}/domains"
    created = _post(client, token, base, name="Mechanical")
    assert created["sort_order"] == 2 and created["organization_id"] == org["id"]
    assert client.post(base, json={"name": "mechanical"}, headers=auth_headers(token)).status_code == 400  # a clash ignores case
    renamed = _patch(client, token, f"{base}/{created['id']}", name="Mechanical design")
    assert renamed["name"] == "Mechanical design"
    moved = client.post(f"{base}/{created['id']}/move", json={"direction": "up"}, headers=auth_headers(token))
    assert moved.status_code == 200 and moved.json()["sort_order"] == 1
    assert client.delete(f"{base}/{created['id']}", headers=auth_headers(token)).status_code == 204
    assert "Mechanical design" not in _org_rows(client, token, org["id"])


def test_a_member_reads_but_cannot_change_the_organisation_domains(client, admin_token):
    from app.modules.architecture.tests._helpers import add_member

    org, project, token = setup(client, admin_token, "Arch domain org rbac", domain_types=False)
    _user_id, member = add_member(client, token, org["id"], project["id"], "arch-domain-member@example.com")
    base = f"{org_base(org['id'])}/domains"
    assert client.get(base, headers=auth_headers(member)).status_code == 200
    assert client.post(base, json={"name": "Nope"}, headers=auth_headers(member)).status_code == 403
    assert client.delete(f"{base}/{next(iter(_org_rows(client, token, org['id']).values()))['id']}", headers=auth_headers(member)).status_code == 403


def test_another_organisations_domain_is_not_found_or_usable(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch domain tenant a", domain_types=False)
    other, _other_project, other_token = setup(client, admin_token, "Arch domain tenant b", domain_types=False)
    foreign = next(iter(_org_rows(client, other_token, other["id"]).values()))
    assert client.patch(f"{org_base(org['id'])}/domains/{foreign['id']}", json={"name": "X"}, headers=auth_headers(token)).status_code == 404
    refused = client.post(
        f"{org_base(org['id'])}/element-types", json={"name": "Stray", "domain_ids": [foreign["id"]]}, headers=auth_headers(token),
    )
    assert refused.status_code == 400


# --- A type in several domains, or none --------------------------------------------------------------------------------------


def test_a_type_is_in_several_domains_or_none_and_a_given_list_replaces_it(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch domain several", domain_types=False)
    rows = _org_rows(client, token, org["id"])
    software, hardware = rows["Software"]["id"], rows["Hardware"]["id"]
    base = f"{org_base(org['id'])}/connection-types"
    both = _post(client, token, base, name="Gateway link", domain_ids=[software, hardware, software])
    assert sorted(both["domain_ids"]) == sorted([software, hardware])  # a repeat counts once
    assert _post(client, token, base, name="Plain link")["domain_ids"] == []  # none fits every domain
    renamed = _patch(client, token, f"{base}/{both['id']}", name="Gateway")
    assert sorted(renamed["domain_ids"]) == sorted([software, hardware])  # omitted: kept
    assert _patch(client, token, f"{base}/{both['id']}", domain_ids=[hardware])["domain_ids"] == [hardware]
    assert _patch(client, token, f"{base}/{both['id']}", domain_ids=[])["domain_ids"] == []
    assert _org_rows(client, token, org["id"], "connection-types")["Gateway"]["domain_ids"] == []


def test_the_old_domain_field_is_gone(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch domain old field", domain_types=False)
    row = next(iter(_org_rows(client, token, org["id"], "element-types").values()))
    assert "domain" not in row and "domain_ids" in row


def test_an_organisation_type_cannot_use_a_project_domain_but_a_project_type_can_use_both(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch domain tiers", domain_types=False)
    p = project["id"]
    local = _post(client, token, f"{project_base(p)}/domains", name="Local domain")
    refused = client.post(
        f"{org_base(org['id'])}/element-types", json={"name": "Org type", "domain_ids": [local["id"]]}, headers=auth_headers(token),
    )
    assert refused.status_code == 400
    hardware = _org_rows(client, token, org["id"])["Hardware"]["id"]
    made = _post(client, token, f"{project_base(p)}/element-types", name="Both", domain_ids=[local["id"], hardware])
    assert sorted(made["domain_ids"]) == sorted([local["id"], hardware])


# --- The project tier: own rows, hide and restore ----------------------------------------------------------------------------


def test_a_project_adds_its_own_domain_and_hides_and_restores_an_organisation_default(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch domain hide", domain_types=False)
    p, h = project["id"], auth_headers(token)
    base = f"{project_base(p)}/domains"
    own = _post(client, token, base, name="Optical")
    assert own["project_id"] == p
    assert client.post(base, json={"name": "software"}, headers=h).status_code == 400  # a visible default's name is taken
    software = _org_rows(client, token, org["id"])["Software"]
    assert client.delete(f"{base}/{software['id']}", headers=h).status_code == 204  # hides
    assert "Software" not in _project_rows(client, token, p) and "Software" in _org_rows(client, token, org["id"])
    assert [r["name"] for r in client.get(f"{base}/hidden", headers=h).json()] == ["Software"]
    restored = client.post(f"{base}/restore", json={"org_type_ids": None}, headers=h)
    assert restored.status_code == 200 and [r["name"] for r in restored.json()["restored"]] == ["Software"]
    assert "Software" in _project_rows(client, token, p)
    assert client.delete(f"{base}/{own['id']}", headers=h).status_code == 204  # a project's own row is deleted
    assert "Optical" not in _project_rows(client, token, p)


def test_hiding_a_domain_stops_new_use_but_keeps_what_a_type_already_has(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch domain hidden use", domain_types=False)
    p, h = project["id"], auth_headers(token)
    hardware = _org_rows(client, token, org["id"])["Hardware"]["id"]
    radar = _post(client, token, f"{project_base(p)}/element-types", name="Radar", domain_ids=[hardware])
    assert client.delete(f"{project_base(p)}/domains/{hardware}", headers=h).status_code == 204
    kept = _patch(client, token, f"{project_base(p)}/element-types/{radar['id']}", name="Radar unit", domain_ids=[hardware])
    assert kept["domain_ids"] == [hardware]
    refused = client.post(f"{project_base(p)}/element-types", json={"name": "New", "domain_ids": [hardware]}, headers=h)
    assert refused.status_code == 400


# --- In use ------------------------------------------------------------------------------------------------------------------


def test_a_domain_a_type_is_in_or_a_toggle_rule_names_is_never_deleted(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch domain in use", domain_types=False)
    p, h = project["id"], auth_headers(token)
    own = _post(client, token, f"{project_base(p)}/domains", name="Thermal")
    org_domain = _post(client, token, f"{org_base(org['id'])}/domains", name="Optics")
    element_type = _post(client, token, f"{project_base(p)}/element-types", name="Heater", domain_ids=[own["id"]])
    assert client.delete(f"{project_base(p)}/domains/{own['id']}", headers=h).status_code == 409
    _patch(client, token, f"{project_base(p)}/element-types/{element_type['id']}", domain_ids=[])
    connection_type = _post(client, token, f"{project_base(p)}/connection-types", name="Heat pipe", domain_ids=[own["id"]])
    assert client.delete(f"{project_base(p)}/domains/{own['id']}", headers=h).status_code == 409
    _patch(client, token, f"{project_base(p)}/connection-types/{connection_type['id']}", domain_ids=[])

    diagram = make_diagram(client, token, p, "Rules")
    save_toggles(client, token, p, diagram, [{"name": "Optics", "rule": {"domain_ids": [org_domain["id"]]}}])
    assert client.delete(f"{org_base(org['id'])}/domains/{org_domain['id']}", headers=h).status_code == 409
    assert client.delete(f"{project_base(p)}/domains/{own['id']}", headers=h).status_code == 204  # nothing names it now


# --- Toggle rules ------------------------------------------------------------------------------------------------------------


def test_a_toggle_rule_matches_a_type_with_any_of_its_domains_and_a_type_with_none_matches_no_domain_rule(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch domain rule")
    p = project["id"]
    ds = domains(client, token, p)
    multi = _post(client, token, f"{project_base(p)}/element-types", name="Hybrid", domain_ids=[ds["Software"], ds["Hardware"]])
    plain = _post(client, token, f"{project_base(p)}/element-types", name="Neutral")
    types = element_types(client, token, p)
    hybrid = make_element(client, token, p, "Hybrid unit", type_name="Hybrid")
    neutral = make_element(client, token, p, "Neutral unit", type_name="Neutral")
    sensor = make_element(client, token, p, "Sensor unit", type_name="Sensor")  # Hardware only
    diagram = place_all(client, token, p, make_diagram(client, token, p, "Rule"), hybrid["id"], neutral["id"], sensor["id"])
    assert multi["id"] == types["Hybrid"] and plain["domain_ids"] == []

    current = {"diagram": diagram}

    def hidden(rule_domains) -> set[str]:
        saved = save_toggles(
            client, token, p, current["diagram"], [{"name": "Off", "default_on": False, "rule": {"domain_ids": rule_domains}}],
        )
        current["diagram"] = saved
        nodes = view(client, token, p, saved["id"])["nodes"]
        return {n["name"] for n in nodes if n.get("hidden")}

    assert hidden([ds["Software"]]) == {"Hybrid unit"}
    assert hidden([ds["Hardware"]]) == {"Hybrid unit", "Sensor unit"}
    assert hidden([ds["Software"], ds["Hardware"]]) == {"Hybrid unit", "Sensor unit"}


def test_a_rule_naming_a_domain_the_project_cannot_use_is_refused(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch domain rule refused", domain_types=False)
    other, _other_project, other_token = setup(client, admin_token, "Arch domain rule other", domain_types=False)
    foreign = next(iter(_org_rows(client, other_token, other["id"]).values()))
    diagram = make_diagram(client, token, project["id"], "Rule")
    save_toggles(client, token, project["id"], diagram, [{"name": "Bad", "rule": {"domain_ids": [foreign["id"]]}}], expect=400)
    assert org["id"] != other["id"]


# --- Nested projects ---------------------------------------------------------------------------------------------------------


def test_a_child_project_shows_the_nearest_configured_ancestors_domains_and_copies_them_on_its_first_change(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch domain nested")
    enable_module(client, token, org["id"])
    h = auth_headers(token)
    parent = create_project(client, token, org["id"], "Arch domain nested parent", can_be_parent=True)
    pb = project_base(parent["id"])
    mechanical = _post(client, token, f"{pb}/domains", name="Mechanical")
    assert client.delete(f"{pb}/domains/{_org_rows(client, token, org['id'])['Hardware']['id']}", headers=h).status_code == 204
    heater = _post(client, token, f"{pb}/element-types", name="Heater", domain_ids=[mechanical["id"]])

    child = create_project(client, token, org["id"], "Arch domain nested child", parent_project_id=parent["id"])
    cb = project_base(child["id"])
    assert sorted(_project_rows(client, token, child["id"])) == ["Mechanical", "Software"]  # the ancestor's list
    inherited_types = _project_rows(client, token, child["id"], "element-types")
    assert inherited_types["Heater"]["id"] == heater["id"]  # inherited, not yet the child's own
    diagram = make_diagram(client, token, child["id"], "Child rules")
    save_toggles(client, token, child["id"], diagram, [{"name": "Mech", "rule": {"domain_ids": [mechanical["id"]]}}])

    created = _post(client, token, f"{cb}/domains", name="Optical")  # the first change copies the inherited configuration
    assert created["project_id"] == child["id"]
    child_rows = _project_rows(client, token, child["id"])
    assert sorted(child_rows) == ["Mechanical", "Optical", "Software"]
    assert child_rows["Mechanical"]["id"] != mechanical["id"] and child_rows["Mechanical"]["project_id"] == child["id"]
    # The child's copy of the type, and the diagram's rule, name the child's copy of the domain, not the ancestor's row.
    copy = _project_rows(client, token, child["id"], "element-types")["Heater"]
    assert copy["project_id"] == child["id"] and copy["domain_ids"] == [child_rows["Mechanical"]["id"]]
    (toggle,) = view(client, token, child["id"], diagram["id"])["toggles"]
    assert toggle["rule"]["domain_ids"] == [child_rows["Mechanical"]["id"]]
    # The ancestor is unchanged.
    assert sorted(_project_rows(client, token, parent["id"])) == ["Mechanical", "Software"]
    assert _project_rows(client, token, parent["id"], "element-types")["Heater"]["domain_ids"] == [mechanical["id"]]


# --- Bundles -----------------------------------------------------------------------------------------------------------------


def test_the_project_bundle_carries_domains_by_name_and_the_hidden_defaults(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch domain bundle", domain_types=False)
    p, h = project["id"], auth_headers(token)
    own = _post(client, token, f"{project_base(p)}/domains", name="Optical")
    ds = _org_rows(client, token, org["id"])
    assert client.delete(f"{project_base(p)}/domains/{ds['Software']['id']}", headers=h).status_code == 204
    _post(client, token, f"{project_base(p)}/element-types", name="Lens", domain_ids=[own["id"], ds["Hardware"]["id"]])
    _post(client, token, f"{project_base(p)}/connection-types", name="Fibre", domain_ids=[own["id"]])
    diagram = make_diagram(client, token, p, "Rules")
    save_toggles(client, token, p, diagram, [{"name": "Optical", "rule": {"domain_ids": [own["id"]]}}])

    source, data = _bundle(client, token, p)
    assert [d["name"] for d in data[PROJECT_DOMAINS_KEY]] == ["Optical"] and data[HIDDEN_DOMAINS_KEY] == ["Software"]
    assert "id" not in data[PROJECT_DOMAINS_KEY][0] and "project_id" not in data[PROJECT_DOMAINS_KEY][0]
    (lens,) = data["architecture_project_element_types"]
    assert lens["domain_names"] == ["Hardware", "Optical"] and "domain" not in lens
    assert data["architecture_project_connection_types"][0]["domain_names"] == ["Optical"]
    assert data["architecture_diagrams"][0]["toggles"][0]["rule"]["domain_names"] == ["Optical"]

    copy = _import(client, token, org["id"], source, data, "Arch domain bundle copy")
    rows = _project_rows(client, token, copy)
    assert rows["Optical"]["project_id"] == copy and "Software" not in rows  # the hidden default is hidden again
    lens_copy = _project_rows(client, token, copy, "element-types")["Lens"]
    assert sorted(lens_copy["domain_ids"]) == sorted([rows["Optical"]["id"], rows["Hardware"]["id"]])
    assert _project_rows(client, token, copy, "connection-types")["Fibre"]["domain_ids"] == [rows["Optical"]["id"]]
    (diagram_copy,) = client.get(f"{project_base(copy)}/diagrams", headers=h).json()
    (toggle,) = view(client, token, copy, diagram_copy["id"])["toggles"]
    assert toggle["rule"]["domain_ids"] == [rows["Optical"]["id"]]


def test_a_type_naming_a_hidden_default_keeps_it_on_import_and_a_missing_domain_is_created(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch domain bundle hidden", domain_types=False)
    p, h = project["id"], auth_headers(token)
    hardware = _org_rows(client, token, org["id"])["Hardware"]["id"]
    _post(client, token, f"{project_base(p)}/element-types", name="Board", domain_ids=[hardware])
    assert client.delete(f"{project_base(p)}/domains/{hardware}", headers=h).status_code == 204
    source, data = _bundle(client, token, p)
    data["architecture_project_element_types"][0]["domain_names"].append("Acoustic")
    copy = _import(client, token, org["id"], source, data, "Arch domain bundle hidden copy")
    rows = _project_rows(client, token, copy)
    assert "Hardware" not in rows and rows["Acoustic"]["project_id"] == copy  # a hidden default is not created again
    board = _project_rows(client, token, copy, "element-types")["Board"]
    assert sorted(board["domain_ids"]) == sorted([hardware, rows["Acoustic"]["id"]])


def test_a_bundle_written_before_domains_were_rows_reads_its_one_value(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch domain legacy")
    p = project["id"]
    _post(client, token, f"{project_base(p)}/element-types", name="Local board")
    _post(client, token, f"{project_base(p)}/connection-types", name="Local link")
    _post(client, token, f"{project_base(p)}/connection-types", name="Local plain")
    diagram = make_diagram(client, token, p, "Rules")
    save_toggles(client, token, p, diagram, [{"name": "Hardware", "rule": {"domain_ids": [domains(client, token, p)["Hardware"]]}}])
    source, data = _bundle(client, token, p)
    for key, value in (("architecture_project_element_types", "hardware"), ("architecture_project_connection_types", "software")):
        entry = data[key][0]
        entry.pop("domain_names")
        entry["domain"] = value
    plain = data["architecture_project_connection_types"][1]
    plain.pop("domain_names")
    plain["domain"] = "any"
    rule = data["architecture_diagrams"][0]["toggles"][0]["rule"]
    rule.pop("domain_names")
    rule["domains"] = ["hardware"]
    copy = _import(client, token, org["id"], source, data, "Arch domain legacy copy")
    ds = domains(client, token, copy)
    assert _project_rows(client, token, copy, "element-types")["Local board"]["domain_ids"] == [ds["Hardware"]]
    connections = _project_rows(client, token, copy, "connection-types")
    assert connections["Local link"]["domain_ids"] == [ds["Software"]] and connections["Local plain"]["domain_ids"] == []
    (diagram_copy,) = client.get(f"{project_base(copy)}/diagrams", headers=auth_headers(token)).json()
    (toggle,) = view(client, token, copy, diagram_copy["id"])["toggles"]
    assert toggle["rule"]["domain_ids"] == [ds["Hardware"]]


def test_the_organisation_bundle_round_trips_domains_and_the_types_in_them(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch domain org bundle", domain_types=False)
    h = auth_headers(token)
    mechanical = _post(client, token, f"{org_base(org['id'])}/domains", name="Mechanical")
    hardware = _org_rows(client, token, org["id"])["Hardware"]["id"]
    _post(client, token, f"{org_base(org['id'])}/element-types", name="Housing", domain_ids=[mechanical["id"], hardware])
    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h)
    assert export.status_code == 200, export.text
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))
    assert sorted(d["name"] for d in org_json[ORG_DOMAINS_KEY]) == ["Hardware", "Mechanical", "Software"]
    housing = next(t for t in org_json["architecture_element_types"] if t["name"] == "Housing")
    assert housing["domain_names"] == ["Hardware", "Mechanical"]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Arch domain org bundle copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org = imported.json()["organization"]["id"]
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(
            text("SELECT name FROM architecture_domains WHERE organization_id = :o ORDER BY sort_order, name"), {"o": uuid.UUID(new_org)},
        )]
        linked = [r[0] for r in conn.execute(text(
            "SELECT d.name FROM architecture_element_type_domains l JOIN architecture_element_types t ON t.id = l.element_type_id "
            "JOIN architecture_domains d ON d.id = l.domain_id WHERE t.organization_id = :o AND t.name = 'Housing' ORDER BY d.name"
        ), {"o": uuid.UUID(new_org)})]
    assert sorted(names) == ["Hardware", "Mechanical", "Software"] and len(names) == 3  # the seeded defaults are not doubled
    assert linked == ["Hardware", "Mechanical"]


def test_the_domain_sections_are_template_configuration_and_a_template_child_receives_them(client, admin_token):
    assert {PROJECT_DOMAINS_KEY, HIDDEN_DOMAINS_KEY} <= PROJECT_KEYS
    org, project, token = setup(client, admin_token, "Arch domain template", domain_types=False)
    p, h = project["id"], auth_headers(token)
    optical = _post(client, token, f"{project_base(p)}/domains", name="Optical")
    ds = _org_rows(client, token, org["id"])
    assert client.delete(f"{project_base(p)}/domains/{ds['Software']['id']}", headers=h).status_code == 204
    _post(client, token, f"{project_base(p)}/element-types", name="Lens", domain_ids=[optical["id"]])
    assert client.patch(f"/api/v1/projects/{p}", json={"is_template": True}, headers=h).status_code == 200
    created = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "Arch domain template child", "summary": "", "template_project_id": p}, headers=h,
    )
    assert created.status_code == 201, created.text
    child = created.json()["id"]
    rows = _project_rows(client, token, child)
    assert rows["Optical"]["project_id"] == child and "Software" not in rows
    assert _project_rows(client, token, child, "element-types")["Lens"]["domain_ids"] == [rows["Optical"]["id"]]


# --- Registration ------------------------------------------------------------------------------------------------------------


def test_the_domain_vocabulary_has_its_own_suppression_kind():
    from app.modules.architecture.service import CONNECTION_TYPES, ELEMENT_TYPES
    from app.services.definition_suppression import get_registered_definition_kinds

    assert len({DOMAINS.kind, ELEMENT_TYPES.kind, CONNECTION_TYPES.kind}) == 3
    assert DOMAINS.kind in get_registered_definition_kinds()


def test_every_domain_change_is_audited(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch domain audit", domain_types=False)
    p = project["id"]
    created = _post(client, token, f"{project_base(p)}/domains", name="Optical")
    _patch(client, token, f"{project_base(p)}/domains/{created['id']}", name="Optical design")
    assert client.delete(f"{project_base(p)}/domains/{created['id']}", headers=auth_headers(token)).status_code == 204
    with engine.connect() as conn:
        actions = [r[0] for r in conn.execute(text(
            "SELECT action FROM audit_events WHERE entity_type = 'architecture_domain' AND project_id = :p ORDER BY created_at"
        ), {"p": uuid.UUID(p)})]
    assert actions == ["created", "updated", "deleted"] and org["id"]


# --- Migration ---------------------------------------------------------------------------------------------------------------


def test_the_domains_migration_converts_the_old_value_to_rows_and_links_and_back(client, admin_token):
    """Downgrading 0199 writes the first linked Software or Hardware domain back as the old value and a toggle rule's
    domain names as `domains`; upgrading again turns a value into a row and a link (`any` into none) and a rule's values
    into `domain_ids`, creating only the rows an organisation used."""
    org, project, token = setup(client, admin_token, "Arch domain migration", domain_types=False)
    p = project["id"]
    ds = _org_rows(client, token, org["id"])
    _post(client, token, f"{org_base(org['id'])}/element-types", name="Org board", domain_ids=[ds["Hardware"]["id"]])
    _post(client, token, f"{project_base(p)}/element-types", name="Project service", domain_ids=[ds["Software"]["id"]])
    _post(client, token, f"{project_base(p)}/element-types", name="Project plain")
    diagram = make_diagram(client, token, p, "Rules")
    save_toggles(client, token, p, diagram, [{"name": "Hardware", "rule": {"domain_ids": [ds["Hardware"]["id"]], "tags": ["x"]}}])

    command.downgrade(build_alembic_config(), "0198")
    try:
        with engine.connect() as conn:
            assert to_regclass(conn, "architecture_domains") is None
            old = {r[0]: r[1] for r in conn.execute(text(
                "SELECT name, domain FROM architecture_element_types WHERE name IN ('Org board', 'Project service', 'Project plain')"
            ))}
            assert old == {"Org board": "hardware", "Project service": "software", "Project plain": "any"}
            rule = conn.execute(text("SELECT rule FROM architecture_diagram_toggles WHERE name = 'Hardware' AND diagram_id = :d"),
                                {"d": uuid.UUID(diagram["id"])}).scalar_one()
            assert rule == {"domains": ["hardware"], "tags": ["x"]}
            # Raised while downgraded: the project's plain type becomes Hardware, and the rule also names software.
            conn.execute(text("UPDATE architecture_element_types SET domain = 'hardware' WHERE name = 'Project plain'"))
            conn.execute(text("UPDATE architecture_diagram_toggles SET rule = CAST(:r AS jsonb) WHERE diagram_id = :d"),
                         {"r": json.dumps({"domains": ["hardware", "software", "any"]}), "d": uuid.UUID(diagram["id"])})
            conn.commit()
    finally:
        command.upgrade(build_alembic_config(), "head")

    rows = _org_rows(client, token, org["id"])
    assert sorted(rows) == ["Hardware", "Software"]
    project_types = _project_rows(client, token, p, "element-types")
    assert project_types["Project service"]["domain_ids"] == [rows["Software"]["id"]]
    assert project_types["Project plain"]["domain_ids"] == [rows["Hardware"]["id"]]
    assert _org_rows(client, token, org["id"], "element-types")["Org board"]["domain_ids"] == [rows["Hardware"]["id"]]
    with engine.connect() as conn:
        rule = conn.execute(text("SELECT rule FROM architecture_diagram_toggles WHERE diagram_id = :d"),
                            {"d": uuid.UUID(diagram["id"])}).scalar_one()
        columns = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'architecture_element_types'"
        ))}
    assert "domain" not in columns
    assert "domains" not in rule and sorted(rule["domain_ids"]) == sorted([rows["Hardware"]["id"], rows["Software"]["id"]])


def to_regclass(conn, table: str):
    """The table's regclass name, or `None` when it does not exist."""
    return conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar_one()
