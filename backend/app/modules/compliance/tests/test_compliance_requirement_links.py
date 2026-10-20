"""Tests for a core requirement's links to a Compliance standard's clauses as ordinary generic
links: the organisation-owned
`compliance_requirement` artefact type, the standard -> version -> requirement finder, isolation,
the permissions of the generic link endpoints, cleanup when a draft clause is deleted, project
bundles, the migration from the old traceability table, and the retired routes and MCP tools.

Each test builds its own organisations, so none depends on state left by another test or run.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import text

from alembic import command
from app.database import SessionLocal, engine
from app.modules.compliance.tests.test_compliance_standards_api import (
    _base,
    _create_standard,
    _create_version,
)
from app.modules.compliance.tests.test_compliance_standards_api import (
    _create_requirement as _create_clause,
)
from app.modules.compliance.tests.test_project_compliance_api import _assign_project_role
from app.modules.registry import build_mcp_tool_manifest
from tests.conftest import (
    auth_headers,
    build_alembic_config,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)

REQ = "requirement"
CLAUSE = "compliance_requirement"


def _link_types(client, token, org_id) -> dict[str, str]:
    resp = client.get(f"/api/v1/orgs/{org_id}/link-types", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {lt["forward_name"]: lt["id"] for lt in resp.json()}


def _requirement(client, token, project_id, component_id, category_id, name="Access control requirement") -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _setup(client, admin_token, org_id, *, project_name="Clause Link Project"):
    """One project with a core requirement, and one standard version with a parent clause and a
    child clause in the same organisation. Returns a dict of the created records."""
    project = create_project(client, admin_token, org_id, name=project_name)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _requirement(client, admin_token, project["id"], component_id, category_id)
    standard = _create_standard(client, admin_token, org_id, reference=f"ISO-{uuid.uuid4().hex[:5]}", name="Link Test Standard")
    version = _create_version(client, admin_token, org_id, standard["id"], version_label="2.0")
    clause = _create_clause(
        client, admin_token, org_id, standard["id"], version["id"], name="Logical access control", reference="A.5.15"
    )
    child = _create_clause(
        client, admin_token, org_id, standard["id"], version["id"], name="Access rights review", reference="A.5.15.1",
        parent_requirement_id=clause["id"],
    )
    return {
        "project": project, "requirement": requirement, "standard": standard, "version": version,
        "clause": clause, "child": child, "component_id": component_id, "category_id": category_id,
    }


def _page(project_id, requirement_id) -> str:
    return f"/api/v1/projects/{project_id}/artefacts/{REQ}/{requirement_id}"


def _link(client, token, ctx, link_type_id, clause_id=None, direction="outgoing"):
    return client.post(
        f"{_page(ctx['project']['id'], ctx['requirement']['id'])}/links",
        json={
            "link_type_id": link_type_id, "direction": direction, "other_type": CLAUSE,
            "other_id": clause_id or ctx["clause"]["id"],
        },
        headers=auth_headers(token),
    )


def _graph_edges(client, token, ctx) -> list[dict]:
    resp = client.get(
        f"{_page(ctx['project']['id'], ctx['requirement']['id'])}/link-graph", params={"depth": 1}, headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["edges"]


# --- linking and reading ---------------------------------------------------------------------


def test_a_requirement_links_to_a_clause_and_the_graph_shows_it_with_the_standard_in_the_label(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    types = _link_types(client, admin_token, org_id)

    created = _link(client, admin_token, ctx, types["Derives from"])
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["phrase"] == "Derives from" and body["direction"] == "outgoing"
    assert body["other"]["type"] == CLAUSE and body["other"]["type_label"] == "Compliance standard clause"
    assert body["other"]["label"].endswith("· A.5.15 Logical access control")
    assert ctx["standard"]["reference"] in body["other"]["label"] and "v2.0" in body["other"]["label"]
    assert body["other"]["project_id"] is None  # organisation-owned

    graph = client.get(
        f"{_page(ctx['project']['id'], ctx['requirement']['id'])}/link-graph", params={"depth": 1}, headers=auth_headers(admin_token)
    ).json()
    assert [(n["type"], n["id"]) for n in graph["nodes"] if n["type"] == CLAUSE] == [(CLAUSE, ctx["clause"]["id"])]
    assert graph["hidden_count"] == 0 and graph["unavailable_count"] == 0

    again = _link(client, admin_token, ctx, types["Derives from"])
    assert again.status_code == 409  # the same link twice


def test_a_link_can_be_removed_generically(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    created = _link(client, admin_token, ctx, _link_types(client, admin_token, org_id)["Related to"]).json()
    gone = client.delete(
        f"{_page(ctx['project']['id'], ctx['requirement']['id'])}/links/{created['id']}", headers=auth_headers(admin_token)
    )
    assert gone.status_code == 204, gone.text
    assert _graph_edges(client, admin_token, ctx) == []


def test_the_link_reads_from_either_end_in_the_database_only_the_requirement_side_has_a_page(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    types = _link_types(client, admin_token, org_id)
    assert _link(client, admin_token, ctx, types["Derives from"]).status_code == 201
    edge = _graph_edges(client, admin_token, ctx)[0]
    assert edge["phrase"] == "Derives from" and edge["to_type"] == CLAUSE


# --- finder ----------------------------------------------------------------------------------


def test_a_clause_is_found_by_text_from_a_global_search(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    page = _page(ctx["project"]["id"], ctx["requirement"]["id"])
    for needle in ("A.5.15", ctx["standard"]["reference"][:7], "logical access"):
        found = client.get(f"{page}/link-candidates", params={"q": needle}, headers=auth_headers(admin_token)).json()
        assert CLAUSE in {item["type"] for item in found["items"]}, needle
    one_type = client.get(
        f"{page}/link-candidates", params={"other_type": CLAUSE, "q": "A.5.15.1"}, headers=auth_headers(admin_token)
    ).json()
    assert [i["id"] for i in one_type["items"]] == [ctx["child"]["id"]]


def test_the_standard_version_requirement_cascade_narrows_step_by_step(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    other_standard = _create_standard(client, admin_token, org_id, reference=f"ZZ-{uuid.uuid4().hex[:5]}", name="Other Standard")
    other_version = _create_version(client, admin_token, org_id, other_standard["id"], version_label="9.9")
    _create_clause(client, admin_token, org_id, other_standard["id"], other_version["id"], name="Elsewhere", reference="Z.1")
    page = _page(ctx["project"]["id"], ctx["requirement"]["id"])

    def browse(selected=None, **extra):
        params = {"other_type": CLAUSE, **extra, **({"selected": selected} if selected else {})}
        resp = client.get(f"{page}/link-browse", params=params, headers=auth_headers(admin_token))
        assert resp.status_code == 200, resp.text
        return resp.json()

    standards = browse()
    assert (standards["key"], standards["label"]) == ("standard", "Standard")
    assert {o["id"] for o in standards["options"]} >= {ctx["standard"]["id"], other_standard["id"]}
    assert [o["id"] for o in browse(q=ctx["standard"]["reference"])["options"]] == [ctx["standard"]["id"]]

    versions = browse(f"standard:{ctx['standard']['id']}")
    assert versions["key"] == "version"
    # The standard starts with its initial 1.0 version; the newest version is listed first.
    assert [o["label"] for o in versions["options"]] == ["v2.0", "v1.0"]
    assert versions["options"][0]["id"] == ctx["version"]["id"]

    clauses = browse(f"standard:{ctx['standard']['id']},version:{ctx['version']['id']}")
    assert clauses["key"] == "requirement"
    assert {o["id"] for o in clauses["options"]} == {ctx["clause"]["id"], ctx["child"]["id"]}

    chain = f"standard:{ctx['standard']['id']},version:{ctx['version']['id']},requirement:{ctx['clause']['id']}"
    assert browse(chain) is None
    narrowed = client.get(
        f"{page}/link-candidates", params={"other_type": CLAUSE, "selected": f"standard:{ctx['standard']['id']}"},
        headers=auth_headers(admin_token),
    ).json()["items"]
    assert {i["id"] for i in narrowed} == {ctx["clause"]["id"], ctx["child"]["id"]}
    exact = client.get(
        f"{page}/link-candidates", params={"other_type": CLAUSE, "selected": chain}, headers=auth_headers(admin_token)
    ).json()["items"]
    assert [i["id"] for i in exact] == [ctx["clause"]["id"]]


def test_a_version_of_another_standard_is_not_an_option_of_the_chosen_standard(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    other = _create_standard(client, admin_token, org_id, reference=f"OT-{uuid.uuid4().hex[:5]}", name="Other")
    other_version = _create_version(client, admin_token, org_id, other["id"], version_label="3.0")
    page = _page(ctx["project"]["id"], ctx["requirement"]["id"])
    resp = client.get(
        f"{page}/link-browse",
        params={"other_type": CLAUSE, "selected": f"standard:{ctx['standard']['id']},version:{other_version['id']}"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_a_project_compliance_requirement_is_narrowed_by_standard_then_version(client, admin_token, org_id):
    from app.modules.compliance.tests.test_project_compliance_api import (
        _assign_standard_to_project,
        _setup_published_standard_with_tree,
    )

    project = create_project(client, admin_token, org_id, name="Assessment Project")
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _requirement(client, admin_token, project["id"], component_id, category_id)
    standard, version, *_ = _setup_published_standard_with_tree(client, admin_token, org_id)
    _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    page = f"/api/v1/projects/{project['id']}/artefacts/{REQ}/{requirement['id']}"
    first = client.get(
        f"{page}/link-browse", params={"other_type": "project_compliance_requirement"}, headers=auth_headers(admin_token)
    ).json()
    assert first["key"] == "standard" and [o["id"] for o in first["options"]] == [standard["id"]]
    second = client.get(
        f"{page}/link-browse",
        params={"other_type": "project_compliance_requirement", "selected": f"standard:{standard['id']}"},
        headers=auth_headers(admin_token),
    ).json()
    assert second["key"] == "version" and [o["id"] for o in second["options"]] == [version["id"]]
    items = client.get(
        f"{page}/link-candidates",
        params={"other_type": "project_compliance_requirement", "selected": f"standard:{standard['id']},version:{version['id']}"},
        headers=auth_headers(admin_token),
    ).json()["items"]
    assert items and all(i["type"] == "project_compliance_requirement" for i in items)


# --- isolation -------------------------------------------------------------------------------


def test_a_clause_of_another_organisation_is_not_offered_or_linkable(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    other_org, other_token = create_org_admin_in(client, admin_token, "Clause Other Org")
    other_standard = _create_standard(client, other_token, other_org["id"], reference="OTHER-ORG-STD", name="Not this org")
    other_version = _create_version(client, other_token, other_org["id"], other_standard["id"], version_label="2.0")
    other_clause = _create_clause(
        client, other_token, other_org["id"], other_standard["id"], other_version["id"], name="Not this org's clause"
    )
    types = _link_types(client, admin_token, org_id)
    page = _page(ctx["project"]["id"], ctx["requirement"]["id"])

    assert _link(client, admin_token, ctx, types["Related to"], clause_id=other_clause["id"]).status_code == 404
    found = client.get(f"{page}/link-candidates", params={"q": "Not this org"}, headers=auth_headers(admin_token)).json()
    assert found["items"] == []
    standards = client.get(f"{page}/link-browse", params={"other_type": CLAUSE}, headers=auth_headers(admin_token)).json()
    assert other_standard["id"] not in {o["id"] for o in standards["options"]}
    foreign = client.get(
        f"{page}/link-browse", params={"other_type": CLAUSE, "selected": f"standard:{other_standard['id']}"},
        headers=auth_headers(admin_token),
    )
    assert foreign.status_code == 400


def test_a_link_type_of_another_organisation_is_refused(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    other_org, other_token = create_org_admin_in(client, admin_token, "Clause Link Type Org")
    foreign_type = _link_types(client, other_token, other_org["id"])["Related to"]
    assert _link(client, admin_token, ctx, foreign_type).status_code == 400


def test_a_clause_is_hidden_where_the_compliance_module_is_off(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    types = _link_types(client, admin_token, org_id)
    page = _page(ctx["project"]["id"], ctx["requirement"]["id"])
    off = client.put(
        f"/api/v1/projects/{ctx['project']['id']}/modules/compliance/enablement", json={"enabled": False},
        headers=auth_headers(admin_token),
    )
    assert off.status_code == 200, off.text
    assert client.get(f"{page}/link-candidates", params={"other_type": CLAUSE}, headers=auth_headers(admin_token)).json()["items"] == []
    assert client.get(f"{page}/link-browse", params={"other_type": CLAUSE}, headers=auth_headers(admin_token)).json() is None
    assert _link(client, admin_token, ctx, types["Related to"]).status_code == 404


def test_a_view_only_member_can_see_a_link_but_not_make_or_remove_one(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    types = _link_types(client, admin_token, org_id)
    member_id = create_org_user(client, admin_token, org_id, "clause.viewer@example.com", role="member")
    _assign_project_role(client, admin_token, ctx["project"]["id"], member_id, "member")
    member_token = login(client, "clause.viewer@example.com", "Password123!")

    assert _link(client, member_token, ctx, types["Related to"]).status_code == 403
    created = _link(client, admin_token, ctx, types["Related to"]).json()
    seen = client.get(
        f"{_page(ctx['project']['id'], ctx['requirement']['id'])}/link-graph", headers=auth_headers(member_token)
    )
    assert seen.status_code == 200 and any(n["type"] == CLAUSE for n in seen.json()["nodes"])
    forbidden = client.delete(
        f"{_page(ctx['project']['id'], ctx['requirement']['id'])}/links/{created['id']}", headers=auth_headers(member_token)
    )
    assert forbidden.status_code == 403


# --- lifecycle -------------------------------------------------------------------------------


def test_deleting_a_draft_clause_removes_its_links_and_its_descendants(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    types = _link_types(client, admin_token, org_id)
    assert _link(client, admin_token, ctx, types["Related to"]).status_code == 201
    assert _link(client, admin_token, ctx, types["Derives from"], clause_id=ctx["child"]["id"]).status_code == 201
    assert len(_graph_edges(client, admin_token, ctx)) == 2

    gone = client.delete(
        f"{_base(org_id)}/standards/{ctx['standard']['id']}/versions/{ctx['version']['id']}/requirements/{ctx['clause']['id']}",
        headers=auth_headers(admin_token),
    )
    assert gone.status_code == 204, gone.text
    assert _graph_edges(client, admin_token, ctx) == []
    db = SessionLocal()
    try:
        left = db.execute(
            text("SELECT count(*) FROM artefact_links WHERE target_type = 'compliance_requirement' AND source_id = :id"),
            {"id": ctx["requirement"]["id"]},
        ).scalar()
    finally:
        db.close()
    assert left == 0


def test_the_organisations_clauses_are_listed_for_organisation_deletion_cleanup(client, admin_token, org_id):
    from app.modules.compliance.module import _artefact_ids_in_organization

    ctx = _setup(client, admin_token, org_id)
    db = SessionLocal()
    try:
        ids = _artefact_ids_in_organization(db, uuid.UUID(org_id))
    finally:
        db.close()
    assert {uuid.UUID(ctx["clause"]["id"]), uuid.UUID(ctx["child"]["id"])} <= ids


# --- bundles ---------------------------------------------------------------------------------


def _export_zip(client, token, project_id) -> bytes:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _import_zip(client, token, org_id, content, name):
    return client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=auth_headers(token),
    )


def test_a_project_bundle_carries_clause_links_and_import_recreates_them(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    assert _link(client, admin_token, ctx, _link_types(client, admin_token, org_id)["Derives from"]).status_code == 201
    bundle = _export_zip(client, admin_token, ctx["project"]["id"])
    exported = json.loads(zipfile.ZipFile(io.BytesIO(bundle)).read("project.json"))
    assert [(x["requirement_unique_code"], x["standard_reference"], x["version_label"], x["link_type_forward_name"])
            for x in exported["compliance_requirement_links"]] == [
        (ctx["requirement"]["unique_code"], ctx["standard"]["reference"], "2.0", "Derives from")
    ]
    # A requirement -> clause link is not a requirement-to-requirement link.
    assert exported["requirement_links"] == []

    imported = _import_zip(client, admin_token, org_id, bundle, "Clause Links Reimported")
    assert imported.status_code == 201, imported.text
    assert imported.json()["warnings"] == []
    new_project = imported.json()["project"]
    new_requirement = client.get(f"/api/v1/projects/{new_project['id']}/requirements", headers=auth_headers(admin_token)).json()[0]
    graph = client.get(
        f"/api/v1/projects/{new_project['id']}/artefacts/{REQ}/{new_requirement['id']}/link-graph", params={"depth": 1},
        headers=auth_headers(admin_token),
    ).json()
    assert [(e["to_type"], e["to_id"], e["phrase"]) for e in graph["edges"]] == [(CLAUSE, ctx["clause"]["id"], "Derives from")]


def test_import_skips_a_clause_link_whose_standard_is_missing_in_the_target_with_a_warning(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    assert _link(client, admin_token, ctx, _link_types(client, admin_token, org_id)["Related to"]).status_code == 201
    bundle = _export_zip(client, admin_token, ctx["project"]["id"])
    target_org, target_token = create_org_admin_in(client, admin_token, "Clause Import Target Org")
    imported = _import_zip(client, target_token, target_org["id"], bundle, "Elsewhere")
    assert imported.status_code == 201, imported.text
    assert any("was skipped" in w for w in imported.json()["warnings"])
    new_project = imported.json()["project"]
    new_requirement = client.get(f"/api/v1/projects/{new_project['id']}/requirements", headers=auth_headers(target_token)).json()[0]
    graph = client.get(
        f"/api/v1/projects/{new_project['id']}/artefacts/{REQ}/{new_requirement['id']}/link-graph", headers=auth_headers(target_token)
    ).json()
    assert graph["edges"] == []


# --- the retired surface ---------------------------------------------------------------------


def test_the_old_traceability_routes_and_mcp_tools_are_gone(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    old = f"/api/v1/projects/{ctx['project']['id']}/modules/compliance/requirements/{ctx['requirement']['id']}/traceability-links"
    assert client.get(old, headers=auth_headers(admin_token)).status_code == 404
    names = {tool.name for tool in build_mcp_tool_manifest()}
    assert "create_requirement_traceability_link" not in names and "delete_requirement_traceability_link" not in names


# --- the migration ---------------------------------------------------------------------------


def test_migration_moves_every_traceability_row_into_artefact_links_and_back(client, admin_token, org_id):
    ctx = _setup(client, admin_token, org_id)
    types = _link_types(client, admin_token, org_id)
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    command.downgrade(build_alembic_config(), "0068")
    try:
        with engine.begin() as conn:
            for row_id, clause_id, type_name in (
                (first, ctx["clause"]["id"], "Derives from"), (second, ctx["child"]["id"], "Related to"),
            ):
                conn.execute(
                    text(
                        "INSERT INTO compliance_requirement_traceability_links "
                        "(id, requirement_id, compliance_requirement_id, link_type_id, created_by) "
                        "VALUES (:id, :req, :clause, :type, :user)"
                    ),
                    {"id": row_id, "req": ctx["requirement"]["id"], "clause": clause_id, "type": types[type_name], "user": admin_id},
                )
    finally:
        command.upgrade(build_alembic_config(), "head")

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, source_type, source_id, target_type, target_id, link_type_id, created_by, "
                "source_project_id, target_project_id FROM artefact_links "
                "WHERE target_type = 'compliance_requirement' AND source_id = :req ORDER BY target_id"
            ),
            {"req": ctx["requirement"]["id"]},
        ).all()
        table = conn.execute(text("SELECT to_regclass('compliance_requirement_traceability_links')")).scalar()
    assert table is None
    by_id = {str(r.id): r for r in rows}
    assert set(by_id) == {first, second}
    assert str(by_id[first].target_id) == ctx["clause"]["id"] and str(by_id[first].link_type_id) == types["Derives from"]
    assert str(by_id[second].target_id) == ctx["child"]["id"] and str(by_id[second].link_type_id) == types["Related to"]
    assert all(
        r.source_type == "requirement" and str(r.created_by) == admin_id and r.source_project_id is None
        and r.target_project_id is None for r in rows
    )
    # They now read like any other link.
    assert len(_graph_edges(client, admin_token, ctx)) == 2


def test_which_project_roles_can_make_a_clause_link(client, admin_token, org_id):
    """Pins who may link an unapproved requirement to a clause for each built-in project role (`link`/`manage`
    or a stakeholder, project administrator or manager role on the requirement, `view` on the clause), so a
    change to it is a visible decision."""
    ctx = _setup(client, admin_token, org_id)
    types = _link_types(client, admin_token, org_id)
    outcomes = {}
    # A different link type per role, so a role's attempt is never a duplicate of an earlier role's link.
    for role, type_name in zip(
        ("project_manager", "project_administrator", "stakeholder", "member"),
        ("Related to", "Derives from", "Depends on", "Implements"), strict=True,
    ):
        email = f"clause.{role}@example.com"
        user_id = create_org_user(client, admin_token, org_id, email, role="member")
        _assign_project_role(client, admin_token, ctx["project"]["id"], user_id, role)
        outcomes[role] = _link(client, login(client, email, "Password123!"), ctx, types[type_name]).status_code
    assert outcomes == {"project_manager": 201, "project_administrator": 201, "stakeholder": 201, "member": 403}


def test_an_organisation_owned_clause_is_only_offered_from_the_request_project(client, admin_token, org_id):
    """A clause belongs to the organisation, so searching a parent project for it finds nothing: a related
    project can never be used to reach a record the request project would not show."""
    org_ctx = _setup(client, admin_token, org_id, project_name="Clause Parent")
    parent = org_ctx["project"]
    can_be_parent = client.patch(
        f"/api/v1/projects/{parent['id']}", json={"can_be_parent": True}, headers=auth_headers(admin_token)
    )
    assert can_be_parent.status_code == 200, can_be_parent.text
    child = create_project(client, admin_token, org_id, name="Clause Child", parent_project_id=parent["id"])
    component_id, category_id = create_component_and_category(client, admin_token, child["id"])
    requirement = _requirement(client, admin_token, child["id"], component_id, category_id)
    page = _page(child["id"], requirement["id"])
    own = client.get(f"{page}/link-candidates", params={"other_type": CLAUSE}, headers=auth_headers(admin_token)).json()
    assert {i["id"] for i in own["items"]} >= {org_ctx["clause"]["id"]}
    via_parent = client.get(
        f"{page}/link-candidates", params={"other_type": CLAUSE, "other_project_id": parent["id"]},
        headers=auth_headers(admin_token),
    ).json()
    assert via_parent["items"] == []
