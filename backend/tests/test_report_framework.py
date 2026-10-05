"""Tests for the core report framework (`services.report_framework`, Module 1 Phase 12b).

Everything here runs against a synthetic `report_probe` module that is *not*
Context & Strategy, so the framework is proven generic: parameter validation,
registry validation (duplicate slug, unknown role/sub-component), the org gate,
scope rules (readable vs every project, child projects, cross-org isolation),
CSV/PDF rendering with injection neutralised and template branding, the
catalogue endpoints and the MCP tools. The module's routers are mounted on a
throw-away FastAPI app (the real app's routes are built once at import), while
setup and the catalogue use the real app.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.modules import registry as module_registry
from app.modules.registry import (
    ModuleDefinition,
    ModuleRoleDefinition,
    ModuleSubComponentDefinition,
    ReportDefinition,
    ReportParamDefinition,
    build_mcp_tool_manifest,
    build_registry,
    get_module_reports,
    validate_report_definitions,
)
from app.services.report_framework import (
    ReportContext,
    ReportResult,
    ReportSection,
    build_report_routers,
    render_csv,
    render_pdf,
    report_mcp_tools,
)
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

KEY = "report_probe"
ORG_PREFIX = f"/api/v1/orgs/{{organization_id}}/modules/{KEY}"
PROJECT_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{KEY}"
FORMULA = "=HYPERLINK(\"http://evil.example\",\"x\")"
MARKUP = '<img src="file:///etc/passwd"/> & <b>bold</b>'


def _collect(db, ctx: ReportContext) -> ReportResult:
    """Echoes the scope and parameters so tests can see exactly what core handed a collector."""
    return ReportResult(
        key="probe", title="Probe report", scope_label=ctx.scope_label, generated_at=datetime.now(UTC),
        notes=[ctx.scope_note, MARKUP],
        sections=[
            ReportSection("main", "Projects", ["Name", "Note"], [[p.name, FORMULA] for p in ctx.projects], note=MARKUP),
            ReportSection("second", "Second", ["A"], [["only in the PDF"]]),
        ],
        metrics=[("Projects", len(ctx.projects))],
        data={
            "projects": [p.name for p in ctx.projects], "params": {k: str(v) if v is not None else None for k, v in ctx.params.items()},
            "all_org_projects": ctx.all_org_projects, "eligible_alpha": [p.name for p in ctx.eligible(db, "alpha")],
        },
        eligible_projects=len(ctx.projects),
    )


_PARAMS = (
    ReportParamDefinition("mode", "string", default="a", choices=("a", "b"), description="Mode."),
    ReportParamDefinition("limit", "integer", default=3, minimum=1, maximum=5),
    ReportParamDefinition("flag", "boolean"),
    ReportParamDefinition("day", "date"),
    ReportParamDefinition("ref", "uuid"),
)

DEFINITIONS = (
    ReportDefinition(
        "p1", "probe-all", "Probe all", "Readable-scope org report.", _collect, subcomponent="alpha",
        org_level=True, org_role_key="probe_viewer", params=_PARAMS,
    ),
    ReportDefinition(
        "p2", "probe-everything", "Probe everything", "Every-project org report.", _collect, subcomponent="alpha",
        org_level=True, org_role_key="probe_viewer", org_scope="all_org_projects",
    ),
    ReportDefinition("p3", "probe-project-only", "Probe project only", "No org variant.", _collect, subcomponent="alpha"),
    ReportDefinition("p4", "probe-beta", "Probe beta", "Gated by a disabled sub-component.", _collect, subcomponent="beta"),
    # Invalid declarations: each must be excluded, never served or catalogued.
    ReportDefinition("p5", "probe-all", "Duplicate slug", "x", _collect, subcomponent="alpha"),
    ReportDefinition(
        "p6", "probe-bad-role", "Bad role", "x", _collect, subcomponent="alpha", org_level=True,
        org_role_key="probe_project_role",
    ),
    ReportDefinition("p7", "probe-bad-sub", "Bad sub-component", "x", _collect, subcomponent="nope"),
)
ROUTERS = build_report_routers(KEY, DEFINITIONS)


def _org_router() -> APIRouter:
    router = APIRouter(prefix=ORG_PREFIX)
    router.include_router(ROUTERS.org)
    return router


def _project_router() -> APIRouter:
    router = APIRouter(prefix=PROJECT_PREFIX)
    router.include_router(ROUTERS.project)
    return router


def _module() -> ModuleDefinition:
    return ModuleDefinition(
        key=KEY, name="Report Probe", description="Fixture module for the report framework tests.", version="0.0.1",
        default_enabled=True, implemented=False, get_router=_org_router, get_project_router=_project_router,
        sub_components=(
            ModuleSubComponentDefinition(key="alpha", name="Alpha", default_enabled=True),
            ModuleSubComponentDefinition(key="beta", name="Beta", default_enabled=False),
        ),
        roles=(
            ModuleRoleDefinition(role_key="probe_viewer", name="Probe Viewer", description="Runs org reports.", scope="org"),
            ModuleRoleDefinition(role_key="probe_project_role", name="Probe Project", description="x", scope="project"),
        ),
        reports=DEFINITIONS,
        mcp_tools=report_mcp_tools(DEFINITIONS, project_router_prefix=PROJECT_PREFIX),
    )


@pytest.fixture
def probe(client):
    """Registers the probe module; yields a client serving only its routers."""
    module_registry.INSTALLED_MODULES.append(_module())
    build_registry(force=True)
    app = FastAPI()
    app.include_router(_org_router())
    app.include_router(_project_router())
    with TestClient(app) as probe_client:
        yield probe_client
    module_registry.INSTALLED_MODULES[:] = [m for m in module_registry.INSTALLED_MODULES if m.key != KEY]
    build_registry(force=True)


def _enable(client, token, org_id) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{KEY}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    _enable(client, token, org["id"])
    return org, create_project(client, token, org["id"], f"{name} A"), token


def _member(client, admin_token, org_id, project_id, email):
    user_id = create_org_user(client, admin_token, org_id, email)
    if project_id:
        resp = client.post(
            f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(admin_token),
        )
        assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _grant_viewer(client, admin_token, org_id, user_id) -> None:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles", json={"module_key": KEY, "role_key": "probe_viewer"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _get(probe, token, url, expect=200, **params):
    resp = probe.get(url, params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp


def _project_url(project_id, slug="probe-all") -> str:
    return f"/api/v1/projects/{project_id}/modules/{KEY}/reports/{slug}"


def _org_url(org_id, slug="probe-all") -> str:
    return f"/api/v1/orgs/{org_id}/modules/{KEY}/reports/{slug}"


# --- Registry validation ------------------------------------------------------------


def test_invalid_declarations_are_excluded_and_logged(probe):
    slugs = [d.slug for d in get_module_reports(KEY)]
    assert slugs == ["probe-all", "probe-everything", "probe-project-only", "probe-beta"]


def test_validate_report_definitions_reports_each_problem():
    def bad(**overrides):
        base = dict(key="k", slug="s", title="t", description="d", collector=_collect)
        base.update(overrides)
        return ReportDefinition(**base)

    cases = {
        "org_level without an org_role_key": bad(org_level=True),
        "org_role_key on a report": bad(org_role_key="r"),
        "unknown org_scope": bad(org_scope="everyone"),
        "invalid key or slug": bad(slug="Bad Slug"),
        "is invalid or reserved": bad(params=(ReportParamDefinition("format", "string"),)),
        "default is not one of its choices": bad(params=(ReportParamDefinition("x", "string", default="z", choices=("a",)),)),
        "declares bounds on a string": bad(params=(ReportParamDefinition("x", "string", minimum=1),)),
        "duplicate parameter name": bad(params=(ReportParamDefinition("x", "string"), ReportParamDefinition("x", "string"))),
        "default is above its maximum": bad(params=(ReportParamDefinition("x", "integer", default=9, maximum=5),)),
    }
    for expected, definition in cases.items():
        valid, problems = validate_report_definitions([definition])
        assert valid == [], expected
        assert any(expected in p for p in problems), (expected, problems)
    ok, problems = validate_report_definitions([bad()])
    assert len(ok) == 1 and problems == []


# --- Parameters -----------------------------------------------------------------------


def test_params_are_typed_defaulted_and_validated(client, admin_token, probe):
    org, project, token = _setup(client, admin_token, "Params Co")
    url = _project_url(project["id"])
    default = _get(probe, token, url).json()["data"]["params"]
    assert default == {"mode": "a", "limit": "3", "flag": None, "day": None, "ref": None}

    ref = str(uuid.uuid4())
    chosen = _get(probe, token, url, mode="b", limit=5, flag="true", day="2026-03-01", ref=ref).json()["data"]["params"]
    assert chosen == {"mode": "b", "limit": "5", "flag": "True", "day": "2026-03-01", "ref": ref}

    assert "one of: a, b" in _get(probe, token, url, expect=400, mode="z").json()["detail"]
    for bad in ({"limit": 0}, {"limit": 6}, {"limit": "x"}, {"day": "not-a-date"}, {"ref": "nope"}, {"flag": "maybe"}, {"format": "xml"}):
        _get(probe, token, url, expect=422, **bad)
    # Unknown query parameters are ignored, as they always were.
    _get(probe, token, url, whatever="1")


def test_openapi_and_mcp_parameters_come_from_the_declaration(probe):
    spec = probe.get("/openapi.json").json()
    operation = spec["paths"][_project_url("{project_id}")]["get"]
    by_name = {p["name"]: p for p in operation["parameters"]}
    assert {"project_id", "format", "include_children", "report_template_id", "mode", "limit", "flag", "day", "ref"} <= set(by_name)
    assert by_name["limit"]["schema"]["anyOf"][0]["maximum"] == 5 and by_name["mode"]["description"] == "Mode."
    assert "include_children" not in {p["name"] for p in spec["paths"][_org_url("{organization_id}")]["get"]["parameters"]}

    tool = next(t for t in build_mcp_tool_manifest() if t.name == f"{KEY}_get_probe_all_report")
    assert tool.method == "GET" and tool.mutates is False
    names = {p["name"]: p for p in tool.params}
    assert names["project_id"]["in"] == "path" and names["limit"]["type"] == "integer" and "One of: a, b" in names["mode"]["description"]
    assert names["day"]["type"] == "string" and "ISO date" in names["day"]["description"]
    assert "format" not in names and "report_template_id" not in names
    assert f"{KEY}_get_probe_everything_report" in {t.name for t in build_mcp_tool_manifest()}
    # Invalid declarations produce no tool.
    assert all("bad" not in t.name for t in build_mcp_tool_manifest() if t.name.startswith(KEY))


# --- Access ----------------------------------------------------------------------------


def test_project_route_needs_membership_module_and_subcomponent(client, admin_token, probe):
    org, project, token = _setup(client, admin_token, "Gate Co")
    _, outsider = _member(client, token, org["id"], None, "outsider@example.com")
    _get(probe, outsider, _project_url(project["id"]), expect=404)
    _get(probe, token, _project_url(project["id"]))
    # beta is off by default: the route answers 404 like a route that does not exist.
    _get(probe, token, _project_url(project["id"], "probe-beta"), expect=404)
    # Invalid-against-registry reports are not served even though a route exists for them.
    _get(probe, token, _project_url(project["id"], "probe-bad-sub"), expect=404)

    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{KEY}", json={"enabled": False}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    _get(probe, token, _project_url(project["id"]), expect=404)


def test_org_route_needs_the_declared_role(client, admin_token, probe):
    org, project, admin = _setup(client, admin_token, "Role Co")
    user_id, member = _member(client, admin, org["id"], project["id"], "member@example.com")
    _get(probe, member, _org_url(org["id"]), expect=403)
    _get(probe, admin, _org_url(org["id"]))  # org admins hold module roles
    _grant_viewer(client, admin, org["id"], user_id)
    _get(probe, member, _org_url(org["id"]))
    # A project-only slug has no organisation route; a role declared for a project is never accepted.
    _get(probe, admin, _org_url(org["id"], "probe-project-only"), expect=404)
    _get(probe, admin, _org_url(org["id"], "probe-bad-role"), expect=404)


def test_readable_scope_excludes_unreadable_projects_but_all_org_scope_does_not(client, admin_token, probe):
    org, project_a, admin = _setup(client, admin_token, "Scope Co")
    create_project(client, admin, org["id"], "Scope Co B")
    user_id, viewer = _member(client, admin, org["id"], project_a["id"], "viewer@example.com")
    _grant_viewer(client, admin, org["id"], user_id)

    readable = _get(probe, viewer, _org_url(org["id"])).json()["data"]
    assert readable["projects"] == ["Scope Co A"] and readable["all_org_projects"] is False
    everything = _get(probe, viewer, _org_url(org["id"], "probe-everything")).json()["data"]
    assert everything["projects"] == ["Scope Co A", "Scope Co B"] and everything["all_org_projects"] is True
    assert "Covers 2 project(s) in this organisation." in _get(probe, viewer, _org_url(org["id"], "probe-everything")).json()["notes"]


def test_org_report_project_filter_narrows_within_scope_and_never_widens(client, admin_token, probe):
    org, project_a, admin = _setup(client, admin_token, "Filter Co")
    project_b = create_project(client, admin, org["id"], "Filter Co B")
    user_id, viewer = _member(client, admin, org["id"], project_a["id"], "filter-viewer@example.com")
    _grant_viewer(client, admin, org["id"], user_id)
    url = _org_url(org["id"])

    assert _get(probe, admin, url).json()["data"]["projects"] == ["Filter Co A", "Filter Co B"]
    assert _get(probe, admin, url, project_id=project_b["id"]).json()["data"]["projects"] == ["Filter Co B"]
    # The viewer can read only A under the default scope: B is outside it, so the filter cannot reach it.
    assert _get(probe, viewer, url, project_id=project_a["id"]).json()["data"]["projects"] == ["Filter Co A"]
    _get(probe, viewer, url, project_id=project_b["id"], expect=404)
    _get(probe, admin, url, project_id="00000000-0000-0000-0000-000000000000", expect=404)
    _get(probe, admin, url, project_id="not-a-uuid", expect=422)
    # An explicit all-projects scope still lets a viewer filter to a project they hold no role on.
    everything = _get(probe, viewer, _org_url(org["id"], "probe-everything"), project_id=project_b["id"])
    assert everything.json()["data"]["projects"] == ["Filter Co B"]
    # Another organisation's project is never in scope.
    org2, project2, _ = _setup(client, admin_token, "Filter Other")
    _get(probe, admin, url, project_id=project2["id"], expect=404)


def test_org_catalogue_lists_only_projects_the_report_can_be_narrowed_to(client, admin_token, probe):
    """The picker's list is exactly what the route accepts: no project the filter would 404 on."""
    org, project_a, admin = _setup(client, admin_token, "Pick Co")
    create_project(client, admin, org["id"], "Pick Co B")
    create_org_user(client, admin, org["id"], "pick-owner@example.com", role="project_creator")
    owner = login(client, "pick-owner@example.com", "Password123!")
    private = create_project(client, owner, org["id"], "Pick Co Private")
    url = f"/api/v1/orgs/{org['id']}/report-catalogue"

    def listed(token, slug):
        entries = _probe_entries(client.get(url, headers=auth_headers(token)).json())
        return [p["name"] for p in entries[slug]["projects"]]

    # Readable scope: an org admin with no role on the private project is not offered it, and the route agrees.
    assert listed(admin, "probe-all") == ["Pick Co A", "Pick Co B"]
    _get(probe, admin, _org_url(org["id"]), project_id=private["id"], expect=404)
    # An explicit all-projects scope offers every project, and the route accepts each.
    assert listed(admin, "probe-everything") == ["Pick Co A", "Pick Co B", "Pick Co Private"]
    _get(probe, admin, _org_url(org["id"], "probe-everything"), project_id=private["id"])
    # A project where the sub-component is switched off is not offered.
    off = client.put(
        f"/api/v1/projects/{project_a['id']}/modules/{KEY}/subcomponents/alpha", json={"enabled": False}, headers=auth_headers(admin),
    )
    assert off.status_code == 200, off.text
    assert "Pick Co A" not in listed(admin, "probe-all")


def test_org_admin_without_project_roles_sees_no_projects_in_readable_scope(client, admin_token, probe):
    org, _, token = _setup(client, admin_token, "Admin Co")
    create_org_user(client, token, org["id"], "owner@example.com", role="project_creator")
    owner_token = login(client, "owner@example.com", "Password123!")
    create_project(client, owner_token, org["id"], "Admin Co Private")
    names = _get(probe, token, _org_url(org["id"])).json()["data"]["projects"]
    assert "Admin Co Private" not in names


def test_cross_org_isolation(client, admin_token, probe):
    org1, project1, admin1 = _setup(client, admin_token, "Org One")
    org2, _, admin2 = _setup(client, admin_token, "Org Two")
    _get(probe, admin2, _org_url(org1["id"]), expect=404)
    _get(probe, admin2, _project_url(project1["id"]), expect=404)
    assert _get(probe, admin1, _org_url(org1["id"])).json()["data"]["projects"] == ["Org One A"]
    assert _get(probe, admin2, _org_url(org2["id"], "probe-everything")).json()["data"]["projects"] == ["Org Two A"]


def test_include_children_only_adds_readable_children(client, admin_token, probe):
    org, _, admin = _setup(client, admin_token, "Tree Co")
    parent = create_project(client, admin, org["id"], "Tree Parent", can_be_parent=True)
    create_project(client, admin, org["id"], "Tree Child", parent_project_id=parent["id"])
    url = _project_url(parent["id"])
    assert _get(probe, admin, url).json()["data"]["projects"] == ["Tree Parent"]
    assert _get(probe, admin, url, include_children=True).json()["data"]["projects"] == ["Tree Child", "Tree Parent"]
    _, parent_only = _member(client, admin, org["id"], parent["id"], "parent_only@example.com")
    assert _get(probe, parent_only, url, include_children=True).json()["data"]["projects"] == ["Tree Parent"]


def test_subcomponent_check_is_cached_per_project(client, admin_token, probe):
    org, project, token = _setup(client, admin_token, "Elig Co")
    data = _get(probe, token, _project_url(project["id"])).json()["data"]
    assert data["eligible_alpha"] == ["Elig Co A"]


# --- Output formats ------------------------------------------------------------------------


def test_json_shape_and_pdf_csv_files(client, admin_token, probe):
    org, project, token = _setup(client, admin_token, "Format Co")
    body = _get(probe, token, _project_url(project["id"])).json()
    assert set(body) == {"key", "title", "scope_label", "generated_at", "notes", "sections", "metrics", "data", "eligible_projects"}
    assert body["sections"][0]["rows"] == [["Format Co A", FORMULA]]
    assert body["metrics"] == [{"label": "Projects", "value": 1}]

    csv_resp = _get(probe, token, _project_url(project["id"]), format="csv")
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert csv_resp.headers["content-disposition"] == 'attachment; filename="Format Co A-probe-all.csv"'
    lines = csv_resp.text.splitlines()
    assert lines[0] == "Name,Note" and "'=HYPERLINK" in lines[1]  # formula neutralised, first section only
    assert "only in the PDF" not in csv_resp.text

    pdf = _get(probe, token, _project_url(project["id"]), format="pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")


def test_render_functions_handle_empty_results_and_escape_markup():
    result = ReportResult("k", "T", "Scope", datetime.now(UTC), [MARKUP], [ReportSection("s", "S", ["A"], [[MARKUP]], note=MARKUP)])
    assert render_pdf(result).startswith(b"%PDF")
    empty = ReportResult("k", "T", "Scope", datetime.now(UTC), [], [])
    assert render_csv(empty).decode() == "\r\n"
    assert render_pdf(empty).startswith(b"%PDF")
    assert render_csv(ReportResult("k", "T", "S", datetime.now(UTC), [], [ReportSection("s", "S", ["=A"], [["+b"]])])).decode() == "'=A\r\n'+b\r\n"


def test_template_branding_applies_to_pdf_and_foreign_templates_are_rejected(client, admin_token, probe):
    org, project, token = _setup(client, admin_token, "Brand Co")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/report-templates", json={"name": "Branded", "accent_color_hex": "#ff0000", "footer_text": "Confidential"},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    plain = _get(probe, token, _project_url(project["id"]), format="pdf").content
    branded = _get(probe, token, _project_url(project["id"]), format="pdf", report_template_id=template_id).content
    assert branded.startswith(b"%PDF") and branded != plain
    assert _get(probe, token, _org_url(org["id"]), format="pdf", report_template_id=template_id).content.startswith(b"%PDF")

    other, _, other_admin = _setup(client, admin_token, "Brand Other")
    foreign = client.post(f"/api/v1/orgs/{other['id']}/report-templates", json={"name": "Theirs"}, headers=auth_headers(other_admin))
    assert foreign.status_code == 201, foreign.text
    _get(probe, token, _project_url(project["id"]), expect=400, report_template_id=foreign.json()["id"])
    _get(probe, token, _project_url(project["id"]), expect=400, report_template_id=str(uuid.uuid4()))
    _get(probe, token, _project_url(project["id"]), expect=422, report_template_id="nope")


# --- Catalogue -------------------------------------------------------------------------------


def _probe_entries(entries):
    return {e["slug"]: e for e in entries if e["module_key"] == KEY}


def test_project_catalogue_lists_enabled_reports_with_parameters(client, admin_token, probe):
    org, project, token = _setup(client, admin_token, "Catalogue Co")
    resp = client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    entries = _probe_entries(resp.json())
    assert list(entries) == ["probe-all", "probe-everything", "probe-project-only"]  # beta off, invalid excluded
    entry = entries["probe-all"]
    assert entry["scope"] == "project" and entry["supports_include_children"] is True
    assert entry["supports_project_filter"] is False
    assert entry["path"] == _project_url(project["id"]) and entry["formats"] == ["json", "pdf", "csv"]
    assert entry["module_name"] == "Report Probe"
    params = {p["name"]: p for p in entry["params"]}
    assert params["mode"]["choices"] == ["a", "b"] and params["limit"]["minimum"] == 1 and params["limit"]["maximum"] == 5
    assert params["day"]["type"] == "date"

    _, outsider = _member(client, token, org["id"], None, "cat_outsider@example.com")
    assert client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(outsider)).status_code == 403
    client.put(f"/api/v1/orgs/{org['id']}/modules/{KEY}", json={"enabled": False}, headers=auth_headers(token))
    assert _probe_entries(client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(token)).json()) == {}


def test_org_catalogue_lists_only_reports_the_caller_may_run(client, admin_token, probe):
    org, project, admin = _setup(client, admin_token, "OrgCat Co")
    user_id, member = _member(client, admin, org["id"], project["id"], "orgcat_member@example.com")
    url = f"/api/v1/orgs/{org['id']}/report-catalogue"
    assert _probe_entries(client.get(url, headers=auth_headers(member)).json()) == {}
    _grant_viewer(client, admin, org["id"], user_id)
    entries = _probe_entries(client.get(url, headers=auth_headers(member)).json())
    assert list(entries) == ["probe-all", "probe-everything"]  # project-only and beta-gated ones are absent
    assert entries["probe-all"]["scope"] == "organization" and entries["probe-all"]["supports_include_children"] is False
    assert entries["probe-all"]["supports_project_filter"] is True
    assert [p["name"] for p in entries["probe-all"]["projects"]] == ["OrgCat Co A"]
    assert entries["probe-all"]["path"] == _org_url(org["id"])

    _, _, outsider = _setup(client, admin_token, "OrgCat Other")
    assert client.get(url, headers=auth_headers(outsider)).status_code == 403


# --- Boundary --------------------------------------------------------------------------------


def test_core_report_files_import_nothing_from_a_specific_module():
    """The boundary rule: core may only reach modules through `modules.registry`."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    for relative in ("services/report_framework.py", "services/report_document.py", "services/reports.py", "routers/report_catalogue.py"):
        tree = ast.parse((app_dir / relative).read_text())
        for node in ast.walk(tree):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names] if isinstance(node, ast.Import) else []
            for name in names:
                assert not name.startswith("app.modules.") or name == "app.modules.registry", (relative, name)
