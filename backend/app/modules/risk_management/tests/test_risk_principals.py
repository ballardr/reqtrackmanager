"""Tests for groups as Risk owners (users and groups on parity, Risk "5b" —
docs/plans/users-and-groups-parity-plan.md).

Covers: each principal kind on create/update/clear with the group's display
fields; the owner on every version so history shows who owned each one;
validation (a foreign organisation's group or user, another project's group, an
unknown id); the owner gate (a member of an owner group may assess a treatment
and record a review, a non-member or a removed member may not); the review
sweep and change-detection notifications reaching every group member, and the
Risk Managers fallback for a group with nobody to notify; deleting a group that
owns risks (usage counts only current versions, blocked, reassigned, cleared, the
audit event names the risk, older versions keep a deleted group); the register
report printing the owner with its kind; bundle export/import round trip and
fallbacks; and the migration backfilling existing rows to `user`.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date, timedelta

from sqlalchemy import select, text

from alembic import command
from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.modules.risk_management.alerts import REVIEW_OVERDUE_TYPE, TREATMENT_REASSESSMENT_TYPE, send_review_notifications
from app.modules.risk_management.models import RiskVersion
from app.modules.risk_management.tests._helpers import (
    assess,
    create_risk,
    grant_project_role,
    mitigate_with_requirement,
    project_base,
    setup,
    user_ref,
)
from app.modules.risk_management.tests.test_risk_export_import import _edit_bundle, _export, _import, _risks
from tests.conftest import (
    auth_headers,
    build_alembic_config,
    create_org_admin_in,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
    login,
)


def _url(project_id, risk_id) -> str:
    return f"{project_base(project_id)}/risks/{risk_id}"


def _put(client, token, project_id, risk_id, **body):
    return client.put(_url(project_id, risk_id), json=body, headers=auth_headers(token))


def _org_ref(group_id) -> dict:
    return {"type": "org_group", "id": group_id}


def _project_ref(group_id) -> dict:
    return {"type": "project_group", "id": group_id}


def _member(client, token, org, project, label: str) -> tuple[str, str]:
    """A project member (no module role) and their login token."""
    email = f"{label}-{uuid.uuid4().hex[:8]}@risk-principal.example.com"
    user_id = create_org_user(client, token, org["id"], email)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(token),
    )
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _days(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _notifications(client, token, kind: str) -> list[dict]:
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    return [r for r in rows if r["type"] == kind]


def _sweep() -> None:
    with SessionLocal() as db:
        send_review_notifications(db)


# --- Create, update, clear: each principal kind --------------------------------------------------------


def test_a_risk_takes_each_principal_kind_and_shows_a_group_by_name(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Kinds Co")
    member_id, _ = _member(client, token, org, project, "kinds")
    team = create_org_group(client, token, org["id"], "Platform Team", users=[member_id])
    squad = create_project_group(client, token, project["id"], "Squad", users=[member_id])
    h = auth_headers(token)

    unowned = create_risk(client, token, project["id"])
    assert unowned["owner"] is None
    by_org = create_risk(client, token, project["id"], owner=_org_ref(team))
    assert by_org["owner"] == {"type": "org_group", "id": team, "label": "Platform Team", "member_count": 1, "exists": True}
    by_project = create_risk(client, token, project["id"], owner=_project_ref(squad))
    assert by_project["owner"]["label"] == "Squad" and by_project["owner"]["type"] == "project_group"
    by_user = create_risk(client, token, project["id"], owner=user_ref(member_id))
    assert by_user["owner"]["type"] == "user" and by_user["owner"]["id"] == member_id

    listed = {r["id"]: r for r in client.get(project_base(project["id"]) + "/risks", headers=h).json()}
    assert listed[by_org["id"]]["owner"]["label"] == "Platform Team"
    assert listed[by_project["id"]]["owner"]["label"] == "Squad"
    assert listed[by_user["id"]]["owner"]["id"] == member_id and listed[unowned["id"]]["owner"] is None


def test_update_switches_and_clears_the_owner_and_each_version_keeps_its_own(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Update Co")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    team = create_org_group(client, token, org["id"], "Owners")
    risk = create_risk(client, token, project["id"], owner=user_ref(me))
    pid, rid = project["id"], risk["id"]

    to_group = _put(client, token, pid, rid, owner=_org_ref(team))
    assert to_group.status_code == 200 and to_group.json()["owner"]["label"] == "Owners"
    # A response is a valid request body (the display fields on the principal are ignored).
    again = _put(client, token, pid, rid, owner=to_group.json()["owner"], cause="Edited")
    assert again.status_code == 200 and again.json()["owner"]["id"] == team
    # Leaving the owner out carries it forward; an explicit null clears it.
    assert _put(client, token, pid, rid, cause="Edited again").json()["owner"]["id"] == team
    cleared = _put(client, token, pid, rid, owner=None)
    assert cleared.status_code == 200 and cleared.json()["owner"] is None

    versions = client.get(_url(pid, rid) + "/versions", headers=auth_headers(token)).json()
    assert [(v["owner"] or {}).get("type") for v in versions] == ["user", "org_group", "org_group", "org_group", None]
    assert versions[1]["owner"]["label"] == "Owners"


# --- Validation ----------------------------------------------------------------------------------------


def test_foreign_and_wrong_scope_principals_are_rejected(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Reject Co")
    other_project = create_project(client, token, org["id"], "Other Project")
    elsewhere = create_project_group(client, token, other_project["id"], "Elsewhere")
    other_org, other_token = create_org_admin_in(client, admin_token, "Risk Principal Foreign Co")
    foreign_group = create_org_group(client, other_token, other_org["id"], "Foreign Team")
    foreign_user = create_org_user(client, other_token, other_org["id"], "risk_foreign_owner@sp.example.com")
    risk = create_risk(client, token, project["id"])

    for bad in (
        _org_ref(foreign_group), user_ref(foreign_user), _project_ref(elsewhere), _org_ref(str(uuid.uuid4())),
    ):
        created = client.post(
            project_base(project["id"]) + "/risks", json={"title": "Bad owner", "owner": bad}, headers=auth_headers(token),
        )
        assert created.status_code == 400, bad
        assert _put(client, token, project["id"], risk["id"], owner=bad).status_code == 400, bad


# --- The owner gate ------------------------------------------------------------------------------------


def test_a_member_of_the_owner_group_may_assess_and_review_but_a_non_member_or_removed_member_may_not(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Gate Co")
    insider_id, insider_token = _member(client, token, org, project, "insider")
    _outsider_id, outsider_token = _member(client, token, org, project, "outsider")
    team = create_org_group(client, token, org["id"], "Risk Reviewers", users=[insider_id])
    risk = create_risk(client, token, project["id"], owner=_org_ref(team))
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk["id"])
    pid, rid = project["id"], risk["id"]

    def review(who):
        body = {"outcome": "confirmed", "notes": "Looks fine.", "next_review_date": _days(30)}
        return client.post(_url(pid, rid) + "/reviews", json=body, headers=auth_headers(who))

    assert assess(client, outsider_token, pid, rid, link_id).status_code == 403
    assert review(outsider_token).status_code == 403
    assert assess(client, insider_token, pid, rid, link_id).status_code == 200
    assert review(insider_token).status_code == 201
    # A group owner confers no manage right: the member still cannot edit the risk.
    assert _put(client, insider_token, pid, rid, cause="Nope").status_code == 403

    removed = client.delete(f"/api/v1/orgs/{org['id']}/groups/{team}/members/{insider_id}", headers=auth_headers(token))
    assert removed.status_code == 204, removed.text
    assert assess(client, insider_token, pid, rid, link_id).status_code == 403
    assert review(insider_token).status_code == 403


# --- Notifications -------------------------------------------------------------------------------------


def test_the_review_sweep_and_change_detection_notify_every_member_of_an_owner_group(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Notify Co")
    first_id, first_token = _member(client, token, org, project, "first")
    second_id, second_token = _member(client, token, org, project, "second")
    _bystander_id, bystander_token = _member(client, token, org, project, "bystander")
    team = create_org_group(client, token, org["id"], "Review Board", users=[first_id, second_id])
    risk = create_risk(client, token, project["id"], owner=_org_ref(team), review_date=_days(-2))

    _sweep()

    for member_token in (first_token, second_token):
        rows = _notifications(client, member_token, REVIEW_OVERDUE_TYPE)
        assert len(rows) == 1 and rows[0]["entity_id"] == risk["id"]
    assert _notifications(client, bystander_token, REVIEW_OVERDUE_TYPE) == []

    link_id, requirement_id = mitigate_with_requirement(client, token, org, project, risk["id"])
    assert assess(client, token, project["id"], risk["id"], link_id).status_code == 200
    current = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement_id}", headers=auth_headers(token)
    ).json()
    edited = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement_id}",
        json={
            "name": current["name"], "reasoning": current["reasoning"], "clarification": current["clarification"],
            "description": "Now says something different.", "component_id": current["component_id"],
            "category_id": current["category_id"], "owner": current["owner"],
        },
        headers=auth_headers(token),
    )
    assert edited.status_code == 200, edited.text
    for member_token in (first_token, second_token):
        assert len(_notifications(client, member_token, TREATMENT_REASSESSMENT_TYPE)) == 1


def test_an_owner_group_with_nobody_to_notify_falls_back_to_the_risk_managers(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Empty Group Co")
    manager_id, manager_token = _member(client, token, org, project, "manager")
    grant_project_role(client, token, project["id"], manager_id, "risk_manager")
    empty = create_org_group(client, token, org["id"], "Nobody Home")
    create_risk(client, token, project["id"], owner=_org_ref(empty), review_date=_days(-1))

    _sweep()

    assert len(_notifications(client, manager_token, REVIEW_OVERDUE_TYPE)) == 1


# --- Deleting a group that owns risks ------------------------------------------------------------------


def test_deleting_an_owner_group_counts_current_versions_blocks_reassigns_and_audits_the_risk(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Delete Co")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    team = create_org_group(client, token, org["id"], "Doomed Team")
    h = auth_headers(token)
    risk = create_risk(client, token, project["id"], owner=_org_ref(team))
    # Version 1 names the group, version 2 does not, version 3 names it again.
    _put(client, token, project["id"], risk["id"], owner=user_ref(me))
    _put(client, token, project["id"], risk["id"], owner=_org_ref(team))
    group_url = f"/api/v1/orgs/{org['id']}/groups/{team}"

    usage = client.get(f"{group_url}/usage", headers=h).json()
    assert [(i["label"], i["count"], i["mandatory"]) for i in usage["items"]] == [("risk owners", 1, False)]
    assert usage["total"] == 1 and usage["mandatory_total"] == 0, "older versions are not counted"

    assert client.delete(group_url, headers=h).status_code == 409
    done = client.delete(group_url, params={"replacement_type": "user", "replacement_id": me}, headers=h)
    assert done.status_code == 204, done.text

    assert client.get(_url(project["id"], risk["id"]), headers=h).json()["owner"]["id"] == me
    history = client.get(_url(project["id"], risk["id"]) + "/versions", headers=h).json()
    assert history[0]["owner"]["label"] == "Deleted group" and history[0]["owner"]["exists"] is False
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "principal_reassigned")).all()
        assert {str(e.entity_id) for e in events} == {risk["id"]}


def test_clear_optional_empties_the_owner_and_a_project_group_can_be_replaced(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Clear Co")
    h = auth_headers(token)
    team = create_org_group(client, token, org["id"], "Clear Team")
    risk = create_risk(client, token, project["id"], owner=_org_ref(team))
    resp = client.delete(f"/api/v1/orgs/{org['id']}/groups/{team}", params={"clear_optional": "true"}, headers=h)
    assert resp.status_code == 204, resp.text
    assert client.get(_url(project["id"], risk["id"]), headers=h).json()["owner"] is None

    squad = create_project_group(client, token, project["id"], "Doomed Squad")
    squad_risk = create_risk(client, token, project["id"], owner=_project_ref(squad))
    successor = create_org_group(client, token, org["id"], "Successor")
    url = f"/api/v1/projects/{project['id']}/groups/{squad}"
    assert client.delete(url, headers=h).status_code == 409
    done = client.delete(url, params={"replacement_type": "org_group", "replacement_id": successor}, headers=h)
    assert done.status_code == 204, done.text
    owner = client.get(_url(project["id"], squad_risk["id"]), headers=h).json()["owner"]
    assert owner["type"] == "org_group" and owner["id"] == successor


# --- Reports -------------------------------------------------------------------------------------------


def test_the_register_prints_the_owner_with_its_kind(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Report Co")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    team = create_org_group(client, token, org["id"], "Risk Board")
    create_risk(client, token, project["id"], title="By group", owner=_org_ref(team))
    create_risk(client, token, project["id"], title="By user", owner=user_ref(me))
    create_risk(client, token, project["id"], title="Nobody")

    resp = client.get(project_base(project["id"]) + "/reports/risk-register", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    register = next(s for s in resp.json()["sections"] if s["key"] == "register")
    owners = {row[1]: row[register["columns"].index("Owner")] for row in register["rows"]}
    assert owners["By group"] == "Risk Board (Org group)"
    assert owners["By user"] not in ("", "Risk Board (Org group)") and "(" not in owners["By user"]
    assert owners["Nobody"] == ""


# --- Bundles -------------------------------------------------------------------------------------------


def test_bundle_round_trip_keeps_each_owner_kind_and_drops_an_unmatched_group_with_a_warning(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Bundle Co")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    team = create_org_group(client, token, org["id"], "Bundle Team")
    squad = create_project_group(client, token, project["id"], "Bundle Squad")
    by_group = create_risk(client, token, project["id"], title="By group", owner=_org_ref(team))
    by_squad = create_risk(client, token, project["id"], title="By squad", owner=_project_ref(squad))
    by_user = create_risk(client, token, project["id"], title="By user", owner=user_ref(me))
    bundle = _export(client, token, project["id"])

    exported = json.loads(zipfile.ZipFile(io.BytesIO(bundle)).read("project.json"))
    owners = {r["title"]: r["owner"] for r in exported["risks"]}
    assert owners["By group"] == {"type": "org_group", "name": "Bundle Team"}
    assert owners["By squad"] == {"type": "project_group", "name": "Bundle Squad"}
    assert owners["By user"]["type"] == "user" and "@" in owners["By user"]["email"]

    imported = _import(client, token, org["id"], bundle, "Risk Principal Bundle Reimported")
    after = _risks(client, token, imported["project"]["id"])
    assert imported["warnings"] == []
    assert after[by_group["unique_code"]]["owner"]["id"] == team
    assert after[by_user["unique_code"]]["owner"]["id"] == me
    # A project group travels with the project, so the import names its own copy of the group.
    copied = after[by_squad["unique_code"]]["owner"]
    assert copied["type"] == "project_group" and copied["label"] == "Bundle Squad" and copied["id"] != squad

    def rename_groups(doc: dict) -> None:
        for entry in doc["risks"]:
            if entry["owner"] and entry["owner"]["type"] != "user":
                entry["owner"]["name"] = "Missing Group"

    unmatched = _import(client, token, org["id"], _edit_bundle(bundle, rename_groups), "Risk Principal Bundle Unmatched")
    left = _risks(client, token, unmatched["project"]["id"])
    assert left[by_group["unique_code"]]["owner"] is None and left[by_squad["unique_code"]]["owner"] is None
    assert left[by_user["unique_code"]]["owner"]["id"] == me
    assert sum("Missing Group" in w and "not found" in w for w in unmatched["warnings"]) == 2, unmatched["warnings"]


def test_a_bundle_written_before_groups_existed_still_imports_its_owner_by_email(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Principal Legacy Bundle Co")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    risk = create_risk(client, token, project["id"], owner=user_ref(me))
    bundle = _export(client, token, project["id"])

    def legacy(doc: dict) -> None:
        for entry in doc["risks"]:
            entry["owner_email"] = entry.pop("owner")["email"]

    imported = _import(client, token, org["id"], _edit_bundle(bundle, legacy), "Risk Principal Legacy Reimported")
    after = _risks(client, token, imported["project"]["id"])
    assert after[risk["unique_code"]]["owner"]["id"] == me and imported["warnings"] == []


# --- Migration backfill --------------------------------------------------------------------------------


def test_migration_backfills_existing_rows_to_user(client, admin_token):
    """Runs the real 0081 migration: a risk version written in the pre-migration shape (no `owner_type`
    column) ends up with `user` for its owner, and an unowned one stays unowned."""
    _org, project, token = setup(client, admin_token, "Risk Principal Migration Co")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    owned = create_risk(client, token, project["id"], owner=user_ref(me))
    unowned = create_risk(client, token, project["id"])
    with engine.begin() as conn:  # the backfill labels every owner a user, so leave no other test's group owner behind
        conn.execute(text("UPDATE risk_versions SET owner_id = NULL, owner_type = NULL WHERE owner_type <> 'user'"))
    command.downgrade(build_alembic_config(), "0080")
    try:
        with engine.begin() as conn:
            assert conn.execute(
                text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'risk_versions' AND column_name = 'owner_type'")
            ).scalar() == 0
    finally:
        command.upgrade(build_alembic_config(), "head")

    with SessionLocal() as db:
        versions = {
            str(v.risk_id): v for v in db.scalars(
                select(RiskVersion).where(RiskVersion.risk_id.in_([uuid.UUID(owned["id"]), uuid.UUID(unowned["id"])]))
            )
        }
        assert (versions[owned["id"]].owner_type, str(versions[owned["id"]].owner_id)) == ("user", me)
        assert versions[unowned["id"]].owner_type is None and versions[unowned["id"]].owner_id is None
    resp = client.get(_url(project["id"], owned["id"]), headers=auth_headers(token))
    assert resp.status_code == 200 and resp.json()["owner"]["id"] == me
