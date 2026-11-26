"""
Tests for lifecycle configuration (`services.lifecycles`, `routers.lifecycles`): the pure move rule over every
registered definition, the project and organisation settings, enforcement on a record's own transitions, nested
projects, exemptions, permissions and the audit trail.
"""

from __future__ import annotations

import itertools

import pytest

from app.models.audit import AuditEvent
from app.modules.registry import get_lifecycles
from app.services.lifecycles import effective_moves, table_from_enum, validate_definition
from tests.conftest import SessionLocal, auth_headers, create_org_admin_in, create_org_user, create_project, login

PP = "/modules/context_strategy/pain-points"
_PAIN_POINT_FIELDS = {
    "title": "Slow export", "description": "The export takes minutes.", "priority": "medium",
    "business_impact": "Delays reporting.",
}


# --- the pure rule -----------------------------------------------------------------------------


@pytest.mark.parametrize("artefact_type", sorted(get_lifecycles()))
def test_every_registered_definition_is_valid(artefact_type):
    _, definition = get_lifecycles()[artefact_type]
    assert validate_definition(definition) == []


@pytest.mark.parametrize("artefact_type", sorted(get_lifecycles()))
def test_moves_with_every_subset_of_optional_states_off(artefact_type):
    """A turned-off state is never a target, a record in one still moves on, and every state keeps a way forward."""
    _, definition = get_lifecycles()[artefact_type]
    optional = definition.optional
    for size in range(len(optional) + 1):
        for off in itertools.combinations(optional, size):
            for state, base_next in definition.transitions.items():
                moves = effective_moves(definition, off, state)
                assert not set(moves) & set(off), (state, off)
                assert state not in moves
                # Every move is reachable through only turned-off states from a base move.
                for target, skipped in moves.items():
                    assert set(skipped) <= set(off)
                    assert target in {n for ns in definition.transitions.values() for n in ns}
                # An empty off set changes nothing.
                if not off:
                    assert set(moves) == set(base_next) - {state}
                    assert all(s == () for s in moves.values())
            # The end of the path stays reachable from the start.
            reachable, frontier = {definition.path[0]}, [definition.path[0]]
            while frontier:
                for nxt in effective_moves(definition, off, frontier.pop()):
                    if nxt not in reachable:
                        reachable.add(nxt)
                        frontier.append(nxt)
            assert definition.path[-1] in reachable or definition.path[-1] in off


def test_moves_step_over_a_turned_off_state_and_name_it():
    _, definition = get_lifecycles()["pain_point"]
    assert effective_moves(definition, set(), "submitted") == {"triaged": ()}
    moves = effective_moves(definition, {"triaged"}, "submitted")
    assert moves == {"accepted": ("triaged",), "rejected": ("triaged",), "duplicate": ("triaged",)}


def test_a_record_parked_in_a_turned_off_state_still_moves_on():
    _, definition = get_lifecycles()["pain_point"]
    assert "accepted" in effective_moves(definition, {"triaged"}, "triaged")


def test_two_adjacent_states_off_are_both_stepped_over():
    _, definition = get_lifecycles()["decision"]
    assert effective_moves(definition, {"proposed", "under_review"}, "draft")["approved"] == ("proposed", "under_review")


def test_table_from_enum_keeps_every_state():
    from app.modules.decisions.enums import DecisionStatus

    table = table_from_enum({DecisionStatus.DRAFT: {DecisionStatus.PROPOSED}, DecisionStatus.PROPOSED: set()})
    assert table == {"draft": frozenset({"proposed"}), "proposed": frozenset()}


# --- fixtures and helpers ------------------------------------------------------------------------


def _enable(client, token, org_id, *modules: str) -> None:
    for key in modules:
        resp = client.put(f"/api/v1/orgs/{org_id}/modules/{key}", json={"enabled": True}, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text


def _setup(client, admin_token, name: str, *modules: str, can_be_parent: bool = False):
    org, token = create_org_admin_in(client, admin_token, name)
    _enable(client, token, org["id"], *(modules or ("context_strategy",)))
    project = create_project(client, token, org["id"], f"{name} project", can_be_parent=can_be_parent or None)
    return org, project, token


def _project_role(client, org_admin_token, org_id, project_id, email, role) -> str:
    user_id = create_org_user(client, org_admin_token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text
    return login(client, email, "Password123!")


def _put_project(client, token, project_id, artefact_type, disabled):
    return client.put(
        f"/api/v1/projects/{project_id}/lifecycles/{artefact_type}", json={"disabled_states": disabled},
        headers=auth_headers(token),
    )


def _get_project(client, token, project_id) -> dict:
    resp = client.get(f"/api/v1/projects/{project_id}/lifecycles", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _entry(payload: dict, artefact_type: str) -> dict:
    return next(x for x in payload["lifecycles"] if x["artefact_type"] == artefact_type)


def _pain_point(client, token, project_id) -> str:
    types = client.get(f"/api/v1/projects/{project_id}/modules/context_strategy/pain-point-types", headers=auth_headers(token))
    assert types.status_code == 200, types.text
    resp = client.post(
        f"/api/v1/projects/{project_id}/modules/context_strategy/pain-points",
        json={**_PAIN_POINT_FIELDS, "pain_point_type_id": types.json()[0]["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _post_pp(client, token, project_id, pain_point_id, action, **body):
    return client.post(
        f"/api/v1/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/{action}",
        json=body, headers=auth_headers(token),
    )


def _set_required(client, token, org_id, artefact_type, states):
    return client.put(
        f"/api/v1/orgs/{org_id}/lifecycles/{artefact_type}", json={"required_states": states}, headers=auth_headers(token)
    )


# --- project settings ----------------------------------------------------------------------------


def test_default_project_uses_every_state(client, admin_token):
    _, project, token = _setup(client, admin_token, "Lifecycle Default Co")
    payload = _get_project(client, token, project["id"])
    entry = _entry(payload, "pain_point")
    assert entry["disabled"] == [] and entry["own_disabled"] is None and entry["source"] == "default"
    assert entry["transitions"]["submitted"] == ["triaged"]
    assert [s["key"] for s in entry["path"]][:2] == ["submitted", "triaged"]
    assert {s["key"] for s in entry["off_path"]} == {"rejected", "duplicate"}
    assert payload["can_manage"] is True


def test_a_module_the_project_cannot_use_is_left_out(client, admin_token):
    _, project, token = _setup(client, admin_token, "Lifecycle Module Gate Co")
    types = {x["artefact_type"] for x in _get_project(client, token, project["id"])["lifecycles"]}
    assert "pain_point" in types and "decision" not in types and "risk" not in types


def test_turning_a_state_off_lets_a_pain_point_skip_it(client, admin_token):
    _, project, token = _setup(client, admin_token, "Lifecycle Skip Co")
    pain_point = _pain_point(client, token, project["id"])
    assert _post_pp(client, token, project["id"], pain_point, "accept").status_code == 409

    resp = _put_project(client, token, project["id"], "pain_point", ["triaged"])
    assert resp.status_code == 200, resp.text
    entry = _entry(resp.json(), "pain_point")
    assert entry["disabled"] == ["triaged"] and entry["own_disabled"] == ["triaged"]
    assert set(entry["transitions"]["submitted"]) == {"accepted", "rejected", "duplicate"}

    triage = _post_pp(client, token, project["id"], pain_point, "triage")
    assert triage.status_code == 409 and "turned off" in triage.json()["detail"]
    accepted = _post_pp(client, token, project["id"], pain_point, "accept")
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"


def test_turning_a_state_back_on_restores_the_path(client, admin_token):
    _, project, token = _setup(client, admin_token, "Lifecycle Restore Co")
    _put_project(client, token, project["id"], "pain_point", ["triaged"])
    resp = _put_project(client, token, project["id"], "pain_point", [])
    assert _entry(resp.json(), "pain_point")["disabled"] == []
    pain_point = _pain_point(client, token, project["id"])
    assert _post_pp(client, token, project["id"], pain_point, "accept").status_code == 409


def test_a_record_in_a_state_later_turned_off_can_still_move_on(client, admin_token):
    _, project, token = _setup(client, admin_token, "Lifecycle Parked Co")
    pain_point = _pain_point(client, token, project["id"])
    assert _post_pp(client, token, project["id"], pain_point, "triage").status_code == 200
    _put_project(client, token, project["id"], "pain_point", ["triaged"])
    assert _post_pp(client, token, project["id"], pain_point, "accept").status_code == 200


def test_a_state_that_is_not_optional_is_refused(client, admin_token):
    _, project, token = _setup(client, admin_token, "Lifecycle Not Optional Co")
    assert _put_project(client, token, project["id"], "pain_point", ["accepted"]).status_code == 422
    assert _put_project(client, token, project["id"], "pain_point", ["submitted"]).status_code == 422
    assert _put_project(client, token, project["id"], "nonsense", []).status_code == 404


def test_only_project_administrators_may_change_it(client, admin_token):
    org, project, token = _setup(client, admin_token, "Lifecycle Permission Co")
    manager = _project_role(client, token, org["id"], project["id"], "lc-manager@example.com", "project_manager")
    member = _project_role(client, token, org["id"], project["id"], "lc-member@example.com", "member")
    administrator = _project_role(
        client, token, org["id"], project["id"], "lc-admin@example.com", "project_administrator"
    )
    assert _put_project(client, member, project["id"], "pain_point", ["triaged"]).status_code == 403
    assert _put_project(client, administrator, project["id"], "pain_point", ["triaged"]).status_code == 200
    # A project manager holds the administrator role too, so it may change the setting as well.
    assert _put_project(client, manager, project["id"], "pain_point", ["triaged"]).status_code == 200
    assert _get_project(client, member, project["id"])["can_manage"] is False
    assert _entry(_get_project(client, member, project["id"]), "pain_point")["disabled"] == ["triaged"]


def test_the_change_is_audited_with_keys_only(client, admin_token):
    _, project, token = _setup(client, admin_token, "Lifecycle Audit Co")
    _put_project(client, token, project["id"], "pain_point", ["triaged"])
    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(
            AuditEvent.entity_type == "lifecycle_settings", AuditEvent.project_id == project["id"]
        ).one()
        assert event.action == "updated"
        assert event.detail == {"artefact_type": "pain_point", "disabled_states": ["triaged"], "inherits": False}
    finally:
        db.close()


# --- nested projects -----------------------------------------------------------------------------


def test_a_child_without_a_choice_uses_its_nearest_ancestors(client, admin_token):
    org, parent, token = _setup(client, admin_token, "Lifecycle Nested Co", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    _put_project(client, token, parent["id"], "pain_point", ["triaged"])
    entry = _entry(_get_project(client, token, child["id"]), "pain_point")
    assert entry["disabled"] == ["triaged"] and entry["source"] == "parent_project" and entry["own_disabled"] is None

    # An own choice, even an empty one, ends the inheritance.
    _put_project(client, token, child["id"], "pain_point", [])
    entry = _entry(_get_project(client, token, child["id"]), "pain_point")
    assert entry["disabled"] == [] and entry["source"] == "project"

    # `null` follows the ancestor again.
    resp = _put_project(client, token, child["id"], "pain_point", None)
    assert _entry(resp.json(), "pain_point")["disabled"] == ["triaged"]


# --- organisation requirement and exemption -------------------------------------------------------


def test_an_organisation_requirement_locks_the_state_for_every_project(client, admin_token):
    org, project, token = _setup(client, admin_token, "Lifecycle Required Co", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=project["id"])
    pain_point = _pain_point(client, token, project["id"])
    _put_project(client, token, project["id"], "pain_point", ["triaged"])

    assert _set_required(client, token, org["id"], "pain_point", ["triaged"]).status_code == 200
    entry = _entry(_get_project(client, token, project["id"]), "pain_point")
    # The project's stored choice is kept but no longer applies.
    assert entry["required"] == ["triaged"] and entry["disabled"] == [] and entry["own_disabled"] == ["triaged"]
    assert _entry(_get_project(client, token, child["id"]), "pain_point")["required"] == ["triaged"]
    assert _post_pp(client, token, project["id"], pain_point, "accept").status_code == 409

    refused = _put_project(client, token, project["id"], "pain_point", ["triaged"])
    assert refused.status_code == 409 and "requires" in refused.json()["detail"]

    # Removing the requirement gives the project's own choice back.
    _set_required(client, token, org["id"], "pain_point", [])
    assert _entry(_get_project(client, token, project["id"]), "pain_point")["disabled"] == ["triaged"]


def test_an_exempt_project_may_turn_the_required_state_off(client, admin_token):
    org, project, token = _setup(client, admin_token, "Lifecycle Exempt Co")
    other = create_project(client, token, org["id"], "Other")
    _set_required(client, token, org["id"], "pain_point", ["triaged"])
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/lifecycles/pain_point/exemptions",
        json={"project_id": project["id"], "include_children": False}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    entry = next(x for x in resp.json() if x["artefact_type"] == "pain_point")
    assert entry["exemptions"][0]["project_id"] == project["id"] and entry["required"] == ["triaged"]

    assert _put_project(client, token, project["id"], "pain_point", ["triaged"]).status_code == 200
    assert _entry(_get_project(client, token, project["id"]), "pain_point")["exempt"] is True
    assert _put_project(client, token, other["id"], "pain_point", ["triaged"]).status_code == 409

    gone = client.delete(
        f"/api/v1/orgs/{org['id']}/lifecycles/pain_point/exemptions/{project['id']}", headers=auth_headers(token)
    )
    assert gone.status_code == 200
    # The stored choice stays but the requirement binds again.
    assert _entry(_get_project(client, token, project["id"]), "pain_point")["disabled"] == []


def test_an_exemption_covers_children_only_when_asked(client, admin_token):
    org, parent, token = _setup(client, admin_token, "Lifecycle Exempt Children Co", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    _set_required(client, token, org["id"], "pain_point", ["triaged"])
    url = f"/api/v1/orgs/{org['id']}/lifecycles/pain_point/exemptions"
    client.post(url, json={"project_id": parent["id"], "include_children": False}, headers=auth_headers(token))
    assert _entry(_get_project(client, token, child["id"]), "pain_point")["exempt"] is False
    client.post(url, json={"project_id": parent["id"], "include_children": True}, headers=auth_headers(token))
    assert _entry(_get_project(client, token, child["id"]), "pain_point")["exempt"] is True
    assert _entry(_get_project(client, token, parent["id"]), "pain_point")["exempt"] is True


def test_organisation_endpoints_validate_and_reach_only_their_own_organisation(client, admin_token):
    org, project, token = _setup(client, admin_token, "Lifecycle Org Rules Co")
    other_org, other_project, other_token = _setup(client, admin_token, "Lifecycle Other Org Co")
    assert _set_required(client, token, org["id"], "pain_point", ["accepted"]).status_code == 422
    assert _set_required(client, token, org["id"], "unknown", []).status_code == 404
    url = f"/api/v1/orgs/{org['id']}/lifecycles/pain_point/exemptions"
    foreign = client.post(url, json={"project_id": other_project["id"]}, headers=auth_headers(token))
    assert foreign.status_code == 404
    assert client.get(f"/api/v1/orgs/{org['id']}/lifecycles", headers=auth_headers(other_token)).status_code in (403, 404)
    listing = client.get(f"/api/v1/orgs/{org['id']}/lifecycles", headers=auth_headers(token))
    assert listing.status_code == 200
    assert {x["artefact_type"] for x in listing.json()} == {
            "requirement", "pain_point", "open_question", "strategy", "future_state", "guiding_principle",
            "project_stage", "component_stage",
        }
    assert other_org["id"] != org["id"]


def test_organisation_settings_need_the_organisation_permission(client, admin_token):
    org, project, token = _setup(client, admin_token, "Lifecycle Org Permission Co")
    administrator = _project_role(
        client, token, org["id"], project["id"], "lc-org-admin@example.com", "project_administrator"
    )
    assert client.get(f"/api/v1/orgs/{org['id']}/lifecycles", headers=auth_headers(administrator)).status_code == 403
    assert _set_required(client, administrator, org["id"], "pain_point", ["triaged"]).status_code == 403


def test_required_state_changes_are_audited(client, admin_token):
    org, _, token = _setup(client, admin_token, "Lifecycle Org Audit Co")
    _set_required(client, token, org["id"], "pain_point", ["triaged"])
    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(
            AuditEvent.entity_type == "lifecycle_settings", AuditEvent.organization_id == org["id"]
        ).one()
        assert event.detail == {"artefact_type": "pain_point", "required_states": ["triaged"]}
    finally:
        db.close()


# --- other types ---------------------------------------------------------------------------------


def test_a_decision_goes_from_draft_to_approved_behind_the_approver(client, admin_token):
    org, project, token = _setup(client, admin_token, "Lifecycle Decision Co", "decisions")
    base = f"/api/v1/projects/{project['id']}/modules/decisions"
    types = client.get(f"{base}/decision-types", headers=auth_headers(token)).json()
    decision = client.post(
        base, json={"title": "Use Postgres", "decision_statement": "We will.", "decision_type_id": types[0]["id"]},
        headers=auth_headers(token),
    ).json()
    approve = f"{base}/{decision['id']}/approve"
    assert client.post(approve, json={}, headers=auth_headers(token)).status_code == 409

    assert _put_project(client, token, project["id"], "decision", ["proposed", "under_review"]).status_code == 200
    member = _project_role(client, token, org["id"], project["id"], "lc-decision-member@example.com", "member")
    assert client.post(approve, json={}, headers=auth_headers(member)).status_code == 403
    assert client.post(f"{base}/{decision['id']}/propose", headers=auth_headers(token)).status_code == 409
    approved = client.post(approve, json={}, headers=auth_headers(token))
    assert approved.status_code == 200 and approved.json()["status"] == "approved"


def test_a_skipped_risk_state_still_applies_its_checks(client, admin_token):
    _, project, token = _setup(client, admin_token, "Lifecycle Risk Co", "risk_management")
    _put_project(client, token, project["id"], "risk", ["treatment_planned", "treatment_in_progress"])
    entry = _entry(_get_project(client, token, project["id"]), "risk")
    assert "mitigated" in entry["transitions"]["assessed"]
    assert "treatment_planned" not in entry["transitions"]["assessed"]


# --- bundles and templates -----------------------------------------------------------------------


def test_project_bundle_round_trip_keeps_the_choice(client, admin_token):
    org, project, token = _setup(client, admin_token, "Lifecycle Bundle Co")
    _put_project(client, token, project["id"], "pain_point", ["triaged"])
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert export.status_code == 200
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Imported lifecycle project"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    entry = _entry(_get_project(client, token, new_id), "pain_point")
    assert entry["own_disabled"] == ["triaged"] and entry["disabled"] == ["triaged"]


def test_an_imported_choice_never_turns_off_a_required_state(client, admin_token):
    org, project, token = _setup(client, admin_token, "Lifecycle Bundle Required Co")
    _put_project(client, token, project["id"], "pain_point", ["triaged"])
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    _set_required(client, token, org["id"], "pain_point", ["triaged"])
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Imported under requirement"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    entry = _entry(_get_project(client, token, imported.json()["project"]["id"]), "pain_point")
    assert entry["disabled"] == [] and entry["required"] == ["triaged"]


def test_a_bundle_state_that_cannot_be_turned_off_is_skipped_with_a_warning(client, admin_token):
    import io
    import json
    import zipfile

    org, project, token = _setup(client, admin_token, "Lifecycle Bundle Warn Co")
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    source = zipfile.ZipFile(io.BytesIO(export.content))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for name in source.namelist():
            data = source.read(name)
            if name == "project.json":
                body = json.loads(data)
                body["lifecycles"] = [
                    {"artefact_type": "pain_point", "disabled_states": ["accepted", "triaged"]},
                    {"artefact_type": "no_such_type", "disabled_states": []},
                ]
                data = json.dumps(body).encode()
            out.writestr(name, data)
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Imported with warnings"},
        files={"file": ("bundle.zip", buffer.getvalue(), "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    warnings = " ".join(imported.json().get("warnings", []))
    assert "cannot be turned off" in warnings and "unknown record type" in warnings
    entry = _entry(_get_project(client, token, imported.json()["project"]["id"]), "pain_point")
    assert entry["disabled"] == ["triaged"]


def test_a_project_made_from_a_template_passes_the_choice_on(client, admin_token):
    org, template, token = _setup(client, admin_token, "Lifecycle Template Co")
    _put_project(client, token, template["id"], "pain_point", ["triaged"])
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(token))
    created = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "From template", "summary": "", "template_project_id": template["id"]},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    assert _entry(_get_project(client, token, created.json()["id"]), "pain_point")["disabled"] == ["triaged"]


def test_organisation_bundle_round_trip_keeps_requirements_and_exemptions(client, admin_token):
    from app.models.lifecycle import OrganizationLifecycleExemption, OrganizationLifecycleRequirement

    org, project, token = _setup(client, admin_token, "Lifecycle Org Bundle Co")
    _set_required(client, token, org["id"], "pain_point", ["triaged"])
    client.post(
        f"/api/v1/orgs/{org['id']}/lifecycles/pain_point/exemptions",
        json={"project_id": project["id"], "include_children": True}, headers=auth_headers(token),
    )
    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert export.status_code == 200, export.text
    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Lifecycle Org Copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org_id = imported.json()["organization"]["id"]
    db = SessionLocal()
    try:
        requirements = db.query(OrganizationLifecycleRequirement).filter_by(organization_id=new_org_id).all()
        assert [(r.artefact_type, r.state) for r in requirements] == [("pain_point", "triaged")]
        exemptions = db.query(OrganizationLifecycleExemption).filter_by(organization_id=new_org_id).all()
        assert len(exemptions) == 1 and exemptions[0].include_children is True
        assert str(exemptions[0].project_id) != project["id"]
    finally:
        db.close()
