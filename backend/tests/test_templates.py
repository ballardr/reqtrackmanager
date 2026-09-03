"""Tests for project templates (C-E-04 default template, C-E-05 create from template)."""

from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_user,
    create_project,
    direct_project_roles,
    login,
)


def test_create_project_from_template_copies_configuration_and_requirements(client, admin_token, org_id):
    template = create_project(client, admin_token, org_id, "Template Project")
    component_id, category_id = create_component_and_category(client, admin_token, template["id"])
    client.post(
        f"/api/v1/projects/{template['id']}/requirements",
        json={"name": "Boot fast", "reasoning": "UX", "component_id": component_id, "category_id": category_id, "keywords": ["perf"]},
        headers=auth_headers(admin_token),
    )
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(admin_token))

    resp = client.post(
        "/api/v1/projects",
        json={
            "organization_id": org_id, "name": "New From Template", "summary": "",
            "template_project_id": template["id"],
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    new_project = resp.json()

    components = client.get(f"/api/v1/projects/{new_project['id']}/components", headers=auth_headers(admin_token)).json()
    assert len(components) == 1
    assert components[0]["prefix"] == "SW"

    requirements = client.get(f"/api/v1/projects/{new_project['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert len(requirements) == 1
    assert requirements[0]["name"] == "Boot fast"
    assert requirements[0]["status"] == "draft"
    assert requirements[0]["keywords"] == ["perf"]
    assert requirements[0]["unique_code"] == "SW-PERF-001"

    # The template's own creator holds their manager role via a direct
    # UserProjectRole grant (C-U-10, follow-up UX batch Phase C,
    # 2026-08-31 — no default groups exist to copy any more) —
    # `clone_project` now copies direct role grants too, so that same
    # direct manager grant carries over onto the new project.
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    assert direct_project_roles(new_project["id"]).get(me["id"]) == {"project_manager"}


def test_cannot_use_non_template_project_as_template(client, admin_token, org_id):
    other = create_project(client, admin_token, org_id, "Not A Template")
    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "Should Fail", "summary": "", "template_project_id": other["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_set_default_template_requires_template_flag(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    resp = client.put(
        f"/api/v1/orgs/{org_id}/default-template", json={"project_id": project["id"]}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 400

    client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=auth_headers(admin_token))
    resp = client.put(
        f"/api/v1/orgs/{org_id}/default-template", json={"project_id": project["id"]}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200
    assert resp.json()["default_template_project_id"] == project["id"]


def test_cloning_a_template_preserves_a_directly_granted_non_manager_role(client, admin_token, org_id):
    """The `clone_project` gap found in design review before this phase was
    finalized (docs/decisions.md, follow-up UX batch Phase C): prior to this
    fix, `clone_project` only ever copied `ProjectGroup`/`ProjectGroupMember`
    rows, never `UserProjectRole` rows — so a template's directly-granted
    stakeholders/members/admins would silently vanish for everyone except
    whoever happened to be doing the cloning. Pins that a directly-granted
    *non-manager* role specifically survives a clone (the manager case is
    covered separately, since it also interacts with the C-U-08 fallback)."""
    template = create_project(client, admin_token, org_id, "Direct Grant Template")
    stakeholder_id = create_org_user(client, admin_token, org_id, "template-stakeholder@example.com", role="member")
    grant = client.post(
        f"/api/v1/projects/{template['id']}/roles", json={"user_id": stakeholder_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    assert grant.status_code == 204, grant.text
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(admin_token))

    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "Cloned With Direct Grant", "summary": "", "template_project_id": template["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    new_project = resp.json()

    roles = direct_project_roles(new_project["id"])
    assert roles.get(stakeholder_id) == {"stakeholder"}, "the template's directly-granted stakeholder must survive the clone"


def test_cloning_a_template_with_zero_managers_still_produces_a_valid_manager(client, admin_token, org_id):
    """The second gap found in design review (docs/decisions.md): a
    template whose only manager was a default group is, after this phase's
    migration, either fully materialized-and-deleted or demoted — either
    way, a template can end up with zero managers of its own (this can no
    longer happen through the live API alone, since `revoke_project_role`/
    `delete_project_group` both enforce C-U-08 themselves; the DB is
    manipulated directly here to reach that state, standing in for a
    template a pre-Phase-C default-group migration or a since-emptied
    custom group left this way). `clone_project`'s existing zero-manager
    fallback (`_ensure_project_has_a_manager`, previously only exercised
    via a default-group-based template) must still assign the cloning user
    as manager of the new project — C-U-08 must never regress just because
    the *mechanism* a manager grant is expressed through changed."""
    from app.database import SessionLocal
    from app.models.project import UserProjectRole

    template = create_project(client, admin_token, org_id, "Zero-Manager Template")
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()

    db = SessionLocal()
    try:
        db.query(UserProjectRole).filter(
            UserProjectRole.project_id == template["id"], UserProjectRole.user_id == me["id"],
            UserProjectRole.role == "project_manager",
        ).delete()
        db.commit()
    finally:
        db.close()

    # Confirm the template genuinely has zero managers before cloning —
    # otherwise this test would silently prove nothing.
    assert direct_project_roles(template["id"]) == {}

    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(admin_token))

    other_creator_id = create_org_user(client, admin_token, org_id, "zero-manager-cloner@example.com", role="project_creator")
    other_token = login(client, "zero-manager-cloner@example.com", "Password123!")
    resp = client.post(
        "/api/v1/projects",
        json={
            "organization_id": org_id, "name": "Cloned From Zero-Manager Template", "summary": "",
            "template_project_id": template["id"],
        },
        headers=auth_headers(other_token),
    )
    assert resp.status_code == 201
    new_project = resp.json()

    assert direct_project_roles(new_project["id"]).get(other_creator_id) == {"project_manager"}
