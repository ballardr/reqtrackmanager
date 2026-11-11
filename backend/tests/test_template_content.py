"""Template projects: what a project created from a template receives beyond the core records.

Covers the project list's template filter, the explicit "no template" choice, the declared template keys every
module classifies, and the clone itself (module switches, tag vocabulary, plain settings, module configuration
and starter records returned to fresh drafts). History, comments and archived records never travel.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.module import ProjectModuleEnablement
from app.models.project import Project
from app.modules.decisions.models import Decision, DecisionFile, DecisionTypeDefinition
from app.modules.registry import get_all_module_project_bundle_hooks
from tests.conftest import auth_headers, create_org_admin_in, create_project

DECISIONS = "decisions"


def _template(client, token, org_id, name="Template") -> dict:
    project = create_project(client, token, org_id, name)
    resp = client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return project


def _from_template(client, token, org_id, template_id, name="Child") -> dict:
    resp = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": name, "summary": "", "template_project_id": template_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _names(client, token, query: str) -> set[str]:
    resp = client.get(f"/api/v1/projects?{query}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {p["name"] for p in resp.json()}


def test_every_module_classifies_every_exported_bundle_key(client, admin_token):
    """A key a module's project export returns is copied (configuration or records) or excluded with a reason,
    never silently dropped; a module with records says how to return them to drafts."""
    org, token = create_org_admin_in(client, admin_token, "Template Keys Co")
    project_row = create_project(client, token, org["id"], "Template Keys Project")
    db = SessionLocal()
    try:
        project = db.get(Project, uuid.UUID(project_row["id"]))
        problems = []
        for key, hooks in get_all_module_project_bundle_hooks():
            configuration, records, excluded = hooks.template_configuration_keys, hooks.template_record_keys, set(hooks.template_excluded)
            exported = set(hooks.export(db, project)[0])
            if overlap := (configuration & records) | (configuration & excluded) | (records & excluded):
                problems.append(f"{key}: keys in more than one class: {sorted(overlap)}")
            if unclassified := exported - (configuration | records | excluded):
                problems.append(f"{key}: unclassified bundle keys: {sorted(unclassified)}")
            if records and hooks.template_reset is None:
                problems.append(f"{key}: record keys but no template_reset")
            if blank := [k for k, reason in hooks.template_excluded.items() if not reason.strip()]:
                problems.append(f"{key}: excluded keys without a reason: {blank}")
        assert not problems, "\n".join(problems)
    finally:
        db.close()


def test_project_list_leaves_templates_out_unless_asked(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Template List Co")
    create_project(client, token, org["id"], "Ordinary")
    _template(client, token, org["id"], "A Template")
    query = f"archived=false&organization_id={org['id']}"

    assert _names(client, token, query) == {"Ordinary"}
    assert _names(client, token, query + "&include_templates=true") == {"Ordinary", "A Template"}
    assert _names(client, token, query + "&templates_only=true") == {"A Template"}
    # templates_only wins over include_templates=false and over a default of leaving them out.
    assert _names(client, token, query + "&templates_only=true&include_templates=false") == {"A Template"}


def test_no_template_choice_overrides_the_organisation_default(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Template None Co")
    template = _template(client, token, org["id"], "Default Template")
    resp = client.put(f"/api/v1/orgs/{org['id']}/default-template", json={"project_id": template["id"]}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    client.post(f"/api/v1/projects/{template['id']}/tags", json={"name": "from-template"}, headers=auth_headers(token))

    def tags_of(project_id: str) -> set[str]:
        return {t["name"] for t in client.get(f"/api/v1/projects/{project_id}/tags", headers=auth_headers(token)).json()["tags"]}

    inherited = client.post(
        "/api/v1/projects", json={"organization_id": org["id"], "name": "Default Applies", "summary": ""}, headers=auth_headers(token),
    )
    blank = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "Blank", "summary": "", "use_template": False}, headers=auth_headers(token),
    )
    assert inherited.status_code == 201 and blank.status_code == 201
    assert tags_of(inherited.json()["id"]) == {"from-template"}
    assert tags_of(blank.json()["id"]) == set()


def test_clone_copies_switches_settings_vocabulary_and_fresh_decision_drafts(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Template Clone Co")
    h = auth_headers(token)
    assert client.put(f"/api/v1/orgs/{org['id']}/modules/{DECISIONS}", json={"enabled": True}, headers=h).status_code == 200
    template = _template(client, token, org["id"])
    base = f"/api/v1/projects/{template['id']}/modules/{DECISIONS}"

    # Module switch, settings, tag vocabulary.
    assert client.put(
        f"/api/v1/projects/{template['id']}/modules/{DECISIONS}/enablement", json={"enabled": False}, headers=h,
    ).status_code == 200
    assert client.put(
        f"/api/v1/projects/{template['id']}/modules/{DECISIONS}/enablement", json={"enabled": True}, headers=h,
    ).status_code == 200
    assert client.post(f"/api/v1/projects/{template['id']}/tags", json={"name": "starter"}, headers=h).status_code == 201
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(template["id"]))
        row.review_reminder_lead_days_default = 21
        db.commit()
    finally:
        db.close()

    # A type, an approved-looking decision with an attachment, and an archived one.
    assert client.post(base + "/decision-types", json={"name": "Regulatory"}, headers=h).status_code == 201
    types = {t["name"]: t["id"] for t in client.get(base + "/decision-types", headers=h).json()}
    kept = client.post(base, json={
        "title": "Use Postgres", "decision_statement": "PostgreSQL.", "decision_type_id": types["Regulatory"],
        "decision_date": "2031-05-06",
    }, headers=h)
    assert kept.status_code == 201, kept.text
    kept_id = kept.json()["id"]
    assert client.post(f"{base}/{kept_id}/files", files={"file": ("adr.txt", b"adr", "text/plain")}, headers=h).status_code == 201
    assert client.post(f"{base}/{kept_id}/propose", headers=h).status_code == 200
    dropped = client.post(base, json={"title": "Dropped", "decision_statement": "No.", "decision_type_id": types["Regulatory"]}, headers=h)
    assert client.post(f"{base}/{dropped.json()['id']}/archive", headers=h).status_code == 200

    child = _from_template(client, token, org["id"], template["id"])

    db = SessionLocal()
    try:
        new_id = uuid.UUID(child["id"])
        project = db.get(Project, new_id)
        assert project is not None and project.review_reminder_lead_days_default == 21
        enabled = {r.module_key: r.enabled for r in db.scalars(select(ProjectModuleEnablement).where(ProjectModuleEnablement.project_id == new_id))}
        assert enabled[DECISIONS] is True
        template_id = uuid.UUID(template["id"])
        template_types = [t.name for t in db.scalars(select(DecisionTypeDefinition).where(DecisionTypeDefinition.project_id == template_id))]
        new_types = [t.name for t in db.scalars(select(DecisionTypeDefinition).where(DecisionTypeDefinition.project_id == new_id))]
        assert "Regulatory" in new_types and sorted(new_types) == sorted(template_types)
        decisions = list(db.scalars(select(Decision).where(Decision.project_id == new_id)))
        assert [d.title for d in decisions] == ["Use Postgres"]  # the archived one is not a starting point
        copied = decisions[0]
        assert copied.status.value == "draft" and copied.decision_date is None and not copied.is_archived
        assert copied.unique_code != "" and copied.id != uuid.UUID(kept_id)
        assert db.scalar(select(DecisionFile).where(DecisionFile.decision_id == copied.id)) is not None
    finally:
        db.close()
    tags = client.get(f"/api/v1/projects/{child['id']}/tags", headers=h).json()["tags"]
    assert {t["name"] for t in tags} == {"starter"}


def test_clone_keeps_a_module_off_that_the_template_has_off(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Template Off Co")
    h = auth_headers(token)
    assert client.put(f"/api/v1/orgs/{org['id']}/modules/{DECISIONS}", json={"enabled": True}, headers=h).status_code == 200
    template = _template(client, token, org["id"])
    assert client.put(
        f"/api/v1/projects/{template['id']}/modules/{DECISIONS}/enablement", json={"enabled": False}, headers=h,
    ).status_code == 200
    child = _from_template(client, token, org["id"], template["id"])
    db = SessionLocal()
    try:
        row = db.scalar(select(ProjectModuleEnablement).where(
            ProjectModuleEnablement.project_id == uuid.UUID(child["id"]), ProjectModuleEnablement.module_key == DECISIONS,
        ))
        assert row is not None and row.enabled is False
    finally:
        db.close()


def test_clone_keeps_requirement_codes_links_between_requirements_and_ai_approvals(client, admin_token):
    """Requirement codes (so a link from another record still reaches the same requirement), links between
    requirements, the sequence counter and the AI approvals setting all carry over."""
    from tests.conftest import create_component_and_category

    org, token = create_org_admin_in(client, admin_token, "Template Links Co")
    h = auth_headers(token)
    template = _template(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, template["id"])
    codes = {}
    for name in ("First", "Second", "Dropped"):
        body = client.post(f"/api/v1/projects/{template['id']}/requirements", json={
            "name": name, "component_id": component_id, "category_id": category_id,
        }, headers=h).json()
        codes[name] = body
    assert client.delete(f"/api/v1/projects/{template['id']}/requirements/{codes['Dropped']['id']}", headers=h).status_code == 204
    link_types = {lt["forward_name"]: lt["id"] for lt in client.get(f"/api/v1/orgs/{org['id']}/link-types", headers=h).json()}
    assert client.post(
        f"/api/v1/projects/{template['id']}/requirements/{codes['First']['id']}/links",
        json={"target_requirement_id": codes["Second"]["id"], "link_type_id": link_types["Derives from"]}, headers=h,
    ).status_code == 201
    assert client.patch(f"/api/v1/projects/{template['id']}", json={"allow_ai_approvals": True}, headers=h).status_code == 200

    child = _from_template(client, token, org["id"], template["id"])
    listed = {r["name"]: r for r in client.get(f"/api/v1/projects/{child['id']}/requirements", headers=h).json()}
    assert set(listed) == {"First", "Second"}
    assert listed["First"]["unique_code"] == codes["First"]["unique_code"] and listed["Second"]["unique_code"] == codes["Second"]["unique_code"]
    links = client.get(f"/api/v1/projects/{child['id']}/requirements/{listed['First']['id']}/links", headers=h).json()
    assert [(link["display_name"], link["other_requirement_unique_code"]) for link in links] == [("Derives from", codes["Second"]["unique_code"])]
    created = client.post(f"/api/v1/projects/{child['id']}/requirements", json={
        "name": "Third", "component_id": client.get(f"/api/v1/projects/{child['id']}/components", headers=h).json()[0]["id"],
        "category_id": client.get(f"/api/v1/projects/{child['id']}/categories", headers=h).json()[0]["id"],
    }, headers=h).json()
    assert created["unique_code"] not in {codes[n]["unique_code"] for n in codes}  # the counter continues past the template's
    assert client.get(f"/api/v1/projects/{child['id']}", headers=h).json()["allow_ai_approvals"] is True


def test_a_template_must_be_viewable_to_be_used(client, admin_token):
    """A project creator with no access to a template cannot use it by its id; making it visible allows it."""
    from tests.conftest import create_org_user, login

    org, token = create_org_admin_in(client, admin_token, "Template View Co")
    h = auth_headers(token)
    template = _template(client, token, org["id"])
    create_org_user(client, token, org["id"], "creator-view@example.com", role="project_creator")
    creator = auth_headers(login(client, "creator-view@example.com", "Password123!"))
    body = {"organization_id": org["id"], "name": "Via Hidden", "summary": "", "template_project_id": template["id"]}

    assert client.get("/api/v1/projects?templates_only=true", headers=creator).json() == []
    refused = client.post("/api/v1/projects", json=body, headers=creator)
    assert refused.status_code == 403 and "template" in refused.json()["detail"]
    blank = client.post("/api/v1/projects", json={**body, "template_project_id": None, "use_template": False, "name": "Blank"}, headers=creator)
    assert blank.status_code == 201

    assert client.patch(f"/api/v1/projects/{template['id']}", json={"visibility": "org_wide"}, headers=h).status_code == 200
    assert client.post("/api/v1/projects", json={**body, "name": "Via Visible"}, headers=creator).status_code == 201


def test_an_org_admin_sets_any_template_as_the_default_and_creators_may_use_it_unseen(client, admin_token):
    """The administrator need not hold a role in the template; the organisation's default is offered to every
    project creator whether or not they can view it, while the same template by id stays refused."""
    from tests.conftest import create_org_user, login

    org, token = create_org_admin_in(client, admin_token, "Template Default Co")
    template = _template(client, token, org["id"])  # team-only, created by the first administrator
    client.post(f"/api/v1/projects/{template['id']}/tags", json={"name": "from-default"}, headers=auth_headers(token))
    create_org_user(client, token, org["id"], "second-admin@example.com", role="org_admin")
    second = auth_headers(login(client, "second-admin@example.com", "Password123!"))
    create_org_user(client, token, org["id"], "creator-default@example.com", role="project_creator")
    creator = auth_headers(login(client, "creator-default@example.com", "Password123!"))

    listed = client.get(f"/api/v1/orgs/{org['id']}/projects", headers=second).json()
    assert [(p["name"], p["is_template"]) for p in listed if p["id"] == template["id"]] == [("Template", True)]
    assert client.put(f"/api/v1/orgs/{org['id']}/default-template", json={"project_id": template["id"]}, headers=second).status_code == 200

    by_default = client.post("/api/v1/projects", json={"organization_id": org["id"], "name": "Via Default", "summary": ""}, headers=creator)
    assert by_default.status_code == 201, by_default.text
    tags = client.get(f"/api/v1/projects/{by_default.json()['id']}/tags", headers=auth_headers(token)).json()["tags"]
    assert {t["name"] for t in tags} == {"from-default"}
    other = _template(client, token, org["id"], "Other Template")
    assert client.post("/api/v1/projects", json={
        "organization_id": org["id"], "name": "Via Other", "summary": "", "template_project_id": other["id"],
    }, headers=creator).status_code == 403
