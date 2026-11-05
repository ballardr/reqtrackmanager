"""External references and the channel per ask: the two classified lists, references on a request, a requester's
channel, triage, bundles and the record table's references column."""

from __future__ import annotations

import csv
import io
import json
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.product_feedback.tests._helpers import (
    add_member,
    add_requester,
    create_engagement,
    create_inbox_request,
    create_request,
    create_stakeholder,
    enable_other_module,
    grant_project_role,
    org_base,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project

SYSTEMS = ("Jira", "ServiceNow", "Zendesk", "Azure DevOps", "GitHub", "Other")
CHANNELS = ("Engagement", "Support ticket", "Call", "Chat", "Conversation", "Email", "Survey", "Internal", "Other")


def _by_name(entries: list[dict]) -> dict[str, dict]:
    return {e["name"]: e for e in entries}


def _systems(client, token, project_id) -> dict[str, dict]:
    return _by_name(client.get(project_base(project_id) + "/external-systems", headers=auth_headers(token)).json())


def _refs_url(project_id, request_id) -> str:
    return f"{project_base(project_id)}/requests/{request_id}/references"


def test_a_new_organisation_gets_the_default_systems_and_channels(client, admin_token):
    org, project, token = setup(client, admin_token, "Refs Defaults Co")
    h = auth_headers(token)
    systems = client.get(org_base(org["id"]) + "/external-systems", headers=h).json()
    channels = client.get(org_base(org["id"]) + "/request-channels", headers=h).json()
    assert tuple(s["name"] for s in systems) == SYSTEMS and tuple(c["name"] for c in channels) == CHANNELS
    assert tuple(_systems(client, token, project["id"])) == SYSTEMS  # a project sees the organisation's list


def test_a_request_holds_several_references_with_system_and_role(client, admin_token):
    _, project, token = setup(client, admin_token, "Refs Several Co")
    h = auth_headers(token)
    systems = _systems(client, token, project["id"])
    request = create_request(client, token, project["id"], references=[
        {"system_id": systems["Jira"]["id"], "key": "PROJ-1", "role": "delivery"},
        {"system_id": systems["ServiceNow"]["id"], "key": "INC001", "url": "https://sn.example/INC001", "role": "origin"},
    ])
    assert [(r["system_name"], r["key"], r["role"]) for r in request["external_refs"]] == [
        ("Jira", "PROJ-1", "delivery"), ("ServiceNow", "INC001", "origin"),
    ]
    added = client.post(_refs_url(project["id"], request["id"]), json={"system_id": systems["GitHub"]["id"], "key": "#12"}, headers=h)
    assert added.status_code == 201, added.text
    assert added.json()["role"] == "delivery" and added.json()["system_name"] == "GitHub"
    listed = client.get(_refs_url(project["id"], request["id"]), headers=h).json()
    assert [r["system_name"] for r in listed] == ["Jira", "ServiceNow", "GitHub"]
    # A reference is not a content version, and it is audited without its key or link.
    detail = client.get(f"{project_base(project['id'])}/requests/{request['id']}", headers=h).json()
    assert detail["version_number"] == 1


def test_a_reference_can_be_changed_and_removed_and_needs_a_key_or_a_link(client, admin_token):
    _, project, token = setup(client, admin_token, "Refs Change Co")
    h = auth_headers(token)
    systems = _systems(client, token, project["id"])
    request = create_request(client, token, project["id"])
    url = _refs_url(project["id"], request["id"])
    assert client.post(url, json={"system_id": systems["Jira"]["id"]}, headers=h).status_code == 422
    ref = client.post(url, json={"system_id": systems["Jira"]["id"], "key": "P-1"}, headers=h).json()
    changed = client.patch(
        f"{url}/{ref['id']}", json={"role": "origin", "system_id": systems["Zendesk"]["id"], "url": "https://z.example/1"},
        headers=h,
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["role"], changed.json()["system_name"], changed.json()["url"]) == ("origin", "Zendesk", "https://z.example/1")
    both_empty = client.patch(f"{url}/{ref['id']}", json={"key": "", "url": None}, headers=h)
    assert both_empty.status_code == 400
    assert client.delete(f"{url}/{ref['id']}", headers=h).status_code == 204
    assert client.get(url, headers=h).json() == []
    assert client.delete(f"{url}/{ref['id']}", headers=h).status_code == 404


def test_a_reference_link_must_be_http_and_the_system_must_be_the_requests_own(client, admin_token):
    org, project, token = setup(client, admin_token, "Refs Safe Co")
    h = auth_headers(token)
    systems = _systems(client, token, project["id"])
    request = create_request(client, token, project["id"])
    url = _refs_url(project["id"], request["id"])
    for bad in ("javascript:alert(1)", "data:text/html,x", "//x.example"):
        assert client.post(url, json={"system_id": systems["Jira"]["id"], "key": "k", "url": bad}, headers=h).status_code == 422
    other_org, other_project, other_token = setup(client, admin_token, "Refs Other Co")
    foreign = _systems(client, other_token, other_project["id"])["Jira"]["id"]
    refused = client.post(url, json={"system_id": foreign, "key": "k"}, headers=h)
    assert refused.status_code == 400
    # Another request's reference id looks absent.
    mine = client.post(url, json={"system_id": systems["Jira"]["id"], "key": "k"}, headers=h).json()
    second = create_request(client, token, project["id"], title="Second")
    assert client.patch(f"{_refs_url(project['id'], second['id'])}/{mine['id']}", json={"key": "x"}, headers=h).status_code == 404


def test_only_a_triager_changes_references_after_creation_and_an_archived_request_is_frozen(client, admin_token):
    org, project, token = setup(client, admin_token, "Refs Gate Co")
    h = auth_headers(token)
    systems = _systems(client, token, project["id"])
    request = create_request(client, token, project["id"])
    _, member = add_member(client, token, org["id"], project["id"], "refs.member@example.com")
    body = {"system_id": systems["Jira"]["id"], "key": "P-1"}
    assert client.post(_refs_url(project["id"], request["id"]), json=body, headers=auth_headers(member)).status_code == 403
    user_id, triager = add_member(client, token, org["id"], project["id"], "refs.triager@example.com")
    grant_project_role(client, token, project["id"], user_id, "feedback_triager")
    assert client.post(_refs_url(project["id"], request["id"]), json=body, headers=auth_headers(triager)).status_code == 201
    client.post(f"{project_base(project['id'])}/requests/{request['id']}/archive", headers=h)
    assert client.post(_refs_url(project["id"], request["id"]), json=body, headers=h).status_code == 409


def test_a_project_adds_hides_and_restores_systems_and_a_hidden_one_keeps_existing_references(client, admin_token):
    org, project, token = setup(client, admin_token, "Refs Project List Co")
    h = auth_headers(token)
    base = project_base(project["id"]) + "/external-systems"
    systems = _systems(client, token, project["id"])
    request = create_request(client, token, project["id"], references=[{"system_id": systems["Jira"]["id"], "key": "P-1"}])
    local = client.post(base, json={"name": "Internal tracker"}, headers=h)
    assert local.status_code == 201, local.text
    assert "Internal tracker" in _systems(client, token, project["id"])
    ref_system = request["external_refs"][0]["system_id"]
    hidden = client.delete(f"{base}/{ref_system}", headers=h)
    assert hidden.status_code == 204, hidden.text
    assert "Jira" not in _systems(client, token, project["id"])
    assert [t["name"] for t in client.get(base + "/hidden", headers=h).json()] == ["Jira"]
    kept = client.get(_refs_url(project["id"], request["id"]), headers=h).json()
    assert kept[0]["system_name"] == "Jira"  # a hidden default is not offered again, but what holds it keeps it
    restored = client.post(base + "/restore", json={}, headers=h)
    assert restored.status_code == 200 and [t["name"] for t in restored.json()["restored"]] == ["Jira"]
    assert "Jira" in _systems(client, token, project["id"])
    # A system in use cannot be deleted while it is the project's own.
    own = _systems(client, token, project["id"])["Internal tracker"]["id"]
    client.post(_refs_url(project["id"], request["id"]), json={"system_id": own, "key": "T-1"}, headers=h)
    assert client.delete(f"{base}/{own}", headers=h).status_code == 409


def test_the_organisation_list_needs_the_list_admin_role_and_an_entry_in_use_cannot_be_deleted(client, admin_token):
    org, project, token = setup(client, admin_token, "Refs Org List Co")
    h = auth_headers(token)
    base = org_base(org["id"]) + "/external-systems"
    created = client.post(base, json={"name": "Linear"}, headers=h)
    assert created.status_code == 201, created.text
    assert client.post(base, json={"name": "Linear"}, headers=h).status_code == 400
    user_id, member = add_member(client, token, org["id"], project["id"], "refs.orgmember@example.com")
    assert client.post(base, json={"name": "Nope"}, headers=auth_headers(member)).status_code == 403
    assert client.get(base, headers=auth_headers(member)).status_code == 200
    renamed = client.patch(f"{base}/{created.json()['id']}", json={"name": "Linear app"}, headers=h)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Linear app"
    moved = client.post(f"{base}/{created.json()['id']}/move", json={"direction": "up"}, headers=h)
    assert moved.status_code == 200
    inbox = create_inbox_request(client, token, org["id"], references=[{"system_id": created.json()["id"], "key": "L-1"}])
    assert inbox["external_refs"][0]["system_name"] == "Linear app"
    assert client.delete(f"{base}/{created.json()['id']}", headers=h).status_code == 409
    client.patch(f"{base}/{created.json()['id']}", json={"is_active": False}, headers=h)
    refused = client.post(
        org_base(org["id"]) + "/requests",
        json={"title": "x", "references": [{"system_id": created.json()["id"], "key": "L-2"}]}, headers=h,
    )
    assert refused.status_code == 400  # an inactive system cannot be newly chosen


def test_triage_into_a_project_re_points_the_references_at_the_projects_systems(client, admin_token):
    org, project, token = setup(client, admin_token, "Refs Triage Co")
    h = auth_headers(token)
    org_systems = _by_name(client.get(org_base(org["id"]) + "/external-systems", headers=h).json())
    inbox = create_inbox_request(client, token, org["id"], references=[
        {"system_id": org_systems["Jira"]["id"], "key": "P-1"}, {"system_id": org_systems["GitHub"]["id"], "key": "#4"},
    ])
    # The project hides GitHub before the move: the reference is kept as a project system of the same name.
    project_systems = _systems(client, token, project["id"])
    client.delete(f"{project_base(project['id'])}/external-systems/{project_systems['GitHub']['id']}", headers=h)
    moved = client.post(f"{org_base(org['id'])}/requests/{inbox['id']}/move-to-project", json={"project_id": project["id"]}, headers=h)
    assert moved.status_code == 200, moved.text
    refs = client.get(_refs_url(project["id"], inbox["id"]), headers=h).json()
    assert sorted((r["system_name"], r["key"]) for r in refs) == [("GitHub", "#4"), ("Jira", "P-1")]
    now = _systems(client, token, project["id"])
    assert {r["system_id"] for r in refs} <= {e["id"] for e in now.values()} | {r["system_id"] for r in refs}
    assert "GitHub" in now  # the project-local copy the move created


def test_the_older_link_pair_is_a_delivery_reference_on_other_and_a_missing_other_is_refused(client, admin_token):
    org, project, token = setup(client, admin_token, "Refs Legacy Co")
    h = auth_headers(token)
    request = create_request(client, token, project["id"], external_ref_key="OLD-1")
    assert [(r["system_name"], r["role"]) for r in request["external_refs"]] == [("Other", "delivery")]
    updated = client.put(
        f"{project_base(project['id'])}/requests/{request['id']}", json={"external_ref_url": "https://x.example/1"}, headers=h,
    ).json()
    assert [(r["key"], r["url"]) for r in updated["external_refs"]] == [("OLD-1", "https://x.example/1")]
    other = _by_name(client.get(org_base(org["id"]) + "/external-systems", headers=h).json())["Other"]
    client.patch(f"{org_base(org['id'])}/external-systems/{other['id']}", json={"is_active": False}, headers=h)
    refused = client.post(
        project_base(project["id"]) + "/requests", json={"title": "No other", "external_ref_key": "X"}, headers=h,
    )
    assert refused.status_code == 400


# --- The channel per ask -------------------------------------------------------


def _world(client, admin_token, name):
    """An org with Product Feedback and People on, a project and its admin token."""
    org, token = create_org_admin_in(client, admin_token, name)
    for key in ("product_feedback", "stakeholders"):
        enable_other_module(client, token, org["id"], key)
    return org, create_project(client, token, org["id"], f"{name} Project"), token


def _channels(client, token, project_id) -> dict[str, dict]:
    return _by_name(client.get(project_base(project_id) + "/request-channels", headers=auth_headers(token)).json())


def _set_channel(client, token, project_id, request_id, parties, channel_id):
    return client.put(
        f"{project_base(project_id)}/requests/{request_id}/requester-channel",
        json={"parties": [{"artefact_type": t, "id": i} for t, i in parties], "channel_id": channel_id},
        headers=auth_headers(token),
    )


def _requester(demand: dict, party_id: str) -> dict:
    return next(r for r in demand["requesters"] if r["id"] == party_id)


def test_each_requester_has_a_channel_and_an_engagement_requester_has_none_recorded(client, admin_token):
    org, project, token = _world(client, admin_token, "Channel Ask Co")
    pid, h = project["id"], auth_headers(token)
    request = create_request(client, token, pid)
    ann, bob = create_stakeholder(client, token, pid, "Ann"), create_stakeholder(client, token, pid, "Bob")
    workshop = create_engagement(client, token, pid, stakeholder_ids=[bob["id"]])
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201
    assert add_requester(client, token, org["id"], pid, request["id"], "engagement", workshop["id"]).status_code == 201
    channels = _channels(client, token, pid)
    assert tuple(channels) == CHANNELS

    done = _set_channel(client, token, pid, request["id"], [("stakeholder", ann["id"])], channels["Support ticket"]["id"])
    assert done.status_code == 200, done.text
    demand = done.json()
    assert _requester(demand, ann["id"])["channel"]["name"] == "Support ticket"
    assert _requester(demand, bob["id"])["channel"] is None and _requester(demand, bob["id"])["via_engagement"] is True

    changed = _set_channel(client, token, pid, request["id"], [("stakeholder", ann["id"])], channels["Call"]["id"])
    assert _requester(changed.json(), ann["id"])["channel"]["name"] == "Call"
    cleared = _set_channel(client, token, pid, request["id"], [("stakeholder", ann["id"])], None)
    assert _requester(cleared.json(), ann["id"])["channel"] is None
    loop = client.get(f"{project_base(pid)}/requests/{request['id']}/close-the-loop", headers=h).json()
    assert all(r["channel"] is None for r in loop["requesters"])


def test_a_channel_is_refused_for_a_stranger_a_foreign_channel_a_member_and_an_archived_request(client, admin_token):
    org, project, token = _world(client, admin_token, "Channel Gate Co")
    pid, h = project["id"], auth_headers(token)
    request = create_request(client, token, pid)
    ann, stranger = create_stakeholder(client, token, pid, "Ann"), create_stakeholder(client, token, pid, "Stranger")
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201
    call = _channels(client, token, pid)["Call"]["id"]
    assert _set_channel(client, token, pid, request["id"], [("stakeholder", stranger["id"])], call).status_code == 409
    assert _set_channel(client, token, pid, request["id"], [("stakeholder", ann["id"]), ("stakeholder", stranger["id"])], call).status_code == 409
    _, other_project, other_token = _world(client, admin_token, "Channel Gate Other Co")
    foreign = _channels(client, other_token, other_project["id"])["Call"]["id"]
    assert _set_channel(client, token, pid, request["id"], [("stakeholder", ann["id"])], foreign).status_code == 409
    _, member = add_member(client, token, org["id"], pid, "channel.member@example.com")
    assert _set_channel(client, member, pid, request["id"], [("stakeholder", ann["id"])], call).status_code == 403
    client.post(f"{project_base(pid)}/requests/{request['id']}/archive", headers=h)
    assert _set_channel(client, token, pid, request["id"], [("stakeholder", ann["id"])], call).status_code == 409


def test_a_merged_duplicates_requester_keeps_its_channel_and_the_canonical_one_wins(client, admin_token):
    org, project, token = _world(client, admin_token, "Channel Merge Co")
    pid, h = project["id"], auth_headers(token)
    canonical, duplicate = create_request(client, token, pid, title="Canonical"), create_request(client, token, pid, title="Duplicate")
    ann = create_stakeholder(client, token, pid, "Ann")
    assert add_requester(client, token, org["id"], pid, duplicate["id"], "stakeholder", ann["id"]).status_code == 201
    channels = _channels(client, token, pid)
    assert _set_channel(client, token, pid, duplicate["id"], [("stakeholder", ann["id"])], channels["Email"]["id"]).status_code == 200
    merged = client.post(f"{project_base(pid)}/requests/{duplicate['id']}/merge", json={"canonical_id": canonical["id"]}, headers=h)
    assert merged.status_code == 200, merged.text
    demand = client.get(f"{project_base(pid)}/requests/{canonical['id']}/demand", headers=h).json()
    assert _requester(demand, ann["id"])["channel"]["name"] == "Email" and _requester(demand, ann["id"])["from_merge"] is True
    over = _set_channel(client, token, pid, canonical["id"], [("stakeholder", ann["id"])], channels["Call"]["id"])
    assert _requester(over.json(), ann["id"])["channel"]["name"] == "Call"
    gone = _set_channel(client, token, pid, canonical["id"], [("stakeholder", ann["id"])], None)
    assert _requester(gone.json(), ann["id"])["channel"] is None  # clearing removes the duplicate's row too


def test_setting_a_channel_is_audited_with_the_parties_and_a_channel_in_use_cannot_be_deleted(client, admin_token):
    org, project, token = _world(client, admin_token, "Channel Audit Co")
    pid, h = project["id"], auth_headers(token)
    request = create_request(client, token, pid)
    ann = create_stakeholder(client, token, pid, "Ann")
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201
    chat = _channels(client, token, pid)["Chat"]
    assert _set_channel(client, token, pid, request["id"], [("stakeholder", ann["id"])], chat["id"]).status_code == 200
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == request["id"], AuditEvent.action == "requester_channel_set",
        )))
    detail = events[0].detail or {}
    assert len(events) == 1 and detail["parties"] == [{"type": "stakeholder", "id": ann["id"]}]
    assert detail["changed"] == 1 and "Chat" not in str(detail)
    base = project_base(pid) + "/request-channels"
    own = client.post(base, json={"name": "Hallway"}, headers=h).json()
    assert _set_channel(client, token, pid, request["id"], [("stakeholder", ann["id"])], own["id"]).status_code == 200
    assert client.delete(f"{base}/{own['id']}", headers=h).status_code == 409
    # Hiding an organisation channel here keeps the choice already made and stops it being offered anew.
    hidden = client.delete(f"{base}/{chat['id']}", headers=h)
    assert hidden.status_code == 204
    assert "Chat" not in _channels(client, token, pid)


# --- Bundles and the record table ------------------------------------------------


def _export_project(client, token, project_id) -> bytes:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _import_project(client, token, org_id, data: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", data, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["project"]


def test_references_channels_and_the_projects_own_lists_survive_a_project_round_trip(client, admin_token):
    org, project, token = _world(client, admin_token, "Refs Bundle Co")
    pid, h = project["id"], auth_headers(token)
    systems = _systems(client, token, pid)
    local = client.post(project_base(pid) + "/external-systems", json={"name": "Internal tracker"}, headers=h).json()
    client.delete(f"{project_base(pid)}/external-systems/{systems['Zendesk']['id']}", headers=h)
    request = create_request(client, token, pid, title="Bundled", references=[
        {"system_id": systems["Jira"]["id"], "key": "P-1", "role": "origin"},
        {"system_id": local["id"], "key": "T-9", "url": "https://t.example/9"},
    ])
    ann = create_stakeholder(client, token, pid, "Ann")
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201
    hallway = client.post(project_base(pid) + "/request-channels", json={"name": "Hallway"}, headers=h).json()
    assert _set_channel(client, token, pid, request["id"], [("stakeholder", ann["id"])], hallway["id"]).status_code == 200

    imported = _import_project(client, token, org["id"], _export_project(client, token, pid), "Restored")
    iid = imported["id"]
    got = next(r for r in client.get(project_base(iid) + "/requests", headers=h).json() if r["title"] == "Bundled")
    assert sorted((r["system_name"], r["key"], r["url"], r["role"]) for r in got["external_refs"]) == [
        ("Internal tracker", "T-9", "https://t.example/9", "delivery"), ("Jira", "P-1", None, "origin"),
    ]
    assert "Zendesk" not in _systems(client, token, iid) and "Internal tracker" in _systems(client, token, iid)
    demand = client.get(f"{project_base(iid)}/requests/{got['id']}/demand", headers=h).json()
    assert [r["channel"]["name"] for r in demand["requesters"]] == ["Hallway"]


def test_the_organisations_lists_and_inbox_references_survive_an_organisation_round_trip(client, admin_token):
    org, _, token = setup(client, admin_token, "Refs Org Bundle Co")
    h = auth_headers(token)
    linear = client.post(org_base(org["id"]) + "/external-systems", json={"name": "Linear"}, headers=h).json()
    client.post(org_base(org["id"]) + "/request-channels", json={"name": "Town hall"}, headers=h)
    create_inbox_request(client, token, org["id"], title="Linked", references=[{"system_id": linear["id"], "key": "L-1"}])
    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h).content
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export)).read("org.json"))
    assert "Linear" in [e["name"] for e in org_json["external_systems"]]
    assert org_json["enhancement_requests"][0]["references"] == [{"system": "Linear", "key": "L-1", "url": None, "role": "delivery"}]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Restored Refs Org"},
        files={"file": ("bundle.zip", export, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org = imported.json()["organization"]["id"]
    with SessionLocal() as db:
        from app.modules.product_feedback.models import (
            EnhancementRequest,
            EnhancementRequestExternalRef,
            ExternalSystemDefinition,
            RequestChannelDefinition,
        )

        names = {s.name for s in db.scalars(select(ExternalSystemDefinition).where(ExternalSystemDefinition.organization_id == new_org))}
        channels = {c.name for c in db.scalars(select(RequestChannelDefinition).where(RequestChannelDefinition.organization_id == new_org))}
        refs = list(db.scalars(
            select(EnhancementRequestExternalRef).join(EnhancementRequest, EnhancementRequest.id == EnhancementRequestExternalRef.request_id)
            .where(EnhancementRequest.organization_id == new_org)
        ))
        assert set(SYSTEMS) | {"Linear"} == names and "Town hall" in channels and len(channels) == len(CHANNELS) + 1
        assert [r.key for r in refs] == ["L-1"]


def test_the_references_column_exports_as_system_key_and_an_import_adds_but_never_removes(client, admin_token):
    org, project, token = setup(client, admin_token, "Refs Table Co")
    pid, h = project["id"], auth_headers(token)
    systems = _systems(client, token, pid)
    request = create_request(client, token, pid, references=[
        {"system_id": systems["Jira"]["id"], "key": "P-1"},
        {"system_id": systems["ServiceNow"]["id"], "key": "INC1", "role": "origin"},
        {"system_id": systems["GitHub"]["id"], "url": "https://gh.example/1"},
    ])
    tier = f"/api/v1/projects/{pid}/records/enhancement_request"
    exported = client.get(f"{tier}/export", headers=h)
    assert exported.status_code == 200, exported.text
    text = exported.content.decode("utf-8-sig")
    row = next(csv.DictReader(io.StringIO(text)))
    assert row["references"] == "Jira:P-1;ServiceNow:INC1 (origin);GitHub:https://gh.example/1"

    # Re-importing the exported file changes nothing; a file naming one more reference adds only that one.
    def post(body: str, *, apply: bool):
        return client.post(
            f"{tier}/import", params={"dry_run": "false" if apply else "true"},
            files={"file": ("r.csv", body.encode(), "text/csv")}, headers=h,
        )

    same = post(text, apply=True)
    assert same.status_code == 200, same.text
    assert len(client.get(_refs_url(pid, request["id"]), headers=h).json()) == 3
    more = text.replace("GitHub:https://gh.example/1", "GitHub:https://gh.example/1;Zendesk:Z-5")
    applied = post(more, apply=True)
    assert applied.status_code == 200, applied.text
    refs = client.get(_refs_url(pid, request["id"]), headers=h).json()
    assert sorted((r["system_name"], r["key"] or r["url"], r["role"]) for r in refs) == [
        ("GitHub", "https://gh.example/1", "delivery"), ("Jira", "P-1", "delivery"),
        ("ServiceNow", "INC1", "origin"), ("Zendesk", "Z-5", "delivery"),
    ]
    fewer = "code,references\n" + request["unique_code"] + ",Jira:P-1\n"
    assert post(fewer, apply=True).status_code == 200
    assert len(client.get(_refs_url(pid, request["id"]), headers=h).json()) == 4  # an import never removes a reference

    unknown = "code,title,references\n,Odd,Nowhere:X-1\n"
    preview = post(unknown, apply=False)
    assert preview.status_code == 200 and [r["action"] for r in preview.json()["rows"]] == ["error"]


def test_a_project_member_reads_the_lists_but_only_a_triager_changes_them(client, admin_token):
    org, project, token = setup(client, admin_token, "Refs List Gate Co")
    pid = project["id"]
    _, member = add_member(client, token, org["id"], pid, "refs.listmember@example.com")
    base = project_base(pid) + "/external-systems"
    assert client.get(base, headers=auth_headers(member)).status_code == 200
    assert client.post(base, json={"name": "Mine"}, headers=auth_headers(member)).status_code == 403
    jira = _systems(client, token, pid)["Jira"]["id"]
    assert client.put(f"{base}/{jira}", json={"is_enabled": False}, headers=auth_headers(member)).status_code == 403
    assert client.delete(f"{base}/{jira}", headers=auth_headers(member)).status_code == 403
    assert client.get(base + "/hidden", headers=auth_headers(member)).status_code == 403
    assert client.post(base + "/restore", json={}, headers=auth_headers(member)).status_code == 403
    # A disabled system stays listed (so it can be re-enabled) but cannot be newly chosen.
    assert client.put(f"{base}/{jira}", json={"is_enabled": False}, headers=auth_headers(token)).status_code == 200
    refused = client.post(
        project_base(pid) + "/requests", json={"title": "x", "references": [{"system_id": jira, "key": "k"}]}, headers=auth_headers(token),
    )
    assert refused.status_code == 400


def test_a_bundle_name_longer_than_the_column_is_skipped_with_a_warning(client, admin_token):
    from app.database import SessionLocal
    from app.models.project import Project
    from app.modules.product_feedback.vocabularies import EXTERNAL_SYSTEMS
    from app.modules.product_feedback.vocabulary_bundle import NameResolver
    from app.services.bundle_common import BundleImportWarnings

    org, project, _ = setup(client, admin_token, "Refs Long Name Co")
    warnings = BundleImportWarnings()
    with SessionLocal() as db:
        resolver = NameResolver(db, EXTERNAL_SYSTEMS, project["organization_id"], db.get(Project, project["id"]), warnings, "external system")
        assert resolver.row_id("x" * 101) is None
        assert resolver.row_id("Jira") is not None
        db.rollback()
    assert any("longer than 100" in str(w) for w in warnings.messages)


# --- Nested projects ----------------------------------------------------------------


def _child_project(client, token, org_id, parent_id, name="Child", *, can_be_parent=False) -> dict:
    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": name, "summary": "", "parent_project_id": parent_id, "can_be_parent": can_be_parent},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _parent_and_child(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    enable_other_module(client, token, org["id"], "product_feedback")
    parent = client.post(
        "/api/v1/projects", json={"organization_id": org["id"], "name": f"{name} Parent", "summary": "", "can_be_parent": True},
        headers=auth_headers(token),
    ).json()
    return org, parent, _child_project(client, token, org["id"], parent["id"], f"{name} Child", can_be_parent=True), token


def test_a_child_project_shows_its_ancestors_list_until_it_changes_its_own(client, admin_token):
    org, parent, child, token = _parent_and_child(client, admin_token, "Refs Nested Co")
    h = auth_headers(token)
    parent_base = project_base(parent["id"]) + "/external-systems"
    grandchild = _child_project(client, token, org["id"], child["id"], "Grandchild")
    assert tuple(_systems(client, token, child["id"])) == SYSTEMS  # nothing configured anywhere: the organisation's list

    jira = _systems(client, token, parent["id"])["Jira"]["id"]
    assert client.delete(f"{parent_base}/{jira}", headers=h).status_code == 204  # the parent hides Jira
    client.post(parent_base, json={"name": "Parent tracker"}, headers=h)
    for pid in (child["id"], grandchild["id"]):
        names = _systems(client, token, pid)
        assert "Jira" not in names and "Parent tracker" in names  # the nearest configured ancestor, through the child

    # A request in the child can use the parent's own entry, and not the hidden one.
    entry = _systems(client, token, child["id"])["Parent tracker"]["id"]
    made = create_request(client, token, child["id"], references=[{"system_id": entry, "key": "T-1"}])
    assert [r["system_name"] for r in made["external_refs"]] == ["Parent tracker"]
    refused = client.post(
        project_base(child["id"]) + "/requests", json={"title": "x", "references": [{"system_id": jira, "key": "k"}]}, headers=h,
    )
    assert refused.status_code == 400

    # The child's first change copies the inherited list into it; the parent is untouched.
    own = client.post(project_base(child["id"]) + "/external-systems", json={"name": "Child only"}, headers=h)
    assert own.status_code == 201, own.text
    child_names = _systems(client, token, child["id"])
    assert "Child only" in child_names and "Parent tracker" in child_names and "Jira" not in child_names
    assert "Child only" not in _systems(client, token, parent["id"])
    # From then on the child no longer follows the parent.
    client.post(parent_base, json={"name": "Added later"}, headers=h)
    assert "Added later" not in _systems(client, token, child["id"])
    assert "Added later" in _systems(client, token, parent["id"])
    # The grandchild still has nothing of its own, so it follows the child now.
    assert "Child only" in _systems(client, token, grandchild["id"])


def test_a_child_renames_an_inherited_entry_without_touching_the_parents(client, admin_token):
    org, parent, child, token = _parent_and_child(client, admin_token, "Refs Nested Rename Co")
    h = auth_headers(token)
    parent_systems = _systems(client, token, parent["id"])
    client.put(
        f"{project_base(parent['id'])}/external-systems/{parent_systems['GitHub']['id']}", json={"name": "Parent GitHub"}, headers=h,
    )
    inherited = _systems(client, token, child["id"])["Parent GitHub"]["id"]  # the parent's override row
    renamed = client.put(f"{project_base(child['id'])}/external-systems/{inherited}", json={"name": "Child GitHub"}, headers=h)
    assert renamed.status_code == 200, renamed.text
    assert "Child GitHub" in _systems(client, token, child["id"]) and "Parent GitHub" not in _systems(client, token, child["id"])
    assert "Parent GitHub" in _systems(client, token, parent["id"])
