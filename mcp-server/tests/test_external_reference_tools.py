"""
Module: tests.test_external_reference_tools

Unit tests for the external reference tools: each is a thin call to the backend's endpoint, so what is pinned here is
the request (method, path, body, query) and that the backend's refusal passes through. A fake `_call_backend`
stands in for the backend, so none is needed. The write tools exist only in write mode, so they are called in a
subprocess that starts the server with `MCP_WRITES_ENABLED` set.
"""

from __future__ import annotations

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
RECORD = "22222222-2222-2222-2222-222222222222"
SYSTEM = "33333333-3333-3333-3333-333333333333"
REFERENCE = "44444444-4444-4444-4444-444444444444"

_SCRIPT = textwrap.dedent(
    """
    import asyncio, json, sys
    import httpx
    import server

    calls = []

    async def fake(method, path, **kwargs):
        calls.append({"method": method, "path": path, "json": kwargs.get("json"), "params": kwargs.get("params")})
        return httpx.Response(200, json={"references": []})

    server._call_backend = fake

    async def main():
        tools = {name: (await server.mcp.get_tool(name)).fn for name in sys.argv[1:]}
        P, R, S, X = %(p)r, %(r)r, %(s)r, %(x)r
        await tools["add_artefact_external_reference"](P, artefact_type="requirement", artefact_id=R, system_id=S, key="PROJ-1", role="origin")
        await tools["update_artefact_external_reference"](P, artefact_type="requirement", artefact_id=R, reference_id=X, clear_url=True, note="n")
        await tools["remove_artefact_external_reference"](P, artefact_type="requirement", artefact_id=R, reference_id=X)
        try:
            await tools["update_artefact_external_reference"](P, artefact_type="requirement", artefact_id=R, reference_id=X)
        except ValueError as exc:
            calls.append({"error": str(exc)})
        print(json.dumps(calls))

    asyncio.run(main())
    """
) % {"p": PROJECT, "r": RECORD, "s": SYSTEM, "x": REFERENCE}


def test_the_write_tools_send_the_endpoints_requests():
    names = ["add_artefact_external_reference", "update_artefact_external_reference", "remove_artefact_external_reference"]
    done = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(SERVER_DIR)!r})\n{_SCRIPT}", *names],
        capture_output=True, text=True, env={**os.environ, "MCP_WRITES_ENABLED": "true"}, check=False, cwd=SERVER_DIR,
    )
    assert done.returncode == 0, done.stderr
    add, update, remove, refused = json.loads(done.stdout.strip().splitlines()[-1])
    base = f"/api/v1/projects/{PROJECT}/artefacts/requirement/{RECORD}/external-references"
    assert (add["method"], add["path"]) == ("POST", base)
    assert add["json"] == {"system_id": SYSTEM, "key": "PROJ-1", "note": "", "role": "origin"}
    assert (update["method"], update["path"], update["json"]) == ("PATCH", f"{base}/{REFERENCE}", {"url": None, "note": "n"})
    assert (remove["method"], remove["path"]) == ("DELETE", f"{base}/{REFERENCE}")
    assert "at least one field" in refused["error"]


def test_the_read_tools_name_the_endpoints_and_validate_their_input():
    import asyncio

    import httpx

    import server

    calls: list[dict] = []

    async def fake(method, path, **kwargs):
        calls.append({"method": method, "path": path, "params": kwargs.get("params")})
        return httpx.Response(200, json={"references": [], "records": []})

    async def run() -> None:
        original = server._call_backend
        server._call_backend = fake
        try:
            get = (await server.mcp.get_tool("get_artefact_external_references")).fn
            find = (await server.mcp.get_tool("find_artefacts_by_external_reference")).fn
            await get(PROJECT, artefact_type="requirement", artefact_id=RECORD)
            await find(PROJECT, key="PROJ-1", system="Jira", artefact_type="decision")
            with pytest.raises(ValueError, match="key"):
                await find(PROJECT, key="  ")
            with pytest.raises(ValueError):
                await get(PROJECT, artefact_type="requirement", artefact_id="not-a-uuid")
        finally:
            server._call_backend = original

    asyncio.run(run())
    assert calls[0] == {
        "method": "GET", "path": f"/api/v1/projects/{PROJECT}/artefacts/requirement/{RECORD}/external-references", "params": None,
    }
    assert calls[1]["path"] == f"/api/v1/projects/{PROJECT}/records/by-external-reference"
    assert calls[1]["params"] == {"key": "PROJ-1", "system": "Jira", "artefact_type": "decision"}
    assert len(calls) == 2


def test_list_requirements_passes_the_reference_filters():
    import asyncio

    import httpx

    import server

    seen: list[dict] = []

    async def fake(method, path, **kwargs):
        seen.append(kwargs.get("params") or {})
        return httpx.Response(200, json=[])

    async def run() -> None:
        original = server._call_backend
        server._call_backend = fake
        try:
            await (await server.mcp.get_tool("list_requirements")).fn(PROJECT, external_systems=["Jira"], external_key="DOC")
        finally:
            server._call_backend = original

    asyncio.run(run())
    assert seen[0]["external_system"] == ["Jira"] and seen[0]["external_key"] == "DOC"
