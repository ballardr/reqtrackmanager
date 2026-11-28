"""Tests for traceability rules (`modules.traceability.rules`, `rules_router`, `rule_evaluation`, `rule_fields`): gating and
permissions, validation, the profile and project owners and what resolves for a project (profile tiers, the nested fallback,
hiding and restoring), evaluating a rule against real records and links (scope conditions, groups, counts, untyped and
incoming links, links into an ancestor project), the derived hierarchy, the presets, the audit events, the bundles, that a
project's rule changes never touch how links are created, and that an evaluation's statement count does not grow with the
records."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import event, select

from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.models.project import Project
from app.modules import registry
from app.modules.seams import RuleConditionField
from app.modules.traceability import bundle, rule_evaluation, rule_tree, rules
from app.modules.traceability.enums import TraceabilityState
from app.modules.traceability.models import GovernanceProfile, GovernanceTraceabilityRule
from app.modules.traceability.tests.test_governance_profiles import _choose, _create, _enable, _exempt, _fake_definition
from app.services import definition_suppression
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import ACTION, REQ, World

ORG = "/api/v1/orgs/{org}/modules/traceability"
PROJECT = "/api/v1/projects/{project}/modules/traceability"


def _world(client, admin_token, name) -> World:
    world = World(client, admin_token, name)
    _enable(client, world.token, world.org["id"])
    return world


def _leaf(target=REQ, subtype=None, **extra) -> dict:
    return {"op": "link", "targets": [{"artefact_type": target, "subtype": subtype}], **extra}


def _group(op, *children) -> dict:
    return {"op": op, "children": list(children)}


def _cond(field, operator="equals", value=None) -> dict:
    return {"op": "condition", "field": field, "operator": operator, "value": value}


def _body(name="Rule", *, source=REQ, subtype=None, requires=None, level="informational", **extra) -> dict:
    return {
        "name": name, "source_type": source, "source_subtype": subtype, "level": level,
        "requires": requires or _leaf(subtype="Business Requirement"), **extra,
    }


def _profile_url(org_id, profile_id, suffix="") -> str:
    return ORG.format(org=org_id) + f"/profiles/{profile_id}/rules{suffix}"


def _project_url(project_id, suffix="") -> str:
    return PROJECT.format(project=project_id) + f"/rules{suffix}"


def _add_profile_rule(client, token, org_id, profile_id, body=None, status=201):
    resp = client.post(_profile_url(org_id, profile_id), json=body or _body(), headers=auth_headers(token))
    assert resp.status_code == status, resp.text
    return resp.json()


def _add_rule(client, token, project_id, body=None, status=201):
    resp = client.post(_project_url(project_id), json=body or _body(), headers=auth_headers(token))
    assert resp.status_code == status, resp.text
    return resp.json()


def _rules(client, token, project_id) -> list[dict]:
    resp = client.get(_project_url(project_id), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["rules"]


def _names(client, token, project_id) -> list[str]:
    return [r["name"] for r in _rules(client, token, project_id)]


def _audit(entity_id: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == "governance_traceability_rule", AuditEvent.entity_id == entity_id,
        ).order_by(AuditEvent.created_at)))
    finally:
        db.close()


def _part(client, token, org_id, enabled: bool) -> None:
    resp = client.put(
        ORG.format(org=org_id) + "/subcomponents/traceability_rules", json={"enabled": enabled}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _member(client, token, org_id, project_id, role) -> str:
    email = f"rules_{uuid.uuid4().hex[:8]}@example.com"
    user_id = create_org_user(client, token, org_id, email)
    resp = client.post(f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    return login(client, email, "Password123!")


# --- gating and permissions ----------------------------------------------------------------------


def test_the_routes_are_not_found_while_the_module_or_the_part_is_off(client, admin_token):
    world = World(client, admin_token, "Rules Off Org")
    project = world.project()
    assert client.get(_project_url(project["id"]), headers=auth_headers(world.token)).status_code == 404
    _enable(client, world.token, world.org["id"])
    assert client.get(_project_url(project["id"]), headers=auth_headers(world.token)).status_code == 200
    _part(client, world.token, world.org["id"], False)
    assert client.get(_project_url(project["id"]), headers=auth_headers(world.token)).status_code == 404
    profile = _create(client, world.token, world.org["id"], "P")
    assert client.get(_profile_url(world.org["id"], profile["id"]), headers=auth_headers(world.token)).status_code == 404


def test_switching_rules_off_changes_nothing_about_creating_links(client, admin_token):
    world = _world(client, admin_token, "Rules Links Org")
    project = world.project()
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    derives = world.link_type("Derives", "Is source of")
    first = world.generic_link(project, (REQ, a), derives, (REQ, b))
    assert first.status_code == 201, first.text
    _part(client, world.token, world.org["id"], False)
    c = world.requirement(project, "C")
    assert world.generic_link(project, (REQ, a), derives, (REQ, c)).status_code == 201


def test_a_member_reads_the_rules_but_only_a_traceability_manager_changes_them(client, admin_token):
    world = _world(client, admin_token, "Rules Permission Org")
    project = world.project()
    rule = _add_rule(client, world.token, project["id"])
    member = _member(client, world.token, world.org["id"], project["id"], "stakeholder")
    manager = _member(client, world.token, world.org["id"], project["id"], "project_manager")
    seen = client.get(_project_url(project["id"]), headers=auth_headers(member))
    assert seen.status_code == 200 and seen.json()["can_manage"] is False
    assert seen.json()["rules"][0]["can_edit"] is False
    for call in (
        lambda: client.post(_project_url(project["id"]), json=_body("X"), headers=auth_headers(member)),
        lambda: client.patch(_project_url(project["id"], f"/{rule['id']}"), json={"enabled": False}, headers=auth_headers(member)),
        lambda: client.delete(_project_url(project["id"], f"/{rule['id']}"), headers=auth_headers(member)),
        lambda: client.get(_project_url(project["id"], "/options"), headers=auth_headers(member)),
    ):
        assert call().status_code == 403
    assert client.post(_project_url(project["id"]), json=_body("By manager"), headers=auth_headers(manager)).status_code == 201


def test_only_holders_of_the_organisation_atom_manage_a_profiles_rules(client, admin_token):
    world = _world(client, admin_token, "Rules Org Permission Org")
    profile = _create(client, world.token, world.org["id"], "Mine")
    create_org_user(client, world.token, world.org["id"], "rules_org_member@example.com")
    member = login(client, "rules_org_member@example.com", "Password123!")
    url = _profile_url(world.org["id"], profile["id"])
    assert client.get(url, headers=auth_headers(member)).status_code == 403
    assert client.post(url, json=_body(), headers=auth_headers(member)).status_code == 403
    assert client.get(url, headers=auth_headers(world.token)).status_code == 200


def test_a_profile_of_another_organisation_is_not_found(client, admin_token):
    mine = _world(client, admin_token, "Rules Own Org")
    other = _world(client, admin_token, "Rules Other Org")
    foreign = _create(client, other.token, other.org["id"], "Foreign")
    rule = _add_profile_rule(client, other.token, other.org["id"], foreign["id"])
    url = _profile_url(mine.org["id"], foreign["id"])
    assert client.get(url, headers=auth_headers(mine.token)).status_code == 404
    assert client.post(url, json=_body(), headers=auth_headers(mine.token)).status_code == 404
    assert client.get(url + f"/{rule['id']}", headers=auth_headers(mine.token)).status_code == 404


# --- validation ----------------------------------------------------------------------------------


@pytest.mark.parametrize("body, status, fragment", [
    ({"source": "nonsense"}, 422, "not a record type a rule can apply to"),
    ({"requires": _leaf("nonsense")}, 422, "is not a record type"),
    ({"requires": _group("all")}, 422, "at least one part"),
    ({"requires": _leaf(min=3, max=1)}, 422, "maximum cannot be below"),
    ({"requires": _leaf(link_types={"mode": "types", "ids": [str(uuid.uuid4())]})}, 422, "not available to this rule"),
    ({"applies_when": _cond("mystery", "equals", "x")}, 422, "not a field a rule can test"),
    ({"applies_when": _cond("requirement_type_rank", "equals", 1), "source": "requirement_action"}, 422, "does not apply"),
    ({"applies_when": {"op": "not", "child": _leaf()}}, 422, "scope is a group"),
    ({"level": "mandatory"}, 422, ""),
    ({"name": "   "}, 422, "needs a name"),
])
def test_an_invalid_rule_is_refused_with_the_fault(client, admin_token, body, status, fragment):
    world = _world(client, admin_token, "Rules Validation Org")
    project = world.project()
    payload = _body(**{k: v for k, v in body.items() if k != "source"})
    if "source" in body:
        payload["source_type"] = body["source"]
    if "name" in body:
        payload["name"] = body["name"]
    resp = client.post(_project_url(project["id"]), json=payload, headers=auth_headers(world.token))
    assert resp.status_code == status, resp.text
    assert fragment in json.dumps(resp.json())


def test_a_tree_that_is_too_deep_or_too_large_is_refused(client, admin_token):
    world = _world(client, admin_token, "Rules Limits Org")
    project = world.project()
    deep: dict = _leaf()
    for _ in range(5):
        deep = _group("all", deep)
    assert "nested at most 4" in _add_rule(client, world.token, project["id"], _body(requires=deep), 422)["detail"]
    wide = _group("all", *[_leaf() for _ in range(25)])
    assert "at most 25 parts" in _add_rule(client, world.token, project["id"], _body(requires=wide), 422)["detail"]


def test_a_rule_name_is_unique_among_the_owners_rules_ignoring_case(client, admin_token):
    world = _world(client, admin_token, "Rules Name Org")
    project = world.project()
    other = world.project("Other")
    _add_rule(client, world.token, project["id"], _body("Trace Up"))
    assert "already exists" in _add_rule(client, world.token, project["id"], _body("trace up"), 409)["detail"]
    _add_rule(client, world.token, other["id"], _body("Trace Up"))


def test_a_profile_rule_may_name_only_organisation_wide_link_types(client, admin_token):
    world = _world(client, admin_token, "Rules Local Link Org")
    project = world.project()
    org_type = world.link_type("Org wide", "Reverse")
    local = client.post(
        f"/api/v1/projects/{project['id']}/link-types", json={"forward_name": "Local only", "reverse_name": "Back"},
        headers=auth_headers(world.token),
    )
    assert local.status_code == 201, local.text
    profile = _create(client, world.token, world.org["id"], "P")
    requires = lambda type_id: _leaf(link_types={"mode": "types", "ids": [str(type_id)]})  # noqa: E731
    _add_profile_rule(client, world.token, world.org["id"], profile["id"], _body("Ok", requires=requires(org_type)))
    refused = _add_profile_rule(client, world.token, world.org["id"], profile["id"], _body("No", requires=requires(local.json()["id"])), 422)
    assert "not available to this rule" in refused["detail"]
    _add_rule(client, world.token, project["id"], _body("Project may", requires=requires(local.json()["id"])))


# --- create, change and delete, with audit -------------------------------------------------------


def test_a_rule_is_created_changed_and_deleted_with_an_audit_event_for_each(client, admin_token):
    world = _world(client, admin_token, "Rules Crud Org")
    project = world.project()
    rule = _add_rule(client, world.token, project["id"], _body("First", description="Why", level="warning"))
    assert (rule["source_type_label"], rule["level"], rule["enabled"], rule["problems"]) == ("Requirement", "warning", True, [])
    second = _add_rule(client, world.token, project["id"], _body("Second"))
    assert (rule["sort_order"], second["sort_order"]) == (0, 1)

    changed = client.patch(
        _project_url(project["id"], f"/{rule['id']}"),
        json={"name": "Renamed", "level": "required", "enabled": False, "applies_when": _cond("subtype", "equals", "Project Requirement")},
        headers=auth_headers(world.token),
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["name"], changed.json()["level"], changed.json()["enabled"]) == ("Renamed", "required", False)
    assert changed.json()["applies_when"]["field"] == "subtype"
    cleared = client.patch(_project_url(project["id"], f"/{rule['id']}"), json={"applies_when": None}, headers=auth_headers(world.token))
    assert cleared.json()["applies_when"] is None and cleared.json()["name"] == "Renamed"

    assert client.delete(_project_url(project["id"], f"/{rule['id']}"), headers=auth_headers(world.token)).status_code == 204
    assert _names(client, world.token, project["id"]) == ["Second"]
    events = _audit(rule["id"])
    assert [e.action for e in events] == ["created", "updated", "updated", "deleted"]
    assert events[1].detail is not None and events[1].detail["changed"] == ["applies_when", "enabled", "level", "name"]
    assert "requires" not in json.dumps(events[0].detail)


def test_an_update_that_removes_a_required_field_is_refused(client, admin_token):
    world = _world(client, admin_token, "Rules Required Org")
    project = world.project()
    rule = _add_rule(client, world.token, project["id"])
    for field in ("requires", "name", "level", "source_type", "enabled"):
        resp = client.patch(_project_url(project["id"], f"/{rule['id']}"), json={field: None}, headers=auth_headers(world.token))
        assert resp.status_code == 422, (field, resp.text)
    assert _rules(client, world.token, project["id"])[0]["name"] == "Rule"


def test_only_a_rule_the_project_owns_can_be_changed_or_deleted_through_its_routes(client, admin_token):
    world = _world(client, admin_token, "Rules Own Only Org")
    project = world.project()
    profile = _create(client, world.token, world.org["id"], "Everywhere", mode="enforced")
    from_profile = _add_profile_rule(client, world.token, world.org["id"], profile["id"])
    url = _project_url(project["id"], f"/{from_profile['id']}")
    assert client.patch(url, json={"enabled": False}, headers=auth_headers(world.token)).status_code == 404
    assert client.delete(url, headers=auth_headers(world.token)).status_code == 404


def test_a_stored_rule_whose_type_is_no_longer_available_is_listed_with_a_problem(client, admin_token):
    world = _world(client, admin_token, "Rules Problem Org")
    project = world.project()
    rule = _add_rule(client, world.token, project["id"], _body("Gone soon"))
    db = SessionLocal()
    try:
        row = db.get(GovernanceTraceabilityRule, uuid.UUID(rule["id"]))
        assert row is not None
        row.source_type = "retired_type"
        db.commit()
    finally:
        db.close()
    listed = _rules(client, world.token, project["id"])[0]
    assert listed["problems"] and "retired_type" in listed["problems"][0]
    evaluation = client.get(_project_url(project["id"], f"/{rule['id']}/evaluation"), headers=auth_headers(world.token))
    assert evaluation.status_code == 200 and evaluation.json()["problems"] == ["The record type 'retired_type' is not available."]


# --- what applies to a project -------------------------------------------------------------------


def test_the_rules_of_applicable_profiles_come_first_with_their_source_and_enforcement(client, admin_token):
    world = _world(client, admin_token, "Rules Tiers Org")
    project = world.project()
    enforced = _create(client, world.token, world.org["id"], "A enforced", mode="enforced")
    default = _create(client, world.token, world.org["id"], "B default", mode="default")
    opt_in = _create(client, world.token, world.org["id"], "C opt in", mode="opt_in")
    for profile, name in ((enforced, "Enforced rule"), (default, "Default rule"), (opt_in, "Opt-in rule")):
        _add_profile_rule(client, world.token, world.org["id"], profile["id"], _body(name))
    _add_rule(client, world.token, project["id"], _body("Own rule"))
    assert _names(client, world.token, project["id"]) == ["Enforced rule", "Default rule", "Own rule"]
    _choose(client, world.token, project["id"], opt_in["id"], True)
    listed = _rules(client, world.token, project["id"])
    assert [r["name"] for r in listed] == ["Enforced rule", "Default rule", "Opt-in rule", "Own rule"]
    assert [(r["source"], r["source_name"], r["enforced"]) for r in listed] == [
        ("profile", "A enforced", True), ("profile", "B default", False), ("profile", "C opt in", False), ("project", None, False),
    ]
    assert [(r["can_edit"], r["can_hide"]) for r in listed] == [(False, False), (False, True), (False, True), (True, False)]
    _choose(client, world.token, project["id"], default["id"], False)
    assert "Default rule" not in _names(client, world.token, project["id"])
    _exempt(client, world.token, world.org["id"], enforced["id"], project["id"])
    assert "Enforced rule" not in _names(client, world.token, project["id"])


def test_a_child_follows_the_nearest_ancestors_rules_until_it_has_its_own(client, admin_token):
    world = _world(client, admin_token, "Rules Nested Org")
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    grandchild = world.project("Grandchild", parent=child)
    _add_rule(client, world.token, parent["id"], _body("Parent rule"))
    inherited = _rules(client, world.token, grandchild["id"])
    assert [(r["name"], r["source"], r["source_name"], r["can_edit"]) for r in inherited] == [("Parent rule", "parent_project", "Parent", False)]
    _add_rule(client, world.token, child["id"], _body("Child rule"))
    assert [(r["name"], r["source"]) for r in _rules(client, world.token, grandchild["id"])] == [("Child rule", "parent_project")]
    assert _names(client, world.token, parent["id"]) == ["Parent rule"]
    _add_rule(client, world.token, grandchild["id"], _body("Own"))
    assert [(r["name"], r["source"]) for r in _rules(client, world.token, grandchild["id"])] == [("Own", "project")]


# --- hiding and restoring ------------------------------------------------------------------------


def test_a_project_hides_and_restores_the_rule_of_an_optional_profile(client, admin_token):
    world = _world(client, admin_token, "Rules Hide Org")
    project = world.project()
    default = _create(client, world.token, world.org["id"], "Optional", mode="default")
    rule = _add_profile_rule(client, world.token, world.org["id"], default["id"], _body("Hideable"))
    hidden = client.post(_project_url(project["id"], f"/{rule['id']}/hide"), headers=auth_headers(world.token))
    assert hidden.status_code == 200 and hidden.json()["hidden"] is True
    assert _rules(client, world.token, project["id"])[0]["hidden"] is True
    restored = client.post(_project_url(project["id"], "/restore"), json={"rule_ids": None}, headers=auth_headers(world.token))
    assert restored.status_code == 200 and restored.json()["rules"][0]["hidden"] is False
    assert [e.action for e in _audit(rule["id"])] == ["created", "hidden", "restored"]


def test_a_rule_of_an_enforced_profile_cannot_be_hidden(client, admin_token):
    world = _world(client, admin_token, "Rules Enforced Hide Org")
    project = world.project()
    enforced = _create(client, world.token, world.org["id"], "Binding", mode="enforced")
    rule = _add_profile_rule(client, world.token, world.org["id"], enforced["id"])
    refused = client.post(_project_url(project["id"], f"/{rule['id']}/hide"), headers=auth_headers(world.token))
    assert refused.status_code == 409
    own = _add_rule(client, world.token, project["id"])
    assert client.post(_project_url(project["id"], f"/{own['id']}/hide"), headers=auth_headers(world.token)).status_code == 404
    assert client.post(_project_url(project["id"], f"/{uuid.uuid4()}/hide"), headers=auth_headers(world.token)).status_code == 404


def test_hiding_needs_the_project_atom_and_one_project_hiding_does_not_touch_another(client, admin_token):
    world = _world(client, admin_token, "Rules Hide Scope Org")
    one, two = world.project("One"), world.project("Two")
    default = _create(client, world.token, world.org["id"], "Optional", mode="default")
    rule = _add_profile_rule(client, world.token, world.org["id"], default["id"])
    member = _member(client, world.token, world.org["id"], one["id"], "stakeholder")
    assert client.post(_project_url(one["id"], f"/{rule['id']}/hide"), headers=auth_headers(member)).status_code == 403
    client.post(_project_url(one["id"], f"/{rule['id']}/hide"), headers=auth_headers(world.token))
    assert _rules(client, world.token, two["id"])[0]["hidden"] is False


def test_deleting_a_profile_rule_removes_every_projects_hiding_of_it(client, admin_token):
    world = _world(client, admin_token, "Rules Forget Org")
    project = world.project()
    default = _create(client, world.token, world.org["id"], "Optional", mode="default")
    rule = _add_profile_rule(client, world.token, world.org["id"], default["id"])
    client.post(_project_url(project["id"], f"/{rule['id']}/hide"), headers=auth_headers(world.token))
    assert client.delete(_profile_url(world.org["id"], default["id"], f"/{rule['id']}"), headers=auth_headers(world.token)).status_code == 204
    db = SessionLocal()
    try:
        assert definition_suppression.get_suppressed_ids(db, uuid.UUID(project["id"]), rules.RULE_KIND) == set()
    finally:
        db.close()
    assert _rules(client, world.token, project["id"]) == []


def test_deleting_a_profile_removes_every_projects_hiding_of_its_rules(client, admin_token):
    world = _world(client, admin_token, "Rules Profile Delete Org")
    project = world.project()
    default = _create(client, world.token, world.org["id"], "Optional", mode="default")
    rule = _add_profile_rule(client, world.token, world.org["id"], default["id"])
    client.post(_project_url(project["id"], f"/{rule['id']}/hide"), headers=auth_headers(world.token))
    deleted = client.delete(ORG.format(org=world.org["id"]) + f"/profiles/{default['id']}", headers=auth_headers(world.token))
    assert deleted.status_code == 204, deleted.text
    db = SessionLocal()
    try:
        assert definition_suppression.get_suppressed_ids(db, uuid.UUID(project["id"]), rules.RULE_KIND) == set()
        assert db.get(GovernanceTraceabilityRule, uuid.UUID(rule["id"])) is None
    finally:
        db.close()


# --- evaluating ----------------------------------------------------------------------------------


class Scenario:
    """A project holding requirements of the three default types, with typed links."""

    def __init__(self, client, admin_token, name="Rules Eval Org") -> None:
        self.client = client
        self.world = _world(client, admin_token, name)
        self.project = self.world.project()
        self.types = {
            t["name"]: t["id"]
            for t in client.get(f"/api/v1/projects/{self.project['id']}/requirement-types", headers=auth_headers(self.world.token)).json()
        }
        self.derives = self.world.link_type("Derives", "Is source of")
        self.relates = self.world.link_type("Relates", "Relates back")

    def requirement(self, kind: str, name: str, project: dict | None = None) -> uuid.UUID:
        project = project or self.project
        types = {
            t["name"]: t["id"]
            for t in self.client.get(f"/api/v1/projects/{project['id']}/requirement-types", headers=auth_headers(self.world.token)).json()
        }
        resp = self.client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "component_id": project["component_id"], "category_id": project["category_id"], "type_id": types[kind]},
            headers=auth_headers(self.world.token),
        )
        assert resp.status_code == 201, resp.text
        return uuid.UUID(resp.json()["id"])

    def evaluation(self, rule: dict, project: dict | None = None) -> dict:
        project = project or self.project
        resp = self.client.get(_project_url(project["id"], f"/{rule['id']}/evaluation"), headers=auth_headers(self.world.token))
        assert resp.status_code == 200, resp.text
        return resp.json()


def _derivation(client, scenario: Scenario) -> dict:
    """Three project requirements, two stakeholder requirements and a business requirement, linked P1 to S1 by 'Derives',
    P2 to S1 by 'Relates' and P3 to nothing, plus S1 to B1."""
    s, b = scenario, scenario.requirement("Business Requirement", "B1")
    s1 = scenario.requirement("Stakeholder Requirement", "S1")
    s.requirement("Stakeholder Requirement", "S2")
    p = [scenario.requirement("Project Requirement", f"P{i}") for i in (1, 2, 3)]
    s.world.link((REQ, p[0]), (REQ, s1), s.derives)
    s.world.link((REQ, p[1]), (REQ, s1), s.relates)
    s.world.link((REQ, s1), (REQ, b), s.derives)
    return {"business": b, "stakeholder": s1, "project": p}


def test_a_rule_counts_the_records_it_applies_to_and_those_that_meet_it(client, admin_token):
    scenario = Scenario(client, admin_token)
    _derivation(client, scenario)
    token, pid = scenario.world.token, scenario.project["id"]
    any_link = _add_rule(client, token, pid, _body(
        "Any link", subtype="Project Requirement", requires=_leaf(subtype="Stakeholder Requirement"),
    ))
    assert scenario.evaluation(any_link) == {
        "source_total": 3, "in_scope": 3, "satisfied": 2, "inherited": 0, "excepted": 0, "unsatisfied": 1, "problems": [],
        "leaves": [{"path": "", "label": "Links to Requirement (Stakeholder Requirement)", "met": 2, "inherited": 0, "unmet": 1}],
    }
    derives_only = _add_rule(client, token, pid, _body(
        "Derives only", subtype="Project Requirement",
        requires=_leaf(subtype="Stakeholder Requirement", link_types={"mode": "types", "ids": [str(scenario.derives)]}),
    ))
    assert scenario.evaluation(derives_only)["satisfied"] == 1
    stakeholder = _add_rule(client, token, pid, _body(
        "Stakeholders trace up", subtype="Stakeholder Requirement", requires=_leaf(subtype="Business Requirement"),
    ))
    assert (scenario.evaluation(stakeholder)["in_scope"], scenario.evaluation(stakeholder)["satisfied"]) == (2, 1)


def test_the_applies_when_tree_narrows_the_records_in_scope(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Scope Org")
    _derivation(client, scenario)
    token, pid = scenario.world.token, scenario.project["id"]
    requires = _leaf(subtype="Business Requirement")

    def count(applies_when) -> int:
        rule = _add_rule(client, token, pid, _body(f"Scope {uuid.uuid4().hex[:6]}", requires=requires, applies_when=applies_when))
        return scenario.evaluation(rule)["in_scope"]

    assert count(None) == 6
    assert count(_cond("subtype", "equals", "Project Requirement")) == 3
    assert count(_cond("subtype", "in", ["Project Requirement", "Business Requirement"])) == 4
    assert count({"op": "not", "child": _cond("subtype", "equals", "Project Requirement")}) == 3
    assert count(_cond("requirement_type_rank", "greater_than", 1)) == 5
    assert count(_cond("requirement_type_rank", "less_or_equal", 2)) == 3
    not_project = {"op": "not", "child": _cond("subtype", "equals", "Project Requirement")}
    assert count(_group("all", _cond("requirement_type_rank", "greater_than", 1), not_project)) == 2
    assert count(_group("any", _cond("subtype", "equals", "Business Requirement"), _cond("subtype", "equals", "Project Requirement"))) == 4
    assert count(_cond("status", "equals", "draft")) == 6
    assert count(_cond("status", "equals", "approved")) == 0
    assert count(_cond("requirement_type_rank", "is_set", None)) == 6
    assert count(_cond("component", "is_set", None)) == 6
    assert count(_cond("tag", "is_set", None)) == 0


def test_groups_combine_leaves_with_and_and_or_and_a_maximum_limits_the_count(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Groups Org")
    facts = _derivation(client, scenario)
    token, pid = scenario.world.token, scenario.project["id"]
    scenario.world.link((REQ, facts["project"][0]), (REQ, facts["business"]), scenario.derives)
    to_stakeholder = _leaf(subtype="Stakeholder Requirement")
    to_business = _leaf(subtype="Business Requirement")
    both = _add_rule(client, token, pid, _body("Both", subtype="Project Requirement", requires=_group("all", to_stakeholder, to_business)))
    either = _add_rule(client, token, pid, _body("Either", subtype="Project Requirement", requires=_group("any", to_stakeholder, to_business)))
    assert scenario.evaluation(both)["satisfied"] == 1  # only P1 has both
    assert scenario.evaluation(either)["satisfied"] == 2  # P1 and P2
    result = scenario.evaluation(both)
    assert [(leaf["path"], leaf["met"], leaf["unmet"]) for leaf in result["leaves"]] == [("0", 2, 1), ("1", 1, 2)]
    at_most_none = _add_rule(client, token, pid, _body(
        "No direct business link", subtype="Project Requirement", requires=_leaf(subtype="Business Requirement", min=0, max=0),
    ))
    assert scenario.evaluation(at_most_none)["satisfied"] == 2  # P2 and P3 have none
    at_least_two = _add_rule(client, token, pid, _body("Two", subtype="Project Requirement", requires=_leaf(min=2)))
    assert scenario.evaluation(at_least_two)["satisfied"] == 1  # P1: S1 and B1


def test_a_record_linked_twice_to_one_record_counts_once_and_incoming_links_are_counted(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Incoming Org")
    facts = _derivation(client, scenario)
    token, pid = scenario.world.token, scenario.project["id"]
    scenario.world.link((REQ, facts["project"][0]), (REQ, facts["stakeholder"]), scenario.relates)  # a second link, same pair
    twice = _add_rule(client, token, pid, _body("Min two", subtype="Project Requirement", requires=_leaf(subtype="Stakeholder Requirement", min=2)))
    assert scenario.evaluation(twice)["satisfied"] == 0
    incoming = _add_rule(client, token, pid, _body(
        "Is derived from", subtype="Stakeholder Requirement", requires=_leaf(subtype="Project Requirement", direction="incoming"),
    ))
    assert scenario.evaluation(incoming)["satisfied"] == 1  # S1 is linked from P1 and P2; S2 from none


def test_an_untyped_link_from_an_action_satisfies_an_incoming_untyped_leaf(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Untyped Org")
    facts = _derivation(client, scenario)
    token, pid = scenario.world.token, scenario.project["id"]
    action = scenario.world.action(scenario.project)
    scenario.world.link((ACTION, action), (REQ, facts["project"][0]))
    action_types = client.get(f"/api/v1/projects/{pid}/action-types", headers=auth_headers(token)).json()
    verified = _add_rule(client, token, pid, _body(
        "Verified", subtype="Project Requirement",
        requires=_leaf(ACTION, action_types[0]["name"], direction="incoming", link_types={"mode": "untyped"}),
    ))
    assert scenario.evaluation(verified)["satisfied"] == 1
    typed_only = _add_rule(client, token, pid, _body(
        "Typed only", subtype="Project Requirement",
        requires=_leaf(ACTION, direction="incoming", link_types={"mode": "types", "ids": [str(scenario.derives)]}),
    ))
    assert scenario.evaluation(typed_only)["satisfied"] == 0


def test_a_link_to_an_archived_or_missing_record_does_not_satisfy_a_rule(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Archived Org")
    facts = _derivation(client, scenario)
    token, pid = scenario.world.token, scenario.project["id"]
    rule = _add_rule(client, token, pid, _body("Needs stakeholder", subtype="Project Requirement", requires=_leaf(subtype="Stakeholder Requirement")))
    assert scenario.evaluation(rule)["satisfied"] == 2
    resp = client.delete(f"/api/v1/projects/{pid}/requirements/{facts['stakeholder']}", headers=auth_headers(token))
    assert resp.status_code in (200, 204), resp.text
    assert scenario.evaluation(rule)["satisfied"] == 0


def test_an_evaluation_is_counts_only(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Counts Org")
    _derivation(client, scenario)
    token, pid = scenario.world.token, scenario.project["id"]
    rule = _add_rule(client, token, pid)
    result = scenario.evaluation(rule)
    assert set(result) == {"source_total", "in_scope", "satisfied", "inherited", "excepted", "unsatisfied", "leaves", "problems"}
    assert "P1" not in json.dumps(result)
    member = _member(client, token, scenario.world.org["id"], pid, "stakeholder")
    assert client.get(_project_url(pid, f"/{rule['id']}/evaluation"), headers=auth_headers(member)).status_code == 200


def test_an_evaluation_needs_the_view_permission_on_the_source_type(client, admin_token, monkeypatch):
    from app.modules.traceability import rules_router

    scenario = Scenario(client, admin_token, "Rules View Gate Org")
    token, pid = scenario.world.token, scenario.project["id"]
    rule = _add_rule(client, token, pid)
    monkeypatch.setattr(rules_router, "permission_satisfied", lambda held, wanted: False if wanted.startswith("requirement") else True)
    resp = client.get(_project_url(pid, f"/{rule['id']}/evaluation"), headers=auth_headers(token))
    assert resp.status_code == 403, resp.text


def test_a_condition_may_test_a_record_in_an_ancestor_project_through_a_cross_project_link(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Ancestor Org")
    parent = scenario.world.project("Parent")
    child = scenario.world.project("Child", parent=parent)
    business = scenario.requirement("Business Requirement", "Parent business", parent)
    stakeholder = scenario.requirement("Stakeholder Requirement", "Child stakeholder", child)
    scenario.requirement("Stakeholder Requirement", "Unlinked", child)
    scenario.world.link(
        (REQ, stakeholder), (REQ, business), scenario.derives,
        source_project_id=uuid.UUID(child["id"]), target_project_id=uuid.UUID(parent["id"]),
    )
    requires = rule_tree.parse_requires(_leaf(subtype="Business Requirement"))
    db = SessionLocal()
    try:
        def evaluate(cross: bool):
            return rule_evaluation.evaluate_rule(
                db, uuid.UUID(child["id"]), source_type=REQ, source_subtype="Stakeholder Requirement", applies_when=None,
                requires=requires, include_cross_project=cross,
            )

        assert evaluate(False).count(TraceabilityState.MET) == 0
        crossed = evaluate(True)
        assert (crossed.source_total, len(crossed.in_scope), crossed.count(TraceabilityState.MET)) == (2, 2, 1)
    finally:
        db.close()


def test_the_statements_of_an_evaluation_depend_on_the_rule_and_not_on_the_records(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Flat Org")
    token, pid = scenario.world.token, scenario.project["id"]
    rule = _add_rule(client, token, pid, _body(
        "Flat", subtype="Project Requirement", applies_when=_cond("requirement_type_rank", "greater_than", 1),
        requires=_group(
            "all", _leaf(subtype="Stakeholder Requirement"),
            _group("any", _leaf(subtype="Business Requirement"), _leaf(ACTION, direction="incoming")),
        ),
    ))
    target = scenario.requirement("Stakeholder Requirement", "Target")

    def statements() -> int:
        seen: list[str] = []
        listener = lambda conn, cursor, statement, *args: seen.append(statement)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        db = SessionLocal()
        try:
            row = db.get(GovernanceTraceabilityRule, uuid.UUID(rule["id"]))
            project = db.get(Project, uuid.UUID(pid))
            assert row is not None and project is not None
            result = rules.evaluate(db, project, row)
            return len(seen) if result.source_total >= 0 else -1
        finally:
            event.remove(engine, "before_cursor_execute", listener)
            db.close()

    def add(count: int) -> None:
        for _ in range(count):
            source = scenario.requirement("Project Requirement", f"P{uuid.uuid4().hex[:6]}")
            scenario.world.link((REQ, source), (REQ, target), scenario.derives)

    add(3)
    few = statements()
    add(12)
    many = statements()
    assert few == many, (few, many)


# --- the hierarchy -------------------------------------------------------------------------------


def test_the_hierarchy_is_derived_from_the_active_rules_with_ranks(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Hierarchy Org")
    token, pid = scenario.world.token, scenario.project["id"]
    _add_rule(client, token, pid, _body("Project to stakeholder", subtype="Project Requirement", requires=_leaf(subtype="Stakeholder Requirement")))
    _add_rule(client, token, pid, _body("Stakeholder to business", subtype="Stakeholder Requirement", requires=_leaf(subtype="Business Requirement")))
    off = _add_rule(client, token, pid, _body(
        "Switched off", subtype="Business Requirement", requires=_leaf(subtype="Project Requirement"), enabled=False,
    ))
    verified = _add_rule(client, token, pid, _body(
        "Verified", subtype="Project Requirement", requires=_group("any", _leaf(ACTION, direction="incoming"), _leaf("decision")),
    ))
    resp = client.get(_project_url(pid, "/hierarchy"), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    found = resp.json()
    pairs = {(e["child"]["subtype"] or e["child"]["artefact_type"], e["parent"]["subtype"] or e["parent"]["artefact_type"]) for e in found["edges"]}
    assert ("Project Requirement", "Stakeholder Requirement") in pairs and ("Stakeholder Requirement", "Business Requirement") in pairs
    assert (ACTION, "Project Requirement") in pairs  # an incoming link: the action is the child
    assert ("Project Requirement", "decision") in pairs
    assert all(e["rule_id"] != off["id"] for e in found["edges"])
    assert [(r["subtype"], r["rank"]) for r in found["roots"] if r["artefact_type"] == REQ] == [("Business Requirement", 1)]
    optional = {e["rule_id"]: e["optional"] for e in found["edges"] if e["rule_id"] == verified["id"]}
    assert optional == {verified["id"]: True}
    assert all(e["rank_conflict"] is False for e in found["edges"])


def test_a_link_from_a_higher_ranked_type_to_a_lower_ranked_one_is_flagged(client, admin_token):
    scenario = Scenario(client, admin_token, "Rules Rank Conflict Org")
    token, pid = scenario.world.token, scenario.project["id"]
    _add_rule(client, token, pid, _body("Backwards", subtype="Business Requirement", requires=_leaf(subtype="Project Requirement")))
    edge = client.get(_project_url(pid, "/hierarchy"), headers=auth_headers(token)).json()["edges"][0]
    assert edge["rank_conflict"] is True


def test_a_rule_hidden_in_a_project_is_not_in_its_hierarchy(client, admin_token):
    world = _world(client, admin_token, "Rules Hierarchy Hidden Org")
    project = world.project()
    default = _create(client, world.token, world.org["id"], "Optional", mode="default")
    rule = _add_profile_rule(client, world.token, world.org["id"], default["id"], _body("From profile", subtype="Project Requirement"))
    assert len(client.get(_project_url(project["id"], "/hierarchy"), headers=auth_headers(world.token)).json()["edges"]) == 1
    client.post(_project_url(project["id"], f"/{rule['id']}/hide"), headers=auth_headers(world.token))
    assert client.get(_project_url(project["id"], "/hierarchy"), headers=auth_headers(world.token)).json()["edges"] == []


# --- options and presets -------------------------------------------------------------------------


def test_the_editor_options_list_types_fields_link_types_levels_and_presets(client, admin_token):
    world = _world(client, admin_token, "Rules Options Org")
    project = world.project()
    link_type = world.link_type("Option link", "Back")
    options = client.get(_project_url(project["id"], "/options"), headers=auth_headers(world.token)).json()
    by_type = {t["artefact_type"]: t for t in options["types"]}
    assert "Project Requirement" in by_type[REQ]["subtypes"] and by_type[REQ]["can_be_source"] is True
    assert {f["key"] for f in options["fields"]} >= {"subtype", "requirement_type_rank", "component", "category", "tag", "status"}
    rank = next(f for f in options["fields"] if f["key"] == "requirement_type_rank")
    assert rank["value_kind"] == "number" and rank["artefact_types"] == [REQ] and "greater_than" in rank["operators"]
    assert str(link_type) in {t["id"] for t in options["link_types"]}
    assert options["levels"] == ["informational", "warning", "required"]
    assert [p["key"] for p in options["presets"]] == ["none", "type", "type_or_alternative"]
    assert (options["max_depth"], options["max_nodes"]) == (rule_tree.MAX_DEPTH, rule_tree.MAX_NODES)
    org_options = client.get(ORG.format(org=world.org["id"]) + "/rules/options", headers=auth_headers(world.token)).json()
    assert "Project Requirement" in {s for t in org_options["types"] if t["artefact_type"] == REQ for s in t["subtypes"]}


def test_a_preset_builds_a_tree_the_rule_endpoint_accepts(client, admin_token):
    world = _world(client, admin_token, "Rules Presets Org")
    project = world.project()
    url = _project_url(project["id"], "/presets/type_or_alternative")
    choices = {"target_type": REQ, "target_subtype": "Business Requirement", "alternative_type": "decision"}
    built = client.post(url, json=choices, headers=auth_headers(world.token))
    assert built.status_code == 200, built.text
    tree = built.json()["requires"]
    assert tree["op"] == "any" and len(tree["children"]) == 2
    assert _add_rule(client, world.token, project["id"], _body("From preset", requires=tree))["requires"]["op"] == "any"
    nothing = client.post(_project_url(project["id"], "/presets/none"), json={}, headers=auth_headers(world.token))
    assert nothing.json() == {"requires": None}
    assert client.post(_project_url(project["id"], "/presets/type"), json={}, headers=auth_headers(world.token)).status_code == 422
    assert client.post(_project_url(project["id"], "/presets/nope"), json={"target_type": REQ}, headers=auth_headers(world.token)).status_code == 422
    org_preset = client.post(
        ORG.format(org=world.org["id"]) + "/rules/presets/type", json={"target_type": REQ}, headers=auth_headers(world.token),
    )
    assert org_preset.status_code == 200


# --- a module registers a condition field --------------------------------------------------------


def test_a_registered_condition_field_can_be_tested_by_a_rule(client, admin_token, monkeypatch):
    scenario = Scenario(client, admin_token, "Rules Field Org")
    _derivation(client, scenario)
    odd = RuleConditionField(
        key="odd_name", label="Odd name", value_kind="text",
        values=lambda db, project_id, artefact_type, ids: {i: ["odd"] for i in ids if i.int % 2 == 1}, artefact_types=(REQ,),
    )
    original = registry.get_rule_condition_fields
    monkeypatch.setattr(registry, "get_rule_condition_fields", lambda: {**original(), "odd_name": ("fake", odd)})
    token, pid = scenario.world.token, scenario.project["id"]
    rule = _add_rule(client, token, pid, _body("Odd", applies_when=_cond("odd_name", "equals", "odd")))
    db = SessionLocal()
    try:
        from app.models.requirement import Requirement

        expected = sum(1 for i in db.scalars(select(Requirement.id).where(Requirement.project_id == uuid.UUID(pid))) if i.int % 2 == 1)
    finally:
        db.close()
    assert scenario.evaluation(rule)["in_scope"] == expected
    monkeypatch.setattr(registry, "get_rule_condition_fields", original)
    assert scenario.evaluation(rule)["problems"] == ["The condition field 'odd_name' is not available."]


def test_a_module_cannot_register_the_same_condition_field_twice():
    field = RuleConditionField(key="dup", label="Dup", value_kind="text", values=lambda *_a: {})
    with pytest.raises(ValueError, match="duplicate rule condition field"):
        _fake_definition().__class__(
            key="fake_dup_fields", name="Dup", description="Fixture.", version="0.0.1", default_enabled=True, implemented=False,
            get_router=lambda: None, no_org_bundle="Fixture.", no_project_bundle="Fixture.", rule_condition_fields=(field, field),
        )


# --- bundles -------------------------------------------------------------------------------------


def _export_project(client, token, project_id) -> bytes:
    exported = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    return exported.content


def test_a_projects_own_rules_and_hidden_rules_travel_in_its_bundle(client, admin_token):
    world = _world(client, admin_token, "Rules Bundle Org")
    project = world.project()
    link_type = world.link_type("Bundled", "Back")
    own = _add_rule(client, world.token, project["id"], _body(
        "Own", subtype="Project Requirement", level="required", description="Why",
        applies_when=_cond("tag", "equals", "safety"),
        requires=_group(
            "all",
            _leaf(subtype="Business Requirement", link_types={"mode": "types", "ids": [str(link_type)]}, min=2),
            _leaf(ACTION, direction="incoming"),
        ),
    ))
    default = _create(client, world.token, world.org["id"], "Optional", mode="default")
    from_profile = _add_profile_rule(client, world.token, world.org["id"], default["id"], _body("Profile rule"))
    client.post(_project_url(project["id"], f"/{from_profile['id']}/hide"), headers=auth_headers(world.token))

    content = _export_project(client, world.token, project["id"])
    data = json.loads(zipfile.ZipFile(io.BytesIO(content)).read("project.json"))
    assert [r["name"] for r in data[bundle.RULES_KEY]] == ["Own"]
    exported_requires = data[bundle.RULES_KEY][0]["requires"]
    bundled_name = next(name for name in world.link_types_by_name() if name.startswith("Bundled"))
    assert exported_requires["children"][0]["link_types"] == {"mode": "types", "ids": [bundled_name]}
    assert data[bundle.HIDDEN_RULES_KEY] == [{"profile": "Optional", "rule": "Profile rule"}]

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Copy"},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=auth_headers(world.token),
    )
    assert imported.status_code == 201, imported.text
    copy_id = imported.json()["project"]["id"]
    listed = _rules(client, world.token, copy_id)
    copied = next(r for r in listed if r["source"] == "project")
    assert (copied["name"], copied["level"], copied["description"], copied["source_subtype"]) == ("Own", "required", "Why", "Project Requirement")
    assert copied["requires"]["children"][0]["link_types"]["ids"] == [str(link_type)]
    assert copied["applies_when"]["value"] == "safety" and own["id"] != copied["id"]
    assert next(r for r in listed if r["source"] == "profile")["hidden"] is True


def test_a_rule_naming_a_link_type_the_organisation_lacks_is_reported_and_not_imported(client, admin_token):
    world = _world(client, admin_token, "Rules Missing Link Org")
    project = world.project()
    warnings: list[str] = []
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        assert row is not None
        rules.import_project_rows(db, row, [
            {"name": "Lost", "source_type": REQ, "level": "required", "requires": _leaf(link_types={"mode": "types", "ids": ["No such link type"]})},
            {"name": "Fine", "source_type": REQ, "level": "warning", "requires": _leaf()},
            {"name": "Odd level", "source_type": REQ, "level": "mandatory", "requires": _leaf()},
            {"name": "Odd type", "source_type": "nonsense", "level": "warning", "requires": _leaf()},
        ], warnings.append)
        db.flush()
        assert [r.name for r in rules.own_rules(db, row.id)] == ["Fine"]
    finally:
        db.rollback()
        db.close()
    assert len(warnings) == 3
    assert "No such link type" in warnings[0] and "enforcement level" in warnings[1] and "not a record type" in warnings[2]


def test_a_profiles_rules_travel_in_the_organisation_bundle(client, admin_token):
    world = _world(client, admin_token, "Rules Org Bundle Org")
    seeded = next(iter(world.link_types_by_name().values()))
    custom = world.link_type("Org custom", "Back")
    profile = _create(client, world.token, world.org["id"], "Regulated")
    _add_profile_rule(client, world.token, world.org["id"], profile["id"], _body(
        "Trace up", subtype="Project Requirement", level="required",
        requires=_leaf(subtype="Stakeholder Requirement", link_types={"mode": "types", "ids": [seeded["id"]]}),
    ))
    _add_profile_rule(client, world.token, world.org["id"], profile["id"], _body(
        "Custom link", requires=_leaf(link_types={"mode": "types", "ids": [str(custom)]}),
    ))
    exported = client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=auth_headers(world.token))
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("org.json"))
    entry = next(e for e in data["governance_profiles"] if e["name"] == "Regulated")
    exported_rules = entry["contributions"]["traceability:traceability_rules"]
    assert [r["name"] for r in exported_rules] == ["Trace up", "Custom link"] and exported_rules[0]["kind"] == "traceability_rules"
    assert exported_rules[0]["requires"]["link_types"]["ids"] == [seeded["forward_name"]]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Rules Org Bundle Imported Org"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code in (200, 201), imported.text
    # The bundle carries no custom link types, so the rule that names one is reported and left out.
    assert any("'Custom link' was not imported" in w and "Org custom" in w for w in imported.json()["warnings"])
    new_org = uuid.UUID(imported.json()["organization"]["id"])
    db = SessionLocal()
    try:
        new_profile = db.scalars(select(GovernanceProfile).where(
            GovernanceProfile.organization_id == new_org, GovernanceProfile.name == "Regulated",
        )).one()
        stored = rules.profile_rules(db, new_profile.id)
        assert [(r.name, r.level, r.source_subtype) for r in stored] == [("Trace up", "required", "Project Requirement")]
        names = rules._link_type_names(db, rules._link_type_ids_in(stored[0].requires))
        assert list(names.values()) == [seeded["forward_name"]]
    finally:
        db.close()


def test_rules_are_template_configuration():
    from app.modules.registry import get_module

    module = get_module("traceability")
    assert module is not None and module.project_bundle_hooks is not None
    assert {bundle.RULES_KEY, bundle.HIDDEN_RULES_KEY} <= set(module.project_bundle_hooks.template_configuration_keys)
