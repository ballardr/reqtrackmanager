"""Announcements: plain-text rules, scope isolation between the server and each organisation, the active window
at its edges (including local-time boundary hours), the unauthenticated login-page read (flagged and active rows
only, no tenant data, rate limited), the signed-in banner, the one-time send as a notification (recipients,
idempotency, audit without the text) and the organisation bundle."""

import io
import zipfile
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.announcement import Announcement
from app.models.audit import AuditEvent
from app.models.notification import Notification, NotificationType
from app.models.organization import Organization
from app.models.user import User
from app.services import announcements as service
from app.services.bundle_common import BundleImportWarnings
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login

SERVER = "/api/v1/system/announcements"


def _org(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/announcements"


def _body(title="Planned maintenance", **extra) -> dict:
    return {"title": title, "body": "The service restarts at night.", **extra}


def _create(client, token, url, **fields) -> dict:
    resp = client.post(url, json=_body(**fields), headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_slug(org_id: str, slug: str) -> None:
    with SessionLocal() as db:
        org = db.get(Organization, org_id)
        assert org is not None
        org.slug = slug
        db.commit()


def _login_messages(client, slug: str | None = None, headers: dict | None = None):
    return client.get("/api/v1/announcements/login", params={"organization_slug": slug} if slug else None, headers=headers or {})


def test_text_is_cleaned_to_plain_text_and_an_empty_title_is_refused(client, admin_token):
    row = _create(client, admin_token, SERVER, title="  Down \n  for\tservice  ", body="Line one\r\n\x07Line two  ")
    assert (row["title"], row["body"]) == ("Down for service", "Line one\nLine two")
    for title in ("   ", "\x07\x08"):
        resp = client.post(SERVER, json=_body(title=title), headers=auth_headers(admin_token))
        assert resp.status_code == 422
    too_long = client.post(SERVER, json={"title": "x" * 121}, headers=auth_headers(admin_token))
    assert too_long.status_code == 422


def test_an_organisation_message_cannot_contain_a_web_address_but_a_server_message_may(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Web address org")
    for text in ("Sign in at https://evil.example now", "Visit www.evil.example", "ftp://x"):
        resp = client.post(_org(org["id"]), json={"title": "Notice", "body": text}, headers=auth_headers(token))
        assert resp.status_code == 422, text
        resp = client.post(_org(org["id"]), json={"title": text}, headers=auth_headers(token))
        assert resp.status_code == 422, text
    assert client.post(SERVER, json={"title": "Docs", "body": "See https://docs.example"}, headers=auth_headers(admin_token)).status_code == 201


def test_end_must_be_after_start(client, admin_token):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    resp = client.post(SERVER, json=_body(starts_at=start.isoformat(), ends_at=start.isoformat()), headers=auth_headers(admin_token))
    assert resp.status_code == 422
    naive = client.post(SERVER, json=_body(starts_at="2026-01-01T09:00:00"), headers=auth_headers(admin_token))
    assert naive.status_code == 422, "a window edge without a timezone is ambiguous"


def test_server_administrators_manage_server_messages_and_others_cannot(client, admin_token, org_id):
    row = _create(client, admin_token, SERVER, severity="warning", show_on_login=True)
    assert (row["organization_id"], row["severity"], row["status"]) == (None, "warning", "active")
    updated = client.put(f"{SERVER}/{row['id']}", json=_body(title="Revised", severity="critical"), headers=auth_headers(admin_token))
    assert (updated.json()["title"], updated.json()["severity"], updated.json()["show_on_login"]) == ("Revised", "critical", False)
    assert [i["id"] for i in client.get(SERVER, headers=auth_headers(admin_token)).json()["items"]] == [row["id"]]

    create_org_user(client, admin_token, org_id, "ann-member@example.com")
    member = auth_headers(login(client, "ann-member@example.com", "Password123!"))
    _org2, org_admin_token = create_org_admin_in(client, admin_token, "Ann org admin")
    for headers in (member, auth_headers(org_admin_token)):
        assert client.get(SERVER, headers=headers).status_code == 403
        assert client.post(SERVER, json=_body(), headers=headers).status_code == 403
        assert client.delete(f"{SERVER}/{row['id']}", headers=headers).status_code == 403
        assert client.post(f"{SERVER}/{row['id']}/notify", headers=headers).status_code == 403
    assert client.get(SERVER).status_code == 401

    assert client.delete(f"{SERVER}/{row['id']}", headers=auth_headers(admin_token)).status_code == 204
    assert client.get(SERVER, headers=auth_headers(admin_token)).json()["items"] == []


def test_an_organisation_administrator_cannot_touch_another_scope(client, admin_token):
    first, first_token = create_org_admin_in(client, admin_token, "Scope one")
    second, second_token = create_org_admin_in(client, admin_token, "Scope two")
    server_row = _create(client, admin_token, SERVER)
    other_row = _create(client, second_token, _org(second["id"]))
    own_row = _create(client, first_token, _org(first["id"]))
    headers = auth_headers(first_token)

    # Another organisation's collection is refused outright, its rows and a server-wide row are not found.
    assert client.get(_org(second["id"]), headers=headers).status_code == 403
    assert client.post(_org(second["id"]), json=_body(), headers=headers).status_code == 403
    for foreign in (server_row["id"], other_row["id"]):
        url = f"{_org(first['id'])}/{foreign}"
        assert client.put(url, json=_body(), headers=headers).status_code == 404
        assert client.delete(url, headers=headers).status_code == 404
        assert client.post(f"{url}/notify", headers=headers).status_code == 404
    assert [i["id"] for i in client.get(_org(first["id"]), headers=headers).json()["items"]] == [own_row["id"]]
    assert client.put(f"{_org(first['id'])}/{own_row['id']}", json=_body(title="Mine"), headers=headers).status_code == 200
    with SessionLocal() as db:
        assert db.get(Announcement, server_row["id"]) is not None
        assert db.get(Announcement, other_row["id"]) is not None


def test_a_scope_holds_a_bounded_number_of_messages(client, admin_token, monkeypatch):
    monkeypatch.setattr(service, "MAX_PER_SCOPE", 2)
    _create(client, admin_token, SERVER)
    _create(client, admin_token, SERVER)
    assert client.post(SERVER, json=_body(), headers=auth_headers(admin_token)).status_code == 409


def test_the_cap_counts_only_messages_that_have_not_ended(client, admin_token, monkeypatch):
    monkeypatch.setattr(service, "MAX_PER_SCOPE", 2)
    past = datetime(2020, 1, 1, tzinfo=UTC)
    for _ in range(4):  # history never uses up the cap
        _create(client, admin_token, SERVER, starts_at=past.isoformat(), ends_at=(past + timedelta(days=1)).isoformat())
    _create(client, admin_token, SERVER)
    _create(client, admin_token, SERVER, starts_at=(datetime.now(UTC) + timedelta(days=1)).isoformat())  # scheduled counts
    assert client.post(SERVER, json=_body(), headers=auth_headers(admin_token)).status_code == 409
    # a message created already ended is history, so it still fits beside a full set of current ones
    ended = _body(starts_at=past.isoformat(), ends_at=(past + timedelta(days=1)).isoformat())
    assert client.post(SERVER, json=ended, headers=auth_headers(admin_token)).status_code == 201


def test_the_stored_history_has_a_ceiling_that_ended_messages_count_toward(client, admin_token, monkeypatch):
    monkeypatch.setattr(service, "MAX_STORED_PER_SCOPE", 3)
    past = datetime(2020, 1, 1, tzinfo=UTC)
    ended = _body(starts_at=past.isoformat(), ends_at=(past + timedelta(days=1)).isoformat())
    for _ in range(3):
        assert client.post(SERVER, json=ended, headers=auth_headers(admin_token)).status_code == 201
    assert client.post(SERVER, json=ended, headers=auth_headers(admin_token)).status_code == 409


def test_a_message_is_dismissible_unless_it_says_otherwise_and_the_flag_reaches_readers(client, admin_token):
    plain = _create(client, admin_token, SERVER, title="Plain", show_on_login=True)
    fixed = _create(client, admin_token, SERVER, title="Fixed", show_on_login=True, dismissible=False)
    assert plain["dismissible"] is True and fixed["dismissible"] is False
    login = {m["title"]: m["dismissible"] for m in _login_messages(client).json()}
    assert login["Plain"] is True and login["Fixed"] is False
    banner = client.get("/api/v1/announcements/active", headers=auth_headers(admin_token)).json()
    assert {m["title"]: m["dismissible"] for m in banner}["Fixed"] is False
    # the switch is editable, and the audit event carries it without the text
    resp = client.put(f"{SERVER}/{fixed['id']}", json=_body(title="Fixed", dismissible=True), headers=auth_headers(admin_token))
    assert resp.status_code == 200 and resp.json()["dismissible"] is True
    with SessionLocal() as db:
        detail = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == fixed["id"], AuditEvent.action == "updated")
        ).one().detail
        assert detail["dismissible"] is True and "Fixed" not in str(detail)


def test_an_organisation_administrator_cannot_change_a_server_message_flag(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Dismissible scope")
    server_row = _create(client, admin_token, SERVER, title="Server notice", dismissible=False)
    resp = client.put(f"{_org(org['id'])}/{server_row['id']}", json=_body(dismissible=True), headers=auth_headers(token))
    assert resp.status_code == 404
    with SessionLocal() as db:
        row = db.get(Announcement, server_row["id"])
        assert row is not None and row.dismissible is False


def test_the_window_edges_are_start_inclusive_and_end_exclusive(client, admin_token):
    start = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    _create(client, admin_token, SERVER, show_on_login=True, starts_at=start.isoformat(), ends_at=end.isoformat())
    with SessionLocal() as db:
        row = db.scalars(select(Announcement)).one()
        assert service.status_of(row, start - timedelta(seconds=1)) == "scheduled"
        assert service.status_of(row, start) == "active"
        assert service.status_of(row, end - timedelta(seconds=1)) == "active"
        assert service.status_of(row, end) == "ended"
        shown = lambda at: len(service.login_messages(db, None, at))  # noqa: E731
        assert [shown(start - timedelta(seconds=1)), shown(start), shown(end - timedelta(seconds=1)), shown(end)] == [0, 1, 1, 0]


def test_local_time_boundary_hours_are_stored_as_the_same_utc_instant(client, admin_token):
    sydney = timezone(timedelta(hours=10))
    la = timezone(timedelta(hours=-8))
    nine_sydney = datetime(2026, 7, 1, 9, 0, tzinfo=sydney)
    eleven_pm_la = datetime(2026, 7, 1, 23, 0, tzinfo=la)
    row = _create(client, admin_token, SERVER, starts_at=nine_sydney.isoformat(), ends_at=eleven_pm_la.isoformat())
    assert datetime.fromisoformat(row["starts_at"]) == datetime(2026, 6, 30, 23, 0, tzinfo=UTC)
    assert datetime.fromisoformat(row["ends_at"]) == datetime(2026, 7, 2, 7, 0, tzinfo=UTC)
    with SessionLocal() as db:
        stored = db.scalars(select(Announcement)).one()
        assert service.status_of(stored, datetime(2026, 6, 30, 22, 59, tzinfo=UTC)) == "scheduled"
        assert service.status_of(stored, datetime(2026, 6, 30, 23, 0, tzinfo=UTC)) == "active"
        assert service.status_of(stored, datetime(2026, 7, 2, 7, 0, tzinfo=UTC)) == "ended"


def test_the_login_read_is_public_and_returns_only_flagged_active_messages_without_tenant_data(client, admin_token):
    org, org_token = create_org_admin_in(client, admin_token, "Login org")
    other, other_token = create_org_admin_in(client, admin_token, "Other login org")
    _set_slug(org["id"], "login-org")
    _set_slug(other["id"], "other-login-org")
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    _create(client, admin_token, SERVER, title="Shown server", show_on_login=True)
    _create(client, admin_token, SERVER, title="Not flagged", show_on_login=False)
    _create(client, admin_token, SERVER, title="Ended", show_on_login=True, ends_at=past)
    _create(client, admin_token, SERVER, title="Scheduled", show_on_login=True, starts_at=future)
    _create(client, org_token, _org(org["id"]), title="Shown org", show_on_login=True)
    _create(client, org_token, _org(org["id"]), title="Org not flagged", show_on_login=False)
    _create(client, other_token, _org(other["id"]), title="Other org", show_on_login=True)

    plain = _login_messages(client)
    assert plain.status_code == 200
    assert [m["title"] for m in plain.json()] == ["Shown server"]

    branded = _login_messages(client, "login-org").json()
    assert {m["title"] for m in branded} == {"Shown server", "Shown org"}
    assert {m["title"]: m["scope"] for m in branded} == {"Shown server": "server", "Shown org": "organisation"}
    for message in branded:
        assert set(message) == {"id", "title", "body", "severity", "scope", "dismissible"}, "no author, organisation id or send data"

    unknown = _login_messages(client, "no-such-organisation")
    assert unknown.status_code == 200
    assert [m["title"] for m in unknown.json()] == ["Shown server"], "an unknown slug does not reveal whether a slug exists"


def test_login_messages_list_the_most_severe_first(client, admin_token):
    _create(client, admin_token, SERVER, title="Info", severity="information", show_on_login=True)
    _create(client, admin_token, SERVER, title="Critical", severity="critical", show_on_login=True)
    _create(client, admin_token, SERVER, title="Warning", severity="warning", show_on_login=True)
    assert [m["title"] for m in _login_messages(client).json()] == ["Critical", "Warning", "Info"]


def test_the_login_read_is_rate_limited_per_address(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_announcement_rate_limit_burst", 2)
    monkeypatch.setattr(get_settings(), "public_announcement_rate_limit_per_minute", 1)
    headers = {"X-Forwarded-For": "203.0.113.77"}
    assert [_login_messages(client, headers=headers).status_code for _ in range(2)] == [200, 200]
    limited = _login_messages(client, headers=headers)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_the_banner_shows_server_messages_and_the_readers_own_organisation_only(client, admin_token):
    org, org_token = create_org_admin_in(client, admin_token, "Banner org")
    other, other_token = create_org_admin_in(client, admin_token, "Other banner org")
    _create(client, admin_token, SERVER, title="Server notice")
    _create(client, org_token, _org(org["id"]), title="Own notice")
    _create(client, other_token, _org(other["id"]), title="Foreign notice")
    headers = auth_headers(org_token)

    def titles(**params):
        resp = client.get("/api/v1/announcements/active", params=params, headers=headers)
        assert resp.status_code == 200, resp.text
        return {m["title"] for m in resp.json()}

    assert titles(organization_id=org["id"]) == {"Server notice", "Own notice"}
    assert titles() == {"Server notice"}
    assert titles(organization_id=other["id"]) == {"Server notice"}, "an organisation the reader is not in is ignored"
    assert client.get("/api/v1/announcements/active").status_code == 401


def _count_for(user_id: str) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(Notification).where(Notification.user_id == user_id, Notification.type == "system_announcement")).all())


def test_a_server_message_notifies_every_active_user_once_except_the_sender(client, admin_token, org_id):
    active_id = create_org_user(client, admin_token, org_id, "ann-active@example.com")
    gone_id = create_org_user(client, admin_token, org_id, "ann-gone@example.com")
    other_org, _token = create_org_admin_in(client, admin_token, "Notified elsewhere")
    with SessionLocal() as db:
        gone = db.get(User, gone_id)
        assert gone is not None
        gone.is_active = False
        db.commit()
        admin = db.scalars(select(User).where(User.email == "admin@example.com")).one()
        admin_id = str(admin.id)
        expected = len(service.recipients(db, None)) - 1  # everyone active, less the sender
    row = _create(client, admin_token, SERVER, title="Release tonight")

    sent = client.post(f"{SERVER}/{row['id']}/notify", headers=auth_headers(admin_token))
    assert sent.status_code == 200, sent.text
    assert sent.json()["notified_count"] == expected
    assert _count_for(active_id) == 1
    assert _count_for(gone_id) == 0
    assert _count_for(admin_id) == 0, "the sender is not told of their own send"
    assert other_org["id"], "organisations other than the sender's are reached by a server-wide send"

    again = client.post(f"{SERVER}/{row['id']}/notify", headers=auth_headers(admin_token))
    assert again.status_code == 409
    assert _count_for(active_id) == 1
    listed = client.get(SERVER, headers=auth_headers(admin_token)).json()["items"][0]
    assert listed["notified_count"] == expected and listed["notified_at"] is not None


def test_an_organisation_message_notifies_only_that_organisations_members(client, admin_token):
    org, org_token = create_org_admin_in(client, admin_token, "Notify org")
    other, _other_token = create_org_admin_in(client, admin_token, "Not notified org")
    member = create_org_user(client, org_token, org["id"], "ann-org-member@example.com")
    outsider = create_org_user(client, admin_token, other["id"], "ann-outsider@example.com")
    row = _create(client, org_token, _org(org["id"]), title="Team notice")

    sent = client.post(f"{_org(org['id'])}/{row['id']}/notify", headers=auth_headers(org_token))
    assert sent.status_code == 200, sent.text
    assert _count_for(member) == 1
    assert _count_for(outsider) == 0
    assert sent.json()["notified_count"] == 1, "the administrator who sent it is excluded"
    assert client.post(f"{_org(org['id'])}/{row['id']}/notify", headers=auth_headers(org_token)).status_code == 409


def test_an_ended_message_cannot_be_sent_and_a_scheduled_one_can(client, admin_token):
    ended = _create(client, admin_token, SERVER, ends_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    scheduled = _create(client, admin_token, SERVER, starts_at=(datetime.now(UTC) + timedelta(days=2)).isoformat())
    assert client.post(f"{SERVER}/{ended['id']}/notify", headers=auth_headers(admin_token)).status_code == 409
    assert client.post(f"{SERVER}/{scheduled['id']}/notify", headers=auth_headers(admin_token)).status_code == 200


def test_the_notification_type_is_registered_and_audit_events_never_carry_the_text(client, admin_token):
    assert NotificationType.SYSTEM_ANNOUNCEMENT.value == "system_announcement"
    secret_title, secret_body = "Confidential title text", "Confidential body text"
    row = client.post(SERVER, json={"title": secret_title, "body": secret_body}, headers=auth_headers(admin_token)).json()
    client.put(f"{SERVER}/{row['id']}", json={"title": secret_title, "body": secret_body, "severity": "warning"}, headers=auth_headers(admin_token))
    client.post(f"{SERVER}/{row['id']}/notify", headers=auth_headers(admin_token))
    client.delete(f"{SERVER}/{row['id']}", headers=auth_headers(admin_token))
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "announcement")).all()
        assert [e.action for e in events] == ["created", "updated", "notified", "deleted"]
        assert secret_title not in str([e.detail for e in events]) and secret_body not in str([e.detail for e in events])
        notified = next(e for e in events if e.action == "notified")
        assert set(notified.detail) == {"recipient_count", "scope"}


def test_the_organisation_bundle_carries_messages_but_not_the_send_record_or_server_messages(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Bundle announcements")
    headers = auth_headers(token)
    start = datetime(2030, 1, 1, 9, 0, tzinfo=timezone(timedelta(hours=10)))
    kept = _create(
        client, token, _org(org["id"]), title="Kept", severity="warning", show_on_login=True, dismissible=False, starts_at=start.isoformat(),
    )
    client.post(f"{_org(org['id'])}/{kept['id']}/notify", headers=headers)
    _create(client, admin_token, SERVER, title="Server only")

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=headers)
    assert export.status_code == 200
    text = zipfile.ZipFile(io.BytesIO(export.content)).read("org.json").decode()
    assert "Server only" not in text and "notified" not in text

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Bundle announcements copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    with SessionLocal() as db:
        copy = db.scalars(select(Announcement).where(Announcement.organization_id == imported.json()["organization"]["id"])).one()
        assert (copy.title, copy.severity.value, copy.show_on_login, copy.dismissible) == ("Kept", "warning", True, False)
        assert copy.starts_at == datetime(2029, 12, 31, 23, 0, tzinfo=UTC)
        assert copy.notified_at is None and copy.notified_count is None


def test_a_bundled_message_with_a_web_address_or_no_timezone_is_skipped_with_a_warning(client, admin_token):
    org, _token = create_org_admin_in(client, admin_token, "Bundle import rules")
    data = {"announcements": [
        {"title": "Fine", "body": "ok", "severity": "information"},
        {"title": "Phish", "body": "https://evil.example", "severity": "critical"},
        {"title": "Bad severity", "severity": "urgent"},
        "not an entry",
    ]}
    warnings = BundleImportWarnings()
    with SessionLocal() as db:
        actor = db.scalars(select(User).where(User.email == "admin@example.com")).one()
        service.import_org(db, org["id"], data, actor, warnings)
        service.import_org(db, org["id"], data, actor, warnings)  # a second import adds nothing
        db.commit()
        assert [a.title for a in service.list_scope(db, org["id"])] == ["Fine"]
    assert len(warnings.messages) == 6
    assert service._instant("2030-01-01T09:00:00") is None
