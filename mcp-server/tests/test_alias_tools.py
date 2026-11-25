"""
Module: tests.test_alias_tools

Unit tests for the requirement alias tools and the `additional_places` argument of `create_requirement` and
`update_requirement`: each is a thin call to the existing endpoint, so what is pinned here is the request (method,
path, body), the local validation before one, and that update leaves the further places alone when they are omitted.
A fake `_call_backend` stands in for the backend. The write tools exist only in write mode, so they are called in a
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
REQUIREMENT = "22222222-2222-2222-2222-222222222222"
ALIAS = "33333333-3333-3333-3333-333333333333"
COMPONENT = "44444444-4444-4444-4444-444444444444"
CATEGORY = "55555555-5555-5555-5555-555555555555"
LINK_TYPE = "66666666-6666-6666-6666-666666666666"

_CURRENT = {
    "name": "Bus", "reasoning": "", "clarification": "", "description": "", "component_id": COMPONENT,
    "category_id": CATEGORY, "owner": {"type": "user", "id": "77777777-7777-7777-7777-777777777777"},
    "target_stage_id": "88888888-8888-8888-8888-888888888888", "level": "requirement", "custom_fields": {},
    "review_date": None, "review_lead_days": None, "reviewer": None,
}

_SCRIPT = textwrap.dedent(
    """
    import asyncio, json, sys
    import httpx
    import server

    calls = []

    async def fake(method, path, **kwargs):
        calls.append({"method": method, "path": path, "json": kwargs.get("json")})
        return httpx.Response(200, json=%(current)r)

    server._call_backend = fake

    async def main():
        names = ["create_requirement", "update_requirement", "remove_requirement_alias",
                 "promote_requirement_alias", "make_requirement_alias_independent"]
        t = {n: (await server.mcp.get_tool(n)).fn for n in names}
        P, R, A, C, K, L = %(p)r, %(r)r, %(a)r, %(c)r, %(k)r, %(l)r
        place = {"component_id": C, "category_id": K}
        await t["create_requirement"](P, name="Bus", component_id=C, category_id=K, additional_places=[place])
        await t["update_requirement"](P, requirement_id=R, name="Bus 2")
        await t["update_requirement"](P, requirement_id=R, additional_places=[place])
        await t["update_requirement"](P, requirement_id=R, additional_places=[])
        await t["remove_requirement_alias"](P, requirement_id=R, alias_id=A)
        await t["promote_requirement_alias"](P, requirement_id=R, alias_id=A)
        await t["make_requirement_alias_independent"](P, requirement_id=R, alias_id=A)
        await t["make_requirement_alias_independent"](P, requirement_id=R, alias_id=A, related_link_type_id=L)
        errors = []
        for label, call in (
            ("bad place", t["create_requirement"](
                P, name="x", component_id=C, category_id=K,
                additional_places=[{"component_id": "no", "category_id": K}])),
            ("bad alias", t["remove_requirement_alias"](P, requirement_id=R, alias_id="nope")),
            ("bad link type", t["make_requirement_alias_independent"](P, requirement_id=R, alias_id=A, related_link_type_id="nope")),
        ):
            try:
                await call
            except ValueError as exc:
                errors.append(label)
        print(json.dumps({"calls": calls, "errors": errors}))

    asyncio.run(main())
    """
) % {"current": _CURRENT, "p": PROJECT, "r": REQUIREMENT, "a": ALIAS, "c": COMPONENT, "k": CATEGORY, "l": LINK_TYPE}


def test_the_alias_tools_send_the_endpoints_requests_and_validate_first():
    done = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(SERVER_DIR)!r})\n{_SCRIPT}"],
        capture_output=True, text=True, env={**os.environ, "MCP_WRITES_ENABLED": "true"}, check=False, cwd=SERVER_DIR,
    )
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    base = f"/api/v1/projects/{PROJECT}/requirements"
    place = {"component_id": COMPONENT, "category_id": CATEGORY}
    calls = result["calls"]
    assert (calls[0]["method"], calls[0]["path"], calls[0]["json"]["additional_places"]) == ("POST", base, [place])
    # An update that does not name the places leaves them alone (a stale copy would retire places added since).
    update_calls = [c for c in calls if c["method"] == "PUT"]
    assert "additional_places" not in update_calls[0]["json"]
    assert update_calls[1]["json"]["additional_places"] == [place]
    assert update_calls[2]["json"]["additional_places"] == []
    rest = [(c["method"], c["path"], c["json"]) for c in calls if c["method"] in ("DELETE", "POST") and c is not calls[0]]
    assert rest == [
        ("DELETE", f"{base}/{REQUIREMENT}/aliases/{ALIAS}", None),
        ("POST", f"{base}/{REQUIREMENT}/aliases/{ALIAS}/promote", None),
        ("POST", f"{base}/{REQUIREMENT}/aliases/{ALIAS}/make-independent", {"related_link_type_id": None}),
        ("POST", f"{base}/{REQUIREMENT}/aliases/{ALIAS}/make-independent", {"related_link_type_id": LINK_TYPE}),
    ]
    assert result["errors"] == ["bad place", "bad alias", "bad link type"]
