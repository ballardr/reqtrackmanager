"""Tests for governance profiles (`modules.traceability.router`, `project_router`, `profiles`, `profile_resolution`):
the organisation API, a project's view and choices, who may change what, how a profile resolves for a project (Enforced,
exempt, Default, opted out, Opt-in, offered, not reached; nested children), the order of applicable profiles, the audit
events, and the `ProfileContributor` registration (validation and the counts shown beside a profile)."""

from __future__ import annotations

import uuid as uuid_lib

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.module import OrganizationModuleSubComponentDefault
from app.modules import registry as module_registry
from app.modules.registry import ModuleDefinition, ModuleSubComponentDefinition, build_registry
from app.modules.seams import ProfileContributor
from app.modules.traceability import profile_resolution
from app.modules.traceability._shared import TRACEABILITY_MODULE_KEY
from app.modules.traceability.enums import ProfileOutcome
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project

BASE = "/api/v1/orgs/{org}/modules/traceability"
PROJECT_BASE = "/api/v1/projects/{project}/modules/traceability"


def _enable(client, token, org_id) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{TRACEABILITY_MODULE_KEY}",
        json={"enabled": True, "default_project_enabled": True}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    _enable(client, token, org["id"])
    return org, token


def _create(client, token, org_id, name, mode="enforced", target_kind="all_projects", targets=(), status=201, description=""):
    resp = client.post(
        BASE.format(org=org_id) + "/profiles",
        json={"name": name, "description": description, "mode": mode, "target_kind": target_kind, "targets": list(targets)},
        headers=auth_headers(token),
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _outcome(client, token, project_id, profile_id) -> str | None:
    resp = client.get(PROJECT_BASE.format(project=project_id) + "/profiles", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    found = [p for p in resp.json()["profiles"] if p["id"] == profile_id]
    return found[0]["outcome"] if found else None


def _choose(client, token, project_id, profile_id, opted_in, status=200):
    resp = client.put(
        PROJECT_BASE.format(project=project_id) + f"/profiles/{profile_id}/choice", json={"opted_in": opted_in},
        headers=auth_headers(token),
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _exempt(client, token, org_id, profile_id, project_id, *, include_children=False, reason="", status=200):
    resp = client.post(
        BASE.format(org=org_id) + f"/profiles/{profile_id}/exemptions",
        json={"project_id": project_id, "include_children": include_children, "reason": reason}, headers=auth_headers(token),
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _audit(entity_id: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "governance_profile", AuditEvent.entity_id == entity_id)))
    finally:
        db.close()


# --- gating ---------------------------------------------------------------------------------


def test_endpoints_are_not_found_while_the_module_is_off(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Profiles Module Off Org")
    project = create_project(client, token, org["id"])
    assert client.get(BASE.format(org=org["id"]) + "/profiles", headers=auth_headers(token)).status_code == 404
    assert client.get(PROJECT_BASE.format(project=project["id"]) + "/profiles", headers=auth_headers(token)).status_code == 404


def test_only_holders_of_the_organisation_atom_manage_profiles(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Org Permission Org")
    create_org_user(client, token, org["id"], "profiles_member@example.com")
    member_token = client.post(
        "/api/v1/auth/login", json={"email": "profiles_member@example.com", "password": "Password123!"}
    ).json()["access_token"]
    url = BASE.format(org=org["id"]) + "/profiles"
    assert client.get(url, headers=auth_headers(member_token)).status_code == 403
    assert client.post(
        url, json={"name": "X", "mode": "enforced"}, headers=auth_headers(member_token),
    ).status_code == 403
    assert client.get(url, headers=auth_headers(token)).status_code == 200


def test_a_profile_of_another_organisation_is_not_found(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Own Org")
    other, other_token = _setup(client, admin_token, "Profiles Other Org")
    foreign = _create(client, other_token, other["id"], "Foreign")
    url = BASE.format(org=org["id"]) + f"/profiles/{foreign['id']}"
    assert client.get(url, headers=auth_headers(token)).status_code == 404
    assert client.patch(url, json={"name": "Taken"}, headers=auth_headers(token)).status_code == 404
    assert client.delete(url, headers=auth_headers(token)).status_code == 404


# --- profile CRUD ---------------------------------------------------------------------------


def test_create_rename_change_mode_and_delete_a_profile(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Crud Org")
    h = auth_headers(token)
    created = _create(client, token, org["id"], "  Regulated  ", description="Applies to regulated work")
    assert created["name"] == "Regulated"
    assert created["mode"] == "enforced" and created["target_kind"] == "all_projects"
    assert created["description"] == "Applies to regulated work"

    _create(client, token, org["id"], "regulated", status=409)  # case-insensitive duplicate
    _create(client, token, org["id"], "   ", status=422)
    _create(client, token, org["id"], "Bad Mode", mode="mandatory", status=422)

    url = BASE.format(org=org["id"]) + f"/profiles/{created['id']}"
    renamed = client.patch(url, json={"name": "Regulated work", "mode": "default"}, headers=h)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Regulated work" and renamed.json()["mode"] == "default"
    second = _create(client, token, org["id"], "Second")
    assert client.patch(
        BASE.format(org=org["id"]) + f"/profiles/{second['id']}", json={"name": "REGULATED WORK"}, headers=h,
    ).status_code == 409

    listing = client.get(BASE.format(org=org["id"]) + "/profiles", headers=h).json()
    assert [p["name"] for p in listing] == ["Regulated work", "Second"]

    assert client.delete(url, headers=h).status_code == 204
    assert client.get(url, headers=h).status_code == 404


def test_every_change_writes_one_audit_event_without_policy_content(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Audit Org")
    project = create_project(client, token, org["id"], "Audited")
    profile = _create(client, token, org["id"], "Audited profile", description="Secret-sounding description")
    url = BASE.format(org=org["id"]) + f"/profiles/{profile['id']}"
    client.patch(url, json={"mode": "default"}, headers=auth_headers(token))
    client.put(
        url + "/targets", json={"target_kind": "selected_projects", "targets": [{"project_id": project["id"]}]},
        headers=auth_headers(token),
    )
    client.patch(url, json={"mode": "enforced"}, headers=auth_headers(token))
    _exempt(client, token, org["id"], profile["id"], project["id"], reason="Pilot with its own controls")
    client.delete(url + f"/exemptions/{project['id']}", headers=auth_headers(token))
    client.delete(url, headers=auth_headers(token))

    events = _audit(profile["id"])
    assert [e.action for e in sorted(events, key=lambda e: e.created_at)] == [
        "created", "updated", "targets_set", "updated", "exemption_added", "exemption_removed", "deleted",
    ]
    dumped = " ".join(str(e.detail) for e in events)
    assert "Secret-sounding description" not in dumped and "Pilot with its own controls" not in dumped
    assert all(str(e.organization_id) == org["id"] for e in events)


# --- targets --------------------------------------------------------------------------------


def test_targets_name_projects_of_the_organisation_only(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Targets Org")
    other, other_token = _setup(client, admin_token, "Profiles Targets Other Org")
    mine = create_project(client, token, org["id"], "Mine")
    theirs = create_project(client, other_token, other["id"], "Theirs")
    _create(
        client, token, org["id"], "Bad", mode="default", target_kind="selected_projects",
        targets=[{"project_id": theirs["id"]}], status=422,
    )
    profile = _create(
        client, token, org["id"], "Selected", mode="default", target_kind="selected_projects",
        targets=[{"project_id": mine["id"], "include_children": True}],
    )
    assert [(t["project_name"], t["include_children"]) for t in profile["targets"]] == [("Mine", True)]

    url = BASE.format(org=org["id"]) + f"/profiles/{profile['id']}/targets"
    h = auth_headers(token)
    assert client.put(
        url, json={"target_kind": "selected_projects", "targets": [{"project_id": theirs["id"]}]}, headers=h,
    ).status_code == 422
    cleared = client.put(url, json={"target_kind": "all_projects", "targets": [{"project_id": mine["id"]}]}, headers=h)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["targets"] == [] and cleared.json()["target_kind"] == "all_projects"


# --- outcomes -------------------------------------------------------------------------------


def test_an_enforced_profile_binds_every_targeted_project_until_it_is_exempt(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Enforced Org")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    other = create_project(client, token, org["id"], "Other")
    profile = _create(client, token, org["id"], "Everyone")

    for project in (parent, child, other):
        assert _outcome(client, token, project["id"], profile["id"]) == "enforced"

    # An exemption of the parent alone leaves its child bound.
    _exempt(client, token, org["id"], profile["id"], parent["id"], reason="Pilot")
    assert _outcome(client, token, parent["id"], profile["id"]) == "exempt"
    assert _outcome(client, token, child["id"], profile["id"]) == "enforced"

    detail = _exempt(client, token, org["id"], profile["id"], parent["id"], include_children=True, reason="Pilot tree")
    assert _outcome(client, token, child["id"], profile["id"]) == "exempt"
    assert _outcome(client, token, other["id"], profile["id"]) == "enforced"
    assert [(e["project_name"], e["include_children"], e["reason"]) for e in detail["exemptions"]] == [("Parent", True, "Pilot tree")]
    by_project = {p["project_name"]: p for p in detail["projects"]}
    assert by_project["Child"]["outcome"] == "exempt" and by_project["Child"]["applies"] is False
    assert by_project["Other"]["applies"] is True

    removed = client.delete(
        BASE.format(org=org["id"]) + f"/profiles/{profile['id']}/exemptions/{parent['id']}", headers=auth_headers(token),
    )
    assert removed.status_code == 200, removed.text
    assert _outcome(client, token, child["id"], profile["id"]) == "enforced"
    assert client.delete(
        BASE.format(org=org["id"]) + f"/profiles/{profile['id']}/exemptions/{parent['id']}", headers=auth_headers(token),
    ).status_code == 404


def test_a_selected_profile_reaches_a_project_and_optionally_its_children(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Selected Org")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    other = create_project(client, token, org["id"], "Other")
    alone = _create(
        client, token, org["id"], "Alone", target_kind="selected_projects", targets=[{"project_id": parent["id"]}],
    )
    tree = _create(
        client, token, org["id"], "Tree", target_kind="selected_projects",
        targets=[{"project_id": parent["id"], "include_children": True}],
    )
    assert _outcome(client, token, parent["id"], alone["id"]) == "enforced"
    assert _outcome(client, token, child["id"], alone["id"]) is None  # not listed: it does not reach the child
    assert _outcome(client, token, child["id"], tree["id"]) == "enforced"
    assert _outcome(client, token, other["id"], tree["id"]) is None


def test_a_default_profile_applies_until_the_project_opts_out(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Default Org")
    project = create_project(client, token, org["id"], "Chooser")
    profile = _create(client, token, org["id"], "Default set", mode="default")
    assert _outcome(client, token, project["id"], profile["id"]) == "default"

    body = _choose(client, token, project["id"], profile["id"], False)
    listed = [p for p in body["profiles"] if p["id"] == profile["id"]][0]
    assert listed["outcome"] == "opted_out" and listed["applies"] is False and listed["choice"] is False
    assert listed["can_choose"] is True

    _choose(client, token, project["id"], profile["id"], True, status=422)  # a Default profile takes only an opt-out
    _choose(client, token, project["id"], profile["id"], None)
    assert _outcome(client, token, project["id"], profile["id"]) == "default"


def test_an_opt_in_profile_applies_only_where_the_project_chooses_it(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Opt In Org")
    project = create_project(client, token, org["id"], "Chooser")
    profile = _create(client, token, org["id"], "Opt-in set", mode="opt_in")
    assert _outcome(client, token, project["id"], profile["id"]) == "available"
    _choose(client, token, project["id"], profile["id"], False, status=422)  # an Opt-in profile takes only an opt-in
    _choose(client, token, project["id"], profile["id"], True)
    assert _outcome(client, token, project["id"], profile["id"]) == "opted_in"
    _choose(client, token, project["id"], profile["id"], None)
    assert _outcome(client, token, project["id"], profile["id"]) == "available"


def test_an_enforced_profile_takes_no_choice_and_an_unreached_project_cannot_choose(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Refused Choice Org")
    reached = create_project(client, token, org["id"], "Reached")
    unreached = create_project(client, token, org["id"], "Unreached")
    enforced = _create(client, token, org["id"], "Enforced set")
    selected = _create(
        client, token, org["id"], "Selected opt-in", mode="opt_in", target_kind="selected_projects",
        targets=[{"project_id": reached["id"]}],
    )
    _choose(client, token, reached["id"], enforced["id"], False, status=409)
    _choose(client, token, unreached["id"], selected["id"], True, status=409)
    _choose(client, token, reached["id"], selected["id"], True)
    # Only an Enforced profile has exemptions.
    _exempt(client, token, org["id"], selected["id"], reached["id"], status=409)


def test_a_choice_left_from_an_earlier_mode_is_ignored_and_kept(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Stale Choice Org")
    project = create_project(client, token, org["id"], "Chooser")
    profile = _create(client, token, org["id"], "Switching", mode="default")
    _choose(client, token, project["id"], profile["id"], False)
    url = BASE.format(org=org["id"]) + f"/profiles/{profile['id']}"

    client.patch(url, json={"mode": "enforced"}, headers=auth_headers(token))
    assert _outcome(client, token, project["id"], profile["id"]) == "enforced"  # the opt-out no longer lifts anything
    client.patch(url, json={"mode": "default"}, headers=auth_headers(token))
    assert _outcome(client, token, project["id"], profile["id"]) == "opted_out"


def test_applicable_profiles_are_ordered_enforced_then_default_then_opted_in(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Order Org")
    project = create_project(client, token, org["id"], "Ordered")
    optional = _create(client, token, org["id"], "A opt-in", mode="opt_in")
    _create(client, token, org["id"], "B default", mode="default")
    _create(client, token, org["id"], "C enforced")
    _create(client, token, org["id"], "D opt-in not chosen", mode="opt_in")
    out = _create(client, token, org["id"], "E default opted out", mode="default")
    _choose(client, token, project["id"], optional["id"], True)
    _choose(client, token, project["id"], out["id"], False)

    db = SessionLocal()
    try:
        applied = profile_resolution.applicable_profiles(db, uuid_lib.UUID(project["id"]))
        assert [(a.name, a.outcome) for a in applied] == [
            ("C enforced", ProfileOutcome.ENFORCED), ("B default", ProfileOutcome.DEFAULT), ("A opt-in", ProfileOutcome.OPTED_IN),
        ]
        assert profile_resolution.applicable_profiles(db, uuid_lib.uuid4()) == []
    finally:
        db.close()

    listing = client.get(PROJECT_BASE.format(project=project["id"]) + "/profiles", headers=auth_headers(token)).json()
    assert [p["name"] for p in listing["profiles"]] == [
        "C enforced", "B default", "E default opted out", "A opt-in", "D opt-in not chosen",
    ]


def test_a_project_is_not_told_about_profiles_that_do_not_reach_it(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Disclosure Org")
    project = create_project(client, token, org["id"], "Mine")
    elsewhere = create_project(client, token, org["id"], "Elsewhere")
    secret = _create(
        client, token, org["id"], "Confidential programme", target_kind="selected_projects",
        targets=[{"project_id": elsewhere["id"]}],
    )
    listing = client.get(PROJECT_BASE.format(project=project["id"]) + "/profiles", headers=auth_headers(token)).json()
    assert secret["name"] not in str(listing)


# --- project permissions --------------------------------------------------------------------


def test_a_member_reads_the_project_profiles_but_only_a_governance_manager_chooses(client, admin_token):
    org, token = _setup(client, admin_token, "Profiles Project Permission Org")
    project = create_project(client, token, org["id"], "Permissions")
    profile = _create(client, token, org["id"], "Choosable", mode="default")
    for email, role in (("prof_member@example.com", "member"), ("prof_manager@example.com", "project_manager")):
        user_id = create_org_user(client, token, org["id"], email)
        resp = client.post(
            f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token),
        )
        assert resp.status_code in (200, 201, 204), resp.text
    tokens = {
        email: client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"}).json()["access_token"]
        for email in ("prof_member@example.com", "prof_manager@example.com")
    }
    member, manager = tokens["prof_member@example.com"], tokens["prof_manager@example.com"]

    seen = client.get(PROJECT_BASE.format(project=project["id"]) + "/profiles", headers=auth_headers(member))
    assert seen.status_code == 200 and seen.json()["can_manage"] is False
    _choose(client, member, project["id"], profile["id"], False, status=403)
    assert _choose(client, manager, project["id"], profile["id"], False)["can_manage"] is True

    # Someone with no role on the project does not see it.
    stranger_id = create_org_user(client, token, org["id"], "prof_stranger@example.com")
    assert stranger_id
    stranger = client.post(
        "/api/v1/auth/login", json={"email": "prof_stranger@example.com", "password": "Password123!"}
    ).json()["access_token"]
    assert client.get(PROJECT_BASE.format(project=project["id"]) + "/profiles", headers=auth_headers(stranger)).status_code in (403, 404)


# --- contributors ---------------------------------------------------------------------------

FAKE_KEY = "fake_profile_contributor_module"


def _fake_contributor(rows):
    def count_rows(db, profile_ids):
        return {pid: len(rows[pid]) for pid in profile_ids if pid in rows}

    return ProfileContributor(
        key="things", name="Fake things", count_rows=count_rows, export_rows=lambda db, pid: list(rows.get(pid, [])),
        import_rows=lambda db, pid, entries, warn: rows.setdefault(pid, []).extend(entries), sub_component="things",
    )


def _fake_definition(profile_contributors: tuple[ProfileContributor, ...] = ()) -> ModuleDefinition:
    return ModuleDefinition(
        key=FAKE_KEY, name="Fake Contributor Module", description="Fixture.", version="0.0.1", default_enabled=True,
        implemented=False, get_router=lambda: None, no_org_bundle="Fixture.", no_project_bundle="Fixture.",
        sub_components=(ModuleSubComponentDefinition(key="things", name="Things"),),
        profile_contributors=profile_contributors,
    )


def test_a_contributor_cannot_name_an_undeclared_sub_component_or_repeat_a_key():
    contributor = _fake_contributor({})
    with pytest.raises(ValueError, match="undeclared sub-component"):
        _fake_definition(profile_contributors=(ProfileContributor(
            key="x", name="X", count_rows=contributor.count_rows, export_rows=contributor.export_rows,
            import_rows=contributor.import_rows, sub_component="nope",
        ),))
    with pytest.raises(ValueError, match="duplicate profile contributor"):
        _fake_definition(profile_contributors=(contributor, contributor))


def test_a_profile_lists_the_policy_rows_of_each_contributor_in_effect(client, admin_token):
    rows: dict[uuid_lib.UUID, list[dict]] = {}
    module_registry.INSTALLED_MODULES.append(_fake_definition(profile_contributors=(_fake_contributor(rows),)))
    build_registry(force=True)
    try:
        org, token = _setup(client, admin_token, "Profiles Contributor Org")
        profile = _create(client, token, org["id"], "With things")
        rows[uuid_lib.UUID(profile["id"])] = [{"a": 1}, {"a": 2}]
        listing = client.get(BASE.format(org=org["id"]) + "/profiles", headers=auth_headers(token)).json()
        assert listing[0]["contributions"] == [{"key": f"{FAKE_KEY}:things", "name": "Fake things", "count": 2}]

        db = SessionLocal()
        try:
            db.add(OrganizationModuleSubComponentDefault(
                organization_id=uuid_lib.UUID(org["id"]), module_key=FAKE_KEY, subcomponent_key="things", enabled=False,
                default_project_enabled=False,
            ))
            db.commit()
        finally:
            db.close()
        listing = client.get(BASE.format(org=org["id"]) + "/profiles", headers=auth_headers(token)).json()
        assert listing[0]["contributions"] == []  # a kind whose sub-component is off is not listed; its rows are kept
        assert rows[uuid_lib.UUID(profile["id"])] == [{"a": 1}, {"a": 2}]
    finally:
        module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_KEY]
        build_registry(force=True)
