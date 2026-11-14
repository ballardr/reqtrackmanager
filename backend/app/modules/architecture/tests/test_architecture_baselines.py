"""Tests for the architecture's part of a baseline: what the snapshot holds (ports, boxes, states, tags; no comments,
creators or owners; no archived records), the automatic stage baseline and the manual one, the permission to take one, the
references the project cannot read being emptied, the read of a baseline and its records, and the comparison with the live
model and between two baselines. Every test builds its own organisation."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.requirement import BaselineItem
from app.modules.architecture import baseline_compare
from app.modules.architecture.baseline_snapshot import SNAPSHOT_PROVIDERS
from app.modules.architecture.tests._helpers import (
    add_member,
    grant,
    make_architect,
    make_collection,
    make_connection,
    make_diagram,
    make_element,
    make_org_element,
    org_base,
    place_all,
    project_base,
    put_element,
    setup,
    sound_machine,
)
from app.modules.registry import BaselineSnapshotContext
from tests.conftest import auth_headers, create_component_and_category, create_project
from tests.stage_helpers import move_stage

ELEMENT = "architecture_element"
CONNECTION = "architecture_connection"
DIAGRAM = "architecture_diagram"
MACHINE = "architecture_state_machine_diagram"
ARCHITECTURE_TYPES = [ELEMENT, CONNECTION, DIAGRAM, MACHINE]


def _scene(client, token, project_id):
    """Two elements joined by a connection, a diagram placing both and a state machine diagram of the first."""
    gateway = make_element(client, token, project_id, "Gateway", type_name="Service")
    cloud = make_element(client, token, project_id, "Cloud", type_name="Service", description="Backend")
    link = make_connection(client, token, project_id, gateway["id"], cloud["id"], protocol="v1")
    diagram = place_all(client, token, project_id, make_diagram(client, token, project_id, "Context", activate=True), gateway["id"], cloud["id"])
    machine, _states = sound_machine(client, token, project_id, gateway["id"])
    return gateway, cloud, link, diagram, machine


def _take(client, token, project_id, label="Baseline", *, types=None, expect=201):
    body = {"label": label, **({"item_types": types} if types is not None else {})}
    resp = client.post(f"/api/v1/projects/{project_id}/baselines", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _view(client, token, project_id, baseline_id, *, expect=200):
    resp = client.get(f"{project_base(project_id)}/baselines/{baseline_id}", headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _compare(client, token, project_id, baseline_id, against="live", *, expect=200):
    resp = client.get(
        f"{project_base(project_id)}/baselines/{baseline_id}/compare", params={"against": against}, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _by_type(comparison) -> dict[str, dict]:
    return {t["item_type"]: t for t in comparison["types"]}


def test_a_manual_baseline_captures_every_architecture_record_as_it_stands(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch baseline snapshot")
    gateway, _cloud, _link, _diagram, _machine = _scene(client, token, project["id"])
    client.post(f"{project_base(project['id'])}/elements/{gateway['id']}/comments", json={"body": "Private discussion"}, headers=auth_headers(token))

    baseline = _take(client, token, project["id"], "Before review", types=ARCHITECTURE_TYPES)
    assert baseline["kind"] == "manual"
    assert baseline["item_counts"] == {ELEMENT: 2, CONNECTION: 1, DIAGRAM: 1, MACHINE: 1}

    listed = _view(client, token, project["id"], baseline["id"])
    assert [r["item_type"] for r in listed["records"]] == [ELEMENT, ELEMENT, CONNECTION, DIAGRAM, MACHINE]

    element_row = next(r for r in listed["records"] if r["name"] == "Gateway")
    item = client.get(f"{project_base(project['id'])}/baselines/{baseline['id']}/items/{element_row['id']}", headers=auth_headers(token))
    assert item.status_code == 200, item.text
    content = item.json()["content"]
    assert content["name"] == "Gateway" and content["unique_code"] == element_row["code"]
    assert "owner" not in content or isinstance(content["owner"], str)
    assert not {"comments", "comment_pins", "created_by_email", "archived_by_email", "created_at", "is_archived"} & content.keys()

    machine_row = next(r for r in listed["records"] if r["item_type"] == MACHINE)
    machine_content = client.get(
        f"{project_base(project['id'])}/baselines/{baseline['id']}/items/{machine_row['id']}", headers=auth_headers(token),
    ).json()["content"]
    assert len(machine_content["states"]) == 3 and len(machine_content["transitions"]) == 2

    diagram_row = next(r for r in listed["records"] if r["item_type"] == DIAGRAM)
    diagram_content = client.get(
        f"{project_base(project['id'])}/baselines/{baseline['id']}/items/{diagram_row['id']}", headers=auth_headers(token),
    ).json()["content"]
    assert len(diagram_content["boxes"]) == 2


def test_an_archived_record_is_not_captured(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch baseline archived")
    keep = make_element(client, token, project["id"], "Keep", type_name="Service")
    drop = make_element(client, token, project["id"], "Drop", type_name="Service")
    archived = client.post(f"{project_base(project['id'])}/elements/{drop['id']}/archive", headers=auth_headers(token))
    assert archived.status_code == 200, archived.text

    baseline = _take(client, token, project["id"], types=[ELEMENT])
    assert baseline["item_counts"] == {ELEMENT: 1}
    assert [r["name"] for r in _view(client, token, project["id"], baseline["id"])["records"]] == [keep["name"]]


def test_a_stage_baseline_captures_the_architecture_too(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch baseline stage")
    _scene(client, token, project["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    created = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Boot within 3s", "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    headers = auth_headers(token)
    stage_id = client.get(f"/api/v1/projects/{project['id']}/stages", headers=headers).json()[0]["id"]
    assert move_stage(client, project["id"], stage_id, "approved", headers=headers).status_code == 200

    [baseline] = client.get(f"/api/v1/projects/{project['id']}/baselines", headers=headers).json()
    assert baseline["kind"] == "stage"
    assert baseline["item_counts"] == {"requirement": 1, ELEMENT: 2, CONNECTION: 1, DIAGRAM: 1, MACHINE: 1}
    assert _view(client, token, project["id"], baseline["id"])["stage_name"]


def test_a_component_baseline_captures_no_architecture():
    with SessionLocal() as db:
        context = BaselineSnapshotContext(kind="stage", stage_id=uuid.uuid4(), component_id=uuid.uuid4(), actor_id=None)
        assert all(provider.snapshot(db, None, context) == [] for provider in SNAPSHOT_PROVIDERS.values())


def test_taking_a_baseline_needs_the_architect_atom_for_each_type(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch baseline permission")
    _scene(client, token, project["id"])
    _uid, reader = add_member(client, token, org["id"], project["id"], "arch.baseline.reader@example.com")
    architect = make_architect(client, token, org["id"], project["id"], "arch.baseline.architect@example.com")

    refused = _take(client, reader, project["id"], types=[ELEMENT], expect=403)
    assert "permission" in refused["detail"].lower()
    assert _take(client, architect, project["id"], types=[ELEMENT])["item_counts"] == {ELEMENT: 2}

    # A reader may still read what was captured.
    baseline = _take(client, token, project["id"], types=ARCHITECTURE_TYPES)
    assert len(_view(client, reader, project["id"], baseline["id"])["records"]) == 5


def test_a_baseline_of_another_project_looks_absent(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch baseline scope")
    other = create_project(client, token, org["id"], "Arch baseline scope other")
    make_element(client, token, other["id"], "Elsewhere", type_name="Service")
    foreign = _take(client, token, other["id"], types=[ELEMENT])

    _view(client, token, project["id"], foreign["id"], expect=404)
    _compare(client, token, project["id"], foreign["id"], expect=404)
    own = _take(client, token, project["id"], types=[ELEMENT])
    _compare(client, token, project["id"], own["id"], against=foreign["id"], expect=404)
    _compare(client, token, project["id"], own["id"], against="not-an-id", expect=422)
    missing = client.get(f"{project_base(project['id'])}/baselines/{own['id']}/items/{uuid.uuid4()}", headers=auth_headers(token))
    assert missing.status_code == 404


def test_a_shared_element_the_project_cannot_read_is_not_named_in_a_snapshot(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch baseline shared")
    platform = make_org_element(client, token, org["id"], "Platform")
    collection = make_collection(client, token, org_base(org["id"]), "Platform set", members=[platform["id"]])
    given = grant(client, token, org_base(org["id"]), collection["id"], project_id=project["id"])
    local = make_element(client, token, project["id"], "Local", type_name="Service")
    make_connection(client, token, project["id"], local["id"], platform["id"])

    visible = _take(client, token, project["id"], "While shared", types=[CONNECTION])
    row = _view(client, token, project["id"], visible["id"])["records"][0]
    content = client.get(f"{project_base(project['id'])}/baselines/{visible['id']}/items/{row['id']}", headers=auth_headers(token)).json()["content"]
    assert content["target_ref"]["code"] == platform["unique_code"]

    revoked = client.delete(f"{org_base(org['id'])}/collections/{collection['id']}/grants/{given['id']}", headers=auth_headers(token))
    assert revoked.status_code == 204, revoked.text
    hidden = _take(client, token, project["id"], "After revoking", types=[CONNECTION])
    row = _view(client, token, project["id"], hidden["id"])["records"][0]
    content = client.get(f"{project_base(project['id'])}/baselines/{hidden['id']}/items/{row['id']}", headers=auth_headers(token)).json()["content"]
    assert content["target_ref"] == {}
    with SessionLocal() as db:
        text = str([i.snapshot for i in db.scalars(select(BaselineItem).where(BaselineItem.baseline_id == uuid.UUID(hidden["id"])))])
    assert "Platform" not in text and "organization" not in text


def test_a_baseline_compares_with_the_live_model(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch baseline live")
    gateway, cloud, _link, _diagram, _machine = _scene(client, token, project["id"])
    baseline = _take(client, token, project["id"], "Baseline", types=ARCHITECTURE_TYPES)

    same = _by_type(_compare(client, token, project["id"], baseline["id"]))
    assert all(not t["added"] and not t["removed"] and not t["changed"] for t in same.values())
    assert same[ELEMENT]["unchanged"] == 2

    put_element(client, token, project["id"], gateway, name="Edge gateway", description="Terminates clients")
    added = make_element(client, token, project["id"], "Cache", type_name="Service")
    client.post(f"{project_base(project['id'])}/elements/{cloud['id']}/archive", headers=auth_headers(token))

    result = _compare(client, token, project["id"], baseline["id"])
    assert result["against"] == "live" and result["against_label"] == "Live model" and result["baseline_label"] == "Baseline"
    elements = _by_type(result)[ELEMENT]
    assert [r["name"] for r in elements["added"]] == [added["name"]]
    assert [r["name"] for r in elements["removed"]] == ["Cloud"]
    [changed] = elements["changed"]
    assert changed["name"] == "Edge gateway"
    fields = {f["field"]: f for f in changed["fields"]}
    assert (fields["name"]["before"], fields["name"]["after"]) == ("Gateway", "Edge gateway")
    assert fields["description"]["before"] is None and fields["description"]["after"] == "Terminates clients"
    assert elements["unchanged"] == 0


def test_a_baseline_compares_with_a_later_baseline_and_a_list_field_reports_entries(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch baseline pair")
    gateway, _cloud, _link, _diagram, _machine = _scene(client, token, project["id"])
    first = _take(client, token, project["id"], "First", types=[ELEMENT])
    port = client.post(
        f"{project_base(project['id'])}/elements/{gateway['id']}/ports", json={"name": "uplink", "direction": "out"},
        headers=auth_headers(token),
    )
    assert port.status_code in (200, 201), port.text
    second = _take(client, token, project["id"], "Second", types=[ELEMENT])

    result = _compare(client, token, project["id"], first["id"], against=second["id"])
    assert result["against"] == "baseline" and result["against_id"] == second["id"] and result["against_label"] == "Second"
    [changed] = _by_type(result)[ELEMENT]["changed"]
    [ports] = [f for f in changed["fields"] if f["field"] == "ports"]
    assert len(ports["added"]) == 1 and "uplink" in ports["added"][0] and ports["removed"] == []
    assert ports["before"] is None and ports["after"] is None

    reverse = _compare(client, token, project["id"], second["id"], against=first["id"])
    [back] = [f for f in _by_type(reverse)[ELEMENT]["changed"][0]["fields"] if f["field"] == "ports"]
    assert back["added"] == [] and len(back["removed"]) == 1


def test_a_baseline_outlives_its_records(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch baseline outlives")
    gateway, _cloud, _link, _diagram, _machine = _scene(client, token, project["id"])
    baseline = _take(client, token, project["id"], types=ARCHITECTURE_TYPES)
    removed = client.post(f"{project_base(project['id'])}/elements/{gateway['id']}/archive", headers=auth_headers(token))
    assert removed.status_code == 200, removed.text

    records = _view(client, token, project["id"], baseline["id"])["records"]
    assert any(r["name"] == "Gateway" for r in records)
    item = next(r for r in records if r["name"] == "Gateway")
    assert client.get(f"{project_base(project['id'])}/baselines/{baseline['id']}/items/{item['id']}", headers=auth_headers(token)).status_code == 200


# --- The comparison rules, without a database --------------------------------------------------


def test_the_comparison_ignores_the_order_of_a_list_and_reports_each_entry_once():
    before = {"unique_code": "ELM-001", "name": "A", "tags": ["x", "y"], "ports": [{"name": "p"}, {"name": "q"}]}
    after = {"unique_code": "ELM-001", "name": "A", "tags": ["y", "x"], "ports": [{"name": "q"}, {"name": "p"}, {"name": "r"}]}
    [change] = baseline_compare.changed_fields(before, after)
    assert change.field == "ports" and change.added == ['{"name":"r"}'] and change.removed == []

    [type_result] = baseline_compare.compare({ELEMENT: [before]}, {ELEMENT: [after]}, [ELEMENT])
    assert (type_result.unchanged, len(type_result.changed)) == (0, 1)


def test_the_comparison_treats_an_empty_value_and_a_missing_key_alike():
    assert baseline_compare.changed_fields({"unique_code": "C", "protocol": ""}, {"unique_code": "C"}) == []
    [change] = baseline_compare.changed_fields({"unique_code": "C", "is_x": True}, {"unique_code": "C", "is_x": False})
    assert (change.before, change.after) == ("Yes", "No")
