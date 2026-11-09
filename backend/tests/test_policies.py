"""Server policies: administrator-only writes, the two built-in slots, the working copy versus the published
version, the append-only versions, the public read (published server policies only, no author or working copy,
rate limited), body validation (a closed vocabulary; script, event handler and unsafe link refused) and audit
events that never carry the text."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.policy import PolicyDocument, PolicyDocumentVersion, PolicyState
from tests.conftest import auth_headers, create_org_admin_in

SYSTEM = "/api/v1/system/policies"
PUBLIC = "/api/v1/public/policies"


def _doc(*paragraphs: str) -> dict:
    return {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]} for text in paragraphs
    ]}


def _create(client, token, **fields) -> dict:
    payload = {"title": "Acceptable use", "body": _doc("Use the service responsibly."), **fields}
    resp = client.post(SYSTEM, json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _publish(client, token, policy_id: str, note: str = "") -> dict:
    resp = client.post(f"{SYSTEM}/{policy_id}/publish", json={"change_note": note}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _put(client, token, policy_id: str, **fields):
    payload = {"title": "Acceptable use", "body": _doc("Use the service responsibly."), **fields}
    return client.put(f"{SYSTEM}/{policy_id}", json=payload, headers=auth_headers(token))


def test_only_server_administrators_can_write_or_read_the_administration_endpoints(client, admin_token):
    _org, org_token = create_org_admin_in(client, admin_token, "Policy org admin")
    created = _create(client, admin_token)
    for method, url, kwargs in (
        ("get", SYSTEM, {}),
        ("post", SYSTEM, {"json": {"title": "x"}}),
        ("get", f"{SYSTEM}/{created['id']}", {}),
        ("put", f"{SYSTEM}/{created['id']}", {"json": {"title": "x"}}),
        ("post", f"{SYSTEM}/{created['id']}/publish", {"json": {}}),
        ("post", f"{SYSTEM}/{created['id']}/unpublish", {}),
        ("delete", f"{SYSTEM}/{created['id']}", {}),
    ):
        assert getattr(client, method)(url, headers=auth_headers(org_token), **kwargs).status_code == 403, (method, url)
        assert getattr(client, method)(url, **kwargs).status_code == 401, (method, url)


def test_the_two_slots_are_listed_unset_first_and_take_their_fixed_title(client, admin_token):
    listing = client.get(SYSTEM, headers=auth_headers(admin_token)).json()
    assert [(r["key"], r["title"], r["id"]) for r in listing] == [("privacy", "Privacy policy", None), ("data", "Data policy", None)]
    made = _create(client, admin_token, key="data", title="Something else")
    assert (made["key"], made["title"], made["state"], made["current_version"]) == ("data", "Data policy", "draft", 0)
    renamed = _put(client, admin_token, made["id"], title="Renamed")
    assert renamed.status_code == 200 and renamed.json()["title"] == "Data policy", "a slot cannot be renamed"
    listing = client.get(SYSTEM, headers=auth_headers(admin_token)).json()
    assert [r["key"] for r in listing[:2]] == ["privacy", "data"]
    assert listing[1]["id"] == made["id"]
    again = client.post(SYSTEM, json={"key": "data", "body": _doc("x")}, headers=auth_headers(admin_token))
    assert again.status_code == 409
    unknown = client.post(SYSTEM, json={"key": "other", "body": _doc("x")}, headers=auth_headers(admin_token))
    assert unknown.status_code == 422


def test_a_slot_cannot_be_deleted_but_another_policy_can(client, admin_token):
    slot = _create(client, admin_token, key="privacy")
    resp = client.delete(f"{SYSTEM}/{slot['id']}", headers=auth_headers(admin_token))
    assert resp.status_code == 409
    other = _create(client, admin_token, title="Terms of service")
    assert client.delete(f"{SYSTEM}/{other['id']}", headers=auth_headers(admin_token)).status_code == 204
    assert client.get(f"{SYSTEM}/{other['id']}", headers=auth_headers(admin_token)).status_code == 404


def test_a_draft_is_not_public_and_a_published_policy_carries_no_author_or_working_copy(client, admin_token):
    made = _create(client, admin_token, title="Visible policy", effective_from="2026-12-01")
    assert client.get(PUBLIC).json() == []
    assert client.get(f"{PUBLIC}/{made['id']}").status_code == 404, "a draft is the same 404 as an unknown id"
    _publish(client, admin_token, made["id"], "First")
    listing = client.get(PUBLIC)
    assert listing.headers["Cache-Control"] == "no-store"
    [row] = listing.json()
    assert set(row) == {"id", "key", "title", "effective_from", "version", "published_at"}
    assert (row["title"], row["version"], row["effective_from"]) == ("Visible policy", 1, "2026-12-01")
    detail = client.get(f"{PUBLIC}/{made['id']}").json()
    assert set(detail) == {*row, "body"}
    assert detail["body"] == _doc("Use the service responsibly.")
    assert client.get(f"{PUBLIC}/{uuid.uuid4()}").status_code == 404


def test_editing_a_published_policy_changes_nothing_public_until_it_is_published_again(client, admin_token):
    made = _create(client, admin_token, title="Stable policy")
    _publish(client, admin_token, made["id"])
    edited = _put(client, admin_token, made["id"], title="Stable policy v2", body=_doc("Changed text."))
    assert edited.json()["has_unpublished_changes"] is True
    assert edited.json()["current_version"] == 1 and len(edited.json()["versions"]) == 1
    public = client.get(f"{PUBLIC}/{made['id']}").json()
    assert (public["title"], public["body"], public["version"]) == ("Stable policy", _doc("Use the service responsibly."), 1)
    second = _publish(client, admin_token, made["id"], "Reworded")
    assert second["current_version"] == 2 and second["has_unpublished_changes"] is False
    assert [v["version"] for v in second["versions"]] == [2, 1]
    assert second["versions"][0]["change_note"] == "Reworded"
    public = client.get(f"{PUBLIC}/{made['id']}").json()
    assert (public["title"], public["version"]) == ("Stable policy v2", 2)
    old = client.get(f"{SYSTEM}/{made['id']}/versions/1", headers=auth_headers(admin_token)).json()
    assert old["body"] == _doc("Use the service responsibly.") and old["title"] == "Stable policy"
    assert client.get(f"{SYSTEM}/{made['id']}/versions/9", headers=auth_headers(admin_token)).status_code == 404


def test_unpublishing_removes_it_from_the_public_read_and_keeps_every_version(client, admin_token):
    made = _create(client, admin_token, title="Retired policy")
    _publish(client, admin_token, made["id"])
    resp = client.post(f"{SYSTEM}/{made['id']}/unpublish", headers=auth_headers(admin_token))
    assert resp.status_code == 200 and resp.json()["state"] == "draft"
    assert client.get(PUBLIC).json() == []
    assert client.get(f"{PUBLIC}/{made['id']}").status_code == 404
    assert len(client.get(f"{SYSTEM}/{made['id']}", headers=auth_headers(admin_token)).json()["versions"]) == 1
    assert _publish(client, admin_token, made["id"])["current_version"] == 2


def test_publishing_needs_text_and_creating_or_editing_a_draft_writes_no_version(client, admin_token):
    empty = client.post(SYSTEM, json={"title": "Empty policy"}, headers=auth_headers(admin_token))
    assert empty.status_code == 201
    refused = client.post(f"{SYSTEM}/{empty.json()['id']}/publish", json={}, headers=auth_headers(admin_token))
    assert refused.status_code == 422
    assert _put(client, admin_token, empty.json()["id"], body=_doc("Now with text.")).status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(PolicyDocumentVersion).where(PolicyDocumentVersion.policy_id == empty.json()["id"])).all() == []
    blank = client.post(SYSTEM, json={"title": "  ", "body": _doc("x")}, headers=auth_headers(admin_token))
    assert blank.status_code == 422


def test_an_organisation_policy_is_never_public_or_reachable_through_the_server_endpoints(client, admin_token):
    org, _token = create_org_admin_in(client, admin_token, "Policy owner org")
    with SessionLocal() as db:
        row = PolicyDocument(
            organization_id=org["id"], title="Org only", body=_doc("Private."), state=PolicyState.PUBLISHED, current_version=1,
        )
        db.add(row)
        db.flush()
        db.add(PolicyDocumentVersion(
            policy_id=row.id, version=1, title="Org only", body=_doc("Private."), published_at=datetime.now(UTC),
        ))
        db.commit()
        policy_id = str(row.id)
    assert client.get(PUBLIC).json() == []
    assert client.get(f"{PUBLIC}/{policy_id}").status_code == 404
    assert client.get(f"{SYSTEM}/{policy_id}", headers=auth_headers(admin_token)).status_code == 404
    assert _put(client, admin_token, policy_id).status_code == 404
    assert all(r["id"] != policy_id for r in client.get(SYSTEM, headers=auth_headers(admin_token)).json())


def test_the_body_accepts_a_closed_vocabulary_and_rebuilds_it_without_unknown_fields(client, admin_token):
    body = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 2, "onclick": "x()"}, "content": [{"type": "text", "text": "Scope"}]},
        {"type": "paragraph", "attrs": {"class": "evil"}, "content": [
            {"type": "text", "text": "Read ", "marks": [{"type": "bold"}]},
            {"type": "text", "text": "this", "marks": [
                {"type": "link", "attrs": {"href": "https://example.org/p", "target": "_top", "onclick": "x()"}},
            ]},
            {"type": "text", "text": "mail", "marks": [{"type": "link", "attrs": {"href": "mailto:a@example.org"}}]},
        ]},
        {"type": "bulletList", "content": [{"type": "listItem", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "one", "marks": [{"type": "italic"}]}]},
        ]}]},
        {"type": "horizontalRule"},
    ]}
    stored = _create(client, admin_token, body=body)["body"]
    assert stored["content"][0] == {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Scope"}]}
    assert stored["content"][1]["content"][1]["marks"] == [{"type": "link", "attrs": {"href": "https://example.org/p"}}]
    assert "attrs" not in stored["content"][1]


def test_script_event_handler_and_unsafe_link_are_refused(client, admin_token):
    def refused(content: list) -> None:
        resp = client.post(SYSTEM, json={"title": "Bad", "body": {"type": "doc", "content": content}}, headers=auth_headers(admin_token))
        assert resp.status_code == 422, content

    refused([{"type": "script", "content": [{"type": "text", "text": "alert(1)"}]}])
    refused([{"type": "html", "text": "<script>alert(1)</script>"}])
    refused([{"type": "image", "attrs": {"src": "x", "onerror": "alert(1)"}}])
    for href in ("javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,x", "vbscript:x", "//evil.example", "", "https://x\u0000.example"):
        refused([{"type": "paragraph", "content": [
            {"type": "text", "text": "x", "marks": [{"type": "link", "attrs": {"href": href}}]},
        ]}])
    refused([{"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [{"type": "underline"}]}]}])
    refused([{"type": "heading", "attrs": {"level": 9}, "content": []}])
    refused([{"type": "horizontalRule", "content": [{"type": "text", "text": "x"}]}])
    nested: dict = {"type": "paragraph", "content": []}
    for _ in range(12):
        nested = {"type": "blockquote", "content": [nested]}
    refused([nested])
    too_long = client.post(
        SYSTEM, json={"title": "Long", "body": _doc("x" * 100_001)}, headers=auth_headers(admin_token),
    )
    assert too_long.status_code == 422
    assert client.post(SYSTEM, json={"title": "Bad", "body": {"type": "paragraph"}}, headers=auth_headers(admin_token)).status_code == 422


def test_audit_events_carry_the_key_version_and_length_but_never_the_text(client, admin_token):
    made = _create(client, admin_token, key="privacy", body=_doc("Secret wording of the policy."))
    _publish(client, admin_token, made["id"], "Confidential note")
    client.post(f"{SYSTEM}/{made['id']}/unpublish", headers=auth_headers(admin_token))
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "policy", AuditEvent.entity_id == made["id"])).all()
    assert {e.action for e in events} == {"created", "published", "unpublished"}
    for event in events:
        text = str(event.detail)
        assert "Secret wording" not in text and "Confidential note" not in text and "Privacy policy" not in text
    published = next(e for e in events if e.action == "published")
    assert published.detail["key"] == "privacy" and published.detail["current_version"] == 1
    assert published.detail["text_length"] == len("Secret wording of the policy.")


def test_the_public_read_is_rate_limited_per_address(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_announcement_rate_limit_burst", 2)
    monkeypatch.setattr(get_settings(), "public_announcement_rate_limit_per_minute", 1)
    headers = {"X-Forwarded-For": "203.0.113.91"}
    assert [client.get(PUBLIC, headers=headers).status_code for _ in range(2)] == [200, 200]
    limited = client.get(PUBLIC, headers=headers)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert client.get(f"{PUBLIC}/{uuid.uuid4()}", headers=headers).status_code == 429, "the detail read shares the bucket"


def test_two_requests_creating_the_same_slot_leave_one_and_answer_409(client, admin_token, monkeypatch):
    first = _create(client, admin_token, key="privacy")
    # The second request passes the existence check (as when both read before either wrote); the unique index decides.
    monkeypatch.setattr("app.services.policies.list_scope", lambda db, organization_id: [])
    again = client.post(SYSTEM, json={"key": "privacy", "body": _doc("x")}, headers=auth_headers(admin_token))
    assert again.status_code == 409
    monkeypatch.undo()
    with SessionLocal() as db:
        assert len(db.scalars(select(PolicyDocument).where(PolicyDocument.key == "privacy")).all()) == 1
    assert client.get(f"{SYSTEM}/{first['id']}", headers=auth_headers(admin_token)).status_code == 200
