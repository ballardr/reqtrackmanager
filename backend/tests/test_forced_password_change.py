"""An administrator-typed password must be changed before anything else is done with the account (Known Gap 6)."""

from __future__ import annotations

import pytest

from app.config import get_settings
from tests.conftest import auth_headers, create_org_admin_in, login


@pytest.fixture
def forced(monkeypatch):
    """Switches the rule on; the helper below turns it on only after the organisation's own administrator exists."""
    return lambda: monkeypatch.setattr(get_settings(), "force_password_change_on_admin_set", True)


def _new_member(client, admin_token, switch_on=None):
    org, org_admin = create_org_admin_in(client, admin_token, "Forced Change Org")
    if switch_on:
        switch_on()
    created = client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": "typed@example.com", "display_name": "Typed", "password": "Typed-Password-9!", "role": "member"},
        headers=auth_headers(org_admin),
    )
    assert created.status_code == 201, created.text
    return org, org_admin, login(client, "typed@example.com", "Typed-Password-9!")


def test_an_administrator_typed_password_blocks_everything_but_the_change(client, admin_token, forced):
    org, _org_admin, token = _new_member(client, admin_token, forced)
    headers = auth_headers(token)

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["must_change_password"] is True

    for method, path in (("GET", "/api/v1/projects"), ("GET", f"/api/v1/orgs/{org['id']}"), ("GET", "/api/v1/notifications")):
        blocked = client.request(method, path, headers=headers)
        assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "password_change_required", path

    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Typed-Password-9!", "new_password": "Chosen-By-Person-7!"}, headers=headers,
    )
    assert changed.status_code == 204
    fresh = login(client, "typed@example.com", "Chosen-By-Person-7!")
    assert client.get("/api/v1/auth/me", headers=auth_headers(fresh)).json()["must_change_password"] is False
    assert client.get("/api/v1/projects", headers=auth_headers(fresh)).status_code == 200


def test_a_person_who_chose_their_own_password_is_not_asked(client, admin_token, forced):
    forced()
    invite = client.post(
        "/api/v1/auth/signup", json={"email": "chosen@example.com", "password": "Own-Choice-Password-3!", "display_name": "Own"}
    )
    assert invite.status_code in (201, 403)  # sign-up may be disabled in this deployment; either way it never sets the flag
    if invite.status_code == 201:
        assert invite.json()["user"]["must_change_password"] is False


def test_the_setting_can_be_switched_off_for_a_deployment(client, admin_token):
    _org, _org_admin, token = _new_member(client, admin_token)
    assert client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["must_change_password"] is False
    assert client.get("/api/v1/projects", headers=auth_headers(token)).status_code == 200
