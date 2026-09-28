"""Tests for Context & Strategy's Phase 3 backend API
(docs/plans/module-01-context-and-strategy-plan.md Phase 3 — Pain Points)
— the real HTTP endpoints (`router.py`'s org-scoped Pain Point type CRUD,
`project_router.py`'s project-scoped Pain Point/type-override surface),
through the `client` fixture, mirroring `test_context_strategy_future_
state_api.py`'s own "go through the real API" convention. A new sibling
file rather than appending to either existing one (Decided by: Agent,
following Phase 2's own precedent for the same reason: one file per
artefact type reads more cleanly than a single ever-growing combined file).

Covers: Pain Point create/get (project-scoped only — no org-scoped Pain
Point resource), the broad-creation permission model (any project member,
§6.5), the two-tier type vocabulary (org `PainPointTypeDefinition` CRUD via
`router.py`, project `ProjectPainPointType` overrides/local types via
`project_router.py`, and the merged effective-list resolution), the
branching lifecycle (`Submitted -> Triaged -> {Rejected | Duplicate |
Accepted -> Addressed -> Closed}`, all three post-Triaged branches),
manager-only actions 403ing for a plain member, a Fine-Grained Access
Control custom-role permission grant satisfying the decide gate,
disabled-module/sub-component 404s, cross-project isolation, and
comments/direct file attachments (including the deliberately-broad
"any member may add evidence" file-upload gate).
"""

from __future__ import annotations

import uuid

from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

MODULE_KEY = "context_strategy"


# --- Small API helpers -------------------------------------------------------


def _enable_module(client, org_admin_token, org_id) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text


def _org_base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/modules/context_strategy"


def _project_base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/modules/context_strategy"


def _setup(client, admin_token, org_name: str):
    """Creates an org (with a real org_admin), a project (the org_admin
    becomes its `PROJECT_MANAGER`), and enables Context & Strategy for the
    organisation. Returns (org, project, org_admin_token)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, org_name)
    _enable_module(client, org_admin_token, org["id"])
    project = create_project(client, org_admin_token, org["id"], f"{org_name} Project")
    return org, project, org_admin_token


def _add_plain_member(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
    user_id = create_org_user(client, org_admin_token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _grant_project_module_role(client, org_admin_token, project_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/projects/{project_id}/members/{user_id}/module-roles",
        json={"module_key": MODULE_KEY, "role_key": role_key},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text


def _grant_org_module_role(client, org_admin_token, org_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": MODULE_KEY, "role_key": role_key},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text


def _list_effective_types(client, token, project_id) -> list[dict]:
    resp = client.get(_project_base(project_id) + "/pain-point-types", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _market_type_id(client, token, project_id) -> str:
    types = _list_effective_types(client, token, project_id)
    market = next(t for t in types if t["name"] == "Market")
    return market["id"]


_PAYLOAD_FIELDS = {
    "title": "Manual inspection reports are frequently delayed past SLA",
    "description": "Field inspectors submit reports via paper forms, re-keyed days later.",
    "source": "Customer support ticket #481",
    "impact": "Utility customers routinely miss their own regulatory reporting windows.",
    "evidence": "14 SLA-breach tickets in the last quarter, all citing report delay as root cause.",
    "priority": "high",
    "date_identified": "2026-09-01",
}


def _create_pain_point(client, token, project_id, *, type_id: str | None = None, **extra) -> dict:
    if type_id is None:
        type_id = _market_type_id(client, token, project_id)
    payload = {**_PAYLOAD_FIELDS, "pain_point_type_id": type_id, **extra}
    resp = client.post(_project_base(project_id) + "/pain-points", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_to_triaged(client, token, project_id, pain_point_id) -> dict:
    resp = client.post(
        f"{_project_base(project_id)}/pain-points/{pain_point_id}/triage", json={}, headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Org-scoped Pain Point type vocabulary -----------------------------------


def test_org_default_pain_point_types_seeded_on_org_creation(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "PainPoint Default Types Co")
    _enable_module(client, org_admin_token, org["id"])
    resp = client.get(_org_base(org["id"]) + "/pain-point-types", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    names = {t["name"] for t in resp.json()}
    assert names == {"Market", "User", "Operator"}


def test_org_pain_point_type_admin_can_create_rename_move_and_delete(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "PainPoint Type Admin Co")
    _enable_module(client, org_admin_token, org["id"])

    resp = client.post(
        _org_base(org["id"]) + "/pain-point-types", json={"name": "Regulatory"}, headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 201, resp.text
    type_id = resp.json()["id"]

    resp = client.patch(
        f"{_org_base(org['id'])}/pain-point-types/{type_id}", json={"name": "Regulatory/Compliance"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Regulatory/Compliance"

    resp = client.post(
        f"{_org_base(org['id'])}/pain-point-types/{type_id}/move", json={"direction": "up"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.delete(f"{_org_base(org['id'])}/pain-point-types/{type_id}", headers=auth_headers(org_admin_token))
    assert resp.status_code == 204, resp.text


def test_plain_org_member_cannot_manage_org_pain_point_types(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "PainPoint Type Admin RBAC Co")
    _enable_module(client, org_admin_token, org["id"])
    create_org_user(client, org_admin_token, org["id"], "pp_type_plain@example.com")
    plain_token = login(client, "pp_type_plain@example.com", "Password123!")

    resp = client.post(
        _org_base(org["id"]) + "/pain-point-types", json={"name": "Regulatory"}, headers=auth_headers(plain_token)
    )
    assert resp.status_code == 403, resp.text


def test_org_pain_point_type_delete_blocked_while_referenced_by_a_project(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Type In Use Co")
    market_id = _market_type_id(client, org_admin_token, project["id"])
    # Materializes the passthrough `ProjectPainPointType` row for "Market".
    _create_pain_point(client, org_admin_token, project["id"], type_id=market_id)

    resp = client.delete(f"{_org_base(org['id'])}/pain-point-types/{market_id}", headers=auth_headers(org_admin_token))
    assert resp.status_code == 409, resp.text


# --- Project-scoped Pain Point type vocabulary (overrides + local) ----------


def test_project_admin_can_override_an_org_type_and_add_a_local_type(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Project Type Co")
    market_id = _market_type_id(client, org_admin_token, project["id"])

    resp = client.put(
        f"{_project_base(project['id'])}/pain-point-types/{market_id}",
        json={"name": "Market (renamed)", "is_enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    override = resp.json()
    assert override["org_type_id"] == market_id
    assert override["name_override"] == "Market (renamed)"
    assert override["is_enabled"] is False

    types = _list_effective_types(client, org_admin_token, project["id"])
    market_entry = next(t for t in types if t["id"] == override["id"])
    assert market_entry["name"] == "Market (renamed)"
    assert market_entry["is_enabled"] is False
    assert market_entry["source"] == "project_override"

    resp = client.post(
        _project_base(project["id"]) + "/pain-point-types", json={"name": "Internal Tooling"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    local_type = resp.json()
    assert local_type["org_type_id"] is None
    assert local_type["name_override"] == "Internal Tooling"

    types = _list_effective_types(client, org_admin_token, project["id"])
    assert any(t["name"] == "Internal Tooling" and t["source"] == "project_local" for t in types)


def test_disabled_pain_point_type_cannot_be_selected_at_creation(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Disabled Type Co")
    market_id = _market_type_id(client, org_admin_token, project["id"])
    resp = client.put(
        f"{_project_base(project['id'])}/pain-point-types/{market_id}", json={"is_enabled": False},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    payload = {**_PAYLOAD_FIELDS, "pain_point_type_id": market_id}
    resp = client.post(_project_base(project["id"]) + "/pain-points", json=payload, headers=auth_headers(org_admin_token))
    assert resp.status_code == 400, resp.text


def test_plain_member_cannot_manage_project_pain_point_types(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Project Type RBAC Co")
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "pp_type_project_plain@example.com"
    )
    market_id = _market_type_id(client, org_admin_token, project["id"])
    resp = client.put(
        f"{_project_base(project['id'])}/pain-point-types/{market_id}", json={"name": "Nope"},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text


def test_project_local_pain_point_type_delete_blocked_while_in_use(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Local Type In Use Co")
    resp = client.post(
        _project_base(project["id"]) + "/pain-point-types", json={"name": "Field Ops"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    local_type_id = resp.json()["id"]
    _create_pain_point(client, org_admin_token, project["id"], type_id=local_type_id)

    resp = client.delete(
        f"{_project_base(project['id'])}/pain-point-types/{local_type_id}", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 409, resp.text


def test_unused_project_local_pain_point_type_can_be_deleted(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Local Type Unused Co")
    resp = client.post(
        _project_base(project["id"]) + "/pain-point-types", json={"name": "Field Ops"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    local_type_id = resp.json()["id"]

    resp = client.delete(
        f"{_project_base(project['id'])}/pain-point-types/{local_type_id}", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 204, resp.text


# --- Create / get / update ----------------------------------------------------


def test_create_and_get_pain_point(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "PainPoint Create Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])

    assert pain_point["project_id"] == project["id"]
    assert pain_point["status"] == "submitted"
    assert pain_point["pain_point_type_name"] == "Market"
    assert pain_point["is_locked"] is False

    resp = client.get(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == pain_point["id"]


def test_any_project_member_may_create_a_pain_point_no_manager_role_required(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Broad Create Co")
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "pp_broad_creator@example.com"
    )
    _create_pain_point(client, member_token, project["id"])


def test_plain_member_cannot_update_a_pain_point(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Update RBAC Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "pp_update_denied@example.com"
    )
    market_id = _market_type_id(client, org_admin_token, project["id"])
    payload = {**_PAYLOAD_FIELDS, "pain_point_type_id": market_id, "priority": "low"}
    resp = client.put(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}", json=payload,
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text


def test_manager_can_update_a_pain_point(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "PainPoint Update Manager Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])
    market_id = _market_type_id(client, org_admin_token, project["id"])
    payload = {**_PAYLOAD_FIELDS, "pain_point_type_id": market_id, "priority": "low", "title": "Revised title"}
    resp = client.put(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}", json=payload,
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Revised title"
    assert resp.json()["priority"] == "low"


# --- Branching lifecycle -------------------------------------------------------


def test_full_branch_accepted_through_closed(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "PainPoint Accept Branch Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])
    _advance_to_triaged(client, org_admin_token, project["id"], pain_point["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/accept", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/address", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "addressed"

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/close", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "closed"
    assert resp.json()["is_locked"] is True


def test_branch_rejected_requires_a_comment(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "PainPoint Reject Branch Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])
    _advance_to_triaged(client, org_admin_token, project["id"], pain_point["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/reject", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/reject",
        json={"comment": "Out of scope for this product line."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"
    assert resp.json()["is_locked"] is True


def test_branch_duplicate_requires_a_comment(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "PainPoint Duplicate Branch Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])
    _advance_to_triaged(client, org_admin_token, project["id"], pain_point["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/mark-duplicate",
        json={"comment": "Duplicate of PP-0007."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "duplicate"
    assert resp.json()["is_locked"] is True


def test_illegal_transition_is_409(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "PainPoint Illegal Transition Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/accept", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_plain_member_cannot_triage(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Triage RBAC Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "pp_triage_denied@example.com"
    )
    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/triage", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text


def test_pain_point_manager_role_can_triage(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Manager Role Co")
    user_id, manager_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "pp_manager@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "pain_point_manager")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/triage", json={},
        headers=auth_headers(manager_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "triaged"


def test_triage_reachable_via_custom_role_grant_of_approve_baseline_permission(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Custom Role Co")
    user_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "pp_custom_role@example.com"
    )
    pain_point = _create_pain_point(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/triage", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(
            organization_id=uuid.UUID(org["id"]), name="Pain Point Decider (Custom)",
            description="Custom test role.", scope="project",
        )
        db.add(role)
        db.flush()
        db.add(
            CustomRolePermission(custom_role_id=role.id, permission=encode_permission("pain_point", "approve_baseline"))
        )
        db.add(
            UserCustomRoleGrant(
                custom_role_id=role.id, user_id=uuid.UUID(user_id), organization_id=uuid.UUID(org["id"]),
                project_id=uuid.UUID(project["id"]),
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/triage", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "triaged"


# --- Disabled module / cross-tenant isolation -------------------------------


def test_disabled_module_is_404_not_403(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "PainPoint Disabled Co")
    project = create_project(client, org_admin_token, org["id"], "PainPoint Disabled Co Project")
    resp = client.get(_project_base(project["id"]) + "/pain-points", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_disabled_pain_point_subcomponent_is_404(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Subcomponent Disabled Co")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/pain_point",
        json={"enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(_project_base(project["id"]) + "/pain-points", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_pain_point_from_another_project_is_404(client, admin_token):
    _, project_a, org_admin_token = _setup(client, admin_token, "PainPoint Isolation Co A")
    _, project_b, _ = _setup(client, admin_token, "PainPoint Isolation Co B")
    pain_point = _create_pain_point(client, org_admin_token, project_a["id"])

    resp = client.get(
        f"{_project_base(project_b['id'])}/pain-points/{pain_point['id']}", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 404, resp.text


# --- Comments and evidence attachments ---------------------------------------


def test_comment_add_list_and_author_only_edit(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Comment Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "pp_commenter@example.com"
    )

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/comments",
        json={"body": "This also affects the night-shift inspection crew."}, headers=auth_headers(member_token),
    )
    assert resp.status_code == 201, resp.text
    comment = resp.json()

    resp = client.get(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/comments", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    resp = client.patch(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/comments/{comment['id']}",
        json={"body": "Edited: also affects the night-shift crew."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 403, resp.text


def test_any_member_may_upload_evidence_file(client, admin_token):
    """§6.5's broad "Add evidence" — deliberately open to any project
    member, unlike Strategy/Future State's owner-gated direct file uploads
    (see `project_router.upload_project_pain_point_file`'s own docstring)."""
    org, project, org_admin_token = _setup(client, admin_token, "PainPoint Evidence Co")
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "pp_evidence_uploader@example.com"
    )
    pain_point = _create_pain_point(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/files",
        files={"file": ("evidence.txt", b"14 SLA-breach tickets attached.", "text/plain")},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 201, resp.text

    resp = client.get(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/files", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1


def test_evidence_file_upload_locked_once_terminal(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "PainPoint Evidence Locked Co")
    pain_point = _create_pain_point(client, org_admin_token, project["id"])
    _advance_to_triaged(client, org_admin_token, project["id"], pain_point["id"])
    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/reject",
        json={"comment": "Not applicable."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/pain-points/{pain_point['id']}/files",
        files={"file": ("late.txt", b"too late", "text/plain")}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text
