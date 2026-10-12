"""Tests for the Risk Management module's Phase 1 project API
(docs/plans/module-03-risk-management-plan.md), through the real HTTP endpoints.

Covers: create/read/list, identifiers, partial update and clearing, version
history, status being read-only, reference validation (levels, owner, type),
archive, RBAC (any member proposes; manager edits; FGAC grant), module and
sub-component gates, cross-tenant isolation, comments and files, audit logging,
org deletion and registration.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.modules.risk_management.models import Risk, RiskVersion
from app.modules.risk_management.tests._helpers import (
    PAYLOAD,
    add_member,
    create_risk,
    grant_org_role,
    grant_project_role,
    levels,
    project_base,
    setup,
    user_ref,
)
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project


def _risks(project_id) -> str:
    return project_base(project_id) + "/risks"


# --- CRUD, versions ----------------------------------------------------------


def test_create_assigns_sequential_codes_and_starts_identified_and_unscored(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Create Co")
    first = create_risk(client, token, project["id"])
    second = create_risk(client, token, project["id"], title="Second")
    assert (first["unique_code"], second["unique_code"]) == ("RSK-001", "RSK-002")
    assert first["status"] == "identified" and first["version_number"] == 1 and first["project_id"] == project["id"]
    assert first["title"] == PAYLOAD["title"] and first["statement"] == PAYLOAD["statement"]
    assert first["inherent_rating"] is None and first["residual_rating"] is None
    assert first["risk_type_id"] is None and first["treatment_strategy"] is None and first["owner"] is None
    assert [r["unique_code"] for r in client.get(_risks(project["id"]), headers=auth_headers(token)).json()] == ["RSK-001", "RSK-002"]
    assert client.get(f"{_risks(project['id'])}/{first['id']}", headers=auth_headers(token)).json()["id"] == first["id"]


def test_codes_are_per_project(client, admin_token):
    org, project_a, token = setup(client, admin_token, "Risk Codes Co")
    project_b = create_project(client, token, org["id"], "Risk Codes B")
    create_risk(client, token, project_a["id"])
    assert create_risk(client, token, project_b["id"])["unique_code"] == "RSK-001"


def test_title_is_required(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Title Co")
    resp = client.post(_risks(project["id"]), json={"statement": "x"}, headers=auth_headers(token))
    assert resp.status_code == 422
    assert client.post(_risks(project["id"]), json={"title": ""}, headers=auth_headers(token)).status_code == 422


def test_partial_update_versions_history_and_clearing(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Update Co")
    h = auth_headers(token)
    risk = create_risk(client, token, project["id"], treatment_strategy="mitigate", review_date="2026-12-01")
    owner = create_org_user(client, token, org["id"], "owner@risk-update.example.com")
    url = f"{_risks(project['id'])}/{risk['id']}"

    resp = client.put(url, json={"cause": "Refined cause", "owner": user_ref(owner), "change_note": "why"}, headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cause"] == "Refined cause" and body["owner"]["id"] == owner and body["owner"]["label"] and body["version_number"] == 2
    assert body["title"] == PAYLOAD["title"] and body["treatment_strategy"] == "mitigate"  # carried forward
    assert body["review_date"] == "2026-12-01"

    cleared = client.put(url, json={"treatment_strategy": None, "owner": None, "review_date": None, "statement": None}, headers=h).json()
    assert cleared["treatment_strategy"] is None and cleared["owner"] is None and cleared["review_date"] is None
    assert cleared["statement"] == "" and cleared["version_number"] == 3

    versions = client.get(url + "/versions", headers=h).json()
    assert [v["version_number"] for v in versions] == [1, 2, 3]
    assert versions[1]["change_note"] == "why" and versions[0]["cause"] == PAYLOAD["cause"] and versions[2]["valid_to"] is None
    assert client.put(url, json={"title": None}, headers=h).status_code == 422


def test_status_is_not_editable_through_update(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Status Co")
    risk = create_risk(client, token, project["id"])
    resp = client.put(f"{_risks(project['id'])}/{risk['id']}", json={"status": "closed", "title": "Renamed"}, headers=auth_headers(token))
    assert resp.status_code == 200 and resp.json()["status"] == "identified" and resp.json()["title"] == "Renamed"
    resp = client.post(_risks(project["id"]), json={**PAYLOAD, "status": "closed"}, headers=auth_headers(token))
    assert resp.json()["status"] == "identified"


def test_an_edit_waits_for_a_concurrent_edit_instead_of_failing(client, admin_token):
    """Edits close the current version and insert the next, so two unserialised
    edits would collide on the version number (a 500). The update takes the risk's
    row lock first: held here by another transaction, the edit must block, then
    apply once it is released."""
    import threading

    _, project, token = setup(client, admin_token, "Risk Lock Co")
    risk = create_risk(client, token, project["id"])
    url = f"{_risks(project['id'])}/{risk['id']}"
    result: dict = {}

    def edit() -> None:
        result["response"] = client.put(url, json={"cause": "after the lock"}, headers=auth_headers(token))

    with SessionLocal() as holder:
        holder.execute(select(Risk.id).where(Risk.id == uuid.UUID(risk["id"])).with_for_update())
        worker = threading.Thread(target=edit)
        worker.start()
        worker.join(timeout=2)
        assert worker.is_alive(), "the edit finished while another transaction held the risk's row lock"
        holder.rollback()
    worker.join(timeout=30)
    assert result["response"].status_code == 200, result["response"].text
    assert result["response"].json()["version_number"] == 2


def test_archive_and_unarchive(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Archive Co")
    h = auth_headers(token)
    risk = create_risk(client, token, project["id"])
    url = f"{_risks(project['id'])}/{risk['id']}"
    assert client.post(url + "/archive", headers=h).json()["is_archived"] is True
    assert client.get(_risks(project["id"]), headers=h).json() == []
    assert len(client.get(_risks(project["id"]) + "?include_archived=true", headers=h).json()) == 1
    assert client.post(url + "/unarchive", headers=h).json()["is_archived"] is False
    assert len(client.get(_risks(project["id"]), headers=h).json()) == 1


# --- Reference validation ----------------------------------------------------


def test_levels_must_be_the_organisations_and_on_the_right_axis(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Levels Co")
    _, other_project, other_token = setup(client, admin_token, "Risk Levels Other Co")
    mine = levels(client, token, project["id"])
    theirs = levels(client, other_token, other_project["id"])
    h = auth_headers(token)
    ok = client.post(_risks(project["id"]), json={**PAYLOAD, "inherent_likelihood_level_id": mine["likelihood"]["Likely"]}, headers=h)
    assert ok.status_code == 201, ok.text
    for field, level_id in (
        ("inherent_likelihood_level_id", theirs["likelihood"]["Likely"]),  # another organisation's level
        ("inherent_likelihood_level_id", mine["consequence"]["Major"]),  # right org, wrong axis
        ("residual_detectability_level_id", mine["likelihood"]["Rare"]),
        ("inherent_consequence_level_id", str(uuid.uuid4())),  # unknown
    ):
        resp = client.post(_risks(project["id"]), json={**PAYLOAD, field: level_id}, headers=h)
        assert resp.status_code == 400, (field, resp.text)
    risk = ok.json()
    resp = client.put(f"{_risks(project['id'])}/{risk['id']}", json={"residual_consequence_level_id": theirs["consequence"]["Minor"]}, headers=h)
    assert resp.status_code == 400


def test_owner_must_belong_to_the_organisation(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Owner Co")
    other_org, other_token = create_org_admin_in(client, admin_token, "Risk Owner Other Co")
    outsider = create_org_user(client, other_token, other_org["id"], "outsider@risk-owner.example.com")
    insider = create_org_user(client, token, org["id"], "insider@risk-owner.example.com")
    h = auth_headers(token)
    assert client.post(_risks(project["id"]), json={**PAYLOAD, "owner": user_ref(outsider)}, headers=h).status_code == 400
    assert client.post(_risks(project["id"]), json={**PAYLOAD, "owner": user_ref(insider)}, headers=h).json()["owner"]["id"] == insider


# --- Types -------------------------------------------------------------------


def test_default_types_are_seeded_and_a_risk_can_use_one(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Types Co")
    h = auth_headers(token)
    effective = client.get(project_base(project["id"]) + "/risk-types", headers=h).json()
    assert [t["name"] for t in effective][:3] == ["Safety", "Technical", "Reliability"] and len(effective) == 12
    safety = next(t for t in effective if t["name"] == "Safety")
    risk = create_risk(client, token, project["id"], risk_type_id=safety["id"])
    assert risk["risk_type_name"] == "Safety" and risk["risk_type_id"] is not None
    assert client.put(f"{_risks(project['id'])}/{risk['id']}", json={"risk_type_id": None}, headers=h).json()["risk_type_name"] is None
    assert client.post(_risks(project["id"]), json={**PAYLOAD, "risk_type_id": str(uuid.uuid4())}, headers=h).status_code == 400

    # Another organisation's type (a real id, but not this project's to use) is rejected too.
    other_org, other_project, other_token = setup(client, admin_token, "Risk Types Other Co")
    foreign = client.get(project_base(other_project["id"]) + "/risk-types", headers=auth_headers(other_token)).json()[0]["id"]
    assert client.post(_risks(project["id"]), json={**PAYLOAD, "risk_type_id": foreign}, headers=h).status_code == 400
    assert client.put(f"{_risks(project['id'])}/{risk['id']}", json={"risk_type_id": foreign}, headers=h).status_code == 400


def test_project_can_rename_disable_add_and_delete_types(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Project Types Co")
    h = auth_headers(token)
    base = project_base(project["id"]) + "/risk-types"
    effective = client.get(base, headers=h).json()
    safety = next(t for t in effective if t["name"] == "Safety")
    cost = next(t for t in effective if t["name"] == "Cost")
    risk = create_risk(client, token, project["id"], risk_type_id=safety["id"])

    renamed = client.put(f"{base}/{safety['id']}", json={"name": "Safety & Health"}, headers=h)
    assert renamed.status_code == 200, renamed.text
    assert client.get(f"{_risks(project['id'])}/{risk['id']}", headers=h).json()["risk_type_name"] == "Safety & Health"

    assert client.put(f"{base}/{cost['id']}", json={"is_enabled": False}, headers=h).status_code == 200
    assert client.post(_risks(project["id"]), json={**PAYLOAD, "risk_type_id": cost["id"]}, headers=h).status_code == 400

    local = client.post(base, json={"name": "Regulatory"}, headers=h)
    assert local.status_code == 201, local.text
    assert client.post(base, json={"name": "Regulatory"}, headers=h).status_code == 400
    used = create_risk(client, token, project["id"], risk_type_id=local.json()["id"])
    assert client.delete(f"{base}/{local.json()['id']}", headers=h).status_code == 409
    client.put(f"{_risks(project['id'])}/{used['id']}", json={"risk_type_id": None}, headers=h)
    # Versions are history: a type a past version used stays protected, so removal stays blocked.
    assert client.delete(f"{base}/{local.json()['id']}", headers=h).status_code == 409
    unused = client.post(base, json={"name": "Unused"}, headers=h).json()
    assert client.delete(f"{base}/{unused['id']}", headers=h).status_code == 204
    assert client.delete(f"{base}/{unused['id']}", headers=h).status_code == 404


def test_org_type_admin_manages_the_org_vocabulary(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Org Types Co")
    h = auth_headers(token)
    base = f"/api/v1/orgs/{org['id']}/modules/risk_management/risk-types"
    listed = client.get(base, headers=h).json()
    assert len(listed) == 12 and listed[0]["name"] == "Safety"

    created = client.post(base, json={"name": "Ethical"}, headers=h)
    assert created.status_code == 201, created.text
    assert client.post(base, json={"name": "Ethical"}, headers=h).status_code == 400
    type_id = created.json()["id"]
    assert client.patch(f"{base}/{type_id}", json={"name": "Ethics"}, headers=h).json()["name"] == "Ethics"
    assert client.patch(f"{base}/{type_id}", json={"name": "Safety"}, headers=h).status_code == 400
    moved = client.post(f"{base}/{type_id}/move", json={"direction": "up"}, headers=h)
    assert moved.status_code == 200, moved.text
    assert client.patch(f"{base}/{type_id}", json={"is_active": False}, headers=h).json()["is_active"] is False
    project_types = client.get(project_base(project["id"]) + "/risk-types", headers=h).json()
    assert "Ethics" not in [t["name"] for t in project_types]  # inactive types leave every project's list
    assert client.delete(f"{base}/{type_id}", headers=h).status_code == 204

    # An org type a project has overridden (or used) cannot be removed from under it.
    safety = listed[0]["id"]
    effective = client.get(project_base(project["id"]) + "/risk-types", headers=h).json()
    create_risk(client, token, project["id"], risk_type_id=next(t["id"] for t in effective if t["name"] == "Safety"))
    assert client.delete(f"{base}/{safety}", headers=h).status_code == 409


def test_type_admin_role_gates_org_type_changes(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Type Admin Co")
    user_id, member = add_member(client, token, org["id"], project["id"], "member@risk-type-admin.example.com")
    base = f"/api/v1/orgs/{org['id']}/modules/risk_management/risk-types"
    h = auth_headers(member)
    assert client.get(base, headers=h).status_code == 200
    assert client.post(base, json={"name": "Nope"}, headers=h).status_code == 403
    grant_org_role(client, token, org["id"], user_id, "risk_type_admin")
    assert client.post(base, json={"name": "Allowed"}, headers=h).status_code == 201


# --- RBAC --------------------------------------------------------------------


def test_any_member_proposes_but_only_a_manager_edits(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rbac Co")
    risk = create_risk(client, token, project["id"])
    user_id, member = add_member(client, token, org["id"], project["id"], "member@risk-rbac.example.com")
    h = auth_headers(member)
    url = f"{_risks(project['id'])}/{risk['id']}"
    assert client.get(url, headers=h).status_code == 200
    assert client.get(_risks(project["id"]), headers=h).status_code == 200
    proposed = client.post(_risks(project["id"]), json=PAYLOAD, headers=h)
    assert proposed.status_code == 201 and proposed.json()["creator_id"] == user_id

    type_id = client.get(project_base(project["id"]) + "/risk-types", headers=h).json()[0]["id"]
    for method, path, body in (
        ("put", url, {"title": "x"}), ("post", url + "/archive", None), ("post", url + "/unarchive", None),
        ("post", project_base(project["id"]) + "/risk-types", {"name": "Local"}),
        ("put", f"{project_base(project['id'])}/risk-types/{type_id}", {"name": "Renamed"}),
        ("delete", f"{project_base(project['id'])}/risk-types/{uuid.uuid4()}", None),
    ):
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, headers=h, **kwargs).status_code == 403, path
    assert client.post(url + "/files", files={"file": ("a.txt", b"x", "text/plain")}, headers=h).status_code == 403

    grant_project_role(client, token, project["id"], user_id, "risk_manager")
    assert client.put(url, json={"title": "Edited"}, headers=h).json()["title"] == "Edited"


def test_other_module_roles_confer_nothing_on_risks(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Role Iso Co")
    risk = create_risk(client, token, project["id"])
    user_id, member = add_member(client, token, org["id"], project["id"], "other@risk-iso.example.com")
    grant_org_role(client, token, org["id"], user_id, "risk_type_admin")
    resp = client.put(f"{_risks(project['id'])}/{risk['id']}", json={"title": "x"}, headers=auth_headers(member))
    assert resp.status_code == 403


def test_fgac_manage_grant_satisfies_the_gate(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Fgac Co")
    risk = create_risk(client, token, project["id"])
    user_id, member = add_member(client, token, org["id"], project["id"], "fgac@risk.example.com")
    with SessionLocal() as db:
        role = CustomRoleDefinition(organization_id=uuid.UUID(org["id"]), name="Risk editors", description="Test.", scope="org")
        db.add(role)
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=encode_permission("risk", "manage")))
        db.add(UserCustomRoleGrant(user_id=uuid.UUID(user_id), custom_role_id=role.id, organization_id=uuid.UUID(org["id"])))
        db.commit()
    resp = client.put(f"{_risks(project['id'])}/{risk['id']}", json={"title": "Via FGAC"}, headers=auth_headers(member))
    assert resp.status_code == 200, resp.text


def test_disabled_module_and_subcomponent_are_404(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Risk Disabled Co")
    project = create_project(client, token, org["id"], "Risk Disabled Project")
    assert client.get(_risks(project["id"]), headers=auth_headers(token)).status_code == 404

    org2, project2, token2 = setup(client, admin_token, "Risk Subcomponent Co")
    h = auth_headers(token2)
    assert client.get(_risks(project2["id"]), headers=h).status_code == 200
    resp = client.put(f"/api/v1/orgs/{org2['id']}/modules/risk_management/subcomponents/risk", json={"enabled": False}, headers=h)
    assert resp.status_code == 200, resp.text
    assert client.get(_risks(project2["id"]), headers=h).status_code == 404


def test_non_members_and_other_tenants_get_404(client, admin_token):
    org_a, project_a, token_a = setup(client, admin_token, "Risk Iso A Co")
    org_b, project_b, token_b = setup(client, admin_token, "Risk Iso B Co")
    sibling = create_project(client, token_a, org_a["id"], "Risk Iso Sibling")
    risk = create_risk(client, token_a, project_a["id"])
    for token, project_id in ((token_b, project_a["id"]), (token_b, project_b["id"]), (token_a, sibling["id"])):
        for suffix in ("", "/versions", "/comments", "/files"):
            resp = client.get(f"{_risks(project_id)}/{risk['id']}{suffix}", headers=auth_headers(token))
            assert resp.status_code == 404, (project_id, suffix)
    assert client.post(_risks(project_a["id"]), json=PAYLOAD, headers=auth_headers(token_b)).status_code == 404


# --- Comments, files ---------------------------------------------------------


def test_comments_and_files(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Attach Co")
    risk = create_risk(client, token, project["id"])
    _, member = add_member(client, token, org["id"], project["id"], "commenter@risk.example.com")
    base = f"{_risks(project['id'])}/{risk['id']}"
    comment = client.post(base + "/comments", json={"body": "first"}, headers=auth_headers(member)).json()
    assert comment["risk_id"] == risk["id"] and comment["author_display_name"]
    assert client.patch(f"{base}/comments/{comment['id']}", json={"body": "x"}, headers=auth_headers(token)).status_code == 403
    edited = client.patch(f"{base}/comments/{comment['id']}", json={"body": "edited"}, headers=auth_headers(member)).json()
    assert edited["body"] == "edited" and edited["edited_at"] is not None
    up = client.post(f"{base}/comments/{comment['id']}/files", files={"file": ("n.txt", b"hello", "text/plain")}, headers=auth_headers(member))
    assert up.status_code == 201, up.text
    assert client.get(f"/api/v1/files/{up.json()['id']}", headers=auth_headers(member)).status_code == 200
    assert len(client.get(base + "/comments", headers=auth_headers(token)).json()[0]["attachments"]) == 1
    assert client.delete(f"{base}/comments/{comment['id']}/files/{up.json()['id']}", headers=auth_headers(member)).status_code == 204

    h = auth_headers(token)
    direct = client.post(base + "/files", files={"file": ("e.txt", b"evidence", "text/plain")}, headers=h)
    assert direct.status_code == 201, direct.text
    assert len(client.get(base + "/files", headers=h).json()) == 1
    assert client.get(f"/api/v1/files/{direct.json()['id']}", headers=h).status_code == 200
    assert client.delete(f"{base}/files/{direct.json()['id']}", headers=h).status_code == 204
    assert client.delete(f"{base}/files/{direct.json()['id']}", headers=h).status_code == 404


# --- Audit, org deletion, registration ---------------------------------------


def test_every_mutating_action_is_audit_logged(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Audit Co")
    h = auth_headers(token)
    risk = create_risk(client, token, project["id"])
    url = f"{_risks(project['id'])}/{risk['id']}"
    client.put(url, json={"cause": "x"}, headers=h)
    client.post(url + "/archive", headers=h)
    client.post(url + "/unarchive", headers=h)
    comment = client.post(url + "/comments", json={"body": "a"}, headers=h).json()
    client.patch(f"{url}/comments/{comment['id']}", json={"body": "b"}, headers=h)
    local = client.post(project_base(project["id"]) + "/risk-types", json={"name": "Audited"}, headers=h).json()
    client.put(f"{project_base(project['id'])}/risk-types/{local['id']}", json={"name": "Audited 2"}, headers=h)
    client.delete(f"{project_base(project['id'])}/risk-types/{local['id']}", headers=h)
    with SessionLocal() as db:
        actions = {e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_id == risk["id"]))}
        type_actions = {e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "project_risk_type"))}
    assert actions >= {"created", "updated", "archived", "unarchived", "comment_added", "comment_edited"}
    assert type_actions >= {"created", "updated", "deleted"}


def test_deleting_an_org_removes_risks(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Org Delete Co")
    risk = create_risk(client, token, project["id"])
    client.post(f"{_risks(project['id'])}/{risk['id']}/comments", json={"body": "bye"}, headers=auth_headers(token))
    resp = client.request("DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]}, headers=auth_headers(admin_token))
    assert resp.status_code == 204, resp.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Risk).where(Risk.id == uuid.UUID(risk["id"]))) == 0
        assert db.scalar(select(func.count()).select_from(RiskVersion).where(RiskVersion.risk_id == uuid.UUID(risk["id"]))) == 0


def test_risk_is_a_registered_artefact_type_with_roles_and_scheme():
    from app.modules.registry import get_all_registered_artefact_types, get_all_registered_scoring_schemes
    from app.modules.risk_management.module import MODULE_DEFINITION

    assert "risk" in get_all_registered_artefact_types()
    assert "risk" in get_all_registered_scoring_schemes()
    roles = {r.role_key: r for r in MODULE_DEFINITION.roles}
    assert roles["risk_manager"].scope == "project" and roles["risk_manager"].permissions
    assert roles["risk_type_admin"].scope == "org"
    assert [s.key for s in MODULE_DEFINITION.sub_components] == ["risk"]


def test_the_project_nav_offers_the_risk_register(client, admin_token):
    """Phase 5: the module's `frontend_manifest` puts a "Risks" nav entry pointing at the register route the
    frontend serves (`frontend/src/modules/risk_management/module.ts`)."""
    _, project, token = setup(client, admin_token, "Risk Nav Co")
    resp = client.get(f"/api/v1/projects/{project['id']}/enabled-modules", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    manifest = next(m for m in resp.json() if m["module_key"] == "risk_management")["frontend_manifest"]
    assert manifest["tier"] == "installed" and manifest["nav_label"] == "Risks"
    assert manifest["nav_path"] == f"/projects/{project['id']}/modules/risk_management/risks"
    assert manifest["nav_icon"] == "shield-alert"
