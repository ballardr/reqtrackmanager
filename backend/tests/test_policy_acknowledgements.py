"""Policy acknowledgement: a required policy is accepted per person and version, the record names the text by hash and holds
nothing else, a new version asks again, the audience gates who is asked, administrators see who has accepted (and
export it), and a person with an unaccepted policy can still read and sign out but cannot change data."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.notification import Notification
from app.models.policy import PolicyAcknowledgement
from app.models.user import User
from app.services import policy_acknowledgements as acks
from tests.conftest import auth_headers, create_org_admin_in, create_org_group, create_org_user, login

MINE = "/api/v1/policies/mine"
SYSTEM = "/api/v1/system/policies"


def _doc(*paragraphs: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]} for text in paragraphs]}


@pytest.fixture
def world(client, admin_token):
    """An organisation with an administrator and three members, and a second organisation with its own administrator and member."""
    org, admin = create_org_admin_in(client, admin_token, "Ack Org")
    other, other_admin = create_org_admin_in(client, admin_token, "Other Ack Org")
    ids = {name: create_org_user(client, admin_token, org["id"], f"ack_{name}@example.com") for name in ("first", "second", "third")}
    outsider = create_org_user(client, admin_token, other["id"], "ack_outsider@example.com")
    return {
        "org": org["id"], "admin": admin, "other": other["id"], "other_admin": other_admin, "ids": ids, "outsider_id": outsider,
        "outsider": login(client, "ack_outsider@example.com", "Password123!"),
        **{name: login(client, f"ack_{name}@example.com", "Password123!") for name in ids},
    }


def _base(org: str) -> str:
    return f"/api/v1/orgs/{org}/policies"


def _create(client, world, **fields) -> dict:
    payload = {"title": "Confidentiality agreement", "body": _doc("Keep it to yourself."), "requires_acknowledgement": True, **fields}
    resp = client.post(_base(world["org"]), json=payload, headers=auth_headers(world["admin"]))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _publish(client, world, policy_id: str, **fields) -> dict:
    resp = client.post(f"{_base(world['org'])}/{policy_id}/publish", json=fields, headers=auth_headers(world["admin"]))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _pending(client, token) -> list[dict]:
    resp = client.get(f"{MINE}/pending", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _accept(client, token, policy_id: str, version: int):
    return client.post(f"{MINE}/{policy_id}/acknowledge", json={"version": version}, headers=auth_headers(token))


def _write_probe(client, world, token=None, org=None):
    """A request that changes data: the organisation administrator creates a project."""
    return client.post(
        "/api/v1/projects", json={"organization_id": org or world["org"], "name": f"Probe {uuid.uuid4().hex[:6]}", "summary": ""},
        headers=auth_headers(token or world["admin"]),
    )


# --- who is asked ------------------------------------------------------------------------------------


def test_a_draft_or_a_policy_that_does_not_require_acceptance_asks_nobody(client, world):
    made = _create(client, world)
    assert _pending(client, world["first"]) == []
    plain = _create(client, world, title="Plain", requires_acknowledgement=False)
    _publish(client, world, plain["id"])
    assert _pending(client, world["first"]) == []
    _publish(client, world, made["id"])
    assert [p["title"] for p in _pending(client, world["first"])] == ["Confidentiality agreement"]


def test_everyone_in_the_organisation_is_asked_and_nobody_outside_it(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    for who in ("first", "second", "third", "admin"):
        assert [p["id"] for p in _pending(client, world[who])] == [made["id"]], who
    assert _pending(client, world["other_admin"]) == []
    assert _pending(client, world["outsider"]) == []
    assert client.get(f"{MINE}/pending").status_code == 401


def test_an_audience_limits_who_is_asked_including_by_group(client, world):
    group = create_org_group(client, world["admin"], world["org"], "Board", users=[world["ids"]["second"]])
    made = _create(client, world, audience=[
        {"type": "user", "id": world["ids"]["first"]}, {"type": "org_group", "id": group},
    ])
    _publish(client, world, made["id"])
    assert len(_pending(client, world["first"])) == 1
    assert len(_pending(client, world["second"])) == 1, "a group member is asked as a person"
    assert _pending(client, world["third"]) == []
    assert len(_pending(client, world["admin"])) == 1, "an organisation administrator reads every policy, so is asked"


# --- accepting ---------------------------------------------------------------------------------------


def test_accepting_records_version_hash_and_time_only_and_is_idempotent(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"], change_note="Initial")
    done = _accept(client, world["first"], made["id"], 1)
    assert done.status_code == 200, done.text
    assert set(done.json()) == {"policy_id", "version", "acknowledged_at"}
    assert _pending(client, world["first"]) == []
    assert len(_pending(client, world["second"])) == 1, "acceptance is personal"
    assert _accept(client, world["first"], made["id"], 1).status_code == 200
    with SessionLocal() as db:
        rows = list(db.scalars(select(PolicyAcknowledgement).where(PolicyAcknowledgement.policy_id == uuid.UUID(made["id"]))))
        assert len(rows) == 1
        row = rows[0]
        assert (row.version, str(row.user_id)) == (1, world["ids"]["first"])
        assert len(row.content_hash) == 64 and row.acknowledged_at.tzinfo is not None
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.entity_id == made["id"], AuditEvent.action == "acknowledged")))
        assert len(events) == 1 and "Keep it to yourself" not in str(events[0].detail)


def test_the_hash_names_the_exact_text(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    _accept(client, world["first"], made["id"], 1)
    client.put(
        f"{_base(world['org'])}/{made['id']}", json={"title": made["title"], "body": _doc("Different words.")}, headers=auth_headers(world["admin"]),
    )
    _publish(client, world, made["id"])
    _accept(client, world["first"], made["id"], 2)
    with SessionLocal() as db:
        hashes = {r.version: r.content_hash for r in db.scalars(select(PolicyAcknowledgement))}
    assert len(hashes) == 2 and hashes[1] != hashes[2]


def test_a_new_version_asks_again_and_an_old_version_cannot_be_accepted(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    _accept(client, world["first"], made["id"], 1)
    client.put(
        f"{_base(world['org'])}/{made['id']}", json={"title": made["title"], "body": _doc("Changed.")}, headers=auth_headers(world["admin"]),
    )
    assert _pending(client, world["first"]) == [], "an unpublished edit does not ask again"
    _publish(client, world, made["id"], change_note="Changed")
    waiting = _pending(client, world["first"])
    assert [p["version"] for p in waiting] == [2]
    assert _accept(client, world["first"], made["id"], 1).status_code == 409, "the text changed while it was open"
    assert _accept(client, world["first"], made["id"], 2).status_code == 200
    assert _pending(client, world["first"]) == []


def test_only_a_person_the_policy_applies_to_can_accept_it(client, world):
    made = _create(client, world, audience=[{"type": "user", "id": world["ids"]["first"]}])
    _publish(client, world, made["id"])
    assert _accept(client, world["third"], made["id"], 1).status_code == 404, "outside the audience"
    assert _accept(client, world["outsider"], made["id"], 1).status_code == 404, "another organisation"
    assert _accept(client, world["first"], str(uuid.uuid4()), 1).status_code == 404
    assert client.post(f"{MINE}/{made['id']}/acknowledge", json={"version": 1}).status_code == 401


def test_an_access_token_cannot_accept_on_a_persons_behalf(client, world):
    made = _create(client, world)
    created = client.post(
        "/api/v1/me/pats", json={"name": "headless", "allowed_organization_ids": [world["org"]]}, headers=auth_headers(world["first"]),
    )
    assert created.status_code == 201, created.text
    _publish(client, world, made["id"])
    assert _accept(client, created.json()["token"], made["id"], 1).status_code == 403
    assert len(_pending(client, world["first"])) == 1


# --- the block ---------------------------------------------------------------------------------------


def test_an_unaccepted_policy_blocks_changing_data_and_nothing_else(client, world):
    made = _create(client, world)
    assert _write_probe(client, world).status_code == 201, "nothing is required while the policy is a draft"
    _publish(client, world, made["id"])
    blocked = _write_probe(client, world)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "policy_acknowledgement_required"
    assert blocked.json()["detail"]["policy_ids"] == [made["id"]]
    admin = auth_headers(world["admin"])
    assert client.get("/api/v1/projects", headers=admin).status_code == 200, "reading stays open"
    assert client.post("/api/v1/search", json={"query": "x"}, headers=admin).status_code in (200, 422), "search is a read"
    assert client.get(f"{MINE}/{made['id']}", headers=admin).status_code == 200, "the policy stays readable"
    assert _accept(client, world["admin"], made["id"], 1).status_code == 200
    assert _write_probe(client, world).status_code == 201, "accepting lifts the block"


def test_the_block_follows_the_person_not_the_organisation(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    assert _write_probe(client, world, token=world["other_admin"], org=world["other"]).status_code == 201
    assert _write_probe(client, world).status_code == 403


def test_an_administrator_can_still_switch_the_requirement_off_while_blocked(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    assert _write_probe(client, world).status_code == 403
    off = client.put(
        f"{_base(world['org'])}/{made['id']}",
        json={"title": made["title"], "body": made["body"], "requires_acknowledgement": False}, headers=auth_headers(world["admin"]),
    )
    assert off.status_code == 200 and off.json()["requires_acknowledgement"] is False
    assert _write_probe(client, world).status_code == 201, "the requirement is live, so switching it off needs no publication"
    assert _pending(client, world["first"]) == []


def test_unpublishing_lifts_the_block_and_a_member_can_sign_out_while_blocked(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    assert client.post("/api/v1/auth/logout", headers=auth_headers(world["first"])).status_code != 403
    client.post(f"{_base(world['org'])}/{made['id']}/unpublish", headers=auth_headers(world["admin"]))
    assert _write_probe(client, world).status_code == 201


@pytest.mark.parametrize(("method", "path", "open_"), [
    ("GET", "/api/v1/projects", True), ("HEAD", "/api/v1/projects", True), ("POST", "/api/v1/search", True),
    ("POST", "/api/v1/auth/logout", True), ("POST", "/api/v1/policies/mine/x/acknowledge", True),
    ("PUT", "/api/v1/system/policies/x", True), ("PUT", "/api/v1/orgs/abc/policies/x", True), ("POST", "/api/v1/orgs/abc/files/search", True),
    ("POST", "/api/v1/projects/abc/files/search", True), ("POST", "/api/v1/projects", False), ("PUT", "/api/v1/orgs/abc/groups/x", False),
    ("DELETE", "/api/v1/orgs/abc/users/x", False), ("POST", "/api/v1/orgs/abc/policiesx", False),
])
def test_which_requests_stay_open(method, path, open_):
    assert acks.is_open_request(method, path) is open_


# --- the server's policies ---------------------------------------------------------------------------


def test_a_server_policy_can_require_everyone_and_an_organisation_administrator_cannot_set_it(client, world, admin_token):
    created = client.post(
        SYSTEM, json={"key": "privacy", "body": _doc("How we use data."), "requires_acknowledgement": True}, headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    server_id = created.json()["id"]
    refused = client.put(
        f"{SYSTEM}/{server_id}", json={"body": _doc("x"), "requires_acknowledgement": False}, headers=auth_headers(world["other_admin"]),
    )
    assert refused.status_code == 403
    assert _pending(client, world["first"]) == [], "a draft asks nobody"
    published = client.post(f"{SYSTEM}/{server_id}/publish", json={}, headers=auth_headers(admin_token))
    assert published.status_code == 200, published.text
    for who in ("first", "outsider", "other_admin"):
        waiting = _pending(client, world[who])
        assert [(p["id"], p["organization_id"]) for p in waiting] == [(server_id, None)], who
    assert _accept(client, world["outsider"], server_id, 1).status_code == 200
    assert _pending(client, world["outsider"]) == []
    assert len(_pending(client, world["first"])) == 1
    client.put(f"{SYSTEM}/{server_id}", json={"body": _doc("How we use data."), "requires_acknowledgement": False}, headers=auth_headers(admin_token))
    assert _pending(client, world["first"]) == []


# --- administrators ----------------------------------------------------------------------------------


def test_the_status_view_lists_who_has_and_has_not_accepted(client, world):
    group = create_org_group(client, world["admin"], world["org"], "Board", users=[world["ids"]["second"]])
    made = _create(client, world, audience=[{"type": "org_group", "id": group}, {"type": "user", "id": world["ids"]["first"]}])
    _publish(client, world, made["id"])
    _accept(client, world["first"], made["id"], 1)
    status = client.get(f"{_base(world['org'])}/{made['id']}/acknowledgements", headers=auth_headers(world["admin"]))
    assert status.status_code == 200, status.text
    body = status.json()
    assert (body["required"], body["accepted"], body["version"]) == (3, 1, 1)  # first, second (via the group) and the administrator
    by_email = {p["email"]: p for p in body["people"]}
    assert by_email["ack_first@example.com"]["current"] is True and by_email["ack_first@example.com"]["accepted_at"]
    assert by_email["ack_second@example.com"]["current"] is False and by_email["ack_second@example.com"]["accepted_version"] is None
    assert "ack_third@example.com" not in by_email
    assert [p["current"] for p in body["people"]] == sorted(p["current"] for p in body["people"]), "those yet to accept come first"


def test_the_status_is_for_the_organisations_administrators_only(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    for suffix, method in (("", "get"), ("/export", "get"), ("/remind", "post")):
        url = f"{_base(world['org'])}/{made['id']}/acknowledgements{suffix}"
        for token in (world["first"], world["other_admin"]):
            assert getattr(client, method)(url, headers=auth_headers(token)).status_code == 403, (suffix, "member or other organisation")
        assert getattr(client, method)(url).status_code == 401
    assert client.get(f"{_base(world['other'])}/{made['id']}/acknowledgements", headers=auth_headers(world["other_admin"])).status_code == 404


def test_the_export_is_a_csv_that_carries_no_policy_text_and_is_audited_by_count(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    _accept(client, world["first"], made["id"], 1)
    resp = client.get(f"{_base(world['org'])}/{made['id']}/acknowledgements/export", headers=auth_headers(world["admin"]))
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["cache-control"] == "no-store"
    lines = resp.text.strip().splitlines()
    assert lines[0] == "Name,Email,Status,Accepted version,Accepted at (UTC),Current version"
    assert len(lines) == 5  # header + first, second, third, administrator
    assert "Keep it to yourself" not in resp.text
    assert any(line.startswith("ack_first,ack_first@example.com,Accepted,1,") for line in lines)
    with SessionLocal() as db:
        event = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == made["id"], AuditEvent.action == "acknowledgements_exported")).one()
        assert event.detail == {"key": None, "version": 1, "row_count": 4}


def test_the_csv_neutralises_a_formula_in_a_name():
    row = acks.StatusRow(User(display_name='=HYPERLINK("x")', email="a@example.com"), None, None, False)
    assert "'=HYPERLINK" in acks.status_csv([row], 1)


def test_publishing_a_required_policy_asks_the_unaccepted_once_and_a_reminder_asks_again(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"], change_note="Please read")

    def count(user_id: str) -> int:
        with SessionLocal() as db:
            return len(db.scalars(select(Notification).where(
                Notification.user_id == uuid.UUID(user_id), Notification.type == "policy_acknowledgement_required",
            )).all())

    assert count(world["ids"]["first"]) == 1 and count(world["ids"]["third"]) == 1
    publisher = client.get("/api/v1/auth/me", headers=auth_headers(world["admin"])).json()["id"]
    assert count(publisher) == 0, "the publisher is not told of their own action"
    _accept(client, world["first"], made["id"], 1)
    reminded = client.post(f"{_base(world['org'])}/{made['id']}/acknowledgements/remind", headers=auth_headers(world["admin"]))
    assert reminded.status_code == 200 and reminded.json() == {"notified": 2}, "second and third; the administrator who asks is not told"
    assert count(world["ids"]["first"]) == 1, "someone who accepted is not reminded"
    assert count(world["ids"]["second"]) == 2
    with SessionLocal() as db:
        event = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == made["id"], AuditEvent.action == "acknowledgement_requested")).all()
        assert all("Please read" not in str(e.detail) for e in event)


def test_a_required_policy_sends_one_message_not_two_when_members_are_also_told(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"], notify_members=True)
    with SessionLocal() as db:
        kinds = [n.type for n in db.scalars(select(Notification).where(Notification.user_id == uuid.UUID(world["ids"]["first"])))]
    assert kinds.count("policy_acknowledgement_required") == 1 and "policy_published" not in kinds


def test_switching_the_requirement_on_for_a_published_policy_asks_people(client, world):
    plain = _create(client, world, requires_acknowledgement=False)
    _publish(client, world, plain["id"])
    assert _pending(client, world["first"]) == []
    on = client.put(
        f"{_base(world['org'])}/{plain['id']}",
        json={"title": plain["title"], "body": plain["body"], "requires_acknowledgement": True}, headers=auth_headers(world["admin"]),
    )
    assert on.status_code == 200
    assert len(_pending(client, world["first"])) == 1
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == plain["id"], AuditEvent.action == "acknowledgement_requirement_changed",
        )).all()
        assert [e.detail["requires_acknowledgement"] for e in events] == [True]


def test_a_replacement_that_leaves_the_setting_out_keeps_it(client, world):
    made = _create(client, world)
    kept = client.put(f"{_base(world['org'])}/{made['id']}", json={"title": "Renamed", "body": made["body"]}, headers=auth_headers(world["admin"]))
    assert kept.json()["requires_acknowledgement"] is True


def test_member_list_flags_which_policies_the_caller_must_accept(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    row = client.get(MINE, headers=auth_headers(world["first"])).json()[0]
    assert (row["requires_acknowledgement"], row["acknowledged"]) == (True, False)
    _accept(client, world["first"], made["id"], 1)
    row = client.get(MINE, headers=auth_headers(world["first"])).json()[0]
    assert (row["requires_acknowledgement"], row["acknowledged"]) == (True, True)


def test_acceptances_go_with_the_policy_and_the_person(client, world, admin_token):
    made = _create(client, world)
    _publish(client, world, made["id"])
    _accept(client, world["first"], made["id"], 1)
    assert client.delete(f"{_base(world['org'])}/{made['id']}", headers=auth_headers(world["admin"])).status_code == 204
    with SessionLocal() as db:
        assert db.scalars(select(PolicyAcknowledgement)).first() is None


# --- bundle ------------------------------------------------------------------------------------------


def test_the_requirement_travels_in_the_organisation_bundle_and_the_acceptances_do_not(client, world, admin_token):
    made = _create(client, world)
    _publish(client, world, made["id"])
    _accept(client, world["first"], made["id"], 1)
    exported = client.get(f"/api/v1/orgs/{world['org']}/export", headers=auth_headers(world["admin"]))
    assert exported.status_code == 200, exported.text
    imported = client.post(
        "/api/v1/orgs/import", data={"name": f"Ack Copy {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    copy = uuid.UUID(imported.json()["organization"]["id"])
    with SessionLocal() as db:
        from app.services import policies

        row = policies.list_scope(db, copy)[0]
        assert row.requires_acknowledgement is True and row.state.value == "draft", "arrives as a draft, so nobody is asked yet"
        assert db.scalars(select(PolicyAcknowledgement).where(PolicyAcknowledgement.policy_id == row.id)).first() is None


def test_utc_time_is_recorded(client, world):
    made = _create(client, world)
    _publish(client, world, made["id"])
    before = datetime.now(UTC)
    _accept(client, world["first"], made["id"], 1)
    with SessionLocal() as db:
        stamp = db.scalars(select(PolicyAcknowledgement)).one().acknowledged_at
    assert stamp.utcoffset() is not None and stamp >= before.replace(microsecond=0)
