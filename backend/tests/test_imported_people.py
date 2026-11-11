"""Imported people: stand-ins for people a bundle names who are not members of the importing organisation.

Covers creation and reuse, the refusals every deactivated account already gets, the importer's per-person choices, the
replayed history's marking, the People preview and the retention policy.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.organization import Organization, UserOrgRole
from app.models.user import User
from app.services import imported_people as ip
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, login
from tests.test_project_export_import import _build_rich_project


def _bundle(client, token, org_id) -> bytes:
    project, _, _ = _build_rich_project(client, token, org_id)
    return client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token)).content


def _import(client, token, org_id, bundle, *, people: dict | None = None, name="Imported"):
    data = {"organization_id": org_id, "name": name}
    if people is not None:
        data["people"] = json.dumps(people)
    return client.post(
        "/api/v1/projects/import", data=data, files={"file": ("bundle.zip", bundle, "application/zip")},
        headers=auth_headers(token),
    )


def _preview(client, token, org_id, bundle, people: dict | None = None):
    data = {"organization_id": org_id}
    if people is not None:
        data["people"] = json.dumps(people)
    return client.post(
        "/api/v1/projects/import/preview", data=data, files={"file": ("bundle.zip", bundle, "application/zip")},
        headers=auth_headers(token),
    )


def _stand_ins(org_id) -> list[User]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(User).where(User.imported_organization_id == org_id)))
    finally:
        db.close()


def _me(client, token) -> str:
    return client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]


def test_the_bundle_carries_the_display_names_of_the_people_it_names(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        people = json.loads(zf.read("project.json"))["people"]
    assert {"email": "admin@example.com", "display_name": people[0]["display_name"]} in people
    assert all(p["email"] == p["email"].lower() for p in people)


def test_an_unmatched_person_becomes_one_stand_in_reused_by_a_second_import_and_not_shared_across_organisations(
    client, admin_token, org_id,
):
    bundle = _bundle(client, admin_token, org_id)
    org_a, admin_a = create_org_admin_in(client, admin_token, "Stand-in A")
    org_b, admin_b = create_org_admin_in(client, admin_token, "Stand-in B")

    assert _import(client, admin_a, org_a["id"], bundle, name="First").status_code == 201
    first = {u.id for u in _stand_ins(org_a["id"])}
    assert first
    assert _import(client, admin_a, org_a["id"], bundle, name="Second").status_code == 201
    assert {u.id for u in _stand_ins(org_a["id"])} == first

    assert _import(client, admin_b, org_b["id"], bundle).status_code == 201
    in_b = {u.id for u in _stand_ins(org_b["id"])}
    assert in_b and not (in_b & first)


def test_a_stand_in_holds_no_address_credential_or_role_and_cannot_sign_in_or_be_granted_anything(
    client, admin_token, org_id,
):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Refusals")
    assert _import(client, admin, org["id"], bundle).status_code == 201
    stand_in = next(u for u in _stand_ins(org["id"]) if u.display_name)

    assert stand_in.email.endswith("@imported.example.com") and "admin@example.com" not in stand_in.email
    assert stand_in.password_hash is None and not stand_in.is_active and stand_in.is_archived
    assert stand_in.auth_backend == ip.IMPORTED_BACKEND
    db = SessionLocal()
    try:
        assert db.scalar(select(UserOrgRole).where(UserOrgRole.user_id == stand_in.id)) is None
    finally:
        db.close()

    # Sign-in, role grant and the server administrator's reactivation are all refused.
    assert client.post("/api/v1/auth/login", json={"email": stand_in.email, "password": "Password123!"}).status_code in (401, 403)
    granted = client.post(
        f"/api/v1/orgs/{org['id']}/users/{stand_in.id}/roles", json={"user_id": str(stand_in.id), "role": "member"},
        headers=auth_headers(admin),
    )
    assert granted.status_code in (403, 409)
    reactivated = client.post(
        f"/api/v1/system/users/{stand_in.id}/action", json={"action": "reactivate"}, headers=auth_headers(admin_token),
    )
    assert reactivated.status_code in (404, 405, 409)

    members = client.get(f"/api/v1/orgs/{org['id']}/users", headers=auth_headers(admin)).json()
    assert str(stand_in.id) not in {m["id"] if "id" in m else m.get("user_id") for m in members}


def test_replayed_history_names_the_imported_person_with_the_importer_and_time_in_the_detail(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Replay")
    project_id = _import(client, admin, org["id"], bundle).json()["project"]["id"]

    db = SessionLocal()
    try:
        events = [
            e for e in db.scalars(select(AuditEvent).where(AuditEvent.project_id == project_id))
            if isinstance(e.detail, dict) and "imported_from_bundle" in e.detail
        ]
        assert events
        for e in events:
            actor = db.get(User, e.actor_id)
            assert actor is not None and actor.imported_organization_id is not None
            origin = e.detail["imported_from_bundle"]
            assert origin["imported_by"] == _me(client, admin) and origin["imported_at"]
            assert origin["original_actor_name"] and "original_actor_email" not in origin
    finally:
        db.close()


def test_the_original_email_is_kept_in_the_history_detail_only_when_the_importer_chooses(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Keep email")
    project_id = _import(client, admin, org["id"], bundle, people={"keep_original_email": True}).json()["project"]["id"]

    db = SessionLocal()
    try:
        emails = {
            e.detail["imported_from_bundle"].get("original_actor_email")
            for e in db.scalars(select(AuditEvent).where(AuditEvent.project_id == project_id))
            if isinstance(e.detail, dict) and "imported_from_bundle" in e.detail
        }
        assert "admin@example.com" in emails
    finally:
        db.close()


def _rename_person(bundle: bytes, old: str, new: str) -> bytes:
    """The bundle with one person's address replaced throughout, as if a colleague had done the work."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "project.json":
                data = data.replace(old.encode(), new.encode())
            target.writestr(item, data)
    return out.getvalue()


def test_a_member_is_never_named_as_the_actor_of_a_replayed_entry(client, admin_token, org_id):
    bundle = _rename_person(_bundle(client, admin_token, org_id), "admin@example.com", "colleague@example.com")
    org, admin = create_org_admin_in(client, admin_token, "Member actor")
    colleague = create_org_user(client, admin, org["id"], "colleague@example.com", role="member")

    project_id = _import(client, admin, org["id"], bundle).json()["project"]["id"]

    db = SessionLocal()
    try:
        actors = {
            str(e.actor_id) for e in db.scalars(select(AuditEvent).where(AuditEvent.project_id == project_id))
            if isinstance(e.detail, dict) and "imported_from_bundle" in e.detail
        }
        assert colleague not in actors and actors == {_me(client, admin)}
    finally:
        db.close()
    rows = client.get(f"/api/v1/projects/{project_id}/requirements", headers=auth_headers(admin)).json()
    assert {r["creator_id"] for r in rows} == {colleague}  # authorship of a record still follows the matched member


def test_the_importer_can_map_a_person_to_themself_a_member_or_a_stand_in(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Mapping")
    member = create_org_user(client, admin, org["id"], "renamed@example.com", role="member")

    def creators(people):
        pid = _import(client, admin, org["id"], bundle, people=people, name=f"P{len(str(people))}").json()["project"]["id"]
        rows = client.get(f"/api/v1/projects/{pid}/requirements", headers=auth_headers(admin)).json()
        return {r["creator_id"] for r in rows}

    assert creators({"mapping": {"admin@example.com": "me"}}) == {_me(client, admin)}
    assert creators({"mapping": {"admin@example.com": member}}) == {member}
    forced = creators({"mapping": {"admin@example.com": "stand_in"}})
    assert forced and not (forced & {_me(client, admin), member})


def test_a_mapping_to_someone_outside_the_organisation_is_not_honoured(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Outside map")
    other_org, other_admin = create_org_admin_in(client, admin_token, "Outside owner")
    outsider = _me(client, other_admin)

    pid = _import(client, admin, org["id"], bundle, people={"mapping": {"admin@example.com": outsider}}).json()["project"]["id"]
    rows = client.get(f"/api/v1/projects/{pid}/requirements", headers=auth_headers(admin)).json()
    assert outsider not in {r["creator_id"] for r in rows}
    assert other_org["id"] != org["id"]


def test_the_preview_lists_each_person_and_how_they_resolve_without_writing_anything(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Preview")
    member = create_org_user(client, admin, org["id"], "renamed@example.com", role="member")

    people = _preview(client, admin, org["id"], bundle).json()["people"]
    by_email = {p["email"]: p for p in people}
    assert by_email["admin@example.com"]["resolution"] == "stand_in"
    assert not _stand_ins(org["id"])

    chosen = _preview(client, admin, org["id"], bundle, {"mapping": {"admin@example.com": member}}).json()["people"]
    row = next(p for p in chosen if p["email"] == "admin@example.com")
    assert row["resolution"] == "reassigned" and row["member_id"] == member


def test_only_an_organisation_admin_or_project_creator_may_preview(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Preview gate")
    create_org_user(client, admin, org["id"], "plain@example.com", role="member")
    token = login(client, "plain@example.com", "Password123!")

    assert _preview(client, token, org["id"], bundle).status_code == 403


def test_malformed_people_choices_are_rejected_not_defaulted(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Bad json")
    response = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "x", "people": "{not json"},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(admin),
    )
    assert response.status_code == 422


def test_unused_stand_ins_are_offered_only_when_the_organisation_sets_an_age_and_nothing_refers_to_them(client, admin_token, org_id):
    org, _ = create_org_admin_in(client, admin_token, "Retention")
    db = SessionLocal()
    try:
        organization = db.get(Organization, org["id"])
        assert organization is not None
        stand_in = ip.stand_in_for(db, organization.id, "former@elsewhere.example", "Former Staff")
        stand_in.created_at = datetime.now(UTC) - timedelta(days=400)
        db.flush()

        assert ip.unused_stand_ins(db, organization) == []  # no policy: never offered
        organization.imported_person_retention_days = 365
        assert [u.id for u in ip.unused_stand_ins(db, organization)] == [stand_in.id]
        organization.imported_person_retention_days = 500
        assert ip.unused_stand_ins(db, organization) == []  # not yet old enough
        db.rollback()
    finally:
        db.close()


def test_a_stand_in_that_a_record_refers_to_is_not_offered_and_anonymise_keeps_the_record(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Referenced")
    pid = _import(client, admin, org["id"], bundle).json()["project"]["id"]
    db = SessionLocal()
    try:
        organization = db.get(Organization, org["id"])
        assert organization is not None
        organization.imported_person_retention_days = 1
        for u in ip.unused_stand_ins(db, organization):
            raise AssertionError(f"{u.display_name} is referenced by the import and must not be offered")
        stand_in = db.scalars(select(User).where(User.imported_organization_id == organization.id)).first()
        assert stand_in is not None and ip.references(db, stand_in.id)
        ip.anonymise(db, stand_in)
        assert stand_in.display_name == "Former person"
        db.commit()
    finally:
        db.close()
    rows = client.get(f"/api/v1/projects/{pid}/requirements", headers=auth_headers(admin)).json()
    assert rows


def test_names_from_a_bundle_are_cleaned_and_derived_from_the_address_when_absent():
    assert ip.clean_name("  Alex\x00 Morgan ", "a@b.c") == "Alex Morgan"
    assert ip.clean_name(None, "alex.morgan@example.com") == "Alex Morgan"
    assert ip.clean_name(42, "") == "Imported person"
    assert len(ip.clean_name("x" * 900, "a@b.c")) == 200


def test_the_key_differs_per_organisation_and_ignores_case_and_spacing():
    a, b = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
    import uuid

    assert ip.person_key(uuid.UUID(a), " Alex@Example.com ") == ip.person_key(uuid.UUID(a), "alex@example.com")
    assert ip.person_key(uuid.UUID(a), "alex@example.com") != ip.person_key(uuid.UUID(b), "alex@example.com")


def test_addresses_are_found_by_key_shape_anywhere_in_the_bundle():
    data = {"a": {"owner": {"type": "user", "email": "One@x.io"}}, "b": [{"reviewed_by_email": "two@x.io"}], "c": {"note": "x@y.z"}}
    assert ip.bundle_emails(data) == {"one@x.io", "two@x.io"}


def _people(client, token, org_id):
    return client.get(f"/api/v1/orgs/{org_id}/imported-people", headers=auth_headers(token))


def test_the_organisation_admin_lists_anonymises_and_removes_imported_people(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "People page")
    _import(client, admin, org["id"], bundle)

    listed = _people(client, admin, org["id"]).json()
    assert listed["retention_days"] is None and listed["people"]
    first = listed["people"][0]
    assert first["in_use"] is True and first["due_for_removal"] is False

    # In use: removal is refused, anonymising keeps the records.
    refused = client.delete(f"/api/v1/orgs/{org['id']}/imported-people/{first['id']}", headers=auth_headers(admin))
    assert refused.status_code == 409
    done = client.post(f"/api/v1/orgs/{org['id']}/imported-people/{first['id']}/anonymise", headers=auth_headers(admin))
    assert done.status_code == 204
    assert {p["display_name"] for p in _people(client, admin, org["id"]).json()["people"]} >= {"Former person"}


def test_an_unreferenced_imported_person_is_offered_after_the_retention_age_and_can_be_removed(client, admin_token, org_id):
    org, admin = create_org_admin_in(client, admin_token, "Retention page")
    db = SessionLocal()
    try:
        stand_in = ip.stand_in_for(db, org["id"], "gone@elsewhere.example", "Gone Person")
        stand_in.created_at = datetime.now(UTC) - timedelta(days=30)
        db.commit()
        stand_in_id = str(stand_in.id)
    finally:
        db.close()

    assert _people(client, admin, org["id"]).json()["people"][0]["due_for_removal"] is False
    saved = client.put(f"/api/v1/orgs/{org['id']}/advanced-settings", json={"imported_person_retention_days": 7}, headers=auth_headers(admin))
    assert saved.status_code == 200, saved.text
    row = _people(client, admin, org["id"]).json()["people"][0]
    assert row["in_use"] is False and row["due_for_removal"] is True

    assert client.delete(f"/api/v1/orgs/{org['id']}/imported-people/{stand_in_id}", headers=auth_headers(admin)).status_code == 204
    assert _people(client, admin, org["id"]).json()["people"] == []


def test_a_member_or_another_organisations_imported_person_is_not_found_and_only_admins_may_manage(client, admin_token, org_id):
    bundle = _bundle(client, admin_token, org_id)
    org_a, admin_a = create_org_admin_in(client, admin_token, "Page A")
    org_b, admin_b = create_org_admin_in(client, admin_token, "Page B")
    _import(client, admin_a, org_a["id"], bundle)
    foreign = _people(client, admin_a, org_a["id"]).json()["people"][0]["id"]
    member = _me(client, admin_b)
    plain = create_org_user(client, admin_b, org_b["id"], "plain-page@example.com", role="member")
    plain_token = login(client, "plain-page@example.com", "Password123!")

    for target in (foreign, member):
        assert client.delete(f"/api/v1/orgs/{org_b['id']}/imported-people/{target}", headers=auth_headers(admin_b)).status_code == 404
        assert client.post(f"/api/v1/orgs/{org_b['id']}/imported-people/{target}/anonymise", headers=auth_headers(admin_b)).status_code == 404
    assert plain and _people(client, plain_token, org_b["id"]).status_code == 403


def test_a_principal_field_naming_an_imported_person_counts_as_in_use(client, admin_token, org_id):
    """An owner is stored as a type and id with no foreign key, so the usage check reads the declared principal fields."""
    bundle = _bundle(client, admin_token, org_id)
    org, admin = create_org_admin_in(client, admin_token, "Principal use")
    _import(client, admin, org["id"], bundle)
    db = SessionLocal()
    try:
        ids = [u.id for u in db.scalars(select(User).where(User.imported_organization_id == org["id"]))]
        assert ip.referenced_ids(db, ids) == set(ids)
    finally:
        db.close()


def test_the_application_imports_in_a_fresh_interpreter():
    """`app.main` loads without a circular import: the test session imports modules in another order and hides one."""
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
