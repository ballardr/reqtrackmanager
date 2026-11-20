"""Record code prefixes: an organisation or a project chooses the prefix new records of a type are numbered with.

Pins the resolution order (project, nearest parent project, organisation, built-in default), that a change affects only
records created afterwards and never reuses a number, the collision and shape rules, access, module visibility, audit,
the bundles and templates, and that every registered type creates a record with an override. Each test builds its own
organisation, so none depends on another's state.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import event

from app.code_rules import RECORD_CODE_PATTERN, record_prefix_error, split_record_label
from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.models.organization import Organization
from app.models.project import Project
from app.modules.registry import (
    get_all_registered_artefact_types,
    get_default_code_prefixes,
    get_scaling_probes,
    get_types_without_code_prefix,
)
from app.services import code_prefixes
from app.services.codes import label_title
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login
from tests.link_world import World

PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Prefix Org", context_strategy=True)


def _org(world: World) -> str:
    return f"/api/v1/orgs/{world.org['id']}/code-prefixes"


def _proj(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}/code-prefixes"


def _put(world: World, url: str, prefix: str, token: str | None = None):
    return world.client.put(url, json={"prefix": prefix}, headers=auth_headers(token or world.token))


def _delete(world: World, url: str, token: str | None = None):
    return world.client.delete(url, headers=auth_headers(token or world.token))


def _row(world: World, url: str, artefact_type: str, token: str | None = None) -> dict:
    resp = world.client.get(url, headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return next(r for r in resp.json() if r["artefact_type"] == artefact_type)


def _pain_code(world: World, project: dict) -> str:
    """Creates a Pain Point and returns the code it was numbered with."""
    pain_id = str(world.pain_point(project))
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/modules/context_strategy/pain-points/{pain_id}", headers=auth_headers(world.token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["unique_code"]


def _action_code(world: World, project: dict) -> str:
    action_id = world.action(project)
    rows = world.client.get(f"/api/v1/projects/{project['id']}/actions", headers=auth_headers(world.token)).json()
    return next(a["unique_code"] for a in rows if a["id"] == str(action_id))


# --- the shared rule ---------------------------------------------------------------------------------------------------


def test_prefix_shape_rule():
    assert record_prefix_error("ADR") is None
    assert record_prefix_error("AB") is None
    assert record_prefix_error("ABCDE") is None
    for bad in ("A", "ABCDEF", "AD1", "A-B", "ad", "", "A B"):
        assert record_prefix_error(bad) is not None, bad


def test_record_code_shape_accepts_a_counter_past_999():
    assert RECORD_CODE_PATTERN.fullmatch("DEC-001")
    assert RECORD_CODE_PATTERN.fullmatch("ADR-12345")
    assert label_title("ADR-12345 A long-lived decision") == "A long-lived decision"
    assert label_title("ISO-27001 v2.0 · A.5.15 Access") == "ISO-27001 v2.0 · A.5.15 Access"


FRONTEND_CASES = Path(__file__).resolve().parents[2] / "frontend/src/components/artefactCodeCases.json"


@pytest.mark.skipif(not FRONTEND_CASES.is_file(), reason="repository checkout not available (the cases are outside backend/)")
def test_the_label_reader_agrees_with_the_frontend_on_shared_vectors():
    """`components/artefactCode.ts` reads the same cases (`artefactCodeCases.json`); both must give the same split."""
    cases = json.loads(FRONTEND_CASES.read_text())
    for case in cases:
        assert split_record_label(case["label"]) == (case["code"], case["title"]), case["label"]


def test_every_registered_type_has_a_default_prefix_or_a_stated_reason():
    registered = get_all_registered_artefact_types()
    defaults = code_prefixes.default_prefixes()
    reasons = {**code_prefixes.core_types_without_prefix(), **get_types_without_code_prefix()}
    missing = registered - set(defaults) - set(reasons)
    assert not missing, f"artefact types with neither a default code prefix nor a reason: {sorted(missing)}"
    assert not (set(defaults) & set(reasons)), "a type is both prefixed and exempt"
    assert not (set(get_default_code_prefixes()) - registered), "a default for a type that is not registered"
    assert all(reason.strip() for reason in reasons.values())
    for artefact_type, prefix in defaults.items():
        assert record_prefix_error(prefix) is None, f"{artefact_type}: {prefix}"
    assert len(set(defaults.values())) == len(defaults), "two types share a built-in prefix"


# --- resolution ------------------------------------------------------------------------------------------------------


def test_without_an_override_the_built_in_prefix_is_used(world):
    project = world.project()
    assert _pain_code(world, project) == "PP-001"
    row = _row(world, _proj(project), PAIN)
    assert (row["prefix"], row["source"], row["own_prefix"], row["default_prefix"]) == ("PP", "default", None, "PP")


def test_organisation_override_applies_to_new_records_and_the_counter_continues(world):
    project = world.project()
    assert _pain_code(world, project) == "PP-001"
    resp = _put(world, f"{_org(world)}/{PAIN}", " pq ")
    assert resp.status_code == 200, resp.text
    assert resp.json()["prefix"] == "PQ"
    assert _pain_code(world, project) == "PQ-002"
    assert _delete(world, f"{_org(world)}/{PAIN}").status_code == 200
    assert _pain_code(world, project) == "PP-003"


def test_project_override_beats_the_organisation_and_names_its_tier(world):
    project = world.project()
    other = world.project("Other")
    assert _put(world, f"{_org(world)}/{PAIN}", "ORG").status_code == 200
    assert _put(world, f"{_proj(project)}/{PAIN}", "PRJ").status_code == 200
    assert _pain_code(world, project) == "PRJ-001"
    assert _pain_code(world, other) == "ORG-001"
    assert _row(world, _proj(project), PAIN)["source"] == "project"
    assert _row(world, _proj(other), PAIN)["source"] == "organization"


def test_a_child_project_follows_its_nearest_ancestor_until_it_sets_its_own(world):
    root = world.project("Root")
    middle = world.project("Middle", parent=root)
    leaf = world.project("Leaf", parent=middle)
    assert _put(world, f"{_org(world)}/{PAIN}", "ORG").status_code == 200
    assert _put(world, f"{_proj(root)}/{PAIN}", "RTP").status_code == 200
    assert _pain_code(world, leaf) == "RTP-001"
    leaf_row = _row(world, _proj(leaf), PAIN)
    assert (leaf_row["prefix"], leaf_row["source"], leaf_row["own_prefix"]) == ("RTP", "parent_project", None)

    assert _put(world, f"{_proj(middle)}/{PAIN}", "MDL").status_code == 200
    assert _pain_code(world, leaf) == "MDL-002"
    assert _put(world, f"{_proj(leaf)}/{PAIN}", "LFP").status_code == 200
    assert _pain_code(world, leaf) == "LFP-003"

    assert _delete(world, f"{_proj(leaf)}/{PAIN}").status_code == 200
    assert _row(world, _proj(leaf), PAIN)["prefix"] == "MDL"
    assert _delete(world, f"{_proj(middle)}/{PAIN}").status_code == 200
    assert _row(world, _proj(leaf), PAIN)["prefix"] == "RTP"
    assert _delete(world, f"{_proj(root)}/{PAIN}").status_code == 200
    assert _row(world, _proj(leaf), PAIN)["prefix"] == "ORG"


def test_the_prefix_is_read_once_per_owner_per_session_and_forgotten_after_a_write(world):
    """A bulk import numbers many records: the overrides are read once, not per record, and a write drops the copy."""
    project = world.project()
    assert _put(world, f"{_proj(project)}/{PAIN}", "ONE").status_code == 200
    db = SessionLocal()
    seen: list[str] = []

    def record(_conn, _cursor, statement, *_args, **_kwargs) -> None:
        if "project_code_prefixes" in statement or "organization_code_prefixes" in statement:
            seen.append(statement)

    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        event.listen(engine, "before_cursor_execute", record)
        try:
            assert [code_prefixes.effective_prefix(db, row, PAIN, "PP") for _ in range(5)] == ["ONE"] * 5
            reads = len(seen)
            assert 0 < reads <= 3, seen  # the chain's project rows and the organisation's, once
            code_prefixes.set_override(db, row, PAIN, "TWO", None)
            assert code_prefixes.effective_prefix(db, row, PAIN, "PP") == "TWO"
        finally:
            event.remove(engine, "before_cursor_execute", record)
        db.rollback()
    finally:
        db.close()


def test_a_row_says_what_clearing_the_prefix_returns_to(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    assert _put(world, f"{_org(world)}/{PAIN}", "ORG").status_code == 200
    row = _row(world, _proj(child), PAIN)
    assert (row["inherited_prefix"], row["inherited_source"]) == ("ORG", "organization")
    assert _put(world, f"{_proj(root)}/{PAIN}", "RTP").status_code == 200
    assert _put(world, f"{_proj(child)}/{PAIN}", "CHD").status_code == 200
    row = _row(world, _proj(child), PAIN)
    assert (row["prefix"], row["source"]) == ("CHD", "project")
    assert (row["inherited_prefix"], row["inherited_source"]) == ("RTP", "parent_project")
    org_row = _row(world, _org(world), PAIN)
    assert (org_row["prefix"], org_row["inherited_prefix"], org_row["inherited_source"]) == ("ORG", "PP", "default")


def test_actions_and_change_requests_follow_the_override_too(world):
    project = world.project()
    assert _action_code(world, project) == "ACT-001"
    assert _put(world, f"{_proj(project)}/requirement_action", "TSK").status_code == 200
    assert _action_code(world, project) == "TSK-002"
    assert _row(world, _proj(project), "change_request")["prefix"] == "CR"
    assert _put(world, f"{_org(world)}/change_request", "CHG").status_code == 200
    assert _row(world, _proj(project), "change_request")["prefix"] == "CHG"


def test_a_requirement_is_outside_the_mechanism(world):
    assert _put(world, f"{_org(world)}/requirement", "RQM").status_code == 400
    assert "requirement" not in {r["artefact_type"] for r in world.client.get(_org(world), headers=auth_headers(world.token)).json()}


def test_a_qualified_code_still_resolves_after_a_prefix_change(world):
    project = world.project()
    pain_id = world.pain_point(project)
    assert _put(world, f"{_proj(project)}/{PAIN}", "NEW").status_code == 200
    new_id = world.pain_point(project, "Another")
    project_code = world.client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(world.token)).json()["code"]
    for code, expected in ((f"{project_code}-PP-001", pain_id), (f"{project_code}-NEW-002", new_id)):
        resp = world.client.get(f"/api/v1/orgs/{world.org['id']}/records/by-code/{code}", headers=auth_headers(world.token))
        assert resp.status_code == 200, (code, resp.text)
        assert resp.json()["id"] == str(expected)


# --- rules -----------------------------------------------------------------------------------------------------------


def test_a_bad_shape_or_an_unknown_type_is_rejected(world):
    for bad in ("A", "ABCDEF", "AD1", "A-B", "", "  "):
        resp = _put(world, f"{_org(world)}/{PAIN}", bad)
        assert resp.status_code == 400, bad
    assert _put(world, f"{_org(world)}/not_a_type", "ABC").status_code == 400
    assert _delete(world, f"{_org(world)}/not_a_type").status_code == 400


def test_two_types_cannot_share_a_prefix_in_one_scope(world):
    project = world.project()
    clash = _put(world, f"{_org(world)}/{PAIN}", "OQ")  # open question's built-in prefix
    assert clash.status_code == 400
    assert "open question" in clash.json()["detail"].lower()
    assert _put(world, f"{_org(world)}/{PAIN}", "XYZ").status_code == 200
    assert _put(world, f"{_org(world)}/open_question", "XYZ").status_code == 400
    # Freed by the change above: pain point no longer uses PP.
    assert _put(world, f"{_org(world)}/open_question", "PP").status_code == 200
    assert _put(world, f"{_proj(project)}/{PAIN}", "PP").status_code == 400


def test_a_project_override_cannot_collide_with_a_value_it_inherits(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    assert _put(world, f"{_proj(root)}/{PAIN}", "ADX").status_code == 200
    assert _put(world, f"{_proj(child)}/open_question", "ADX").status_code == 400
    assert _put(world, f"{_proj(child)}/open_question", "ADY").status_code == 200


def test_a_parent_cannot_take_a_prefix_its_child_already_uses(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    assert _put(world, f"{_proj(child)}/open_question", "ADY").status_code == 200
    blocked = _put(world, f"{_proj(root)}/{PAIN}", "ADY")
    assert blocked.status_code == 400
    assert "nested project" in blocked.json()["detail"]
    assert _put(world, f"{_org(world)}/{PAIN}", "ADY").status_code == 400


def test_a_prefix_cannot_equal_the_organisation_or_a_project_code(world):
    project = world.project("Codes")
    org_code = world.client.get(f"/api/v1/orgs/{world.org['id']}", headers=auth_headers(world.token)).json()["code"]
    project_code = world.client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(world.token)).json()["code"]
    if record_prefix_error(org_code) is None:
        assert _put(world, f"{_org(world)}/{PAIN}", org_code).status_code == 400
    if record_prefix_error(project_code) is None:
        assert _put(world, f"{_org(world)}/{PAIN}", project_code).status_code == 400
        assert _put(world, f"{_proj(project)}/{PAIN}", project_code).status_code == 400


def test_clearing_cannot_create_a_collision_for_a_nested_project(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    assert _put(world, f"{_proj(root)}/{PAIN}", "ZZA").status_code == 200
    assert _put(world, f"{_proj(child)}/{PAIN}", "ZZB").status_code == 200
    assert _put(world, f"{_proj(child)}/open_question", "ZZA").status_code == 200  # the child's own pain point is ZZB
    cleared = _delete(world, f"{_proj(child)}/{PAIN}")  # would follow the root's ZZA, which open questions use here
    assert cleared.status_code == 400
    assert _row(world, _proj(child), PAIN)["prefix"] == "ZZB"


# --- access, visibility and audit ------------------------------------------------------------------------------------


def test_a_member_may_read_but_not_change_a_prefix(world):
    project = world.project()
    email = "prefix-member@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(world.token)
    )
    assert resp.status_code in (200, 201, 204), resp.text
    token = login(world.client, email, "Password123!")
    assert _row(world, _org(world), PAIN, token)["prefix"] == "PP"
    assert _row(world, _proj(project), PAIN, token)["prefix"] == "PP"
    assert _put(world, f"{_org(world)}/{PAIN}", "NOP", token).status_code == 403
    assert _put(world, f"{_proj(project)}/{PAIN}", "NOP", token).status_code == 403
    assert _delete(world, f"{_proj(project)}/{PAIN}", token).status_code == 403


def test_a_project_manager_may_change_the_projects_prefix_but_not_the_organisations(world):
    project = world.project()
    email = "prefix-manager@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "project_manager"},
        headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    token = login(world.client, email, "Password123!")
    assert _put(world, f"{_proj(project)}/{PAIN}", "MGR", token).status_code == 200
    assert _put(world, f"{_org(world)}/{PAIN}", "MGR", token).status_code == 403


def test_another_organisations_administrator_cannot_reach_either_scope(client, admin_token, world):
    project = world.project()
    _other_org, other_token = create_org_admin_in(client, admin_token, "Other Prefix Co")
    assert client.get(_org(world), headers=auth_headers(other_token)).status_code in (403, 404)
    assert client.put(f"{_org(world)}/{PAIN}", json={"prefix": "HAK"}, headers=auth_headers(other_token)).status_code in (403, 404)
    assert client.get(_proj(project), headers=auth_headers(other_token)).status_code in (403, 404)
    assert client.put(f"{_proj(project)}/{PAIN}", json={"prefix": "HAK"}, headers=auth_headers(other_token)).status_code in (403, 404)


def test_a_module_the_organisation_has_off_is_not_listed(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "No Strategy Co")
    types = {r["artefact_type"] for r in client.get(f"/api/v1/orgs/{org['id']}/code-prefixes", headers=auth_headers(token)).json()}
    assert "requirement_action" in types and "change_request" in types
    assert PAIN not in types
    project = create_project(client, token, org["id"], "Plain")
    project_types = {r["artefact_type"] for r in client.get(_proj(project), headers=auth_headers(token)).json()}
    assert PAIN not in project_types


def test_each_change_is_audited_with_the_type_and_prefixes_only(world):
    project = world.project()
    assert _put(world, f"{_proj(project)}/{PAIN}", "AUD").status_code == 200
    assert _put(world, f"{_proj(project)}/{PAIN}", "AUE").status_code == 200
    assert _delete(world, f"{_proj(project)}/{PAIN}").status_code == 200
    db = SessionLocal()
    try:
        events = (
            db.query(AuditEvent).filter(AuditEvent.entity_id == project["id"], AuditEvent.action.like("code_prefix_%"))
            .order_by(AuditEvent.created_at).all()
        )
        assert [e.action for e in events] == ["code_prefix_set", "code_prefix_set", "code_prefix_cleared"]
        assert events[1].detail == {"artefact_type": PAIN, "prefix": "AUE", "previous": "AUD"}
        assert events[2].detail == {"artefact_type": PAIN, "previous": "AUE"}
        assert all(e.project_id is not None and e.organization_id is not None for e in events)
    finally:
        db.close()


def test_the_list_is_core_first_then_by_name(world):
    names = [r["label"] for r in world.client.get(_org(world), headers=auth_headers(world.token)).json()]
    assert names[:2] == ["Action", "Change request"]
    assert names[2:] == sorted(names[2:], key=str.lower)


# --- bundles and templates -------------------------------------------------------------------------------------------


def _bundle_import(world: World, bundle: bytes, name: str) -> dict:
    resp = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_project_bundle_carries_the_projects_own_prefixes(world):
    project = world.project("Source")
    assert _put(world, f"{_proj(project)}/{PAIN}", "BDL").status_code == 200
    assert _put(world, f"{_org(world)}/open_question", "ORQ").status_code == 200  # the organisation's: not in the project's bundle
    export = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(world.token))
    assert export.status_code == 200
    entries = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))["code_prefixes"]
    assert entries == [{"artefact_type": PAIN, "prefix": "BDL"}]

    imported = _bundle_import(world, export.content, "Copy")["project"]
    row = _row(world, _proj(imported), PAIN)
    assert (row["prefix"], row["own_prefix"], row["source"]) == ("BDL", "BDL", "project")
    assert _pain_code(world, imported) == "BDL-001"


def test_a_bundle_prefix_that_no_longer_fits_is_skipped_with_a_warning(world):
    project = world.project("Source")
    assert _put(world, f"{_proj(project)}/{PAIN}", "BDL").status_code == 200
    export = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(world.token)).content
    # The organisation has since given open questions BDL (the project's own override is removed first, so BDL is free).
    assert _delete(world, f"{_proj(project)}/{PAIN}").status_code == 200
    assert _put(world, f"{_org(world)}/open_question", "BDL").status_code == 200
    imported = _bundle_import(world, export, "Copy")
    assert any("record code prefix" in w.lower() and "bdl" in w.lower() for w in imported["warnings"]), imported["warnings"]
    assert _row(world, _proj(imported["project"]), PAIN)["source"] == "default"


def test_a_project_made_from_a_template_has_the_templates_prefixes(world):
    template = world.project("Template")
    assert _put(world, f"{_proj(template)}/{PAIN}", "TPL").status_code == 200
    resp = world.client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    created = world.client.post(
        "/api/v1/projects",
        json={"organization_id": world.org["id"], "name": "From template", "summary": "", "template_project_id": template["id"]},
        headers=auth_headers(world.token),
    )
    assert created.status_code == 201, created.text
    assert _row(world, _proj(created.json()), PAIN)["own_prefix"] == "TPL"
    assert _pain_code(world, created.json()) == "TPL-001"


def test_an_organisation_bundle_carries_the_organisations_prefixes(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Bundle Prefix Co")
    assert client.put(
        f"/api/v1/orgs/{org['id']}/modules/context_strategy", json={"enabled": True}, headers=auth_headers(token)
    ).status_code == 200
    assert client.put(f"/api/v1/orgs/{org['id']}/code-prefixes/{PAIN}", json={"prefix": "OBP"}, headers=auth_headers(token)).status_code == 200
    assert client.put(
        f"/api/v1/orgs/{org['id']}/code-policy",
        json={"kind": "letters", "min_length": 2, "max_length": 4, "assignment": "auto", "locked": False, "enforce_code_everywhere": True},
        headers=auth_headers(token),
    ).status_code == 200
    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert export.status_code == 200, export.text
    assert json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))["code_prefixes"] == [
        {"artefact_type": PAIN, "prefix": "OBP"}
    ]
    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Imported Prefix Co"}, files={"file": ("bundle.zip", export.content, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_id = uuid.UUID(imported.json()["organization"]["id"])
    policy = client.get(f"/api/v1/orgs/{new_id}", headers=auth_headers(admin_token)).json()
    assert policy["project_code_policy"]["max_length"] == 4 and policy["enforce_code_everywhere"] is True
    # The Context & Strategy module may be off in the new organisation, which hides the type from the list;
    # the stored override is what travelled.
    db = SessionLocal()
    try:
        assert code_prefixes.export_overrides(db, db.get(Organization, new_id)) == [{"artefact_type": PAIN, "prefix": "OBP"}]
    finally:
        db.close()


# --- every type ------------------------------------------------------------------------------------------------------


class _Api:
    def __init__(self, client, token: str) -> None:
        self._client, self._headers = client, auth_headers(token)

    def post(self, path, body=None):
        resp = self._client.post(f"/api/v1{path}", json=body or {}, headers=self._headers)
        assert resp.status_code in (200, 201), f"POST {path}: {resp.status_code} {resp.text}"
        return resp.json()

    def put(self, path, body=None):
        resp = self._client.put(f"/api/v1{path}", json=body or {}, headers=self._headers)
        assert resp.status_code in (200, 201), f"PUT {path}: {resp.status_code} {resp.text}"
        return resp.json()

    def get(self, path):
        resp = self._client.get(f"/api/v1{path}", headers=self._headers)
        assert resp.status_code == 200, f"GET {path}: {resp.status_code} {resp.text}"
        return resp.json()


def _codes_of(client, token: str, project_id: str, artefact_type: str) -> list[str]:
    """The `code` column of the type's own CSV export (the one file format every list offers)."""
    resp = client.get(f"/api/v1/projects/{project_id}/records/{artefact_type}/export", headers=auth_headers(token))
    assert resp.status_code == 200, f"{artefact_type}: {resp.status_code} {resp.text[:200]}"
    rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))
    return [r["code"] for r in rows]


def test_every_prefixed_type_creates_a_record_with_an_override(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Every Type Co")
    from app.modules.registry import get_module_registry

    for key, definition in get_module_registry().items():
        assert client.put(f"/api/v1/orgs/{org['id']}/modules/{key}", json={"enabled": True}, headers=auth_headers(token)).status_code == 200
        for sub in definition.sub_components:
            resp = client.put(
                f"/api/v1/orgs/{org['id']}/modules/{key}/subcomponents/{sub.key}", json={"enabled": True}, headers=auth_headers(token)
            )
            assert resp.status_code == 200, resp.text
    project = create_project(client, token, org["id"], "Every Type Project")
    api = _Api(client, token)
    probes = get_scaling_probes()
    defaults = code_prefixes.default_prefixes()
    tested = []
    for index, artefact_type in enumerate(sorted(defaults)):
        probe = probes.get(artefact_type)
        if probe is None:
            continue
        override = "Q" + chr(ord("A") + index // 26) + chr(ord("A") + index % 26)
        resp = client.put(
            f"/api/v1/projects/{project['id']}/code-prefixes/{artefact_type}", json={"prefix": override}, headers=auth_headers(token)
        )
        assert resp.status_code == 200, f"{artefact_type}: {resp.text}"
        before = set(_codes_of(client, token, project["id"], artefact_type))
        probe.create(api, project["id"], 0, 1)
        # A probe may first create records this type depends on (an element for a connection), so only the codes
        # that appeared since are compared; the type's own record is among them.
        added = set(_codes_of(client, token, project["id"], artefact_type)) - before
        assert any(c.startswith(f"{override}-") for c in added), f"{artefact_type}: {sorted(added)}"
        tested.append(artefact_type)
    # A type with no probe cannot be filled through its API here; the scaling-shape guard already requires every type to
    # have a probe or a stated reason, so this only fails if most types stop being exercised.
    assert len(tested) >= 15, tested
