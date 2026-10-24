"""Tests for credential reset: the emailed reset link, administrator-sent links, the forced reset and the CLI.

Covers single use and expiry, the credential epoch ending sessions, enumeration parity on "forgot password",
the forced-reset sign-in block, scoping of administrator sends, secrets never reaching audit rows, and the
command line working when every administrator is locked out.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pyotp
import pytest

from app.cli import credentials as cli
from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.credential_reset import CredentialResetToken
from app.models.pat import PersonalAccessToken
from app.models.user import User
from app.security import hash_pat
from app.services import credential_reset
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login

_TOKEN = re.compile(r"/reset-password#token=([\w-]+)")
NEW_PASSWORD = "BrandNewPassw0rd!"


@pytest.fixture(autouse=True)
def _fresh_limiters():
    credential_reset._limiters.clear()
    yield
    credential_reset._limiters.clear()


@pytest.fixture
def mail():
    """Captures reset emails instead of sending them; yields the mock (args: to, subject, text body)."""
    with patch.object(credential_reset, "send_email", new=Mock()) as sent:
        yield sent


def _token_from(mail_mock, index: int = -1) -> str:
    body = mail_mock.call_args_list[index].args[2]
    match = _TOKEN.search(body)
    assert match, body
    return match.group(1)


def _forgot(client, email):
    return client.post("/api/v1/auth/forgot-password", json={"email": email})


def _reset(client, token, password=NEW_PASSWORD):
    return client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": password})


def _db_user(email) -> User:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        db.expunge(user)
        return user
    finally:
        db.close()


def _mutate_user(email, **fields) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        for key, value in fields.items():
            setattr(user, key, value)
        db.commit()
    finally:
        db.close()


@pytest.fixture
def member(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "member@example.com", password="OldPassword123!")
    return "member@example.com"


# --- forgot / reset ---------------------------------------------------------------------------------------


def test_forgot_password_emails_a_fragment_link_and_stores_only_a_hash(client, member, mail):
    resp = _forgot(client, member)
    assert resp.status_code == 202
    assert mail.call_count == 1
    assert mail.call_args.args[0] == member
    assert "localhost:3000/reset-password#token=" in mail.call_args.args[2]
    assert "?token=" not in mail.call_args.args[2]
    raw = _token_from(mail)
    db = SessionLocal()
    try:
        rows = db.query(CredentialResetToken).all()
        assert len(rows) == 1
        assert rows[0].token_hash == hash_pat(raw) and raw not in rows[0].token_hash
        assert rows[0].issued_via == "forgot"
    finally:
        db.close()


def test_forgot_password_answers_identically_for_unknown_sso_inactive_and_real_accounts(client, admin_token, org_id, member, mail):
    create_org_user(client, admin_token, org_id, "gone@example.com")
    _mutate_user("gone@example.com", is_active=False)
    create_org_user(client, admin_token, org_id, "sso@example.com")
    _mutate_user("sso@example.com", auth_backend="oidc", password_hash=None)

    answers = [_forgot(client, e) for e in (member, "nobody@example.com", "gone@example.com", "sso@example.com")]

    assert {r.status_code for r in answers} == {202}
    assert len({r.text for r in answers}) == 1
    assert [c.args[0] for c in mail.call_args_list] == [member]


def test_forgot_password_does_not_send_a_second_link_within_the_cooldown(client, member, mail):
    _forgot(client, member)
    _forgot(client, member)
    assert mail.call_count == 1


def test_forgot_password_is_rate_limited_per_client_address(client, mail):
    codes = [_forgot(client, f"user{i}@example.com").status_code for i in range(12)]
    assert codes[:10] == [202] * 10
    assert 429 in codes[10:]


def test_reset_sets_the_password_ends_sessions_and_is_single_use(client, member, mail):
    old_token = login(client, member, "OldPassword123!")
    _forgot(client, member)
    raw = _token_from(mail)

    assert _reset(client, raw).status_code == 204

    assert client.get("/api/v1/auth/me", headers=auth_headers(old_token)).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": member, "password": "OldPassword123!"}).status_code == 401
    assert login(client, member, NEW_PASSWORD)
    second = _reset(client, raw, "AnotherPassw0rd!")
    assert second.status_code == 400
    assert "invalid or has expired" in second.json()["detail"]


def test_reset_does_not_sign_the_person_in(client, member, mail):
    _forgot(client, member)
    resp = _reset(client, _token_from(mail))
    assert resp.status_code == 204 and resp.content == b""


def test_an_expired_unknown_or_malformed_link_gets_one_message(client, member, mail):
    _forgot(client, member)
    raw = _token_from(mail)
    db = SessionLocal()
    try:
        db.query(CredentialResetToken).update({"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        db.commit()
    finally:
        db.close()

    expired = _reset(client, raw)
    unknown = _reset(client, "x" * 43)

    assert expired.status_code == unknown.status_code == 400
    assert expired.json() == unknown.json()
    assert _reset(client, "short").status_code == 422


def test_a_weak_new_password_is_rejected_and_the_link_survives(client, member, mail):
    _forgot(client, member)
    raw = _token_from(mail)
    assert _reset(client, raw, "short").status_code == 422
    assert _reset(client, raw).status_code == 204


def test_redeeming_one_link_spends_the_others(client, member, mail):
    _forgot(client, member)
    first = _token_from(mail)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == member).one()
        second, _ = credential_reset.issue_token(db, user, via="admin")
        db.commit()
    finally:
        db.close()

    assert _reset(client, first).status_code == 204
    assert _reset(client, second).status_code == 400


def test_reset_leaves_two_factor_in_place(client, member, mail):
    token = login(client, member, "OldPassword123!")
    enroll = client.post("/api/v1/auth/2fa/enroll", headers=auth_headers(token)).json()
    code = pyotp.TOTP(enroll["secret"]).now()
    assert client.post("/api/v1/auth/2fa/status", json={"action": "confirm", "code": code}, headers=auth_headers(token)).status_code == 204
    _forgot(client, member)
    assert _reset(client, _token_from(mail)).status_code == 204

    resp = client.post("/api/v1/auth/login", json={"email": member, "password": NEW_PASSWORD})
    assert resp.status_code == 200 and "challenge_token" in resp.json()


def test_a_failed_send_leaves_no_live_link(client, member):
    with patch.object(credential_reset, "send_email", new=Mock(side_effect=RuntimeError("smtp down"))):
        assert _forgot(client, member).status_code == 202
    db = SessionLocal()
    try:
        assert db.query(CredentialResetToken).count() == 0
    finally:
        db.close()


# --- administrator-sent links ---------------------------------------------------------------------------


def test_org_admin_sends_a_member_a_link_and_never_sees_it(client, admin_token, org_id, member, mail):
    org_admin_id = create_org_user(client, admin_token, org_id, "oa@example.com", role="org_admin")
    oa = login(client, "oa@example.com", "Password123!")
    member_id = str(_db_user(member).id)

    resp = client.post(f"/api/v1/orgs/{org_id}/users/{member_id}/password-reset", headers=auth_headers(oa))

    assert resp.status_code == 204 and resp.content == b""
    assert mail.call_args.args[0] == member
    raw = _token_from(mail)
    assert _reset(client, raw).status_code == 204
    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(AuditEvent.action == "password_reset_link_sent").one()
        assert str(event.actor_id) == org_admin_id and str(event.organization_id) == org_id
        assert raw not in str(event.detail) and hash_pat(raw) not in str(event.detail)
    finally:
        db.close()


def test_a_plain_member_cannot_send_a_reset_link(client, admin_token, org_id, member, mail):
    create_org_user(client, admin_token, org_id, "plain@example.com")
    plain = login(client, "plain@example.com", "Password123!")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{_db_user(member).id}/password-reset", headers=auth_headers(plain)
    )
    assert resp.status_code == 403
    assert mail.call_count == 0


def test_an_org_admin_cannot_send_a_link_to_someone_outside_their_organisation(client, admin_token, org_id, member, mail):
    other_org, other_admin = create_org_admin_in(client, admin_token, "Other Org")
    resp = client.post(
        f"/api/v1/orgs/{other_org['id']}/users/{_db_user(member).id}/password-reset", headers=auth_headers(other_admin)
    )
    assert resp.status_code == 404
    assert mail.call_count == 0


def test_server_admin_sends_a_link_to_any_account(client, admin_token, member, mail):
    resp = client.post(f"/api/v1/system/users/{_db_user(member).id}/password-reset", headers=auth_headers(admin_token))
    assert resp.status_code == 204
    assert mail.call_args.args[0] == member


def test_a_non_server_admin_cannot_use_the_server_endpoint(client, admin_token, org_id, member, mail):
    create_org_user(client, admin_token, org_id, "oa@example.com", role="org_admin")
    oa = login(client, "oa@example.com", "Password123!")
    resp = client.post(f"/api/v1/system/users/{_db_user(member).id}/password-reset", headers=auth_headers(oa))
    assert resp.status_code == 403


def test_sending_to_an_sso_account_is_refused_with_a_reason(client, admin_token, org_id, mail):
    create_org_user(client, admin_token, org_id, "sso@example.com")
    _mutate_user("sso@example.com", auth_backend="oidc", password_hash=None)
    resp = client.post(f"/api/v1/system/users/{_db_user('sso@example.com').id}/password-reset", headers=auth_headers(admin_token))
    assert resp.status_code == 400 and "single sign-on" in resp.json()["detail"]
    assert mail.call_count == 0


def test_sending_twice_within_a_minute_is_refused_and_does_not_flood(client, admin_token, member, mail):
    url = f"/api/v1/system/users/{_db_user(member).id}/password-reset"
    assert client.post(url, headers=auth_headers(admin_token)).status_code == 204
    assert client.post(url, headers=auth_headers(admin_token)).status_code == 429
    assert mail.call_count == 1


def test_a_send_failure_reports_it_and_leaves_no_link(client, admin_token, member):
    url = f"/api/v1/system/users/{_db_user(member).id}/password-reset"
    with patch.object(credential_reset, "send_email", new=Mock(side_effect=RuntimeError("550 secret@address"))):
        resp = client.post(url, headers=auth_headers(admin_token))
    assert resp.status_code == 502 and "secret@address" not in resp.text
    db = SessionLocal()
    try:
        assert db.query(CredentialResetToken).count() == 0
        assert db.query(AuditEvent).filter(AuditEvent.action == "password_reset_link_sent").count() == 0
    finally:
        db.close()


def test_disabled_email_delivery_is_reported_not_swallowed(client, admin_token, member):
    from app.services.email import EmailDeliveryDisabled

    url = f"/api/v1/system/users/{_db_user(member).id}/password-reset"
    with patch.object(credential_reset, "send_email", new=Mock(side_effect=EmailDeliveryDisabled("off"))):
        resp = client.post(url, headers=auth_headers(admin_token))
    assert resp.status_code == 409


# --- forced reset ---------------------------------------------------------------------------------------


def _force(client, admin_token, **body):
    payload = {"scope": "all", "reset_2fa": False, "send_links": False, **body}
    return client.post("/api/v1/system/credentials/force-reset", json=payload, headers=auth_headers(admin_token))


def test_force_reset_ends_sessions_revokes_tokens_and_blocks_native_sign_in(client, admin_token, org_id, member, mail):
    member_token = login(client, member, "OldPassword123!")
    pat = client.post(
        "/api/v1/me/pats", json={"name": "ci", "allowed_organization_ids": [org_id]}, headers=auth_headers(member_token)
    )
    assert pat.status_code == 201

    resp = _force(client, admin_token, scope="user", user_id=str(_db_user(member).id))

    assert resp.status_code == 200
    assert resp.json()["marked"] == 1 and resp.json()["tokens_revoked"] == 1
    assert client.get("/api/v1/auth/me", headers=auth_headers(member_token)).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {pat.json()['token']}"}).status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"email": member, "password": "OldPassword123!"})
    assert blocked.status_code == 403 and "must be reset" in blocked.json()["detail"]
    wrong = client.post("/api/v1/auth/login", json={"email": member, "password": "not-the-password"})
    assert wrong.status_code == 401 and "must be reset" not in wrong.text
    assert login(client, "admin@example.com", "ChangeMe123!")


def test_force_reset_link_restores_access(client, admin_token, member, mail):
    _force(client, admin_token, scope="user", user_id=str(_db_user(member).id), send_links=True)
    raw = _token_from(mail)
    assert "security reasons" in mail.call_args.args[2]

    assert _reset(client, raw).status_code == 204

    assert login(client, member, NEW_PASSWORD)
    assert _db_user(member).must_reset_credentials is False


def test_force_reset_spends_links_issued_before_it(client, admin_token, member, mail):
    _forgot(client, member)
    before = _token_from(mail)
    _force(client, admin_token, scope="user", user_id=str(_db_user(member).id))
    assert _reset(client, before).status_code == 400


def test_force_reset_all_includes_the_caller_and_lists_sso_accounts(client, admin_token, org_id, member, mail):
    create_org_user(client, admin_token, org_id, "sso@example.com")
    _mutate_user("sso@example.com", auth_backend="oidc", password_hash=None)

    resp = _force(client, admin_token)

    body = resp.json()
    assert body["accounts"] == body["sessions_ended"] == 3
    assert body["marked"] == 2 and body["without_local_credential"] == 1
    assert client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).status_code == 401
    assert "sso@example.com" not in resp.text


def test_force_reset_by_organisation_leaves_other_organisations_alone(client, admin_token, org_id, member, mail):
    other_org, _ = create_org_admin_in(client, admin_token, "Another Org")
    resp = _force(client, admin_token, scope="organization", organization_id=other_org["id"])
    assert resp.json()["accounts"] == 1
    assert _db_user(member).must_reset_credentials is False


def test_force_reset_can_clear_two_factor(client, admin_token, member, mail):
    token = login(client, member, "OldPassword123!")
    enroll = client.post("/api/v1/auth/2fa/enroll", headers=auth_headers(token)).json()
    client.post(
        "/api/v1/auth/2fa/status", json={"action": "confirm", "code": pyotp.TOTP(enroll["secret"]).now()}, headers=auth_headers(token)
    )

    kept = _force(client, admin_token, scope="user", user_id=str(_db_user(member).id)).json()
    assert kept["two_factor_cleared"] == 0 and _db_user(member).is_2fa_enabled is True

    cleared = _force(client, admin_token, scope="user", user_id=str(_db_user(member).id), reset_2fa=True).json()
    after = _db_user(member)
    assert cleared["two_factor_cleared"] == 1 and after.is_2fa_enabled is False and after.totp_secret is None


def test_a_two_factor_challenge_issued_before_a_forced_reset_is_dead(client, admin_token, member, mail):
    token = login(client, member, "OldPassword123!")
    enroll = client.post("/api/v1/auth/2fa/enroll", headers=auth_headers(token)).json()
    secret = enroll["secret"]
    client.post("/api/v1/auth/2fa/status", json={"action": "confirm", "code": pyotp.TOTP(secret).now()}, headers=auth_headers(token))
    challenge = client.post("/api/v1/auth/login", json={"email": member, "password": "OldPassword123!"}).json()["challenge_token"]

    _force(client, admin_token, scope="user", user_id=str(_db_user(member).id))

    resp = client.post("/api/v1/auth/2fa/verify", json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()})
    assert resp.status_code == 401


def test_force_reset_is_server_admin_only_and_validates_its_target(client, admin_token, org_id, member, mail):
    create_org_user(client, admin_token, org_id, "oa@example.com", role="org_admin")
    oa = login(client, "oa@example.com", "Password123!")
    assert _force(client, oa).status_code == 403
    assert _force(client, admin_token, scope="organization").status_code == 400
    assert _force(client, admin_token, scope="organization", organization_id=str(uuid.uuid4())).status_code == 404
    assert _force(client, admin_token, scope="user", user_id=str(uuid.uuid4())).status_code == 404


def test_force_reset_audit_event_holds_counts_and_no_secret(client, admin_token, member, mail):
    _force(client, admin_token, scope="user", user_id=str(_db_user(member).id), send_links=True)
    raw = _token_from(mail)
    db = SessionLocal()
    try:
        events = db.query(AuditEvent).filter(AuditEvent.action == "credentials_force_reset").all()
        assert len(events) == 1
        detail = events[0].detail
        assert detail["scope"] == "user" and detail["accounts"] == 1 and detail["actor"].startswith("user:")
        assert member not in str(detail) and raw not in str(detail)
        assert raw not in " ".join(str(e.detail) for e in db.query(AuditEvent).all())
    finally:
        db.close()


# --- command line ---------------------------------------------------------------------------------------


def _cli(*args) -> int:
    return cli.main(list(args))


def test_cli_issues_a_working_link_when_every_administrator_is_locked_out(client, admin_token, capsys):
    _force(client, admin_token, scope="server_admins")
    assert client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "ChangeMe123!"}).status_code == 403
    capsys.readouterr()

    assert _cli("issue-link", "--server-admins") == 0

    out = capsys.readouterr()
    email, url = out.out.strip().split("\t")
    assert email == "admin@example.com"
    raw = _TOKEN.search(url).group(1)
    assert raw not in out.err
    assert _reset(client, raw, "RecoveredAdmin1!").status_code == 204
    assert login(client, "admin@example.com", "RecoveredAdmin1!")


def test_cli_issue_link_audits_the_actor_but_not_the_link(client, capsys):
    assert _cli("issue-link", "--user", "ADMIN@example.com", "--ttl-minutes", "5") == 0
    raw = _TOKEN.search(capsys.readouterr().out).group(1)
    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(AuditEvent.action == "password_reset_link_issued").one()
        assert event.detail["actor"].startswith("cli:") and event.actor_id is None
        assert event.detail["expires_minutes"] == 5
        assert raw not in str(event.detail)
        row = db.query(CredentialResetToken).one()
        assert row.issued_via == "cli" and row.expires_at - row.created_at <= timedelta(minutes=5, seconds=2)
    finally:
        db.close()


def test_cli_force_reset_shows_the_scope_and_changes_nothing_without_yes(client, member, capsys):
    assert _cli("force-reset", "--all") == 0
    assert "Nothing changed" in capsys.readouterr().err
    assert _db_user(member).must_reset_credentials is False
    assert _db_user(member).token_version == 0


def test_cli_force_reset_applies_by_organisation_code(client, admin_token, org_id, member, capsys):
    code = client.get(f"/api/v1/orgs/{org_id}", headers=auth_headers(admin_token)).json()["code"]
    create_org_user(client, admin_token, org_id, "sso@example.com")
    _mutate_user("sso@example.com", auth_backend="oidc", password_hash=None)

    assert _cli("force-reset", "--org", code, "--yes", "--reset-2fa") == 0

    err = capsys.readouterr().err
    assert "no local password" in err and "sso@example.com" in err
    after = _db_user(member)
    assert after.must_reset_credentials is True and after.token_version == 1
    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(AuditEvent.action == "credentials_force_reset").one()
        assert event.detail["actor"].startswith("cli:") and event.detail["scope"] == "organization"
    finally:
        db.close()


def test_cli_rejects_bad_input(client, capsys):
    assert _cli("issue-link", "--user", "nobody@example.com") == 1
    assert _cli("force-reset", "--org", "NOSUCHORG", "--yes") == 1
    assert _cli("issue-link", "--all", "--ttl-minutes", "100000") == 2
    with pytest.raises(SystemExit):
        _cli("force-reset")


def test_cli_issue_link_skips_accounts_with_no_password_and_says_so(client, admin_token, org_id, capsys):
    create_org_user(client, admin_token, org_id, "sso@example.com")
    _mutate_user("sso@example.com", auth_backend="oidc", password_hash=None)
    assert _cli("issue-link", "--user", "sso@example.com") == 1
    assert "sso@example.com" in capsys.readouterr().err


def test_a_password_change_by_the_person_still_bumps_the_epoch_and_is_unaffected(client, member):
    token = login(client, member, "OldPassword123!")
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "OldPassword123!", "new_password": NEW_PASSWORD},
        headers=auth_headers(token),
    )
    assert resp.status_code == 204
    assert _db_user(member).token_version == 1
    assert db_token_rows() == 0


def db_token_rows() -> int:
    db = SessionLocal()
    try:
        return db.query(CredentialResetToken).count() + db.query(PersonalAccessToken).count()
    finally:
        db.close()


def test_spent_and_long_expired_tokens_are_purged_but_live_and_recent_ones_stay(client, member):
    now = datetime.now(UTC)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == member).one()
        rows = {
            "live": dict(expires_at=now + timedelta(minutes=30)),
            "used_recently": dict(expires_at=now + timedelta(minutes=30), used_at=now - timedelta(days=1)),
            "used_long_ago": dict(expires_at=now - timedelta(days=9), used_at=now - timedelta(days=8)),
            "expired_long_ago": dict(expires_at=now - timedelta(days=8)),
            "expired_recently": dict(expires_at=now - timedelta(days=1)),
        }
        for name, values in rows.items():
            db.add(CredentialResetToken(user_id=user.id, token_hash=hash_pat(name), issued_via="forgot", **values))
        db.commit()

        assert credential_reset.purge_spent_tokens(db) == 2

        kept = {t.token_hash for t in db.query(CredentialResetToken).all()}
        assert kept == {hash_pat(n) for n in ("live", "used_recently", "expired_recently")}
    finally:
        db.close()
