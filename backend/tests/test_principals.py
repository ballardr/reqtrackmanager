"""
Module: tests.test_principals

Pins the shared principal mechanism (`services.principals`,
`models.principal`, `PrincipalReference`): validation, effective membership
(nested org groups, project groups, source projects), the "mine" filter,
labels, notification fan-out, deleting a group that still owns records (block,
reassign, clear, history rows), cross-organisation rejection and bundle
round-tripping.

No module adopts the mechanism yet, so the tests use their own table on a
private metadata (never in the app schema or its migrations) and register it
as a core `PrincipalReference` for the duration of each test.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.database import SessionLocal
from app.database import engine as app_engine
from app.models.audit import AuditEvent
from app.models.enums import PrincipalType
from app.models.principal import (
    principal_check_constraint,
    principal_id_column,
    principal_type_column,
)
from app.models.user import User
from app.modules.registry import PrincipalReference
from app.schemas.principal import PrincipalRef
from app.services import principals
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project


class _Base(DeclarativeBase):
    pass


class Thing(_Base):
    """A stand-in module record with a mandatory `owner` and an optional `reviewer`."""

    __tablename__ = "test_principal_things"
    __table_args__ = (principal_check_constraint("owner"), principal_check_constraint("reviewer", nullable=True))

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    is_current: Mapped[bool] = mapped_column(default=True)
    owner_type: Mapped[str] = principal_type_column()
    owner_id: Mapped[uuid.UUID] = principal_id_column()
    reviewer_type: Mapped[str | None] = principal_type_column(nullable=True)
    reviewer_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)


@pytest.fixture(autouse=True)
def _thing_table(monkeypatch):
    _Base.metadata.create_all(app_engine)
    monkeypatch.setattr(
        principals, "CORE_PRINCIPAL_REFERENCES",
        (
            PrincipalReference(model=Thing, field="owner", label="thing owners", audit_entity_type="test_thing",
                               mandatory=True, live_filter=lambda: Thing.is_current.is_(True)),
            PrincipalReference(model=Thing, field="reviewer", label="thing reviewers", audit_entity_type="test_thing",
                               live_filter=lambda: Thing.is_current.is_(True)),
        ),
    )
    yield
    _Base.metadata.drop_all(app_engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _user(client, admin_token, org_id, name) -> uuid.UUID:
    return uuid.UUID(create_org_user(client, admin_token, org_id, f"{name}@example.com"))


def _org_group(client, admin_token, org_id, name, members=(), nested=()) -> uuid.UUID:
    h = auth_headers(admin_token)
    gid = client.post(f"/api/v1/orgs/{org_id}/groups", json={"name": name}, headers=h).json()["id"]
    for user_id in members:
        assert client.post(f"/api/v1/orgs/{org_id}/groups/{gid}/members", json={"user_id": str(user_id)}, headers=h).status_code == 204
    for child in nested:
        assert client.post(f"/api/v1/orgs/{org_id}/groups/{gid}/members", json={"member_org_group_id": str(child)}, headers=h).status_code == 204
    return uuid.UUID(gid)


def _project_group(client, admin_token, project_id, name, **member) -> uuid.UUID:
    h = auth_headers(admin_token)
    gid = client.post(f"/api/v1/projects/{project_id}/groups", json={"name": name}, headers=h).json()["id"]
    for key, value in member.items():
        assert client.post(f"/api/v1/projects/{project_id}/groups/{gid}/members", json={key: str(value)}, headers=h).status_code == 204
    return uuid.UUID(gid)


def _ref(kind: PrincipalType, ident) -> PrincipalRef:
    return PrincipalRef(type=kind, id=ident)


def _thing(db, owner: PrincipalRef, reviewer: PrincipalRef | None = None, *, current=True) -> uuid.UUID:
    thing = Thing(
        owner_type=owner.type.value, owner_id=owner.id, is_current=current,
        reviewer_type=reviewer.type.value if reviewer else None, reviewer_id=reviewer.id if reviewer else None,
    )
    db.add(thing)
    db.commit()
    return thing.id


# --- Column shape -------------------------------------------------------------------------------


def test_check_constraints_reject_bad_type_and_half_set_optional(db):
    with pytest.raises(IntegrityError):
        db.add(Thing(owner_type="team", owner_id=uuid.uuid4()))
        db.commit()
    db.rollback()
    with pytest.raises(IntegrityError):
        db.add(Thing(owner_type="user", owner_id=uuid.uuid4(), reviewer_type="user", reviewer_id=None))
        db.commit()
    db.rollback()
    db.add(Thing(owner_type="org_group", owner_id=uuid.uuid4()))
    db.commit()


# --- Validation ---------------------------------------------------------------------------------


def test_validate_principal_branches(client, admin_token, org_id, db):
    from fastapi import HTTPException

    member = _user(client, admin_token, org_id, "member")
    group = _org_group(client, admin_token, org_id, "Team", [member])
    project = create_project(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id, "Other")
    pgroup = _project_group(client, admin_token, project["id"], "Project team", user_id=member)
    org = uuid.UUID(org_id)
    pid, other_pid = uuid.UUID(project["id"]), uuid.UUID(other_project["id"])

    principals.validate_principal(db, None, organization_id=org)
    principals.validate_principal(db, _ref(PrincipalType.USER, member), organization_id=org)
    principals.validate_principal(db, _ref(PrincipalType.ORG_GROUP, group), organization_id=org, project_id=pid)
    principals.validate_principal(db, _ref(PrincipalType.PROJECT_GROUP, pgroup), organization_id=org, project_id=pid)

    other_org, other_token = create_org_admin_in(client, admin_token, "Other Org")
    foreign_group = _org_group(client, other_token, other_org["id"], "Foreign")
    foreign_user = uuid.UUID(create_org_user(client, other_token, other_org["id"], "foreign@example.com"))

    for ref, project_id in [
        (_ref(PrincipalType.USER, uuid.uuid4()), None),
        (_ref(PrincipalType.USER, foreign_user), None),
        (_ref(PrincipalType.ORG_GROUP, uuid.uuid4()), None),
        (_ref(PrincipalType.ORG_GROUP, foreign_group), pid),
        (_ref(PrincipalType.PROJECT_GROUP, pgroup), None),
        (_ref(PrincipalType.PROJECT_GROUP, pgroup), other_pid),
        (_ref(PrincipalType.PROJECT_GROUP, uuid.uuid4()), pid),
    ]:
        with pytest.raises(HTTPException) as exc:
            principals.validate_principal(db, ref, organization_id=org, project_id=project_id)
        assert exc.value.status_code == 400


# --- Membership ---------------------------------------------------------------------------------


def test_org_group_membership_is_transitive_and_follows_removal(client, admin_token, org_id, db):
    alice, bob = _user(client, admin_token, org_id, "alice"), _user(client, admin_token, org_id, "bob")
    inner = _org_group(client, admin_token, org_id, "Inner", [alice])
    outer = _org_group(client, admin_token, org_id, "Outer", [bob], nested=[inner])
    ref = _ref(PrincipalType.ORG_GROUP, outer)
    assert principals.principal_member_ids(db, ref) == {alice, bob}
    assert principals.is_principal_member(db, ref, alice)
    assert not principals.is_principal_member(db, None, alice)

    r = client.delete(f"/api/v1/orgs/{org_id}/groups/{inner}/members/{alice}", headers=auth_headers(admin_token))
    assert r.status_code == 204
    db.expire_all()
    assert principals.principal_member_ids(db, ref) == {bob}
    assert principals.principal_member_ids(db, _ref(PrincipalType.USER, bob)) == {bob}


def test_project_group_membership_covers_users_org_groups_and_source_projects(client, admin_token, org_id, db):
    direct, via_org, via_source = (_user(client, admin_token, org_id, n) for n in ("direct", "viaorg", "viasource"))
    team = _org_group(client, admin_token, org_id, "Team", [via_org])
    project = create_project(client, admin_token, org_id)
    source = create_project(client, admin_token, org_id, "Source")
    h = auth_headers(admin_token)
    granted = client.post(
        f"/api/v1/projects/{source['id']}/roles", json={"user_id": str(via_source), "role": "member"}, headers=h
    )
    assert granted.status_code == 204, granted.text
    pgroup = _project_group(client, admin_token, project["id"], "PG", user_id=direct)
    for key, value in (("org_group_id", team), ("source_project_id", source["id"])):
        assert client.post(f"/api/v1/projects/{project['id']}/groups/{pgroup}/members", json={key: str(value)}, headers=h).status_code == 204

    members = principals.principal_member_ids(db, _ref(PrincipalType.PROJECT_GROUP, pgroup))
    assert {direct, via_org, via_source} <= members
    assert principals.project_group_ids_for_user(db, via_source, uuid.UUID(project["id"])) == {pgroup}
    assert principals.project_group_ids_for_user(db, via_org, uuid.UUID(project["id"])) == {pgroup}
    assert principals.project_group_ids_for_user(db, uuid.uuid4(), uuid.UUID(project["id"])) == set()


# --- The "mine" filter --------------------------------------------------------------------------


def test_filter_clause_matches_own_group_and_project_group_rows(client, admin_token, org_id, db):
    me, other = _user(client, admin_token, org_id, "me"), _user(client, admin_token, org_id, "other")
    inner = _org_group(client, admin_token, org_id, "Inner", [me])
    outer = _org_group(client, admin_token, org_id, "Outer", nested=[inner])
    elsewhere = _org_group(client, admin_token, org_id, "Elsewhere", [other])
    project = create_project(client, admin_token, org_id)
    pg_mine = _project_group(client, admin_token, project["id"], "Mine", user_id=me)
    pg_other = _project_group(client, admin_token, project["id"], "Theirs", user_id=other)

    mine = [
        _thing(db, _ref(PrincipalType.USER, me)),
        _thing(db, _ref(PrincipalType.ORG_GROUP, outer)),
        _thing(db, _ref(PrincipalType.PROJECT_GROUP, pg_mine)),
    ]
    _thing(db, _ref(PrincipalType.USER, other))
    _thing(db, _ref(PrincipalType.ORG_GROUP, elsewhere))
    _thing(db, _ref(PrincipalType.PROJECT_GROUP, pg_other))

    clause = principals.principal_filter_clause(
        db, me, Thing.owner_type, Thing.owner_id, project_id=uuid.UUID(project["id"])
    )
    assert set(db.scalars(select(Thing.id).where(clause))) == set(mine)
    org_scope = principals.principal_filter_clause(db, me, Thing.owner_type, Thing.owner_id)
    assert len(db.scalars(select(Thing.id).where(org_scope)).all()) == 2  # no project groups without a project


# --- Labels and recipients ----------------------------------------------------------------------


def test_labels_show_member_counts_and_placeholders_for_missing(client, admin_token, org_id, db):
    alice = _user(client, admin_token, org_id, "alice")
    group = _org_group(client, admin_token, org_id, "Platform", [alice])
    labels = principals.principal_labels(db, [
        _ref(PrincipalType.USER, alice), _ref(PrincipalType.ORG_GROUP, group),
        ("org_group", uuid.uuid4()), ("user", uuid.uuid4()), ("project_group", uuid.uuid4()), None,
    ])
    assert labels[("user", alice)].label == "alice"
    assert (labels[("org_group", group)].label, labels[("org_group", group)].member_count) == ("Platform", 1)
    missing = [v for v in labels.values() if not v.exists]
    assert {m.label for m in missing} == {principals.DELETED_GROUP_LABEL, principals.UNKNOWN_USER_LABEL}
    assert principals.principal_out(db, None, None) is None


def test_recipients_are_deduplicated_and_skip_actor_and_inactive(client, admin_token, org_id, db):
    actor, active, gone = (_user(client, admin_token, org_id, n) for n in ("actor", "active", "gone"))
    one = _org_group(client, admin_token, org_id, "One", [actor, active, gone])
    two = _org_group(client, admin_token, org_id, "Two", [active])
    db.get(User, gone).is_active = False
    db.commit()
    recipients = principals.principal_recipients(
        db, [_ref(PrincipalType.ORG_GROUP, one), _ref(PrincipalType.ORG_GROUP, two), None], exclude=[actor]
    )
    assert recipients == {active}


# --- Deleting a group that still owns records --------------------------------------------------


def test_org_group_delete_blocked_until_reassigned_and_audited(client, admin_token, org_id, db):
    h = auth_headers(admin_token)
    alice = _user(client, admin_token, org_id, "alice")
    doomed = _org_group(client, admin_token, org_id, "Doomed")
    successor = _org_group(client, admin_token, org_id, "Successor", [alice])
    g = _ref(PrincipalType.ORG_GROUP, doomed)
    owned = _thing(db, g, _ref(PrincipalType.USER, alice))
    reviewed = _thing(db, _ref(PrincipalType.USER, alice), g)
    history = _thing(db, g, current=False)

    usage = client.get(f"/api/v1/orgs/{org_id}/groups/{doomed}/usage", headers=h).json()
    assert usage == {
        "total": 2, "mandatory_total": 1,
        "items": [{"label": "thing owners", "count": 1, "mandatory": True},
                  {"label": "thing reviewers", "count": 1, "mandatory": False}],
    }

    blocked = client.delete(f"/api/v1/orgs/{org_id}/groups/{doomed}", headers=h)
    assert blocked.status_code == 409 and "replacement" in blocked.json()["detail"]
    still_blocked = client.delete(f"/api/v1/orgs/{org_id}/groups/{doomed}?clear_optional=true", headers=h)
    assert still_blocked.status_code == 409  # a mandatory owner needs a replacement
    half = client.delete(f"/api/v1/orgs/{org_id}/groups/{doomed}?replacement_type=org_group", headers=h)
    assert half.status_code == 400

    ok = client.delete(
        f"/api/v1/orgs/{org_id}/groups/{doomed}?replacement_type=org_group&replacement_id={successor}", headers=h
    )
    assert ok.status_code == 204, ok.text
    db.expire_all()
    assert (db.get(Thing, owned).owner_type, db.get(Thing, owned).owner_id) == ("org_group", successor)
    assert db.get(Thing, reviewed).reviewer_id == successor
    assert db.get(Thing, history).owner_id == doomed  # history row left alone, displays as a deleted group
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "principal_reassigned")).all()
    assert {e.entity_id for e in events} == {str(owned), str(reviewed)}
    assert {e.detail["field"] for e in events} == {"owner", "reviewer"}


def test_org_group_delete_can_clear_optional_fields_and_rejects_bad_replacements(client, admin_token, org_id, db):
    h = auth_headers(admin_token)
    alice = _user(client, admin_token, org_id, "alice")
    doomed = _org_group(client, admin_token, org_id, "Doomed")
    reviewed = _thing(db, _ref(PrincipalType.USER, alice), _ref(PrincipalType.ORG_GROUP, doomed))
    project = create_project(client, admin_token, org_id)
    pgroup = _project_group(client, admin_token, project["id"], "PG", user_id=alice)
    other_org, other_token = create_org_admin_in(client, admin_token, "Other Org")
    foreign = _org_group(client, other_token, other_org["id"], "Foreign")

    for kind, ident in [("org_group", doomed), ("project_group", pgroup), ("org_group", foreign), ("user", uuid.uuid4())]:
        r = client.delete(f"/api/v1/orgs/{org_id}/groups/{doomed}?replacement_type={kind}&replacement_id={ident}", headers=h)
        assert r.status_code == 400, (kind, r.text)

    ok = client.delete(f"/api/v1/orgs/{org_id}/groups/{doomed}?clear_optional=true", headers=h)
    assert ok.status_code == 204, ok.text
    db.expire_all()
    assert db.get(Thing, reviewed).reviewer_id is None and db.get(Thing, reviewed).reviewer_type is None
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "principal_cleared")).all()


def test_unused_group_deletes_without_a_replacement(client, admin_token, org_id):
    gid = _org_group(client, admin_token, org_id, "Spare")
    assert client.delete(f"/api/v1/orgs/{org_id}/groups/{gid}", headers=auth_headers(admin_token)).status_code == 204


def test_project_group_delete_blocked_then_reassigned_within_the_project(client, admin_token, org_id, db):
    h = auth_headers(admin_token)
    alice = _user(client, admin_token, org_id, "alice")
    project = create_project(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id, "Other")
    doomed = _project_group(client, admin_token, project["id"], "Doomed", user_id=alice)
    sibling = _project_group(client, admin_token, project["id"], "Sibling", user_id=alice)
    stranger = _project_group(client, admin_token, other_project["id"], "Stranger", user_id=alice)
    owned = _thing(db, _ref(PrincipalType.PROJECT_GROUP, doomed))

    base = f"/api/v1/projects/{project['id']}/groups/{doomed}"
    assert client.get(f"{base}/usage", headers=h).json()["mandatory_total"] == 1
    assert client.delete(base, headers=h).status_code == 409
    wrong_project = client.delete(f"{base}?replacement_type=project_group&replacement_id={stranger}", headers=h)
    assert wrong_project.status_code == 400
    ok = client.delete(f"{base}?replacement_type=project_group&replacement_id={sibling}", headers=h)
    assert ok.status_code == 204, ok.text
    db.expire_all()
    assert db.get(Thing, owned).owner_id == sibling


# --- Bundles ------------------------------------------------------------------------------------


def test_bundle_round_trip_and_fallback_to_importing_user(client, admin_token, org_id, db):
    alice = _user(client, admin_token, org_id, "alice")
    team = _org_group(client, admin_token, org_id, "Team")
    project = create_project(client, admin_token, org_id)
    pgroup = _project_group(client, admin_token, project["id"], "PG", user_id=alice)
    importer = _user(client, admin_token, org_id, "importer")
    org, pid = uuid.UUID(org_id), uuid.UUID(project["id"])

    for kind, ident in [("user", alice), ("org_group", team), ("project_group", pgroup)]:
        data = principals.principal_to_bundle(db, kind, ident)
        ref, warning = principals.principal_from_bundle(db, data, organization_id=org, project_id=pid, fallback_user_id=importer)
        assert (ref.type.value, ref.id, warning) == (kind, ident, None)

    assert principals.principal_to_bundle(db, None, None) is None
    assert principals.principal_to_bundle(db, "org_group", uuid.uuid4()) is None
    assert principals.principal_from_bundle(db, None, organization_id=org, project_id=pid, fallback_user_id=importer) == (None, None)
    for data in [
        {"type": "user", "email": "nobody@example.com"},
        {"type": "org_group", "name": "No such group"},
        {"type": "project_group", "name": "No such group"},
    ]:
        ref, warning = principals.principal_from_bundle(db, data, organization_id=org, project_id=pid, fallback_user_id=importer)
        assert (ref.type, ref.id) == (PrincipalType.USER, importer) and warning
    # A project group cannot resolve for an organisation-level import.
    ref, warning = principals.principal_from_bundle(
        db, {"type": "project_group", "name": "PG"}, organization_id=org, project_id=None, fallback_user_id=importer
    )
    assert ref.id == importer and warning

    # An optional field is left empty rather than invented as the importer's.
    for data in [{"type": "user", "email": "nobody@example.com"}, {"type": "org_group", "name": "No such group"}]:
        ref, warning = principals.principal_from_bundle(
            db, data, organization_id=org, project_id=pid, fallback_user_id=importer, required=False
        )
        assert ref is None and "left unset" in warning


def test_principal_columns_expand_a_ref_or_clear_the_field():
    ident = uuid.uuid4()
    assert principals.principal_columns("owner", PrincipalRef(type=PrincipalType.ORG_GROUP, id=ident)) == {
        "owner_type": "org_group", "owner_id": ident,
    }
    assert principals.principal_columns("owner", None) == {"owner_type": None, "owner_id": None}
