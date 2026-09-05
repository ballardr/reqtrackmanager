"""Tests for the module system's Phase 4 module-contributed MCP tools
(docs/compliance-module-plan.md): `app.modules.registry.
build_mcp_tool_manifest`'s mechanical verification of a module's own
`McpToolDefinition` declarations (module-key name prefixing, path-prefix
enforcement against the declaring module's own router, `mutates` derivation
from HTTP method, approval-action exclusion sourced from the resolved
route's own `openapi_extra` metadata rather than the module's declaration),
and `GET /api/v1/system/modules/mcp-tools`'s plain-authentication gating.

Every test that registers a fixture module into the process-global
`INSTALLED_MODULES` list follows `test_module_registry.py`'s own `fake_
module` fixture convention: always tears down by removing it and rebuilding
the registry cache, so this module-level mutable list never leaks state
into another test regardless of execution order."""

import uuid as uuid_lib

import pytest
from fastapi import APIRouter

from app.modules import registry as module_registry
from app.modules.registry import (
    APPROVAL_ACTION_ROUTE_EXTRA,
    McpToolDefinition,
    ModuleDefinition,
    build_mcp_tool_manifest,
    build_registry,
)
from tests.conftest import auth_headers, create_org_user, login

FAKE_MODULE_KEY = "fake_mcp_tool_module"
ROUTER_PREFIX = f"/api/v1/orgs/{{organization_id}}/modules/{FAKE_MODULE_KEY}"


def _fixture_router() -> APIRouter:
    router = APIRouter(prefix=ROUTER_PREFIX)

    @router.get("/things")
    def list_things(organization_id: uuid_lib.UUID):
        return []

    @router.post("/things")
    def create_thing(organization_id: uuid_lib.UUID):
        return {}

    @router.post("/things/{thing_id}/approve", openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA)
    def approve_thing(organization_id: uuid_lib.UUID, thing_id: uuid_lib.UUID):
        return {}

    return router


_ORG_ID_PARAM = {"name": "organization_id", "type": "uuid", "required": True, "in": "path"}


def _fake_module(**overrides) -> ModuleDefinition:
    defaults = dict(
        key=FAKE_MODULE_KEY, name="Fake MCP Tool Module",
        description="A fixture module registered only for this test file's own assertions.",
        version="0.0.1", default_enabled=True, implemented=False, get_router=_fixture_router,
        mcp_tools=(
            McpToolDefinition(
                name="list_things", description="Lists fixture things.", method="GET",
                path_template=f"{ROUTER_PREFIX}/things", params=[_ORG_ID_PARAM],
            ),
            McpToolDefinition(
                name="create_thing", description="Creates a fixture thing.", method="POST",
                path_template=f"{ROUTER_PREFIX}/things", params=[_ORG_ID_PARAM],
            ),
            McpToolDefinition(
                name="sneaky_approve", description="Tries to expose the approval-marked endpoint.",
                method="POST", path_template=f"{ROUTER_PREFIX}/things/{{thing_id}}/approve",
                params=[_ORG_ID_PARAM, {"name": "thing_id", "type": "uuid", "required": True, "in": "path"}],
            ),
            McpToolDefinition(
                name="escape_prefix", description="Tries to point outside this module's own router.",
                method="GET", path_template="/api/v1/system/modules", params=[],
            ),
            McpToolDefinition(
                name="dangling", description="Points at a path with no matching route.",
                method="GET", path_template=f"{ROUTER_PREFIX}/does-not-exist", params=[],
            ),
            McpToolDefinition(
                name="malformed_param_tool", description="Has one malformed param.",
                method="GET", path_template=f"{ROUTER_PREFIX}/things",
                params=[_ORG_ID_PARAM, {"name": "bad_param", "required": True}],
            ),
            McpToolDefinition(
                name=f"{FAKE_MODULE_KEY}_list_things",
                description="Tries to pre-prefix its own local name.",
                method="GET", path_template=f"{ROUTER_PREFIX}/things", params=[],
            ),
        ),
    )
    defaults.update(overrides)
    return ModuleDefinition(**defaults)


@pytest.fixture
def fake_module():
    module_registry.INSTALLED_MODULES.append(_fake_module())
    build_registry(force=True)
    yield FAKE_MODULE_KEY
    module_registry.INSTALLED_MODULES[:] = [
        m for m in module_registry.INSTALLED_MODULES if m.key != FAKE_MODULE_KEY
    ]
    build_registry(force=True)


@pytest.fixture
def fake_module_without_router():
    module_registry.INSTALLED_MODULES.append(
        _fake_module(
            key=f"{FAKE_MODULE_KEY}_no_router", get_router=lambda: None,
            mcp_tools=(
                McpToolDefinition(
                    name="orphan", description="Can never resolve — its module has no router.",
                    method="GET", path_template="/api/v1/orgs/{organization_id}/modules/whatever/orphan",
                    params=[],
                ),
            ),
        )
    )
    build_registry(force=True)
    yield f"{FAKE_MODULE_KEY}_no_router"
    module_registry.INSTALLED_MODULES[:] = [
        m for m in module_registry.INSTALLED_MODULES if m.key != f"{FAKE_MODULE_KEY}_no_router"
    ]
    build_registry(force=True)


def _by_name(tools, name):
    return next((t for t in tools if t.name == name), None)


def test_manifest_includes_valid_get_tool(fake_module):
    tools = build_mcp_tool_manifest()
    tool = _by_name(tools, f"{FAKE_MODULE_KEY}_list_things")
    assert tool is not None
    assert tool.mutates is False
    assert tool.method == "GET"
    assert tool.path_template == f"{ROUTER_PREFIX}/things"
    assert tool.params == [_ORG_ID_PARAM | {"description": ""}]


def test_manifest_derives_mutates_from_method_not_declaration(fake_module):
    tools = build_mcp_tool_manifest()
    tool = _by_name(tools, f"{FAKE_MODULE_KEY}_create_thing")
    assert tool is not None
    assert tool.mutates is True


def test_manifest_excludes_tool_outside_module_router_prefix(fake_module):
    tools = build_mcp_tool_manifest()
    assert _by_name(tools, f"{FAKE_MODULE_KEY}_escape_prefix") is None


def test_manifest_excludes_tool_with_no_matching_route(fake_module):
    tools = build_mcp_tool_manifest()
    assert _by_name(tools, f"{FAKE_MODULE_KEY}_dangling") is None


def test_manifest_excludes_approval_marked_route_regardless_of_declaration(fake_module):
    tools = build_mcp_tool_manifest()
    assert _by_name(tools, f"{FAKE_MODULE_KEY}_sneaky_approve") is None


def test_manifest_drops_malformed_param_but_keeps_the_tool(fake_module):
    tools = build_mcp_tool_manifest()
    tool = _by_name(tools, f"{FAKE_MODULE_KEY}_malformed_param_tool")
    assert tool is not None
    assert tool.params == [_ORG_ID_PARAM | {"description": ""}]


def test_manifest_always_prefixes_tool_name_even_if_self_prefixed(fake_module):
    tools = build_mcp_tool_manifest()
    # The module declared a local name that already looks prefixed
    # (f"{FAKE_MODULE_KEY}_list_things") — the builder must not special-case
    # this away; it always prepends the module key regardless.
    assert _by_name(tools, f"{FAKE_MODULE_KEY}_{FAKE_MODULE_KEY}_list_things") is not None
    # And the "real" list_things tool is unaffected/undoubled.
    assert _by_name(tools, f"{FAKE_MODULE_KEY}_list_things") is not None


def test_manifest_excludes_all_tools_when_module_has_no_router(fake_module_without_router):
    tools = build_mcp_tool_manifest()
    assert _by_name(tools, f"{FAKE_MODULE_KEY}_no_router_orphan") is None
    assert not any(t.name.startswith(f"{FAKE_MODULE_KEY}_no_router") for t in tools)


def test_manifest_endpoint_requires_authentication(client):
    resp = client.get("/api/v1/system/modules/mcp-tools")
    assert resp.status_code == 401


def test_manifest_endpoint_returns_resolved_tools(client, admin_token, fake_module):
    resp = client.get("/api/v1/system/modules/mcp-tools", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    assert f"{FAKE_MODULE_KEY}_list_things" in names
    assert f"{FAKE_MODULE_KEY}_escape_prefix" not in names
    assert f"{FAKE_MODULE_KEY}_sneaky_approve" not in names


def test_manifest_endpoint_requires_no_elevated_role(client, admin_token, org_id, fake_module):
    """A plain org member — no server-admin, no MODULE_ADMINISTRATOR — can
    still call this endpoint: it's gated by plain authentication only, not
    an admin role, per this phase's own hardening pass."""
    create_org_user(client, admin_token, org_id, "mcp-tools-member@example.com", password="Password123!", role="member")
    member_token = login(client, "mcp-tools-member@example.com", "Password123!")
    resp = client.get("/api/v1/system/modules/mcp-tools", headers=auth_headers(member_token))
    assert resp.status_code == 200


# --- Against the REAL registry (Compliance, Phase 6) -------------------------
#
# Every test above proves `build_mcp_tool_manifest`'s mechanics against a
# fixture module — this section proves the real thing: Compliance is now a
# real, permanent `INSTALLED_MODULES` entry (Phase 5) with a real router and
# three declared MCP tools (Phase 6), so this is the "prove itself against
# something real once a real module exists" integration coverage the plan's
# own "Reused Existing Patterns" section calls for, that a fixture-only
# suite can't give on its own. Deliberately does NOT use the `fake_module`
# fixture — no `INSTALLED_MODULES` mutation needed, since Compliance is
# already there.


def test_compliance_mcp_tools_resolve_against_the_real_registry():
    """All five of Compliance's tools (three from Phase 6, two more from
    Phase 7) resolve, are read-only (`mutates=False`, all GET), and carry
    exactly the path parameters their router endpoints require — the
    concrete proof that `module.py`'s declared `path_template`s actually
    match real routes on `compliance.router.router`/`compliance.
    project_router.router`, not just that the strings look right. The
    Phase 7 tools are the first real proof that `build_mcp_tool_manifest`
    validates a tool against *either* of a module's two router prefixes
    (`app.modules.registry.ModuleDefinition.get_project_router`), not just
    `get_router`'s."""
    tools = build_mcp_tool_manifest()
    by_name = {t.name: t for t in tools}

    assert "compliance_list_standards" in by_name
    assert "compliance_get_standard_version" in by_name
    assert "compliance_list_requirements" in by_name
    assert "compliance_get_project_status" in by_name
    assert "compliance_list_non_compliant_requirements" in by_name

    list_standards = by_name["compliance_list_standards"]
    assert list_standards.mutates is False
    assert list_standards.method == "GET"
    assert list_standards.path_template == "/api/v1/orgs/{organization_id}/modules/compliance/standards"
    assert {p["name"] for p in list_standards.params} == {"organization_id"}

    get_version = by_name["compliance_get_standard_version"]
    assert get_version.mutates is False
    assert get_version.path_template == (
        "/api/v1/orgs/{organization_id}/modules/compliance/standards/{standard_id}/versions/{version_id}"
    )
    assert {p["name"] for p in get_version.params} == {"organization_id", "standard_id", "version_id"}
    assert all(p["in"] == "path" and p["required"] for p in get_version.params)

    list_requirements = by_name["compliance_list_requirements"]
    assert list_requirements.mutates is False
    assert list_requirements.path_template == (
        "/api/v1/orgs/{organization_id}/modules/compliance/standards/{standard_id}/versions/{version_id}/requirements"
    )
    assert {p["name"] for p in list_requirements.params} == {"organization_id", "standard_id", "version_id"}

    # Phase 7's two tools: `project_id` only, no `organization_id` at all —
    # the whole reason they live on `get_project_router()` rather than
    # nested under the org-scoped router (see module.py's own docstring).
    get_status = by_name["compliance_get_project_status"]
    assert get_status.mutates is False
    assert get_status.path_template == "/api/v1/projects/{project_id}/modules/compliance/status"
    assert {p["name"] for p in get_status.params} == {"project_id"}

    list_non_compliant = by_name["compliance_list_non_compliant_requirements"]
    assert list_non_compliant.mutates is False
    assert list_non_compliant.path_template == (
        "/api/v1/projects/{project_id}/modules/compliance/non-compliant-requirements"
    )
    assert {p["name"] for p in list_non_compliant.params} == {"project_id"}

    # No mutating tool for publish/retire, applicability, or assessment is
    # declared at all — this module's MCP surface stays deliberately
    # read-only across both Phase 6 and Phase 7.
    assert not any(name.startswith("compliance_") and t.mutates for name, t in by_name.items())
