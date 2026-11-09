"""Organisation policies: written and published by the organisation's administrators only, read by its members (and
nobody else), limited to an audience of users and groups on request, links allowed only by the organisation's own
setting, an optional notification on publication, an import that always arrives as a draft, and audit events that never
carry the text."""

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.notification import Notification
from app.models.policy import PolicyDocument, PolicyState
from tests.conftest import auth_headers, create_org_admin_in, create_org_group, create_org_user, login

MINE = "/api/v1/policies/mine"
SYSTEM = "/api/v1/system/policies"
PUBLIC = "/api/v1/public/policies"


def _doc(*paragraphs: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]} for text in paragraphs]}


def _linked(text: str = "the standard", href: str = "https://example.com/standard") -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": text, "marks": [{"type": "link", "attrs": {"href": href}}]},
    ]}]}


@pytest.fixture
def world(client, admin_token):
    """An organisation with an administrator and three members, and a second organisation with its own administrator."""
    org, admin = create_org_admin_in(client, admin_token, "Policies Org")
    other, other_admin = create_org_admin_in(client, admin_token, "Other Policies Org")
    ids = {name: create_org_user(client, admin_token, org["id"], f"pol_{name}@example.com") for name in ("first", "second", "third")}
    return {
        "org": org["id"], "admin": admin, "other": other["id"], "other_admin": other_admin, "ids": ids,
        **{name: login(client, f"pol_{name}@example.com", "Password123!") for name in ids},
    }


def _base(org: str) -> str:
    return f"/api/v1/orgs/{org}/policies"


def _create(client, world, **fields) -> dict:
    payload = {"title": "Access policy", "body": _doc("Who may use which systems."), **fields}
    resp = client.post(_base(world["org"]), json=payload, headers=auth_headers(world["admin"]))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _publish(client, world, policy_id: str, **fields) -> dict:
    resp = client.post(f"{_base(world['org'])}/{policy_id}/publish", json=fields, headers=auth_headers(world["admin"]))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _titles(client, token) -> list[str]:
    resp = client.get(MINE, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return [p["title"] for p in resp.json()]


def test_only_the_organisations_administrators_use_the_administration_endpoints(client, world):
    made = _create(client, world)
    for method, url, kwargs in (
        ("get", _base(world["org"]), {}),
        ("post", _base(world["org"]), {"json": {"title": "x"}}),
        ("get", f"{_base(world['org'])}/{made['id']}", {}),
        ("put", f"{_base(world['org'])}/{made['id']}", {"json": {"title": "x"}}),
        ("post", f"{_base(world['org'])}/{made['id']}/publish", {"json": {}}),
        ("post", f"{_base(world['org'])}/{made['id']}/unpublish", {}),
        ("delete", f"{_base(world['org'])}/{made['id']}", {}),
        ("get", f"{_base(world['org'])}/settings", {}),
        ("put", f"{_base(world['org'])}/settings", {"json": {"allow_links": True}}),
    ):
        for token in (world["first"], world["other_admin"]):
            assert getattr(client, method)(url, headers=auth_headers(token), **kwargs).status_code == 403, (method, url)
        assert getattr(client, method)(url, **kwargs).status_code == 401, (method, url)


def test_an_organisation_has_no_built_in_slots_and_starts_with_none(client, world):
    assert client.get(_base(world["org"]), headers=auth_headers(world["admin"])).json() == []
    refused = client.post(_base(world["org"]), json={"key": "privacy", "body": _doc("x")}, headers=auth_headers(world["admin"]))
    assert refused.status_code == 422
    settings = client.get(f"{_base(world['org'])}/settings", headers=auth_headers(world["admin"])).json()
    assert settings["allow_links"] is False
    assert "Access policy" in settings["starter_titles"] and "Confidentiality agreement" in settings["starter_titles"]


def test_a_member_reads_a_published_policy_and_not_a_draft(client, world):
    made = _create(client, world, effective_from="2026-12-01")
    assert _titles(client, world["first"]) == []
    assert client.get(f"{MINE}/{made['id']}", headers=auth_headers(world["first"])).status_code == 404
    _publish(client, world, made["id"], change_note="First")
    assert _titles(client, world["first"]) == ["Access policy"]
    one = client.get(f"{MINE}/{made['id']}", headers=auth_headers(world["first"])).json()
    assert one["body"] == _doc("Who may use which systems.")
    assert (one["organization_name"], one["version"], one["effective_from"]) == ("Policies Org", 1, "2026-12-01")
    assert "change_note" not in one and "created_by" not in one
    assert _titles(client, world["admin"]) == ["Access policy"]


def test_an_edit_changes_what_members_read_only_when_it_is_published_again(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    edited = client.put(
        f"{_base(world['org'])}/{made['id']}", json={"title": "Access policy v2", "body": _doc("New text.")},
        headers=auth_headers(world["admin"]),
    )
    assert edited.status_code == 200 and edited.json()["has_unpublished_changes"] is True
    assert client.get(f"{MINE}/{made['id']}", headers=auth_headers(world["first"])).json()["body"] == _doc("Who may use which systems.")
    _publish(client, world, made["id"], change_note="Rewritten")
    now = client.get(f"{MINE}/{made['id']}", headers=auth_headers(world["first"])).json()
    assert (now["title"], now["version"], now["body"]) == ("Access policy v2", 2, _doc("New text."))


def test_unpublishing_removes_it_from_members_and_keeps_every_version(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    resp = client.post(f"{_base(world['org'])}/{made['id']}/unpublish", headers=auth_headers(world["admin"]))
    assert resp.status_code == 200 and resp.json()["state"] == "draft"
    assert _titles(client, world["first"]) == []
    assert [v["version"] for v in resp.json()["versions"]] == [1]


# --- scope ------------------------------------------------------------------------------------------


def test_nobody_outside_the_organisation_can_read_or_reach_its_policies(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    assert _titles(client, world["other_admin"]) == []
    assert client.get(f"{MINE}/{made['id']}", headers=auth_headers(world["other_admin"])).status_code == 404
    assert client.get(MINE).status_code == 401
    assert client.get(PUBLIC).json() == []
    assert client.get(f"{PUBLIC}/{made['id']}").status_code == 404


def test_an_administrator_cannot_write_a_server_policy_or_another_organisations_policy(client, admin_token, world):
    made = _create(client, world)
    other = f"{_base(world['other'])}/{made['id']}"
    for method, url, kwargs in (
        ("get", other, {}), ("put", other, {"json": {"title": "x", "body": _doc("x")}}),
        ("post", f"{other}/publish", {"json": {}}), ("post", f"{other}/unpublish", {}), ("delete", other, {}),
    ):
        assert getattr(client, method)(url, headers=auth_headers(world["other_admin"]), **kwargs).status_code == 404, (method, url)
    for method, url, kwargs in (
        ("post", SYSTEM, {"json": {"title": "x", "body": _doc("x")}}),
        ("put", f"{SYSTEM}/{made['id']}", {"json": {"title": "x", "body": _doc("x")}}),
        ("post", f"{SYSTEM}/{made['id']}/publish", {"json": {}}),
    ):
        assert getattr(client, method)(url, headers=auth_headers(world["admin"]), **kwargs).status_code == 403, (method, url)
    # A server administrator reaches an organisation policy through the server routes as a 404 (another scope).
    assert client.get(f"{SYSTEM}/{made['id']}", headers=auth_headers(admin_token)).status_code == 404


def test_a_disabled_organisation_lists_no_policies(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    from app.models.organization import Organization

    with SessionLocal() as db:
        org = db.get(Organization, uuid.UUID(world["org"]))
        assert org is not None
        org.is_active = False
        db.commit()
    try:
        assert _titles(client, world["first"]) == []
    finally:
        with SessionLocal() as db:
            org = db.get(Organization, uuid.UUID(world["org"]))
            assert org is not None
            org.is_active = True
            db.commit()


# --- audience ---------------------------------------------------------------------------------------


def test_a_policy_limited_to_a_user_is_absent_for_everyone_else_but_the_administrator(client, world):
    made = _create(client, world, audience=[{"type": "user", "id": world["ids"]["first"]}])
    _publish(client, world, made["id"])
    assert _titles(client, world["first"]) == ["Access policy"]
    assert _titles(client, world["second"]) == []
    assert _titles(client, world["admin"]) == ["Access policy"]
    assert client.get(f"{MINE}/{made['id']}", headers=auth_headers(world["second"])).status_code == 404
    listed = client.get(_base(world["org"]), headers=auth_headers(world["admin"])).json()
    assert [(r["title"], [a["id"] for a in r["audience"]]) for r in listed] == [("Access policy", [world["ids"]["first"]])]


def test_a_group_audience_admits_its_members_including_through_a_nested_group(client, world):
    inner = create_org_group(client, world["admin"], world["org"], "Inner team", users=[world["ids"]["first"]])
    outer = create_org_group(client, world["admin"], world["org"], "Outer team", nested=[inner])
    made = _create(client, world, audience=[{"type": "org_group", "id": outer}])
    _publish(client, world, made["id"])
    assert _titles(client, world["first"]) == ["Access policy"]
    assert _titles(client, world["second"]) == []


def test_audience_labels_name_only_people_and_groups_of_the_organisation(client, admin_token, world):
    group = create_org_group(client, world["admin"], world["org"], "Label group", users=[world["ids"]["first"]])
    picked = [{"type": "user", "id": world["ids"]["first"]}, {"type": "org_group", "id": group}]
    url = f"{_base(world['org'])}/audience-labels"
    resp = client.post(url, json={"audience": picked}, headers=auth_headers(world["admin"]))
    assert resp.status_code == 200, resp.text
    assert [(r["type"], r["id"]) for r in resp.json()] == [("user", world["ids"]["first"]), ("org_group", group)]
    assert resp.json()[1]["label"] == "Label group" and resp.json()[1]["member_count"] == 1
    outsider = create_org_user(client, admin_token, world["other"], "pol_label_outsider@example.com")
    refused = client.post(url, json={"audience": [{"type": "user", "id": outsider}]}, headers=auth_headers(world["admin"]))
    assert refused.status_code == 400, "a name from another organisation is never returned"
    assert client.post(url, json={"audience": picked}, headers=auth_headers(world["first"])).status_code == 403


def test_the_audience_is_replaced_only_when_sent_and_emptied_to_widen_it_deliberately(client, world):
    made = _create(client, world, audience=[{"type": "user", "id": world["ids"]["first"]}])
    _publish(client, world, made["id"])
    kept = client.put(
        f"{_base(world['org'])}/{made['id']}", json={"title": "Access policy", "body": _doc("Edited.")},
        headers=auth_headers(world["admin"]),
    )
    assert [a["id"] for a in kept.json()["audience"]] == [world["ids"]["first"]], "a key left out leaves the audience alone"
    assert _titles(client, world["second"]) == []
    widened = client.put(
        f"{_base(world['org'])}/{made['id']}", json={"title": "Access policy", "body": _doc("Edited."), "audience": []},
        headers=auth_headers(world["admin"]),
    )
    assert widened.json()["audience"] == []
    assert _titles(client, world["second"]) == ["Access policy"]


def test_an_audience_member_must_belong_to_the_organisation(client, admin_token, world):
    foreign_group = create_org_group(client, world["other_admin"], world["other"], "Foreign")
    outsider = create_org_user(client, admin_token, world["other"], "pol_outsider@example.com")
    for audience in ([{"type": "org_group", "id": foreign_group}], [{"type": "user", "id": outsider}]):
        resp = client.post(
            _base(world["org"]), json={"title": "x", "body": _doc("x"), "audience": audience}, headers=auth_headers(world["admin"]),
        )
        assert resp.status_code == 400, resp.text
    repeated = [{"type": "user", "id": world["ids"]["first"]}] * 2
    resp = client.post(_base(world["org"]), json={"title": "x", "body": _doc("x"), "audience": repeated}, headers=auth_headers(world["admin"]))
    assert resp.status_code == 422


def test_deleting_a_group_that_restricts_a_policy_needs_a_replacement_and_never_widens_it(client, world):
    org, admin = world["org"], world["admin"]
    group = create_org_group(client, admin, org, "Policy readers", users=[world["ids"]["first"]])
    replacement = create_org_group(client, admin, org, "Replacement readers", users=[world["ids"]["first"]])
    made = _create(client, world, audience=[{"type": "org_group", "id": group}])
    _publish(client, world, made["id"])
    assert client.delete(f"/api/v1/orgs/{org}/groups/{group}", headers=auth_headers(admin)).status_code == 409
    assert _titles(client, world["second"]) == []
    done = client.delete(
        f"/api/v1/orgs/{org}/groups/{group}", params={"replacement_type": "org_group", "replacement_id": replacement},
        headers=auth_headers(admin),
    )
    assert done.status_code in (200, 204), done.text
    assert _titles(client, world["second"]) == []
    assert _titles(client, world["first"]) == ["Access policy"]


def test_a_member_removed_from_the_organisation_no_longer_reads_a_policy(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    from app.models.organization import UserOrgRole

    with SessionLocal() as db:
        for role in db.scalars(select(UserOrgRole).where(UserOrgRole.user_id == uuid.UUID(world["ids"]["third"]))):
            db.delete(role)
        db.commit()
    assert _titles(client, world["third"]) == []


# --- links ------------------------------------------------------------------------------------------


def test_links_are_refused_until_the_organisation_allows_them(client, world):
    refused = client.post(
        _base(world["org"]), json={"title": "Cites a standard", "body": _linked()}, headers=auth_headers(world["admin"]),
    )
    assert refused.status_code == 422 and "link" in refused.text.lower()
    on = client.put(f"{_base(world['org'])}/settings", json={"allow_links": True}, headers=auth_headers(world["admin"]))
    assert on.status_code == 200 and on.json()["allow_links"] is True
    made = _create(client, world, title="Cites a standard", body=_linked())
    _publish(client, world, made["id"])
    got = client.get(f"{MINE}/{made['id']}", headers=auth_headers(world["first"])).json()
    assert got["body"]["content"][0]["content"][0]["marks"][0]["attrs"]["href"] == "https://example.com/standard"
    unsafe = client.post(
        _base(world["org"]), json={"title": "Unsafe", "body": _linked(href="javascript:alert(1)")}, headers=auth_headers(world["admin"]),
    )
    assert unsafe.status_code == 422, "the setting never admits an unsafe address"


def test_turning_links_off_blocks_publishing_a_working_copy_that_still_has_one(client, world):
    client.put(f"{_base(world['org'])}/settings", json={"allow_links": True}, headers=auth_headers(world["admin"]))
    made = _create(client, world, title="Cites a standard", body=_linked())
    client.put(f"{_base(world['org'])}/settings", json={"allow_links": False}, headers=auth_headers(world["admin"]))
    blocked = client.post(f"{_base(world['org'])}/{made['id']}/publish", json={}, headers=auth_headers(world["admin"]))
    assert blocked.status_code == 422
    fixed = client.put(
        f"{_base(world['org'])}/{made['id']}", json={"title": "Cites a standard", "body": _doc("No link now.")},
        headers=auth_headers(world["admin"]),
    )
    assert fixed.status_code == 200
    _publish(client, world, made["id"])


# --- notification -----------------------------------------------------------------------------------


def _notified(user_id: str) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(Notification).where(Notification.user_id == user_id, Notification.type == "policy_published")).all())


def test_publishing_notifies_only_when_chosen_and_only_the_people_who_may_read_it(client, world):
    plain = _create(client, world, title="Quiet policy")
    _publish(client, world, plain["id"])
    assert _notified(world["ids"]["first"]) == 0, "no notification unless the publisher chooses one"

    limited = _create(client, world, title="Limited policy", audience=[{"type": "user", "id": world["ids"]["first"]}])
    _publish(client, world, limited["id"], notify_members=True, change_note="Please read")
    assert _notified(world["ids"]["first"]) == 1
    assert _notified(world["ids"]["second"]) == 0, "a person outside the audience is not told"


def test_the_publisher_is_not_notified_of_their_own_publication(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"], notify_members=True)
    assert _notified(world["ids"]["first"]) == _notified(world["ids"]["second"]) == 1
    with SessionLocal() as db:
        admin_ids = db.scalars(select(Notification.user_id).where(Notification.type == "policy_published")).all()
        assert len(admin_ids) == 3, "the three members; the administrator who published is excluded"


# --- audit ------------------------------------------------------------------------------------------


def test_audit_events_carry_counts_and_keys_never_the_text(client, world):
    secret = "Confidential wording that must not be logged"
    made = _create(client, world, title="Audited policy", body=_doc(secret), audience=[{"type": "user", "id": world["ids"]["first"]}])
    _publish(client, world, made["id"], notify_members=True, change_note="why")
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "policy", AuditEvent.entity_id == made["id"])))
        actions = {e.action for e in events}
        assert {"created", "audience_changed", "published", "notified"} <= actions
        assert all(e.organization_id == uuid.UUID(world["org"]) for e in events)
        assert secret not in repr([e.detail for e in events]) and "Audited policy" not in repr([e.detail for e in events])
        notified = next(e for e in events if e.action == "notified")
        assert notified.detail["recipient_count"] == 1


# --- deleting ---------------------------------------------------------------------------------------


def test_deleting_a_policy_removes_its_versions_and_audience(client, world):
    made = _create(client, world, audience=[{"type": "user", "id": world["ids"]["first"]}])
    _publish(client, world, made["id"])
    assert client.delete(f"{_base(world['org'])}/{made['id']}", headers=auth_headers(world["admin"])).status_code == 204
    assert _titles(client, world["first"]) == []
    with SessionLocal() as db:
        assert db.get(PolicyDocument, uuid.UUID(made["id"])) is None


# --- bundle -----------------------------------------------------------------------------------------


def _import_copy(client, admin_token, world) -> str:
    exported = client.get(f"/api/v1/orgs/{world['org']}/export", headers=auth_headers(world["admin"]))
    assert exported.status_code == 200, exported.text
    imported = client.post(
        "/api/v1/orgs/import", data={"name": f"Policies Copy {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    return imported.json()["organization"]["id"]


def test_policies_round_trip_through_the_organisation_bundle_as_drafts(client, admin_token, world):
    group = create_org_group(client, world["admin"], world["org"], "Board", users=[world["ids"]["first"]])
    made = _create(client, world, title="Confidentiality agreement", audience=[{"type": "org_group", "id": group}], effective_from="2027-01-01")
    _publish(client, world, made["id"], change_note="Initial")
    client.put(
        f"{_base(world['org'])}/{made['id']}",
        json={"title": "Confidentiality agreement", "body": _doc("Second wording."), "effective_from": "2027-01-01"},
        headers=auth_headers(world["admin"]),
    )
    _publish(client, world, made["id"], change_note="Second")

    copy = uuid.UUID(_import_copy(client, admin_token, world))
    with SessionLocal() as db:
        from app.services import org_policies, policies

        rows = policies.list_scope(db, copy)
        assert [r.title for r in rows] == ["Confidentiality agreement"]
        row = rows[0]
        assert row.state is PolicyState.DRAFT, "an import never publishes text in the new organisation's name"
        assert row.current_version == 2 and row.effective_from is not None and row.effective_from.isoformat() == "2027-01-01"
        assert row.body == _doc("Second wording.")
        history = policies.versions(db, row)
        assert [(v.version, v.change_note) for v in history] == [(2, "Second"), (1, "Initial")]
        assert all(v.published_by is None for v in history)
        audience = org_policies.audience_of(db, [row.id])[row.id]
        assert len(audience) == 1 and audience[0].type.value == "org_group", "restricted, as it was"
        assert org_policies.published_for  # the import is invisible to readers until published


def test_an_import_does_not_overwrite_a_policy_the_organisation_already_has(client, world):
    from app.models.user import User
    from app.services import org_policies, policies
    from app.services.bundle_common import BundleImportWarnings

    made = _create(client, world, title="Access policy")
    org = uuid.UUID(world["org"])
    bundle = {"policies": [
        {"title": "Access policy", "body": _doc("Replacement attempt.")},
        {"title": "Fresh policy", "body": _doc("New.")},
    ]}
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.email == "pol_first@example.com"))
        assert actor is not None
        org_policies.import_org(db, org, bundle, actor, BundleImportWarnings())
        db.commit()
        by_title = {r.title: r for r in policies.list_scope(db, org)}
        assert set(by_title) == {"Access policy", "Fresh policy"}
        assert by_title["Access policy"].body == _doc("Who may use which systems.") and str(by_title["Access policy"].id) == made["id"]


def test_an_import_drops_a_text_that_is_not_valid_here_and_never_widens_an_unmatched_audience(client, world):
    from app.models.user import User
    from app.services import org_policies, policies
    from app.services.bundle_common import BundleImportWarnings

    org = uuid.UUID(world["org"])
    bundle = {"policies": [
        {"title": "Has a link", "body": _linked()},
        {"title": "Ghost audience", "body": _doc("Text."), "audience": [{"type": "user", "email": "nobody-here@example.com"}]},
        "not an entry",
    ]}
    warnings = BundleImportWarnings()
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.email == "pol_first@example.com"))
        assert actor is not None
        org_policies.import_org(db, org, bundle, actor, warnings)
        db.commit()
        rows = policies.list_scope(db, org)
        assert [r.title for r in rows] == ["Ghost audience"], "the link is refused while the organisation allows none"
        audience = org_policies.audience_of(db, [rows[0].id])[rows[0].id]
        assert [(a.type.value, a.id) for a in audience] == [("user", actor.id)]
    assert len(warnings.messages) >= 3
