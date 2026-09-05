"""
Module: tests.test_module_tools

Unit tests for the module-contributed MCP tools mechanism (compliance-
module-plan.md Phase 4, see server.py's own "Module-contributed tools"
section) — parsing the backend's manifest, building/registering a
`_DeclarativeModuleTool`, path/query/body param mapping (including that a
path-location value is URL-encoded, not trusted as a bare path segment),
the `MCP_WRITES_ENABLED` gate on mutating tools, and the add/remove diffing
`_apply_module_tool_manifest` performs across refreshes.

Unlike `test_server.py`, these tests need no running backend at all: the
backend's `GET /api/v1/system/modules/mcp-tools` response is faked directly
(`server.httpx.AsyncClient` is patched), and `server._call_backend` is
patched directly wherever a proxied call's own request shape is being
checked. This mirrors the backend's own `test_module_mcp_tools.py`, which
similarly proves the manifest-building side of this same mechanism without
needing a live `mcp-server` process.

Every test resets `server`'s module-level registration state
(`_registered_module_tools`, `_module_tools_last_refresh`) in teardown, and
explicitly deregisters any tool it added — this module's tool registry is
process-global, shared with `test_server.py` if both run in the same
`pytest` invocation, so leaking a registered fixture tool would leak into
that file's own `test_tools_are_discoverable` (which asserts an *exact*
tool-name set)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import server as srv


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"status {self.status_code}")  # noqa: TRY002

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400


def _manifest_entry(**overrides) -> dict:
    entry = {
        "name": "fixture_list_things",
        "description": "Lists fixture things.",
        "method": "GET",
        "path_template": "/api/v1/orgs/{organization_id}/modules/fixture/things",
        "mutates": False,
        "params": [
            {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "org id"},
        ],
    }
    entry.update(overrides)
    return entry


@pytest.fixture(autouse=True)
def _reset_module_tool_state():
    """Ensures every test starts from (and leaves behind) zero registered
    module tools and a forced-stale refresh clock, regardless of what a
    prior test in the same session registered."""
    for name in list(srv._registered_module_tools):
        srv.mcp.local_provider.remove_tool(name)
    srv._registered_module_tools.clear()
    srv._module_tools_last_refresh = 0.0
    yield
    for name in list(srv._registered_module_tools):
        srv.mcp.local_provider.remove_tool(name)
    srv._registered_module_tools.clear()
    srv._module_tools_last_refresh = 0.0


def _patched_manifest_response(entries):
    return patch.object(
        srv.httpx, "AsyncClient",
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=AsyncMock(get=AsyncMock(return_value=_FakeResponse(200, entries)))),
            __aexit__=AsyncMock(return_value=False),
        ),
    )


def test_parse_module_tool_manifest_skips_malformed_entry():
    entries = [_manifest_entry(), {"name": "broken"}]  # missing required keys
    specs = srv._parse_module_tool_manifest(entries)
    assert [s.name for s in specs] == ["fixture_list_things"]


def test_parse_module_tool_manifest_maps_param_fields():
    specs = srv._parse_module_tool_manifest([_manifest_entry()])
    (spec,) = specs
    assert spec.mutates is False
    (param,) = spec.params
    assert param.name == "organization_id"
    assert param.location == "path"
    assert param.required is True


@pytest.mark.asyncio
async def test_apply_manifest_registers_a_get_tool():
    specs = srv._parse_module_tool_manifest([_manifest_entry()])
    srv._apply_module_tool_manifest(specs)
    assert "fixture_list_things" in srv._registered_module_tools
    tools = await srv.mcp.list_tools()
    assert any(t.name == "fixture_list_things" for t in tools)


@pytest.mark.asyncio
async def test_apply_manifest_excludes_mutating_tool_when_writes_disabled(monkeypatch):
    monkeypatch.setattr(srv, "MCP_WRITES_ENABLED", False)
    specs = srv._parse_module_tool_manifest([_manifest_entry(name="fixture_create_thing", method="POST", mutates=True)])
    srv._apply_module_tool_manifest(specs)
    assert "fixture_create_thing" not in srv._registered_module_tools
    tools = await srv.mcp.list_tools()
    assert not any(t.name == "fixture_create_thing" for t in tools)


@pytest.mark.asyncio
async def test_apply_manifest_includes_mutating_tool_when_writes_enabled(monkeypatch):
    monkeypatch.setattr(srv, "MCP_WRITES_ENABLED", True)
    specs = srv._parse_module_tool_manifest([_manifest_entry(name="fixture_create_thing", method="POST", mutates=True)])
    srv._apply_module_tool_manifest(specs)
    assert "fixture_create_thing" in srv._registered_module_tools


def test_apply_manifest_removes_a_tool_no_longer_in_the_manifest():
    srv._apply_module_tool_manifest(srv._parse_module_tool_manifest([_manifest_entry()]))
    assert "fixture_list_things" in srv._registered_module_tools
    srv._apply_module_tool_manifest([])
    assert "fixture_list_things" not in srv._registered_module_tools


@pytest.mark.asyncio
async def test_declarative_tool_url_encodes_path_params_and_maps_query_and_body(monkeypatch):
    monkeypatch.setattr(srv, "MCP_WRITES_ENABLED", True)  # this tool mutates
    entry = _manifest_entry(
        name="fixture_create_thing", method="POST", mutates=True,
        params=[
            {"name": "organization_id", "type": "uuid", "required": True, "in": "path"},
            {"name": "search", "type": "string", "required": False, "in": "query"},
            {"name": "name", "type": "string", "required": True, "in": "body"},
        ],
        path_template="/api/v1/orgs/{organization_id}/modules/fixture/things",
    )
    srv._apply_module_tool_manifest(srv._parse_module_tool_manifest([entry]))

    with patch.object(srv, "_call_backend", new=AsyncMock(return_value=_FakeResponse(201, {"id": "abc"}))) as mock_call:
        tool = srv._registered_module_tools
        assert "fixture_create_thing" in tool
        registered_tool = await srv.mcp.get_tool("fixture_create_thing")
        await registered_tool.run({"organization_id": "org/../evil", "search": "q", "name": "widget"})

    args, kwargs = mock_call.call_args
    assert args[0] == "POST"
    # Path-segment injection characters are URL-encoded, not passed through raw.
    assert args[1] == "/api/v1/orgs/org%2F..%2Fevil/modules/fixture/things"
    assert kwargs["params"] == {"search": "q"}
    assert kwargs["json"] == {"name": "widget"}


@pytest.mark.asyncio
async def test_declarative_tool_raises_clean_error_on_missing_required_param():
    srv._apply_module_tool_manifest(srv._parse_module_tool_manifest([_manifest_entry()]))
    registered_tool = await srv.mcp.get_tool("fixture_list_things")
    with pytest.raises(ValueError, match="Missing required argument 'organization_id'"):
        await registered_tool.run({})


def test_apply_manifest_does_not_reregister_an_unchanged_tool():
    specs = srv._parse_module_tool_manifest([_manifest_entry()])
    srv._apply_module_tool_manifest(specs)
    registered_before = srv.mcp.local_provider._get_component("tool:fixture_list_things")
    srv._apply_module_tool_manifest(specs)  # identical manifest again
    registered_after = srv.mcp.local_provider._get_component("tool:fixture_list_things")
    assert registered_before is registered_after  # never replaced, so never even a duplicate-warning log


@pytest.mark.asyncio
async def test_maybe_refresh_module_tools_skips_when_no_auth_header(monkeypatch):
    monkeypatch.setattr(srv, "_forward_auth_header", lambda: (_ for _ in ()).throw(srv.AuthenticationRequiredError("no token")))
    await srv._maybe_refresh_module_tools()
    assert srv._registered_module_tools == {}
    assert srv._module_tools_last_refresh == 0.0


@pytest.mark.asyncio
async def test_maybe_refresh_module_tools_registers_tools_from_a_real_fetch(monkeypatch):
    monkeypatch.setattr(srv, "_forward_auth_header", lambda: {"Authorization": "Bearer faketoken"})
    with _patched_manifest_response([_manifest_entry()]):
        await srv._maybe_refresh_module_tools()
    assert "fixture_list_things" in srv._registered_module_tools
    assert srv._module_tools_last_refresh > 0.0


@pytest.mark.asyncio
async def test_maybe_refresh_module_tools_does_not_refetch_within_the_refresh_window(monkeypatch):
    monkeypatch.setattr(srv, "_forward_auth_header", lambda: {"Authorization": "Bearer faketoken"})
    with _patched_manifest_response([_manifest_entry()]) as patched:
        await srv._maybe_refresh_module_tools()
        await srv._maybe_refresh_module_tools()
        assert patched.call_count == 1
