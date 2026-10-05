"""Tests for the Stakeholders & Personas module's Phase 1.2 backend API
(docs/plans/module-02-stakeholders-and-personas-plan.md — Stakeholder),
through the real HTTP endpoints.

Covers: org- and project-scoped CRUD and the scope rules, partial update
(including clearing nullable fields), version history, the lifecycle, the
Stakeholder type vocabulary, the `stakeholder` scoring scheme (level
validation, the cadence hint's four quadrants, delete-with-reassignment of a
level in use), "create from org user", the "represents Persona" links from
both ends (with tenancy filtering), hard-delete erasure leaving no rows,
files, links or personal data in the audit trail, RBAC composition, module
gates, cross-tenant isolation, comments/files and audit logging.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.models.file import FileAsset
from app.models.relationship import ArtefactLink
from app.modules.stakeholders.models import (
    Stakeholder,
    StakeholderComment,
    StakeholderCommentFile,
    StakeholderFile,
    StakeholderVersion,
)
from app.modules.stakeholders.tests.test_persona_api import (
    _add_member,
    _create_org_persona,
    _create_project_persona,
    _grant_org_role,
    _grant_project_role,
    _org_base,
    _project_base,
    _setup,
)
from app.services.files import get_storage_backend
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project

_PAYLOAD = {
    "name": "Pat Regulator",
    "description": "Audits safety compliance.",
    "role": "Compliance auditor",
    "organisation_group": "Safety Authority",
    "interests": "Evidence of compliance.",
    "responsibilities": "Annual audit.",
    "goals_needs": "Traceable records.",
    "priorities": "Safety first.",
    "constraints": "Only available in Q4.",
    "workflows_scenarios": "On-site audit.",
    "contact_info": "pat@authority.example.com, +1 555 0100",
    "target_cadence": "quarterly",
    "availability_constraints": "Prefers email.",
}


def _create_project_stakeholder(client, token, project_id, **extra) -> dict:
    resp = client.post(_project_base(project_id) + "/stakeholders", json={**_PAYLOAD, **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_org_stakeholder(client, token, org_id, **extra) -> dict:
    resp = client.post(_org_base(org_id) + "/stakeholders", json={**_PAYLOAD, **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _levels(client, token, org_id) -> dict[str, dict[str, str]]:
    """`{axis: {level name: level id}}` of the org's `stakeholder` scheme."""
    scheme = client.get(f"/api/v1/orgs/{org_id}/scoring-schemes/stakeholder", headers=auth_headers(token)).json()
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in scheme["axes"]}


# --- CRUD, scope, versions ---------------------------------------------------


def test_project_stakeholder_crud_and_versions(client, admin_token):
    _, project, token = _setup(client, admin_token, "Stakeholder Crud Co")
    created = _create_project_stakeholder(client, token, project["id"])
    assert created["scope"] == "project" and created["project_id"] == project["id"]
    assert created["organization_id"] is None
    assert created["status"] == "draft" and created["version_number"] == 1
    assert created["target_cadence"] == "quarterly" and created["contact_info"].startswith("pat@")

    url = f"{_project_base(project['id'])}/stakeholders/{created['id']}"
    resp = client.put(url, json={"priorities": "New", "change_note": "refine"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["priorities"] == "New" and body["name"] == "Pat Regulator" and body["version_number"] == 2
    assert body["target_cadence"] == "quarterly"  # unspecified fields carry forward

    versions = client.get(url + "/versions", headers=auth_headers(token)).json()
    assert [v["version_number"] for v in versions] == [1, 2]
    assert versions[0]["valid_to"] is not None and versions[1]["valid_to"] is None
    assert versions[1]["change_note"] == "refine"
    # Contact info is Confidential and only on the current record, not the history listing.
    assert all("contact_info" not in v for v in versions)


def test_update_can_clear_nullable_fields(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Clear Co")
    user_id = create_org_user(client, token, org["id"], "owner@clear-s.example.com")
    levels = _levels(client, token, org["id"])
    created = _create_project_stakeholder(
        client, token, project["id"], owner_id=user_id, influence_level_id=levels["influence"]["High"],
    )
    assert created["owner_id"] == user_id and created["influence_level_id"] == levels["influence"]["High"]
    url = f"{_project_base(project['id'])}/stakeholders/{created['id']}"
    resp = client.put(
        url, json={"owner_id": None, "target_cadence": None, "influence_level_id": None, "contact_info": None},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["owner_id"] is None and body["target_cadence"] is None and body["influence_level_id"] is None
    assert body["contact_info"] == ""  # a text field clears to empty, never null


def test_invalid_cadence_and_null_name_rejected(client, admin_token):
    _, project, token = _setup(client, admin_token, "Stakeholder Validation Co")
    base = _project_base(project["id"]) + "/stakeholders"
    assert client.post(base, json={**_PAYLOAD, "target_cadence": "fortnightly"}, headers=auth_headers(token)).status_code == 422
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    assert client.put(f"{base}/{stakeholder['id']}", json={"name": None}, headers=auth_headers(token)).status_code == 422


def test_owner_and_user_must_be_org_members(client, admin_token):
    _, project, token = _setup(client, admin_token, "Stakeholder People A Co")
    other_org, _ = create_org_admin_in(client, admin_token, "Stakeholder People B Co")
    outsider = create_org_user(client, admin_token, other_org["id"], "outsider@sb.example.com")
    base = _project_base(project["id"]) + "/stakeholders"
    for field in ("owner_id", "user_id"):
        resp = client.post(base, json={**_PAYLOAD, field: outsider}, headers=auth_headers(token))
        assert resp.status_code == 400, (field, resp.text)


def test_org_stakeholder_crud_and_visible_from_project(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Org Scope Co")
    org_stakeholder = _create_org_stakeholder(client, token, org["id"])
    assert org_stakeholder["scope"] == "organization" and org_stakeholder["project_id"] is None

    listed = client.get(_org_base(org["id"]) + "/stakeholders", headers=auth_headers(token)).json()
    assert [s["id"] for s in listed] == [org_stakeholder["id"]]
    project_list = client.get(_project_base(project["id"]) + "/stakeholders", headers=auth_headers(token)).json()
    assert [s["id"] for s in project_list] == [org_stakeholder["id"]]
    assert client.get(
        _project_base(project["id"]) + "/stakeholders?include_org=false", headers=auth_headers(token)
    ).json() == []
    # The project router can't edit or erase an org stakeholder.
    url = f"{_project_base(project['id'])}/stakeholders/{org_stakeholder['id']}"
    assert client.put(url, json={"priorities": "x"}, headers=auth_headers(token)).status_code == 404
    assert client.delete(url, headers=auth_headers(token)).status_code == 404


def test_archive_hides_from_default_list(client, admin_token):
    _, project, token = _setup(client, admin_token, "Stakeholder Archive Co")
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    base = f"{_project_base(project['id'])}/stakeholders"
    assert client.post(f"{base}/{stakeholder['id']}/archive", headers=auth_headers(token)).json()["is_archived"] is True
    assert client.get(base, headers=auth_headers(token)).json() == []
    assert len(client.get(base + "?include_archived=true", headers=auth_headers(token)).json()) == 1
    assert client.post(f"{base}/{stakeholder['id']}/unarchive", headers=auth_headers(token)).json()["is_archived"] is False


def test_lifecycle_transitions_and_illegal_409(client, admin_token):
    _, project, token = _setup(client, admin_token, "Stakeholder Lifecycle Co")
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    base = f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}"
    h = auth_headers(token)
    assert client.post(base + "/activate", headers=h).json()["status"] == "active"
    assert client.post(base + "/activate", headers=h).status_code == 409
    assert client.post(base + "/retire", json={"comment": "left"}, headers=h).json()["status"] == "retired"
    assert client.post(base + "/retire", headers=h).status_code == 409
    assert client.post(base + "/activate", headers=h).json()["status"] == "active"
    assert client.put(base, json={"priorities": "still editable"}, headers=h).status_code == 200


# --- Types -------------------------------------------------------------------


def test_new_org_gets_default_stakeholder_types(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Stakeholder Types Seed Co")
    enabled = client.put(f"/api/v1/orgs/{org['id']}/modules/stakeholders", json={"enabled": True}, headers=auth_headers(token))
    assert enabled.status_code == 200
    types = client.get(_org_base(org["id"]) + "/stakeholder-types", headers=auth_headers(token)).json()
    assert [t["name"] for t in types] == [
        "Customer", "End user", "Operator", "Maintainer", "Service engineer", "Business owner", "Project sponsor",
        "Regulator", "Supplier", "Internal engineering team", "Support organisation",
    ]


def test_type_crud_in_use_blocking_and_project_override(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Type Crud Co")
    h = auth_headers(token)
    org_url = _org_base(org["id"]) + "/stakeholder-types"
    created = client.post(org_url, json={"name": "Investor"}, headers=h).json()
    assert client.post(org_url, json={"name": "Investor"}, headers=h).status_code == 400  # duplicate
    renamed = client.patch(f"{org_url}/{created['id']}", json={"name": "Backer"}, headers=h).json()
    assert renamed["name"] == "Backer"

    stakeholder = _create_org_stakeholder(client, token, org["id"], stakeholder_type_id=created["id"])
    assert stakeholder["stakeholder_type_name"] == "Backer"
    assert client.delete(f"{org_url}/{created['id']}", headers=h).status_code == 409  # in use

    base = _project_base(project["id"])
    effective = client.get(base + "/stakeholder-types", headers=h).json()
    backer = next(t for t in effective if t["name"] == "Backer")
    resp = client.put(f"{base}/stakeholder-types/{backer['id']}", json={"is_enabled": False}, headers=h)
    assert resp.status_code == 200, resp.text
    local = client.post(base + "/stakeholder-types", json={"name": "Project-only"}, headers=h).json()
    typed = _create_project_stakeholder(client, token, project["id"], stakeholder_type_id=local["id"])
    assert typed["stakeholder_type_name"] == "Project-only"
    assert client.delete(f"{base}/stakeholder-types/{local['id']}", headers=h).status_code == 409
    # A disabled type can't be picked for a new project stakeholder.
    assert client.post(
        base + "/stakeholders", json={**_PAYLOAD, "stakeholder_type_id": resp.json()["id"]}, headers=h
    ).status_code == 400


def test_stakeholder_type_from_another_org_is_rejected(client, admin_token):
    _, project, token = _setup(client, admin_token, "Stakeholder Type Iso A Co")
    org_b, token_b = create_org_admin_in(client, admin_token, "Stakeholder Type Iso B Co")
    client.put(f"/api/v1/orgs/{org_b['id']}/modules/stakeholders", json={"enabled": True}, headers=auth_headers(token_b))
    foreign = client.get(_org_base(org_b["id"]) + "/stakeholder-types", headers=auth_headers(token_b)).json()[0]
    resp = client.post(
        _project_base(project["id"]) + "/stakeholders", json={**_PAYLOAD, "stakeholder_type_id": foreign["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400, resp.text


# --- Scoring: levels, cadence hint, level usage -------------------------------


def test_scoring_levels_are_validated(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Levels Co")
    levels = _levels(client, token, org["id"])
    assert set(levels) == {"influence", "interest"} and list(levels["influence"]) == ["Low", "Medium", "High"]
    ok = _create_project_stakeholder(
        client, token, project["id"], influence_level_id=levels["influence"]["High"],
        interest_level_id=levels["interest"]["Low"],
    )
    assert ok["influence_level_id"] == levels["influence"]["High"]
    base = _project_base(project["id"]) + "/stakeholders"
    # Right org and scheme, but the wrong axis.
    assert client.post(
        base, json={**_PAYLOAD, "influence_level_id": levels["interest"]["High"]}, headers=auth_headers(token)
    ).status_code == 400
    # Another org's level.
    org_b, token_b = create_org_admin_in(client, admin_token, "Stakeholder Levels B Co")
    client.put(f"/api/v1/orgs/{org_b['id']}/modules/stakeholders", json={"enabled": True}, headers=auth_headers(token_b))
    foreign = _levels(client, token_b, org_b["id"])
    assert client.post(
        base, json={**_PAYLOAD, "interest_level_id": foreign["interest"]["High"]}, headers=auth_headers(token)
    ).status_code == 400


def test_cadence_hint_quadrants(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Hint Co")
    h = auth_headers(token)
    lv = _levels(client, token, org["id"])
    cases = [
        ("High", "High", "manage_closely", "monthly"),
        ("Medium", "Medium", "manage_closely", "monthly"),  # Medium counts as high on the default levels
        ("High", "Low", "keep_satisfied", "quarterly"),
        ("Low", "High", "keep_informed", "quarterly"),
        ("Low", "Low", "monitor", "ad_hoc"),
    ]
    for scope_base in (_project_base(project["id"]), _org_base(org["id"])):
        for influence, interest, quadrant, cadence in cases:
            resp = client.get(
                scope_base + "/stakeholders/cadence-hint",
                params={"influence_level_id": lv["influence"][influence], "interest_level_id": lv["interest"][interest]},
                headers=h,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json() == {"quadrant": quadrant, "suggested_cadence": cadence}, (influence, interest)
        # No position until both levels are set; the hint is never applied to a record.
        unset = client.get(scope_base + "/stakeholders/cadence-hint", params={"influence_level_id": lv["influence"]["High"]}, headers=h)
        assert unset.json() == {"quadrant": None, "suggested_cadence": None}
        bad = client.get(
            scope_base + "/stakeholders/cadence-hint",
            params={"influence_level_id": lv["interest"]["High"], "interest_level_id": lv["interest"]["High"]}, headers=h,
        )
        assert bad.status_code == 400


def test_deleting_a_level_in_use_requires_reassignment_of_current_versions(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Level Usage Co")
    h = auth_headers(token)
    lv = _levels(client, token, org["id"])
    stakeholder = _create_project_stakeholder(client, token, project["id"], interest_level_id=lv["interest"]["High"])
    url = f"/api/v1/orgs/{org['id']}/scoring-schemes/stakeholder/levels/{lv['interest']['High']}"
    assert client.delete(url, headers=h).status_code == 409  # in use, no reassignment target
    moved = client.delete(url + f"?reassign_to_id={lv['interest']['Medium']}", headers=h)
    assert moved.status_code == 204, moved.text
    current = client.get(f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}", headers=h).json()
    assert current["interest_level_id"] == lv["interest"]["Medium"]


def test_deleting_an_unused_level_leaves_history_intact(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Level History Co")
    h = auth_headers(token)
    lv = _levels(client, token, org["id"])
    stakeholder = _create_project_stakeholder(client, token, project["id"], interest_level_id=lv["interest"]["Low"])
    url = f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}"
    client.put(url, json={"interest_level_id": lv["interest"]["High"]}, headers=h)  # v1 keeps Low, v2 uses High
    resp = client.delete(f"/api/v1/orgs/{org['id']}/scoring-schemes/stakeholder/levels/{lv['interest']['Low']}", headers=h)
    assert resp.status_code == 204, resp.text  # only a historic version referenced it
    versions = client.get(url + "/versions", headers=h).json()
    assert versions[0]["interest_level_id"] is None and versions[1]["interest_level_id"] == lv["interest"]["High"]


# --- Create from org user ----------------------------------------------------


def test_create_from_user_prefills_and_rejects_duplicates_and_non_members(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder From User Co")
    h = auth_headers(token)
    user_id = create_org_user(client, token, org["id"], "colleague@from-user.example.com")
    for base in (_project_base(project["id"]), _org_base(org["id"])):
        resp = client.post(
            base + "/stakeholders/from-user", json={"user_id": user_id, "role": "Product owner"}, headers=h,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["user_id"] == user_id and body["name"] == "colleague"
        assert body["contact_info"] == "colleague@from-user.example.com" and body["role"] == "Product owner"
        assert client.post(base + "/stakeholders/from-user", json={"user_id": user_id}, headers=h).status_code == 409
    other_org, _ = create_org_admin_in(client, admin_token, "Stakeholder From User B Co")
    outsider = create_org_user(client, admin_token, other_org["id"], "outsider@from-user-b.example.com")
    assert client.post(
        _project_base(project["id"]) + "/stakeholders/from-user", json={"user_id": outsider}, headers=h
    ).status_code == 400


def test_create_from_user_allows_a_new_record_after_archiving(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder From User Archive Co")
    h = auth_headers(token)
    user_id = create_org_user(client, token, org["id"], "again@from-user.example.com")
    base = _project_base(project["id"]) + "/stakeholders"
    first = client.post(base + "/from-user", json={"user_id": user_id}, headers=h).json()
    client.post(f"{base}/{first['id']}/archive", headers=h)
    assert client.post(base + "/from-user", json={"user_id": user_id}, headers=h).status_code == 201


# --- Represents Persona ------------------------------------------------------


def test_represents_links_from_both_ends(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Represents Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    org_persona = _create_org_persona(client, token, org["id"], name="Shared persona")
    own_persona = _create_project_persona(client, token, project["id"], name="Own persona")
    sid = stakeholder["id"]

    for persona in (org_persona, own_persona):
        resp = client.post(f"{base}/stakeholders/{sid}/personas", json={"persona_id": persona["id"]}, headers=h)
        assert resp.status_code == 201, resp.text
        assert resp.json()["id"] == persona["id"] and resp.json()["name"] == persona["name"]
        assert client.post(
            f"{base}/stakeholders/{sid}/personas", json={"persona_id": persona["id"]}, headers=h
        ).status_code == 409  # many-to-many, but not twice

    listed = client.get(f"{base}/stakeholders/{sid}/personas", headers=h).json()
    assert {p["name"] for p in listed} == {"Shared persona", "Own persona"}
    # Many-to-many: a second stakeholder can represent the same persona.
    second = _create_project_stakeholder(client, token, project["id"], name="Second")
    client.post(f"{base}/stakeholders/{second['id']}/personas", json={"persona_id": own_persona["id"]}, headers=h)
    reverse = client.get(f"{base}/personas/{own_persona['id']}/stakeholders", headers=h).json()
    assert {s["name"] for s in reverse} == {"Pat Regulator", "Second"}

    link = next(p for p in listed if p["name"] == "Own persona")
    assert client.delete(f"{base}/stakeholders/{sid}/personas/{link['id']}", headers=h).status_code == 204
    assert client.delete(f"{base}/stakeholders/{sid}/personas/{link['id']}", headers=h).status_code == 404
    assert {p["name"] for p in client.get(f"{base}/stakeholders/{sid}/personas", headers=h).json()} == {"Shared persona"}


def test_org_stakeholder_only_represents_org_personas(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Org Represents Co")
    h = auth_headers(token)
    org_stakeholder = _create_org_stakeholder(client, token, org["id"])
    org_persona = _create_org_persona(client, token, org["id"], name="Org persona")
    project_persona = _create_project_persona(client, token, project["id"], name="Project persona")
    url = f"{_org_base(org['id'])}/stakeholders/{org_stakeholder['id']}/personas"
    assert client.post(url, json={"persona_id": org_persona["id"]}, headers=h).status_code == 201
    # A project persona is not an org-scoped one, so the org route can't see it at all.
    assert client.post(url, json={"persona_id": project_persona["id"]}, headers=h).status_code == 404
    assert [p["name"] for p in client.get(url, headers=h).json()] == ["Org persona"]
    reverse = client.get(f"{_org_base(org['id'])}/personas/{org_persona['id']}/stakeholders", headers=h).json()
    assert [s["id"] for s in reverse] == [org_stakeholder["id"]]
    assert client.delete(f"{url}/{org_persona['id']}", headers=h).status_code == 204


def test_persona_side_list_hides_other_projects_stakeholders(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Stakeholder Reverse Iso Co")
    project_b = create_project(client, token, org["id"], "Stakeholder Reverse Iso B")
    h = auth_headers(token)
    org_persona = _create_org_persona(client, token, org["id"], name="Shared")
    in_a = _create_project_stakeholder(client, token, project_a["id"], name="In A")
    in_b = _create_project_stakeholder(client, token, project_b["id"], name="In B")
    org_level = _create_org_stakeholder(client, token, org["id"], name="Org level")
    for project, stakeholder in ((project_a, in_a), (project_b, in_b)):
        client.post(
            f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}/personas",
            json={"persona_id": org_persona["id"]}, headers=h,
        )
    client.post(
        f"{_org_base(org['id'])}/stakeholders/{org_level['id']}/personas", json={"persona_id": org_persona["id"]}, headers=h
    )
    seen_from_a = client.get(f"{_project_base(project_a['id'])}/personas/{org_persona['id']}/stakeholders", headers=h).json()
    assert {s["name"] for s in seen_from_a} == {"In A", "Org level"}
    seen_from_b = client.get(f"{_project_base(project_b['id'])}/personas/{org_persona['id']}/stakeholders", headers=h).json()
    assert {s["name"] for s in seen_from_b} == {"In B", "Org level"}
    # The org view lists only org-scoped stakeholders, never a project's own.
    seen_from_org = client.get(f"{_org_base(org['id'])}/personas/{org_persona['id']}/stakeholders", headers=h).json()
    assert {s["name"] for s in seen_from_org} == {"Org level"}


def test_cannot_represent_another_orgs_or_projects_persona(client, admin_token):
    org_a, project_a, token_a = _setup(client, admin_token, "Stakeholder Rep Iso A Co")
    _, project_b, token_b = _setup(client, admin_token, "Stakeholder Rep Iso B Co")
    sibling = create_project(client, token_a, org_a["id"], "Stakeholder Rep Sibling")
    stakeholder = _create_project_stakeholder(client, token_a, project_a["id"])
    foreign = _create_project_persona(client, token_b, project_b["id"])
    sibling_persona = _create_project_persona(client, token_a, sibling["id"])
    url = f"{_project_base(project_a['id'])}/stakeholders/{stakeholder['id']}/personas"
    for persona in (foreign, sibling_persona):
        assert client.post(url, json={"persona_id": persona["id"]}, headers=auth_headers(token_a)).status_code == 404


# --- Erasure -----------------------------------------------------------------


def _count(db, model, **where) -> int:
    return db.scalar(select(func.count()).select_from(model).filter_by(**where))


def test_erase_leaves_no_rows_files_links_or_personal_data(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Erase Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    victim = _create_project_stakeholder(client, token, project["id"], name="Secret Name Person")
    bystander = _create_project_stakeholder(client, token, project["id"], name="Bystander")
    persona = _create_project_persona(client, token, project["id"])
    sid, url = victim["id"], f"{base}/stakeholders/{victim['id']}"

    client.put(url, json={"contact_info": "secret@example.com"}, headers=h)  # a second version
    client.post(f"{base}/stakeholders/{sid}/personas", json={"persona_id": persona["id"]}, headers=h)
    client.post(f"{base}/stakeholders/{bystander['id']}/personas", json={"persona_id": persona["id"]}, headers=h)
    comment = client.post(url + "/comments", json={"body": "private note"}, headers=h).json()
    comment_file = client.post(
        f"{url}/comments/{comment['id']}/files", files={"file": ("secret-letter.txt", b"c", "text/plain")}, headers=h,
    ).json()
    direct_file = client.post(url + "/files", files={"file": ("secret-cv.txt", b"d", "text/plain")}, headers=h).json()
    uuids = {uuid.UUID(sid), uuid.UUID(comment["id"])}
    with SessionLocal() as db:
        keys = [db.get(FileAsset, uuid.UUID(f["id"])).storage_key for f in (comment_file, direct_file)]
    for key in keys:
        assert get_storage_backend().read(key)

    assert client.delete(url, headers=h).status_code == 204
    assert client.get(url, headers=h).status_code == 404

    with SessionLocal() as db:
        assert _count(db, Stakeholder, id=uuid.UUID(sid)) == 0
        assert _count(db, StakeholderVersion, stakeholder_id=uuid.UUID(sid)) == 0
        assert _count(db, StakeholderComment, stakeholder_id=uuid.UUID(sid)) == 0
        assert _count(db, StakeholderCommentFile, comment_id=uuid.UUID(comment["id"])) == 0
        assert _count(db, StakeholderFile, stakeholder_id=uuid.UUID(sid)) == 0
        for f in (comment_file, direct_file):
            assert _count(db, FileAsset, id=uuid.UUID(f["id"])) == 0
        links = db.scalars(select(ArtefactLink).where(
            (ArtefactLink.source_id.in_(uuids)) | (ArtefactLink.target_id.in_(uuids))
        )).all()
        assert links == []
        # Another stakeholder's link to the same persona is untouched.
        assert _count(db, ArtefactLink, source_id=uuid.UUID(bystander["id"])) == 1
        # The audit trail records the erasure by id and actor only.
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == sid)).all()
        assert "erased" in {e.action for e in events}
        blob = " ".join(f"{e.action} {e.detail}" for e in events).lower()
        for needle in ("secret", "bystander", "private note", "letter", ".txt"):
            assert needle not in blob, needle
    for key in keys:
        try:
            get_storage_backend().read(key)
        except FileNotFoundError:
            continue
        raise AssertionError("file bytes survived erasure")
    # The bystander and persona survive.
    assert client.get(f"{base}/stakeholders/{bystander['id']}", headers=h).status_code == 200
    assert client.get(f"{base}/personas/{persona['id']}", headers=h).status_code == 200


def test_erase_org_stakeholder_and_authorisation(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Erase Auth Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "member@erase.example.com")
    org_stakeholder = _create_org_stakeholder(client, token, org["id"])
    project_stakeholder = _create_project_stakeholder(client, token, project["id"])
    org_url = f"{_org_base(org['id'])}/stakeholders/{org_stakeholder['id']}"
    project_url = f"{_project_base(project['id'])}/stakeholders/{project_stakeholder['id']}"
    for url in (org_url, project_url):
        assert client.delete(url, headers=auth_headers(member)).status_code == 403
    _grant_project_role(client, token, project["id"], user_id, "stakeholder_owner")
    assert client.delete(org_url, headers=auth_headers(member)).status_code == 403  # project role isn't org scope
    assert client.delete(project_url, headers=auth_headers(member)).status_code == 204
    assert client.delete(org_url, headers=auth_headers(token)).status_code == 204


def test_erase_is_404_across_tenants(client, admin_token):
    org_a, project_a, token_a = _setup(client, admin_token, "Stakeholder Erase Iso A Co")
    _, project_b, token_b = _setup(client, admin_token, "Stakeholder Erase Iso B Co")
    stakeholder = _create_project_stakeholder(client, token_a, project_a["id"])
    assert client.delete(
        f"{_project_base(project_b['id'])}/stakeholders/{stakeholder['id']}", headers=auth_headers(token_b)
    ).status_code == 404
    assert client.get(
        f"{_project_base(project_a['id'])}/stakeholders/{stakeholder['id']}", headers=auth_headers(token_a)
    ).status_code == 200


# --- RBAC --------------------------------------------------------------------


def test_plain_member_can_view_but_not_change(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Member Co")
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    _, member = _add_member(client, token, org["id"], project["id"], "member@member-s.example.com")
    h = auth_headers(member)
    base = _project_base(project["id"])
    sid = stakeholder["id"]
    assert client.get(base + "/stakeholders", headers=h).status_code == 200
    assert client.get(f"{base}/stakeholders/{sid}", headers=h).status_code == 200
    assert client.post(base + "/stakeholders", json=_PAYLOAD, headers=h).status_code == 403
    assert client.post(base + "/stakeholders/from-user", json={"user_id": str(uuid.uuid4())}, headers=h).status_code == 403
    assert client.put(f"{base}/stakeholders/{sid}", json={"priorities": "x"}, headers=h).status_code == 403
    assert client.post(f"{base}/stakeholders/{sid}/retire", headers=h).status_code == 403
    assert client.post(f"{base}/stakeholders/{sid}/archive", headers=h).status_code == 403
    assert client.post(f"{base}/stakeholders/{sid}/personas", json={"persona_id": str(uuid.uuid4())}, headers=h).status_code in (403, 404)
    assert client.post(base + "/stakeholder-types", json={"name": "Nope"}, headers=h).status_code == 403
    assert client.post(f"{base}/stakeholders/{sid}/comments", json={"body": "hi"}, headers=h).status_code == 201


def test_stakeholder_roles_are_scoped_correctly(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Roles Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "roles@roles-s.example.com")
    h = auth_headers(member)
    project_url = _project_base(project["id"]) + "/stakeholders"
    org_url = _org_base(org["id"]) + "/stakeholders"
    _grant_project_role(client, token, project["id"], user_id, "stakeholder_owner")
    assert client.post(project_url, json=_PAYLOAD, headers=h).status_code == 201
    assert client.post(org_url, json=_PAYLOAD, headers=h).status_code == 403
    _grant_org_role(client, token, org["id"], user_id, "org_stakeholder_owner")
    assert client.post(org_url, json=_PAYLOAD, headers=h).status_code == 201
    # A Persona role doesn't confer Stakeholder management.
    other_id, other = _add_member(client, token, org["id"], project["id"], "persona-only@roles-s.example.com")
    _grant_project_role(client, token, project["id"], other_id, "persona_owner")
    assert client.post(project_url, json=_PAYLOAD, headers=auth_headers(other)).status_code == 403


def test_stakeholder_type_admin_role_gates_types_and_scoring_configuration(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Type Admin Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "typeadmin@owner-s.example.com")
    h = auth_headers(member)
    types_url = _org_base(org["id"]) + "/stakeholder-types"
    level_url = f"/api/v1/orgs/{org['id']}/scoring-schemes/stakeholder/axes/influence/levels"
    new_level = {"name": "Critical", "weight": 4, "description": None}
    assert client.post(types_url, json={"name": "Mine"}, headers=h).status_code == 403
    assert client.post(level_url, json=new_level, headers=h).status_code == 403
    _grant_org_role(client, token, org["id"], user_id, "stakeholder_type_admin")
    assert client.post(types_url, json={"name": "Mine"}, headers=h).status_code == 201
    assert client.post(level_url, json=new_level, headers=h).status_code == 201


def test_fgac_manage_grant_satisfies_gate(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Fgac Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "fgac@owner-s.example.com")
    with SessionLocal() as db:
        role = CustomRoleDefinition(
            organization_id=uuid.UUID(org["id"]), name="Stakeholder editors", description="Test role.", scope="org",
        )
        db.add(role)
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=encode_permission("stakeholder", "manage")))
        db.add(UserCustomRoleGrant(user_id=uuid.UUID(user_id), custom_role_id=role.id, organization_id=uuid.UUID(org["id"])))
        db.commit()
    assert client.post(_org_base(org["id"]) + "/stakeholders", json=_PAYLOAD, headers=auth_headers(member)).status_code == 201


# --- Module gates and isolation ----------------------------------------------


def test_disabled_module_is_404_not_403(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Stakeholder Disabled Co")
    project = create_project(client, token, org["id"], "Stakeholder Disabled Project")
    assert client.get(_project_base(project["id"]) + "/stakeholders", headers=auth_headers(token)).status_code == 404
    assert client.get(_org_base(org["id"]) + "/stakeholders", headers=auth_headers(token)).status_code == 404


def test_disabling_stakeholder_subcomponent_leaves_personas_working(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Subcomponent Co")
    h = auth_headers(token)
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/stakeholders/subcomponents/stakeholder", json={"enabled": False}, headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert client.get(_project_base(project["id"]) + "/stakeholders", headers=h).status_code == 404
    assert client.get(_org_base(org["id"]) + "/stakeholders", headers=h).status_code == 404
    assert client.get(_project_base(project["id"]) + "/personas", headers=h).status_code == 200


def test_cross_tenant_stakeholder_is_404(client, admin_token):
    org_a, project_a, token_a = _setup(client, admin_token, "Stakeholder Iso A Co")
    org_b, project_b, token_b = _setup(client, admin_token, "Stakeholder Iso B Co")
    org_stakeholder = _create_org_stakeholder(client, token_a, org_a["id"])
    project_stakeholder = _create_project_stakeholder(client, token_a, project_a["id"])
    hb = auth_headers(token_b)
    for url in (
        f"{_org_base(org_b['id'])}/stakeholders/{org_stakeholder['id']}",
        f"{_project_base(project_b['id'])}/stakeholders/{org_stakeholder['id']}",
        f"{_project_base(project_b['id'])}/stakeholders/{project_stakeholder['id']}",
        f"{_project_base(project_b['id'])}/stakeholders/{project_stakeholder['id']}/comments",
        f"{_project_base(project_b['id'])}/stakeholders/{project_stakeholder['id']}/versions",
    ):
        assert client.get(url, headers=hb).status_code == 404, url


def test_project_stakeholder_not_visible_from_sibling_project(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Stakeholder Sibling Co")
    project_b = create_project(client, token, org["id"], "Stakeholder Sibling Project B")
    stakeholder = _create_project_stakeholder(client, token, project_a["id"])
    assert client.get(
        f"{_project_base(project_b['id'])}/stakeholders/{stakeholder['id']}", headers=auth_headers(token)
    ).status_code == 404


# --- Comments, files and the file-owner hook ---------------------------------


def test_comments_author_only_edit_and_attachments(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Comments Co")
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    _, member = _add_member(client, token, org["id"], project["id"], "commenter@c-s.example.com")
    base = f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}/comments"
    comment = client.post(base, json={"body": "first"}, headers=auth_headers(member)).json()
    assert comment["stakeholder_id"] == stakeholder["id"] and comment["author_display_name"] == "commenter"
    assert client.patch(f"{base}/{comment['id']}", json={"body": "hijack"}, headers=auth_headers(token)).status_code == 403
    edited = client.patch(f"{base}/{comment['id']}", json={"body": "edited"}, headers=auth_headers(member)).json()
    assert edited["body"] == "edited" and edited["edited_at"] is not None
    up = client.post(
        f"{base}/{comment['id']}/files", files={"file": ("n.txt", b"hello", "text/plain")}, headers=auth_headers(member),
    )
    assert up.status_code == 201, up.text
    assert len(client.get(base, headers=auth_headers(member)).json()[0]["attachments"]) == 1
    assert client.delete(f"{base}/{comment['id']}/files/{up.json()['id']}", headers=auth_headers(token)).status_code == 403
    assert client.delete(f"{base}/{comment['id']}/files/{up.json()['id']}", headers=auth_headers(member)).status_code == 204


def test_direct_file_attachment_project_and_org(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Files Co")
    h = auth_headers(token)
    for stakeholder, base in (
        (_create_project_stakeholder(client, token, project["id"]), f"{_project_base(project['id'])}/stakeholders"),
        (_create_org_stakeholder(client, token, org["id"]), f"{_org_base(org['id'])}/stakeholders"),
    ):
        up = client.post(f"{base}/{stakeholder['id']}/files", files={"file": ("a.txt", b"x", "text/plain")}, headers=h)
        assert up.status_code == 201, up.text
        assert len(client.get(f"{base}/{stakeholder['id']}/files", headers=h).json()) == 1
        # Downloadable by a project/org member, i.e. the ownership hook resolves.
        assert client.get(f"/api/v1/files/{up.json()['id']}", headers=h).status_code == 200
        assert client.delete(f"{base}/{stakeholder['id']}/files/{up.json()['id']}", headers=h).status_code == 204
        assert client.get(f"{base}/{stakeholder['id']}/files", headers=h).json() == []


def test_file_download_is_denied_to_another_projects_member(client, admin_token):
    org, project_a, token = _setup(client, admin_token, "Stakeholder File Iso Co")
    project_b = create_project(client, token, org["id"], "Stakeholder File Iso B")
    stakeholder = _create_project_stakeholder(client, token, project_a["id"])
    up = client.post(
        f"{_project_base(project_a['id'])}/stakeholders/{stakeholder['id']}/files",
        files={"file": ("a.txt", b"x", "text/plain")}, headers=auth_headers(token),
    ).json()
    _, member_b = _add_member(client, token, org["id"], project_b["id"], "b-only@file-iso.example.com")
    assert client.get(f"/api/v1/files/{up['id']}", headers=auth_headers(member_b)).status_code in (403, 404)


# --- Organisation deletion ---------------------------------------------------


def test_deleting_an_org_removes_typed_personas_and_stakeholders(client, admin_token):
    """Every record carries a type reference into its org's own type tables, which cascade-delete with the org at
    the same time — so those foreign keys must not block the cascade (they are `ON DELETE SET NULL`)."""
    org, project, token = _setup(client, admin_token, "Stakeholder Org Delete Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    org_persona_type = client.get(_org_base(org["id"]) + "/persona-types", headers=h).json()[0]
    org_stakeholder_type = client.get(_org_base(org["id"]) + "/stakeholder-types", headers=h).json()[0]
    project_type = client.post(base + "/stakeholder-types", json={"name": "Local"}, headers=h).json()
    _create_org_persona(client, token, org["id"], persona_type_id=org_persona_type["id"])
    _create_org_stakeholder(client, token, org["id"], stakeholder_type_id=org_stakeholder_type["id"])
    _create_project_stakeholder(client, token, project["id"], stakeholder_type_id=project_type["id"])
    _create_project_persona(client, token, project["id"], persona_type_id=org_persona_type["id"])

    resp = client.request(
        "DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Stakeholder)) == 0
        assert db.scalar(select(func.count()).select_from(StakeholderVersion)) == 0


# --- Audit and registration --------------------------------------------------


def test_every_mutating_action_is_audit_logged_without_personal_data(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Audit Co")
    h = auth_headers(token)
    base = _project_base(project["id"])
    persona = _create_project_persona(client, token, project["id"])
    stakeholder = _create_project_stakeholder(client, token, project["id"], name="Audited Person Name")
    sid = f"{base}/stakeholders/{stakeholder['id']}"

    client.put(sid, json={"priorities": "x"}, headers=h)
    client.post(sid + "/activate", headers=h)
    client.post(sid + "/retire", headers=h)
    client.post(sid + "/archive", headers=h)
    client.post(sid + "/unarchive", headers=h)
    client.post(sid + "/personas", json={"persona_id": persona["id"]}, headers=h)
    client.delete(f"{sid}/personas/{persona['id']}", headers=h)
    comment = client.post(sid + "/comments", json={"body": "a"}, headers=h).json()
    client.patch(f"{sid}/comments/{comment['id']}", json={"body": "b"}, headers=h)
    up = client.post(f"{sid}/comments/{comment['id']}/files", files={"file": ("person-cv.txt", b"x", "text/plain")}, headers=h).json()
    client.delete(f"{sid}/comments/{comment['id']}/files/{up['id']}", headers=h)
    up2 = client.post(sid + "/files", files={"file": ("person-id.txt", b"x", "text/plain")}, headers=h).json()
    client.delete(f"{sid}/files/{up2['id']}", headers=h)
    local = client.post(base + "/stakeholder-types", json={"name": "Audit local"}, headers=h).json()
    client.put(f"{base}/stakeholder-types/{local['id']}", json={"is_enabled": False}, headers=h)
    client.delete(f"{base}/stakeholder-types/{local['id']}", headers=h)
    org_type = client.post(_org_base(org["id"]) + "/stakeholder-types", json={"name": "Audit org"}, headers=h).json()
    client.patch(f"{_org_base(org['id'])}/stakeholder-types/{org_type['id']}", json={"is_active": False}, headers=h)
    client.delete(f"{_org_base(org['id'])}/stakeholder-types/{org_type['id']}", headers=h)

    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == stakeholder["id"])).all()
        type_actions = {
            (e.entity_type, e.action) for e in db.scalars(
                select(AuditEvent).where(AuditEvent.entity_type.in_(["project_stakeholder_type", "stakeholder_type_definition"]))
            )
        }
    assert {e.action for e in events} >= {
        "created", "updated", "activated", "retired", "archived", "unarchived", "represents_added",
        "represents_removed", "comment_added", "comment_edited", "comment_file_attached", "comment_file_removed",
        "file_attached", "file_unlinked",
    }
    blob = " ".join(str(e.detail) for e in events).lower()
    assert "audited person" not in blob and "person-cv" not in blob and "person-id" not in blob
    assert type_actions >= {
        ("project_stakeholder_type", "created"), ("project_stakeholder_type", "updated"),
        ("project_stakeholder_type", "deleted"), ("stakeholder_type_definition", "created"),
        ("stakeholder_type_definition", "updated"), ("stakeholder_type_definition", "deleted"),
    }


def test_stakeholder_is_a_registered_artefact_type_and_scoring_scheme():
    from app.modules.registry import get_all_registered_artefact_types, get_all_registered_scoring_schemes

    assert "stakeholder" in get_all_registered_artefact_types()
    scheme = get_all_registered_scoring_schemes()["stakeholder"]
    assert scheme.module_key == "stakeholders"
    assert [a.key for a in scheme.scheme.axes] == ["influence", "interest"]
