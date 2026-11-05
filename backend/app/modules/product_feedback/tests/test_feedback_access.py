"""Tests for the access endpoints (`GET .../access`) the UI reads to offer only the controls the server accepts:
a member may submit unless the project restricted submission, a triager may always submit and triage, and the
inbox answers the same question for the organisation tier. Each test builds its own organisation."""

from __future__ import annotations

from app.modules.product_feedback.tests._helpers import (
    add_member,
    grant_org_role,
    grant_project_role,
    org_base,
    project_base,
    setup,
)
from tests.conftest import auth_headers


def _access(client, token, base):
    resp = client.get(base + "/access", headers=auth_headers(token))
    assert resp.status_code == 200
    return resp.json()


def test_a_member_can_submit_but_not_triage_until_the_project_restricts_submission(client, admin_token):
    org, project, admin = setup(client, admin_token, "Access Project Co")
    triager_id, triager = add_member(client, admin, org["id"], project["id"], "triager.access@example.com")
    grant_project_role(client, admin, project["id"], triager_id, "feedback_triager")
    _, member = add_member(client, admin, org["id"], project["id"], "member.access@example.com")
    base = project_base(project["id"])

    assert _access(client, member, base) == {"can_submit": True, "can_triage": False}
    assert _access(client, triager, base) == {"can_submit": True, "can_triage": True}

    client.put(base + "/settings", json={"submission_policy": "triagers"}, headers=auth_headers(admin))
    assert _access(client, member, base) == {"can_submit": False, "can_triage": False}
    assert _access(client, triager, base) == {"can_submit": True, "can_triage": True}


def test_the_inbox_access_follows_the_organisation_triager_role(client, admin_token):
    org, project, admin = setup(client, admin_token, "Access Inbox Co")
    triager_id, triager = add_member(client, admin, org["id"], project["id"], "triager.inbox.access@example.com")
    grant_org_role(client, admin, org["id"], triager_id, "org_feedback_triager")
    _, member = add_member(client, admin, org["id"], project["id"], "member.inbox.access@example.com")
    base = org_base(org["id"])

    assert _access(client, member, base) == {"can_submit": True, "can_triage": False}
    assert _access(client, triager, base) == {"can_submit": True, "can_triage": True}
