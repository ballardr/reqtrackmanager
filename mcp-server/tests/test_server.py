"""
Module: tests.test_server

Integration tests for the MCP server — run against a real, already-running
backend (the same convention as backend/tests/, but this server has no
database of its own to reset, so there's no schema-fixture equivalent
here). Covers the one thing that actually matters for this module: that
authentication is genuinely pass-through — no auth header fails cleanly, a
bad token fails cleanly with the backend's own rejection surfaced, and a
valid token succeeds and returns real data.

Run via (from tests/container):
    docker compose exec mcp-server python -m pytest -q

Requires REQTRACK_ADMIN_EMAIL/REQTRACK_ADMIN_PASSWORD (defaults match the
bootstrap admin every stack creates on first boot) and MCP_SERVER_URL
(default http://localhost:8100/mcp, correct when run from inside the
mcp-server container itself).
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8100/mcp")
REQTRACK_API_URL = os.environ.get("REQTRACK_API_URL", "http://backend:8000")
ADMIN_EMAIL = os.environ.get("REQTRACK_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("REQTRACK_ADMIN_PASSWORD", "ChangeMe123!")


@pytest.fixture(scope="session")
def admin_token() -> str:
    """Logs in as the bootstrap admin once per test session."""
    response = httpx.post(
        f"{REQTRACK_API_URL}/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _client(token: str | None) -> Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return Client(StreamableHttpTransport(url=MCP_SERVER_URL, headers=headers))


def test_health_check_is_reachable_without_auth():
    """The plain liveness check must never require a token — an
    orchestrator's health probe has no ReqTrackManager account."""
    response = httpx.get(MCP_SERVER_URL.replace("/mcp", "/health"), timeout=10)
    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.asyncio
async def test_tools_are_discoverable():
    async with _client(None) as client:
        tools = {t.name for t in await client.list_tools()}
    assert tools == {
        "list_organizations", "list_projects", "get_project",
        "list_requirements", "get_requirement", "get_requirement_history",
        "list_change_requests", "get_change_request", "list_change_request_votes",
        "list_change_request_tasks", "list_change_request_comments",
        "list_requirement_comments", "list_notifications",
        "list_my_reviews_due", "list_project_reviews_due",
    }


@pytest.mark.asyncio
async def test_tool_call_without_auth_header_fails_clearly():
    async with _client(None) as client:
        with pytest.raises(ToolError, match="No Authorization header"):
            await client.call_tool("list_organizations", {})


@pytest.mark.asyncio
async def test_tool_call_with_invalid_token_surfaces_backend_rejection():
    async with _client("not-a-real-token") as client:
        with pytest.raises(ToolError, match="rejected the presented access token"):
            await client.call_tool("list_organizations", {})


@pytest.mark.asyncio
async def test_tool_call_with_malformed_uuid_is_rejected_before_calling_the_backend(admin_token):
    async with _client(admin_token) as client:
        with pytest.raises(ToolError, match="must be a valid UUID"):
            await client.call_tool("get_project", {"project_id": "not-a-uuid"})


@pytest.mark.asyncio
async def test_valid_token_lists_real_organizations(admin_token):
    async with _client(admin_token) as client:
        result = await client.call_tool("list_organizations", {})
    orgs = result.data
    assert isinstance(orgs, list)
    assert all("id" in o and "name" in o for o in orgs)


@pytest.mark.asyncio
async def test_full_tool_chain_returns_consistent_real_data(admin_token):
    """Exercises list_projects -> list_requirements -> get_requirement ->
    get_requirement_history end to end against whatever real data the
    backend currently has (this project's seed scripts, if run), confirming
    the whole chain of forwarded calls stays internally consistent rather
    than just individually returning *something*."""
    async with _client(admin_token) as client:
        projects = (await client.call_tool("list_projects", {})).data
        if not projects:
            pytest.skip("No projects visible to the admin account — seed data (E2E or demo) hasn't been loaded.")
        project = projects[0]

        requirements = (await client.call_tool("list_requirements", {"project_id": project["id"]})).data
        if not requirements:
            pytest.skip(f"Project {project['name']!r} has no requirements to fetch.")
        requirement = requirements[0]

        detail = await client.call_tool(
            "get_requirement", {"project_id": project["id"], "requirement_id": requirement["id"]}
        )
        assert detail.data["unique_code"] == requirement["unique_code"]

        history = await client.call_tool(
            "get_requirement_history", {"project_id": project["id"], "requirement_id": requirement["id"]}
        )
        assert len(history.data) >= 1
        assert history.data[0]["version_number"] == 1


@pytest.mark.asyncio
async def test_change_request_tool_chain_returns_consistent_real_data(admin_token):
    """Exercises list_change_requests -> get_change_request -> votes/tasks/comments
    end to end against whatever real change requests the backend currently has,
    skipping gracefully (rather than failing) if none exist in any visible project."""
    async with _client(admin_token) as client:
        projects = (await client.call_tool("list_projects", {})).data
        if not projects:
            pytest.skip("No projects visible to the admin account — seed data hasn't been loaded.")

        project = None
        change_request = None
        for candidate in projects:
            crs = (await client.call_tool("list_change_requests", {"project_id": candidate["id"]})).data
            if crs:
                project, change_request = candidate, crs[0]
                break
        if change_request is None:
            pytest.skip("No change requests found in any visible project — seed data hasn't been loaded.")

        detail = await client.call_tool(
            "get_change_request", {"project_id": project["id"], "change_request_id": change_request["id"]}
        )
        assert detail.data["id"] == change_request["id"]

        votes = await client.call_tool(
            "list_change_request_votes", {"project_id": project["id"], "change_request_id": change_request["id"]}
        )
        assert "votes" in votes.data and "approve_count" in votes.data

        tasks = await client.call_tool(
            "list_change_request_tasks", {"project_id": project["id"], "change_request_id": change_request["id"]}
        )
        assert isinstance(tasks.data, list)

        comments = await client.call_tool(
            "list_change_request_comments", {"project_id": project["id"], "change_request_id": change_request["id"]}
        )
        assert isinstance(comments.data, list)


@pytest.mark.asyncio
async def test_requirement_comments_tool_returns_a_list(admin_token):
    async with _client(admin_token) as client:
        projects = (await client.call_tool("list_projects", {})).data
        if not projects:
            pytest.skip("No projects visible to the admin account — seed data hasn't been loaded.")
        project = projects[0]

        requirements = (await client.call_tool("list_requirements", {"project_id": project["id"]})).data
        if not requirements:
            pytest.skip(f"Project {project['name']!r} has no requirements to fetch comments for.")
        requirement = requirements[0]

        comments = await client.call_tool(
            "list_requirement_comments", {"project_id": project["id"], "requirement_id": requirement["id"]}
        )
        assert isinstance(comments.data, list)


@pytest.mark.asyncio
async def test_notifications_and_reviews_due_tools_return_lists(admin_token):
    async with _client(admin_token) as client:
        notifications = await client.call_tool("list_notifications", {})
        assert isinstance(notifications.data, list)

        my_reviews = await client.call_tool("list_my_reviews_due", {})
        assert isinstance(my_reviews.data, list)

        projects = (await client.call_tool("list_projects", {})).data
        if not projects:
            pytest.skip("No projects visible to the admin account — seed data hasn't been loaded.")
        project_reviews = await client.call_tool("list_project_reviews_due", {"project_id": projects[0]["id"]})
        assert isinstance(project_reviews.data, list)


LOGIN_PAGE_URL = MCP_SERVER_URL.replace("/mcp", "/login")


def test_login_page_renders_form():
    """`GET /login` must work with no Authorization header at all — it's
    the thing a user visits precisely because they don't have a token yet."""
    response = httpx.get(LOGIN_PAGE_URL, timeout=10)
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert "no-store" in response.headers.get("cache-control", "")


def test_login_with_invalid_credentials_shows_generic_error_without_echoing_input():
    response = httpx.post(LOGIN_PAGE_URL, data={"email": "nobody@example.com", "password": "wrong"}, timeout=10)
    assert response.status_code == 200
    assert "Invalid email or password" in response.text
    assert "nobody@example.com" not in response.text


def test_login_with_valid_credentials_returns_a_usable_token():
    response = httpx.post(LOGIN_PAGE_URL, data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=10)
    assert response.status_code == 200
    assert "Signed in" in response.text
    assert "/mcp" in response.text
    assert "no-store" in response.headers.get("cache-control", "")


def test_login_2fa_with_bad_challenge_token_shows_generic_error():
    """Exercises the error path of the second-step route without needing a
    real 2FA-enabled seeded account (none exists in this project's seed
    data) — a malformed/garbage challenge token is rejected by the backend
    the same way an expired one would be, which is exactly what this route
    needs to surface cleanly."""
    response = httpx.post(
        MCP_SERVER_URL.replace("/mcp", "/login/2fa"),
        data={"challenge_token": "not-a-real-challenge-token", "code": "000000"},
        timeout=10,
    )
    assert response.status_code == 200
    assert "Invalid or expired code" in response.text


def _create_test_org(admin_token: str, *, sso_enabled: bool) -> str:
    """Creates a throwaway org (via the real backend API, server-admin
    only) with a unique slug, to test /login's SSO-branch rendering
    without touching any seeded org. Returns the slug.

    The full SSO *login* round trip (Keycloak redirect, callback,
    provisioning) is proven end to end by
    tests/playwright/tests/e2e-workflows/sso.spec.ts, which has a real
    identity provider to drive a browser through — not reproducible here
    with httpx alone. What's testable at this level, and what these tests
    cover, is /login's org-lookup and conditional rendering.

    A server admin has no role of its own in a brand-new org (I-M-05: the
    server admin role doesn't grant org-internal access) — the one
    documented carve-out is creating that org's *initial* user directly
    with a role, which is what's used here to get a caller who can then
    configure SSO, mirroring how a real org would actually be set up.
    """
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    slug = f"mcp-test-{uuid.uuid4().hex[:10]}"
    org = httpx.post(f"{REQTRACK_API_URL}/api/v1/orgs", json={"name": slug}, headers=admin_headers, timeout=10).json()

    owner_email = f"{slug}@example.com"
    owner_password = "TestOrgOwner123!"
    create_owner = httpx.post(
        f"{REQTRACK_API_URL}/api/v1/orgs/{org['id']}/users",
        json={"email": owner_email, "display_name": "Test Org Owner", "password": owner_password, "role": "org_admin"},
        headers=admin_headers, timeout=10,
    )
    create_owner.raise_for_status()

    login = httpx.post(
        f"{REQTRACK_API_URL}/api/v1/auth/login", json={"email": owner_email, "password": owner_password}, timeout=10,
    )
    login.raise_for_status()
    owner_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    sso_resp = httpx.put(
        f"{REQTRACK_API_URL}/api/v1/orgs/{org['id']}/sso-config",
        json={
            "slug": slug, "sso_enabled": sso_enabled, "sso_only": False,
            "oidc_issuer_url": "https://example-idp.invalid/realm" if sso_enabled else None,
            "oidc_client_id": "test-client" if sso_enabled else None,
        },
        headers=owner_headers, timeout=10,
    )
    sso_resp.raise_for_status()
    return slug


def test_login_page_without_org_param_has_no_sso_button():
    response = httpx.get(LOGIN_PAGE_URL, timeout=10)
    assert "sso-btn" not in response.text


def test_login_page_with_unknown_org_shows_error_and_no_sso_button():
    response = httpx.get(LOGIN_PAGE_URL, params={"org": "no-such-org-slug"}, timeout=10)
    assert response.status_code == 200
    assert "No organisation found" in response.text
    assert "sso-btn" not in response.text


def test_login_page_with_non_sso_org_shows_error_and_no_sso_button(admin_token):
    slug = _create_test_org(admin_token, sso_enabled=False)
    response = httpx.get(LOGIN_PAGE_URL, params={"org": slug}, timeout=10)
    assert response.status_code == 200
    assert "does not have SSO enabled" in response.text
    assert "sso-btn" not in response.text


def test_login_page_with_sso_enabled_org_shows_sso_button_and_native_form(admin_token):
    slug = _create_test_org(admin_token, sso_enabled=True)
    response = httpx.get(LOGIN_PAGE_URL, params={"org": slug}, timeout=10)
    assert response.status_code == 200
    assert 'id="sso-btn"' in response.text
    assert f'data-org-slug="{slug}"' in response.text
    assert 'name="password"' in response.text  # sso_only=False: native form still offered


def test_login_oidc_complete_page_renders_without_a_token():
    """The landing page itself is entirely client-rendered (see
    _OIDC_COMPLETE_BODY) — without a token in the URL fragment (which a
    plain GET never has, since fragments never reach the server), it must
    still return a normal page rather than erroring, and never require
    auth to view."""
    response = httpx.get(LOGIN_PAGE_URL.replace("/login", "/login/oidc/complete"), timeout=10)
    assert response.status_code == 200
    assert "Completing sign-in" in response.text
    assert "no-store" in response.headers.get("cache-control", "")
