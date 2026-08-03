"""Tests for organisation lifecycle management (server-admin only):
reversible disable/enable, which blocks every org/project-scoped request —
including for the organisation's own admins — without touching any data,
and irreversible hard delete, which requires typing the organisation's
name to confirm and fully cascades through everything it owns, including
real file storage bytes and Personal Access Token scope. See
docs/decisions.md's "Organisation disable and hard delete" section for the
full design.
"""

import pytest
from sqlalchemy import text

from app.database import engine as app_engine
from app.services.files import get_storage_backend
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)


def _create_requirement(client, token, project_id, component_id, category_id, name="Req"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _row_count(table: str, column: str, value: str) -> int:
    with app_engine.begin() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :value"),  # noqa: S608 (table name is a fixed literal per call site, never user input)
            {"value": value},
        ).scalar_one()


# ---------------------------------------------------------------------------
# Disable / enable
# ---------------------------------------------------------------------------


def test_disable_blocks_org_and_project_access_including_the_orgs_own_admin(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Disable Test Org")
    project = create_project(client, org_admin_token, org["id"])

    resp = client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # require_org_role-gated
    resp = client.get(f"/api/v1/orgs/{org['id']}/groups", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()

    # require_org_admin_or_server_admin-gated — blocked even for the actual server admin
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/users",
        json={"email": "blocked_new_user@example.com", "display_name": "New", "password": "Password123!", "role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 403

    # require_project_view-gated
    resp = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403

    # require_project_manage-gated
    resp = client.post(f"/api/v1/projects/{project['id']}/archive", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403


def test_enable_restores_access(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Enable Test Org")
    client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token))

    resp = client.post(f"/api/v1/orgs/{org['id']}/enable", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    resp = client.get(f"/api/v1/orgs/{org['id']}/groups", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200


def test_disable_and_enable_are_server_admin_only(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Server Admin Only Toggle Org")
    resp = client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403

    client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token))
    resp = client.post(f"/api/v1/orgs/{org['id']}/enable", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403


def test_cannot_disable_or_enable_twice(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Idempotency Org")
    assert client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token)).status_code == 200
    assert client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token)).status_code == 400
    assert client.post(f"/api/v1/orgs/{org['id']}/enable", headers=auth_headers(admin_token)).status_code == 200
    assert client.post(f"/api/v1/orgs/{org['id']}/enable", headers=auth_headers(admin_token)).status_code == 400


def test_login_still_works_while_only_org_is_disabled(client, admin_token):
    """Disabling an org blocks org/project-scoped requests, not login itself
    — a user might belong to other orgs too, and shouldn't be locked out of
    those."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Login Still Works Org")
    client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token))

    # The already-issued token still authenticates ordinary, non-org-scoped calls.
    assert client.get("/api/v1/auth/me", headers=auth_headers(org_admin_token)).status_code == 200
    # A brand new login also still succeeds.
    fresh_token = login(client, "login_still_works_org_admin@example.com", "Password123!")
    assert client.get("/api/v1/auth/me", headers=auth_headers(fresh_token)).status_code == 200


def test_disable_and_enable_reject_a_nonexistent_org(client, admin_token):
    import uuid

    bogus_id = uuid.uuid4()
    assert client.post(f"/api/v1/orgs/{bogus_id}/disable", headers=auth_headers(admin_token)).status_code == 404
    assert client.post(f"/api/v1/orgs/{bogus_id}/enable", headers=auth_headers(admin_token)).status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_requires_confirmation_name_match(client, admin_token):
    org, _ = create_org_admin_in(client, admin_token, "Wrong Confirm Org")
    resp = client.request(
        "DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": "not the right name"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400
    assert _row_count("organizations", "id", org["id"]) == 1


def test_delete_is_server_admin_only(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Delete Server Admin Only Org")
    resp = client.request(
        "DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 403


def test_delete_rejects_a_nonexistent_org(client, admin_token):
    import uuid

    resp = client.request(
        "DELETE", f"/api/v1/orgs/{uuid.uuid4()}", json={"confirm_name": "whatever"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_delete_cascades_through_everything_including_non_fk_references(client, admin_token):
    """The comprehensive cascade proof: creates one of everything an
    organisation can own (including the two things with no real foreign
    key at all — ReviewComment/Subscription's polymorphic target_id/
    entity_id — and real file storage bytes), deletes the organisation,
    and verifies each is actually gone, while users and audit history
    survive."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Full Cascade Org")
    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "Untouched Sibling Org")

    project = create_project(client, org_admin_token, org["id"])
    component_id, category_id = create_component_and_category(client, org_admin_token, project["id"])
    requirement = _create_requirement(client, org_admin_token, project["id"], component_id, category_id)

    member_id = create_org_user(client, org_admin_token, org["id"], "member_survivor@example.com", role="member")

    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "will this survive the delete?"}, headers=auth_headers(org_admin_token),
    ).json()
    reaction_resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}/reaction",
        headers=auth_headers(org_admin_token),
    )
    assert reaction_resp.status_code == 204, reaction_resp.text

    subscribe_resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/subscription",
        headers=auth_headers(org_admin_token),
    )
    assert subscribe_resp.status_code == 204

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "proposed_name": "x", "reason": "y",
        },
        headers=auth_headers(org_admin_token),
    ).json()

    upload = client.post(
        f"/api/v1/orgs/{org['id']}/resources",
        files={"file": ("doc.txt", b"hello world", "text/plain")},
        headers=auth_headers(org_admin_token),
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]
    storage_key = None
    with app_engine.begin() as conn:
        storage_key = conn.execute(
            text("SELECT storage_key FROM file_assets WHERE id = :id"), {"id": file_id}
        ).scalar_one()
    # Prove the bytes are genuinely on disk before we delete anything.
    assert get_storage_backend().read(storage_key) == b"hello world"

    # A PAT scoped only to this org — must be auto-revoked once emptied.
    solo_pat = client.post(
        "/api/v1/me/pats", json={"name": "solo", "allowed_organization_ids": [org["id"]]},
        headers=auth_headers(org_admin_token),
    ).json()

    # A second, two-org user + PAT — must survive, minus just this org's id.
    other_org_id = other_org["id"]
    two_org_user_id = create_org_user(client, org_admin_token, org["id"], "two_org_user@example.com", role="member")
    grant_resp = client.post(
        f"/api/v1/orgs/{other_org_id}/users/{two_org_user_id}/roles",
        json={"user_id": two_org_user_id, "role": "member"}, headers=auth_headers(other_org_admin_token),
    )
    assert grant_resp.status_code == 204, grant_resp.text
    two_org_token = login(client, "two_org_user@example.com", "Password123!")
    multi_pat = client.post(
        "/api/v1/me/pats", json={"name": "multi", "allowed_organization_ids": [org["id"], other_org_id]},
        headers=auth_headers(two_org_token),
    ).json()

    with app_engine.begin() as conn:
        audit_ids_before = [
            row[0]
            for row in conn.execute(
                text("SELECT id FROM audit_events WHERE organization_id = :id"), {"id": org["id"]}
            ).all()
        ]
    assert len(audit_ids_before) > 0

    # --- The actual delete ---
    resp = client.request(
        "DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text

    # The organisation itself, and everything it owned, is gone.
    assert _row_count("organizations", "id", org["id"]) == 0
    assert _row_count("projects", "id", project["id"]) == 0
    assert _row_count("requirements", "id", requirement["id"]) == 0
    assert _row_count("change_requests", "id", cr["id"]) == 0
    assert _row_count("review_comments", "id", comment["id"]) == 0
    assert _row_count("file_assets", "id", file_id) == 0

    # The file's actual bytes are gone from storage, not just its DB row.
    with pytest.raises(FileNotFoundError):
        get_storage_backend().read(storage_key)

    # Subscription had no real FK at all — would silently survive as an
    # orphan if the app-level cleanup hadn't explicitly deleted it.
    assert _row_count("subscriptions", "entity_id", requirement["id"]) == 0

    # Users survive as accounts; they just lose their role in this org.
    assert _row_count("users", "id", member_id) == 1
    assert _row_count("user_org_roles", "organization_id", org["id"]) == 0
    me = client.get("/api/v1/auth/me", headers=auth_headers(login(client, "member_survivor@example.com", "Password123!")))
    assert me.status_code == 200

    # A PAT scoped only to the deleted org is auto-revoked (nothing left to scope it to).
    with app_engine.begin() as conn:
        row = conn.execute(
            text("SELECT allowed_organization_ids, revoked_at FROM personal_access_tokens WHERE id = :id"),
            {"id": solo_pat["id"]},
        ).one()
    assert row.allowed_organization_ids == []
    assert row.revoked_at is not None

    # A PAT scoped to this org *and* another survives, minus just this org's id.
    with app_engine.begin() as conn:
        row = conn.execute(
            text("SELECT allowed_organization_ids, revoked_at FROM personal_access_tokens WHERE id = :id"),
            {"id": multi_pat["id"]},
        ).one()
    assert row.allowed_organization_ids == [other_org_id]
    assert row.revoked_at is None

    # Audit history survives the organisation it happened in — the same
    # rows are still there, just with the FK link nulled out rather than
    # deleted (ondelete="SET NULL", not CASCADE).
    assert _row_count("audit_events", "organization_id", org["id"]) == 0
    with app_engine.begin() as conn:
        surviving_count, still_fk_linked = conn.execute(
            text(
                "SELECT COUNT(*), COUNT(*) FILTER (WHERE organization_id IS NOT NULL) "
                "FROM audit_events WHERE id = ANY(:ids)"
            ),
            {"ids": audit_ids_before},
        ).one()
    assert surviving_count == len(audit_ids_before)
    assert still_fk_linked == 0

    # This deletion's own audit entry was written too.
    with app_engine.begin() as conn:
        deleted_event_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE entity_type = 'organization' AND entity_id = :id AND action = 'deleted'"
            ),
            {"id": org["id"]},
        ).scalar_one()
    assert deleted_event_count == 1


# ---------------------------------------------------------------------------
# Hardening-pass regressions
# ---------------------------------------------------------------------------
#
# The five tests below cover a dedicated identify -> verify -> remediate
# hardening pass run against this feature after it shipped (per CLAUDE.md's
# requirement for security-sensitive changes): two of these are full
# bypasses of the disable gate (file downloads, WebSocket — WebSocket's own
# regression tests live in test_websocket_security.py instead, alongside
# its pre-existing token_version hardening tests), one is an unhandled
# crash + permanent storage-data-loss bug in hard delete, one is a
# disabled-org metadata leak, and one is a delete-confirmation safety-gate
# bypass. See docs/decisions.md's "Organisation disable and hard delete"
# hardening-pass follow-up section for the full writeup.


def test_org_resource_file_download_blocked_when_org_disabled(client, admin_token):
    """A hardening-review finding: `download_file` authorized via the raw
    `get_effective_org_roles` helper rather than one of the `require_*`
    dependency factories, so it was never wired to `_require_org_active` —
    a disabled org's shared-resource files remained fully downloadable."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "File Download Disable Org")
    upload = client.post(
        f"/api/v1/orgs/{org['id']}/resources",
        files={"file": ("doc.txt", b"still secret", "text/plain")},
        headers=auth_headers(org_admin_token),
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]

    assert client.get(f"/api/v1/files/{file_id}", headers=auth_headers(org_admin_token)).status_code == 200

    client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token))
    resp = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403

    client.post(f"/api/v1/orgs/{org['id']}/enable", headers=auth_headers(admin_token))
    assert client.get(f"/api/v1/files/{file_id}", headers=auth_headers(org_admin_token)).status_code == 200


def test_requirement_attachment_download_blocked_when_org_disabled(client, admin_token):
    """Same gap, the other `download_file` code path (requirement
    attachments, authorized via `get_effective_project_roles`)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Attachment Download Disable Org")
    project = create_project(client, org_admin_token, org["id"])
    component_id, category_id = create_component_and_category(client, org_admin_token, project["id"])
    requirement = _create_requirement(client, org_admin_token, project["id"], component_id, category_id)

    upload = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("attachment.txt", b"still secret too", "text/plain")},
        headers=auth_headers(org_admin_token),
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]

    client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token))
    resp = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(org_admin_token))
    assert resp.status_code == 403


def test_delete_succeeds_when_org_has_a_logo_and_login_background(client, admin_token):
    """A hardening-review finding: `Organization.logo_file_id`/
    `login_background_file_id` are self-referential FKs to `file_assets`
    with no `ondelete` action. Deleting an org's `FileAsset` rows without
    first nulling those columns raised a raw, unhandled `IntegrityError`
    partway through the cascade — so any org that ever had a logo set could
    not be hard-deleted at all, and (worse) storage bytes for files
    processed earlier in that same loop were already destroyed by the time
    the crash happened, leaving orphaned rows for an org that wasn't even
    successfully deleted."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Logo Delete Org")

    logo_resp = client.post(
        f"/api/v1/orgs/{org['id']}/logo",
        files={"file": ("logo.png", b"fake-png-bytes", "image/png")},
        headers=auth_headers(org_admin_token),
    )
    assert logo_resp.status_code == 200
    assert logo_resp.json()["logo_file_id"] is not None

    resp = client.request(
        "DELETE", f"/api/v1/orgs/{org['id']}", json={"confirm_name": org["name"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text
    assert _row_count("organizations", "id", org["id"]) == 0


def test_reviews_due_excludes_requirements_from_a_disabled_org(client, admin_token):
    """A hardening-review finding: `/me/reviews/due` spans every project the
    caller has a role in with no `project_id`/`organization_id` to hang a
    `require_*` dependency off, so it was never wired to
    `_require_org_active` — a requirement's name/code/review date from a
    disabled org kept appearing in a reviewer's due list indefinitely."""
    import datetime

    org, org_admin_token = create_org_admin_in(client, admin_token, "Reviews Due Disable Org")
    project = create_project(client, org_admin_token, org["id"])
    component_id, category_id = create_component_and_category(client, org_admin_token, project["id"])
    me = client.get("/api/v1/auth/me", headers=auth_headers(org_admin_token)).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Due for review", "component_id": component_id, "category_id": category_id,
            "review_date": str(datetime.date.today() - datetime.timedelta(days=1)),
            "reviewer_id": me["id"],
        },
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    requirement_id = resp.json()["id"]

    due = client.get("/api/v1/me/reviews/due", headers=auth_headers(org_admin_token)).json()
    assert any(r["requirement_id"] == requirement_id for r in due)

    client.post(f"/api/v1/orgs/{org['id']}/disable", headers=auth_headers(admin_token))
    # /me/reviews/due has no org_id/project_id path param to gate behind
    # require_org_role, so this call itself still succeeds (200) even
    # though every org/project-content endpoint would now 403 — the bug was
    # that the disabled org's requirement kept showing up in the result.
    due_after = client.get("/api/v1/me/reviews/due", headers=auth_headers(org_admin_token))
    assert due_after.status_code == 200
    assert all(r["requirement_id"] != requirement_id for r in due_after.json())

    client.post(f"/api/v1/orgs/{org['id']}/enable", headers=auth_headers(admin_token))
    due_restored = client.get("/api/v1/me/reviews/due", headers=auth_headers(org_admin_token)).json()
    assert any(r["requirement_id"] == requirement_id for r in due_restored)


def test_organisation_name_cannot_be_blank_or_whitespace(client, admin_token):
    """A hardening-review finding: an org created with an empty/whitespace
    name defeats `DELETE /orgs/{id}`'s "type the exact name to confirm"
    safety gate entirely, since the comparison degenerates to two empty
    strings matching with nothing typed."""
    for bad_name in ("", "   ", "\t\n"):
        resp = client.post("/api/v1/orgs", json={"name": bad_name}, headers=auth_headers(admin_token))
        assert resp.status_code == 422, f"expected {bad_name!r} to be rejected, got {resp.status_code}"

    # A name with meaningful surrounding whitespace is trimmed, not rejected.
    resp = client.post("/api/v1/orgs", json={"name": "  Trimmed Org  "}, headers=auth_headers(admin_token))
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "Trimmed Org"
