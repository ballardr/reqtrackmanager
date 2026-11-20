"""
Module: tests.test_structure_tools

Unit tests for the project-structure tools (components, categories, stages): each is a thin call to the existing
endpoint, so what is pinned here is the request (method, path, body, query), the local validation that happens
before one, and that the backend's refusal passes through. A fake `_call_backend` stands in for the backend. The
write tools exist only in write mode, so they are called in a subprocess that starts the server with
`MCP_WRITES_ENABLED` set.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")

SERVER_DIR = Path(__file__).resolve().parent.parent
PROJECT = "11111111-1111-1111-1111-111111111111"
COMPONENT = "22222222-2222-2222-2222-222222222222"
OTHER_COMPONENT = "55555555-5555-5555-5555-555555555555"
CATEGORY = "33333333-3333-3333-3333-333333333333"

_SCRIPT = textwrap.dedent(
    """
    import asyncio, json, sys
    import httpx
    import server

    calls = []

    async def fake(method, path, **kwargs):
        calls.append({"method": method, "path": path, "json": kwargs.get("json")})
        if kwargs.get("refuse"):
            raise AssertionError("unreachable")
        return httpx.Response(200, json={"ok": True})

    server._call_backend = fake

    async def main():
        names = ["create_component", "update_component", "move_component", "delete_component",
                 "create_category", "update_category", "move_category", "delete_category"]
        t = {n: (await server.mcp.get_tool(n)).fn for n in names}
        P, C, K = %(p)r, %(c)r, %(k)r
        await t["create_component"](P, name=" Software ", prefix=" sw ")
        await t["update_component"](P, component_id=C, name="Software", prefix="sw2")
        await t["move_component"](P, component_id=C, direction="down")
        out = await t["delete_component"](P, component_id=C)
        await t["create_category"](P, component_id=C, name="Performance", prefix="perf")
        await t["update_category"](P, category_id=K, name="Perf", prefix="prf")
        await t["move_category"](P, category_id=K, direction="up")
        deleted = await t["delete_category"](P, category_id=K)
        errors = []
        for label, call in (
            ("direction", t["move_component"](P, component_id=C, direction="sideways")),
            ("blank name", t["create_component"](P, name="  ", prefix="SW")),
            ("blank prefix", t["create_category"](P, component_id=C, name="x", prefix="")),
            ("bad id", t["delete_category"](P, category_id="nope")),
        ):
            try:
                await call
            except ValueError as exc:
                errors.append([label, str(exc)])
        print(json.dumps({"calls": calls, "deleted": [out, deleted], "errors": errors}))

    asyncio.run(main())
    """
) % {"p": PROJECT, "c": COMPONENT, "k": CATEGORY}


def test_the_write_tools_send_the_endpoints_requests_and_validate_first():
    done = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(SERVER_DIR)!r})\n{_SCRIPT}"],
        capture_output=True, text=True, env={**os.environ, "MCP_WRITES_ENABLED": "true"}, check=False, cwd=SERVER_DIR,
    )
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    base = f"/api/v1/projects/{PROJECT}"
    sent = [(c["method"], c["path"], c["json"]) for c in result["calls"]]
    assert sent == [
        ("POST", f"{base}/components", {"name": "Software", "prefix": "SW"}),
        ("PATCH", f"{base}/components/{COMPONENT}", {"name": "Software", "prefix": "SW2"}),
        ("POST", f"{base}/components/{COMPONENT}/move", {"direction": "down"}),
        ("DELETE", f"{base}/components/{COMPONENT}", None),
        ("POST", f"{base}/categories", {"component_id": COMPONENT, "name": "Performance", "prefix": "PERF"}),
        ("PATCH", f"{base}/categories/{CATEGORY}", {"name": "Perf", "prefix": "PRF"}),
        ("POST", f"{base}/categories/{CATEGORY}/move", {"direction": "up"}),
        # No `reassign_to` and no query string: the server refuses unless the category is empty.
        ("DELETE", f"{base}/categories/{CATEGORY}", None),
    ]
    assert result["deleted"] == [
        {"deleted": True, "component_id": COMPONENT}, {"deleted": True, "category_id": CATEGORY},
    ]
    assert [label for label, _ in result["errors"]] == ["direction", "blank name", "blank prefix", "bad id"]


def test_delete_category_does_not_offer_a_reassignment_target():
    done = subprocess.run(
        [
            sys.executable, "-I", "-c",
            f"import sys, asyncio; sys.path.insert(0, {str(SERVER_DIR)!r})\nimport server\n"
            "tool = asyncio.run(server.mcp.get_tool('delete_category'))\n"
            "print(sorted(tool.parameters['properties']))",
        ],
        capture_output=True, text=True, env={**os.environ, "MCP_WRITES_ENABLED": "true"}, check=False, cwd=SERVER_DIR,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "['category_id', 'project_id']"


def test_the_structure_write_tools_are_absent_without_write_mode():
    script = (
        f"import sys, asyncio, json; sys.path.insert(0, {str(SERVER_DIR)!r})\nimport server\n"
        "print(json.dumps([t.name for t in asyncio.run(server.mcp.list_tools())]))"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True, text=True, env={**os.environ, "MCP_WRITES_ENABLED": "false"}, check=False, cwd=SERVER_DIR,
    )
    assert done.returncode == 0, done.stderr
    names = set(json.loads(done.stdout.strip().splitlines()[-1]))
    assert {"list_components", "list_categories", "list_stages"} <= names
    assert not names & {
        "create_component", "update_component", "move_component", "delete_component",
        "create_category", "update_category", "move_category", "delete_category",
    }


def test_the_read_tools_name_the_endpoints_and_filter_categories_by_component():
    import httpx

    import server

    calls: list[tuple[str, str]] = []
    categories = [
        {"id": CATEGORY, "component_id": COMPONENT, "name": "A", "prefix": "A", "sort_order": 0},
        {"id": "44444444-4444-4444-4444-444444444444", "component_id": OTHER_COMPONENT, "name": "B", "prefix": "B", "sort_order": 0},
    ]

    async def fake(method, path, **kwargs):
        calls.append((method, path))
        return httpx.Response(200, json=categories if path.endswith("/categories") else [])

    async def run() -> list[dict]:
        original = server._call_backend
        server._call_backend = fake
        try:
            await (await server.mcp.get_tool("list_components")).fn(PROJECT)
            await (await server.mcp.get_tool("list_stages")).fn(PROJECT)
            everything = await (await server.mcp.get_tool("list_categories")).fn(PROJECT)
            assert len(everything) == 2
            with pytest.raises(ValueError):
                await (await server.mcp.get_tool("list_categories")).fn(PROJECT, component_id="nope")
            return await (await server.mcp.get_tool("list_categories")).fn(PROJECT, component_id=COMPONENT.upper())
        finally:
            server._call_backend = original

    only = asyncio.run(run())
    base = f"/api/v1/projects/{PROJECT}"
    assert calls[:2] == [("GET", f"{base}/components"), ("GET", f"{base}/stages")]
    assert [row["id"] for row in only] == [CATEGORY]
