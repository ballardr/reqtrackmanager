"""Tests for the Risk Management module's Phase 4 reviews and reassessment
scheduling (docs/plans/module-03-risk-management-plan.md), through the real HTTP
endpoints and the module's own sweep and hook entry points.

Covers: recording a review (who may, snapshot of the ratings, the next review
date, validation, archived/closed refusal, the confirm-versus-stale rule), the
review history endpoints, the overdue flag and filter, the daily due/overdue
notification sweep (once per date, re-arming, recipients, exclusions), the
change-detection hook raised by a requirement edit or archive (verdict moved to
needs-reassessment, one notification, unaffected verdicts left alone), the
module-registered notification types in the preferences API, and the declared
MCP tools.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.registry import build_mcp_tool_manifest, get_all_notification_types
from app.modules.risk_management.alerts import (
    REVIEW_DUE_TYPE,
    REVIEW_OVERDUE_TYPE,
    TREATMENT_REASSESSMENT_TYPE,
    send_review_notifications,
)
from app.modules.risk_management.tests._helpers import (
    add_effective_treatment,
    add_member,
    assess,
    create_requirement,
    create_risk,
    generic_link,
    grant_project_role,
    levels,
    link_type_id,
    mitigate_with_requirement,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_project


def _url(project_id, risk_id) -> str:
    return f"{project_base(project_id)}/risks/{risk_id}"


def _tomorrow_plus(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _review(client, token, project_id, risk_id, *, outcome="confirmed", notes="Still valid.", next_review=None, **extra):
    body = {"outcome": outcome, "notes": notes, "next_review_date": next_review or _tomorrow_plus(30), **extra}
    return client.post(_url(project_id, risk_id) + "/reviews", json=body, headers=auth_headers(token))


def _put(client, token, project_id, risk_id, **body):
    resp = client.put(_url(project_id, risk_id), json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _risk(client, token, project_id, risk_id) -> dict:
    return client.get(_url(project_id, risk_id), headers=auth_headers(token)).json()


def _notifications(client, token, kind: str | None = None) -> list[dict]:
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    return [r for r in rows if kind is None or r["type"] == kind]


def _sweep() -> None:
    db = SessionLocal()
    try:
        send_review_notifications(db)
    finally:
        db.close()


def _owner(client, token, org, project, *, role: str | None = None) -> tuple[str, str]:
    """A project member (optionally holding a module role) and their login token."""
    user_id, user_token = add_member(client, token, org["id"], project["id"], f"rev-{uuid.uuid4().hex[:8]}@risk-rev.example.com")
    if role:
        grant_project_role(client, token, project["id"], user_id, role)
    return user_id, user_token


# --- Recording a review --------------------------------------------------------


def test_a_manager_records_a_review_that_snapshots_ratings_and_sets_the_next_date(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Record Co")
    risk = create_risk(client, token, project["id"], review_date=_tomorrow_plus(1))
    lv = levels(client, token, project["id"])
    _put(client, token, project["id"], risk["id"],
         inherent_likelihood_level_id=next(iter(lv["likelihood"].values())),
         inherent_consequence_level_id=next(iter(lv["consequence"].values())))
    add_effective_treatment(client, token, org, project, risk["id"])
    before = _risk(client, token, project["id"], risk["id"])

    resp = _review(client, token, project["id"], risk["id"], notes="  Checked with the supplier. ", next_review=_tomorrow_plus(45))

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["outcome"] == "confirmed" and body["notes"] == "Checked with the supplier."
    assert body["risk_status"] == "identified"
    assert body["risk_version_number"] == before["version_number"]
    assert body["inherent_rating_label"] == before["inherent_rating"]["label"]
    assert body["inherent_rating_score"] == before["inherent_rating"]["normalised"]
    assert body["residual_rating_label"] is None
    assert body["effective_treatment_count"] == 1
    assert body["scheduled_for"] == before["review_date"]
    assert body["next_review_date"] == _tomorrow_plus(45)
    after = _risk(client, token, project["id"], risk["id"])
    assert after["review_date"] == _tomorrow_plus(45)
    assert after["version_number"] == before["version_number"] + 1
    versions = client.get(_url(project["id"], risk["id"]) + "/versions", headers=auth_headers(token)).json()
    assert "Reviewed (Confirmed)" in versions[-1]["change_note"]


def test_a_review_can_clear_the_schedule_and_does_not_add_a_version_if_the_date_is_unchanged(client, admin_token):
    _org, project, token = setup(client, admin_token, "Risk Rev Schedule Co")
    risk = create_risk(client, token, project["id"], review_date=_tomorrow_plus(10))

    assert _review(client, token, project["id"], risk["id"], next_review=_tomorrow_plus(10)).status_code == 201
    assert _risk(client, token, project["id"], risk["id"])["version_number"] == 1

    resp = client.post(
        _url(project["id"], risk["id"]) + "/reviews",
        json={"outcome": "confirmed", "notes": "Retired concern.", "next_review_date": None}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["next_review_date"] is None
    assert _risk(client, token, project["id"], risk["id"])["review_date"] is None


def test_the_owner_may_review_but_a_plain_member_may_not(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Roles Co")
    owner_id, owner_token = _owner(client, token, org, project)
    _other_id, other_token = _owner(client, token, org, project)
    manager_id, manager_token = _owner(client, token, org, project, role="risk_manager")
    risk = create_risk(client, token, project["id"], owner_id=owner_id)

    assert _review(client, other_token, project["id"], risk["id"]).status_code == 403
    assert _review(client, owner_token, project["id"], risk["id"]).status_code == 201
    assert _review(client, manager_token, project["id"], risk["id"]).status_code == 201
    assert manager_id and owner_id


def test_review_validation(client, admin_token):
    _org, project, token = setup(client, admin_token, "Risk Rev Validation Co")
    risk = create_risk(client, token, project["id"])
    url = _url(project["id"], risk["id"]) + "/reviews"

    # The next date is required; a blank-after-trim note is refused; the date must be in the future.
    assert client.post(url, json={"outcome": "confirmed", "notes": "x"}, headers=auth_headers(token)).status_code == 422
    assert client.post(url, json={"outcome": "confirmed", "notes": "", "next_review_date": None}, headers=auth_headers(token)).status_code == 422
    assert _review(client, token, project["id"], risk["id"], notes="   ").status_code == 409
    assert _review(client, token, project["id"], risk["id"], next_review=date.today().isoformat()).status_code == 409
    assert _review(client, token, project["id"], risk["id"], next_review=_tomorrow_plus(-3)).status_code == 409
    assert client.get(url, headers=auth_headers(token)).json() == []


def test_archived_and_closed_risks_are_not_reviewed(client, admin_token):
    _org, project, token = setup(client, admin_token, "Risk Rev Terminal Co")
    closed = create_risk(client, token, project["id"])
    assert client.post(_url(project["id"], closed["id"]) + "/transition", json={"status": "rejected"},
                       headers=auth_headers(token)).status_code == 200
    assert client.post(_url(project["id"], closed["id"]) + "/transition", json={"status": "closed"},
                       headers=auth_headers(token)).status_code == 200
    archived = create_risk(client, token, project["id"])
    assert client.post(_url(project["id"], archived["id"]) + "/archive", headers=auth_headers(token)).status_code == 200

    assert _review(client, token, project["id"], closed["id"]).status_code == 409
    assert _review(client, token, project["id"], archived["id"]).status_code == 409


def test_a_review_cannot_confirm_a_risk_while_a_treatment_needs_reassessment(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Stale Co")
    risk = create_risk(client, token, project["id"])
    link_id, _req = mitigate_with_requirement(client, token, org, project, risk["id"])
    assert assess(client, token, project["id"], risk["id"], link_id).status_code == 200
    assert assess(client, token, project["id"], risk["id"], link_id, status="needs_reassessment", rationale="").status_code == 200

    blocked = _review(client, token, project["id"], risk["id"])
    assert blocked.status_code == 409
    assert "reassessment" in blocked.json()["detail"]
    assert _review(client, token, project["id"], risk["id"], outcome="reassessed", notes="Reworking it.").status_code == 201


# --- History -------------------------------------------------------------------


def test_review_history_is_listed_newest_first_and_scoped_to_the_risk(client, admin_token):
    _org, project, token = setup(client, admin_token, "Risk Rev History Co")
    risk = create_risk(client, token, project["id"])
    other = create_risk(client, token, project["id"])
    first = _review(client, token, project["id"], risk["id"], notes="First.").json()
    second = _review(client, token, project["id"], risk["id"], outcome="reassessed", notes="Second.").json()
    foreign = _review(client, token, project["id"], other["id"], notes="Other.").json()

    listed = client.get(_url(project["id"], risk["id"]) + "/reviews", headers=auth_headers(token)).json()
    assert [r["id"] for r in listed] == [second["id"], first["id"]]
    one = client.get(_url(project["id"], risk["id"]) + f"/reviews/{first['id']}", headers=auth_headers(token))
    assert one.status_code == 200 and one.json()["notes"] == "First."
    assert client.get(_url(project["id"], risk["id"]) + f"/reviews/{foreign['id']}", headers=auth_headers(token)).status_code == 404
    assert client.get(_url(project["id"], risk["id"]) + f"/reviews/{uuid.uuid4()}", headers=auth_headers(token)).status_code == 404


def test_reviews_are_audited_and_tenant_isolated(client, admin_token):
    _org, project, token = setup(client, admin_token, "Risk Rev Audit Co")
    _org2, project2, token2 = setup(client, admin_token, "Risk Rev Audit Other Co")
    risk = create_risk(client, token, project["id"])
    review = _review(client, token, project["id"], risk["id"]).json()

    db = SessionLocal()
    try:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == str(risk["id"]), AuditEvent.action == "reviewed")).all()
    finally:
        db.close()
    assert len(events) == 1 and events[0].detail["review_id"] == review["id"]
    # Another tenant's project cannot see or create reviews against this risk.
    assert client.get(_url(project2["id"], risk["id"]) + "/reviews", headers=auth_headers(token2)).status_code == 404
    assert _review(client, token2, project2["id"], risk["id"]).status_code == 404


# --- Overdue flag and filter -----------------------------------------------------


def test_overdue_flag_and_filter(client, admin_token):
    _org, project, token = setup(client, admin_token, "Risk Rev Overdue Co")
    overdue = create_risk(client, token, project["id"], review_date=_tomorrow_plus(-2))
    future = create_risk(client, token, project["id"], review_date=_tomorrow_plus(20))
    unscheduled = create_risk(client, token, project["id"])

    assert _risk(client, token, project["id"], overdue["id"])["is_review_overdue"] is True
    assert _risk(client, token, project["id"], future["id"])["is_review_overdue"] is False
    base = project_base(project["id"]) + "/risks"
    flagged = client.get(base, params={"review_overdue": True}, headers=auth_headers(token)).json()
    assert [r["id"] for r in flagged] == [overdue["id"]]
    rest = client.get(base, params={"review_overdue": False}, headers=auth_headers(token)).json()
    assert {r["id"] for r in rest} == {future["id"], unscheduled["id"]}


# --- Review notifications ----------------------------------------------------------


def test_the_sweep_notifies_the_owner_once_per_review_date_and_rearms_on_reschedule(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Sweep Co")
    owner_id, owner_token = _owner(client, token, org, project)
    due = create_risk(client, token, project["id"], owner_id=owner_id, review_date=_tomorrow_plus(3))
    overdue = create_risk(client, token, project["id"], owner_id=owner_id, review_date=_tomorrow_plus(-4))
    later = create_risk(client, token, project["id"], owner_id=owner_id, review_date=_tomorrow_plus(60))

    _sweep()
    _sweep()  # idempotent

    due_rows = _notifications(client, owner_token, REVIEW_DUE_TYPE)
    overdue_rows = _notifications(client, owner_token, REVIEW_OVERDUE_TYPE)
    assert [r["entity_id"] for r in due_rows] == [due["id"]]
    assert [r["entity_id"] for r in overdue_rows] == [overdue["id"]]
    assert due_rows[0]["entity_type"] == "risk" and str(project["id"]) == due_rows[0]["project_id"]
    assert due["unique_code"] in due_rows[0]["title"] and later["id"] not in {r["entity_id"] for r in _notifications(client, owner_token)}

    # A reviewed-and-rescheduled risk that falls due again is notified again.
    assert _review(client, token, project["id"], overdue["id"], next_review=_tomorrow_plus(2)).status_code == 201
    _sweep()
    assert len(_notifications(client, owner_token, REVIEW_DUE_TYPE)) == 2


def test_an_unowned_risk_notifies_risk_managers_and_project_managers(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Unowned Co")
    _manager_id, manager_token = _owner(client, token, org, project, role="risk_manager")
    _plain_id, plain_token = _owner(client, token, org, project)
    create_risk(client, token, project["id"], review_date=_tomorrow_plus(-1))

    _sweep()

    assert len(_notifications(client, manager_token, REVIEW_OVERDUE_TYPE)) == 1
    assert _notifications(client, plain_token, REVIEW_OVERDUE_TYPE) == []


def test_the_sweep_skips_closed_archived_and_module_disabled_risks(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Skip Co")
    owner_id, owner_token = _owner(client, token, org, project)
    closed = create_risk(client, token, project["id"], owner_id=owner_id, review_date=_tomorrow_plus(-1))
    for status in ("rejected", "closed"):
        assert client.post(_url(project["id"], closed["id"]) + "/transition", json={"status": status},
                           headers=auth_headers(token)).status_code == 200
    archived = create_risk(client, token, project["id"], owner_id=owner_id, review_date=_tomorrow_plus(-1))
    assert client.post(_url(project["id"], archived["id"]) + "/archive", headers=auth_headers(token)).status_code == 200

    _sweep()
    assert _notifications(client, owner_token, REVIEW_OVERDUE_TYPE) == []

    create_risk(client, token, project["id"], owner_id=owner_id, review_date=_tomorrow_plus(-1))
    off = client.put(f"/api/v1/orgs/{org['id']}/modules/risk_management", json={"enabled": False}, headers=auth_headers(token))
    assert off.status_code == 200, off.text
    _sweep()
    assert _notifications(client, owner_token, REVIEW_OVERDUE_TYPE) == []


# --- Change detection ---------------------------------------------------------------


def _edit_requirement(client, token, project_id, requirement_id, **changes):
    current = client.get(f"/api/v1/projects/{project_id}/requirements/{requirement_id}", headers=auth_headers(token)).json()
    body = {
        "name": current["name"], "reasoning": current["reasoning"], "clarification": current["clarification"],
        "description": current["description"], "component_id": current["component_id"],
        "category_id": current["category_id"], "owner_id": current["owner_id"], **changes,
    }
    resp = client.put(f"/api/v1/projects/{project_id}/requirements/{requirement_id}", json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _treatment_status(client, token, project_id, risk_id, link_id) -> dict:
    items = client.get(_url(project_id, risk_id) + "/treatments", headers=auth_headers(token)).json()["items"]
    return next(i for i in items if i["link_id"] == link_id)


def test_editing_a_mitigating_requirement_sends_the_verdict_back_and_notifies_once(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Detect Co")
    owner_id, owner_token = _owner(client, token, org, project)
    risk = create_risk(client, token, project["id"], owner_id=owner_id)
    link_id, requirement_id = mitigate_with_requirement(client, token, org, project, risk["id"])
    assert assess(client, token, project["id"], risk["id"], link_id).status_code == 200
    assert _risk(client, token, project["id"], risk["id"])["is_effectively_treated"] is True

    _edit_requirement(client, token, project["id"], requirement_id, description="Now says something different.")

    treatment = _treatment_status(client, token, project["id"], risk["id"], link_id)
    assert treatment["status"] == "needs_reassessment"
    assert "changed description" in treatment["reassessment_reason"]
    assert _risk(client, token, project["id"], risk["id"])["is_effectively_treated"] is False
    listing = client.get(_url(project["id"], risk["id"]) + "/treatments", headers=auth_headers(token)).json()
    assert listing["needs_reassessment_count"] == 1 and listing["effective_count"] == 0
    rows = _notifications(client, owner_token, TREATMENT_REASSESSMENT_TYPE)
    assert len(rows) == 1 and rows[0]["entity_id"] == risk["id"]

    # A second edit finds the verdict already sent back: no second notification.
    _edit_requirement(client, token, project["id"], requirement_id, description="And again.")
    assert len(_notifications(client, owner_token, TREATMENT_REASSESSMENT_TYPE)) == 1

    # Reassessing clears the reason and restores the count.
    assert assess(client, token, project["id"], risk["id"], link_id, rationale="Re-checked after the edit.").status_code == 200
    again = _treatment_status(client, token, project["id"], risk["id"], link_id)
    assert again["status"] == "effective" and again["reassessment_reason"] == ""


def test_only_effective_verdicts_are_sent_back(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Detect Scope Co")
    owner_id, owner_token = _owner(client, token, org, project)
    risk = create_risk(client, token, project["id"], owner_id=owner_id)
    proposed_link, proposed_req = mitigate_with_requirement(client, token, org, project, risk["id"])
    ineffective_link, ineffective_req = mitigate_with_requirement(client, token, org, project, risk["id"])
    assert assess(client, token, project["id"], risk["id"], ineffective_link, status="ineffective", rationale="No.").status_code == 200

    _edit_requirement(client, token, project["id"], proposed_req, name="Renamed proposal")
    _edit_requirement(client, token, project["id"], ineffective_req, name="Renamed rejection")

    assert _treatment_status(client, token, project["id"], risk["id"], proposed_link)["status"] == "proposed"
    assert _treatment_status(client, token, project["id"], risk["id"], ineffective_link)["status"] == "ineffective"
    assert _notifications(client, owner_token, TREATMENT_REASSESSMENT_TYPE) == []


def test_an_edit_that_does_not_change_what_the_requirement_says_is_ignored(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Detect Noop Co")
    owner_id, owner_token = _owner(client, token, org, project)
    risk = create_risk(client, token, project["id"], owner_id=owner_id)
    link_id, requirement_id = mitigate_with_requirement(client, token, org, project, risk["id"])
    assert assess(client, token, project["id"], risk["id"], link_id).status_code == 200

    _edit_requirement(client, token, project["id"], requirement_id, change_note="Only a note.")

    assert _treatment_status(client, token, project["id"], risk["id"], link_id)["status"] == "effective"
    assert _notifications(client, owner_token, TREATMENT_REASSESSMENT_TYPE) == []


def test_archiving_the_mitigating_requirement_sends_the_verdict_back(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Detect Archive Co")
    risk = create_risk(client, token, project["id"])
    link_id, requirement_id = mitigate_with_requirement(client, token, org, project, risk["id"])
    assert assess(client, token, project["id"], risk["id"], link_id).status_code == 200

    assert client.delete(f"/api/v1/projects/{project['id']}/requirements/{requirement_id}", headers=auth_headers(token)).status_code == 204

    treatment = _treatment_status(client, token, project["id"], risk["id"], link_id)
    assert treatment["status"] == "needs_reassessment" and "archived" in treatment["reassessment_reason"]


def test_change_detection_leaves_closed_risks_alone_and_audits_the_flag(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Detect Closed Co")
    live = create_risk(client, token, project["id"])
    closed = create_risk(client, token, project["id"])
    live_link, requirement_id = mitigate_with_requirement(client, token, org, project, live["id"])
    assert assess(client, token, project["id"], live["id"], live_link).status_code == 200
    # The same requirement also mitigates a risk that has since been closed out.
    resp = generic_link(
        client, token, project["id"], closed["id"], link_type_id(client, token, org["id"], "Mitigates"), "incoming",
        "requirement", requirement_id,
    )
    assert resp.status_code == 201, resp.text
    closed_link = resp.json()["id"]
    assert assess(client, token, project["id"], closed["id"], closed_link).status_code == 200
    for status in ("rejected", "closed"):
        assert client.post(_url(project["id"], closed["id"]) + "/transition", json={"status": status},
                           headers=auth_headers(token)).status_code == 200

    _edit_requirement(client, token, project["id"], requirement_id, description="Changed.")

    assert _treatment_status(client, token, project["id"], live["id"], live_link)["status"] == "needs_reassessment"
    assert _treatment_status(client, token, project["id"], closed["id"], closed_link)["status"] == "effective"
    db = SessionLocal()
    try:
        events = db.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == live["id"], AuditEvent.action == "treatment_needs_reassessment")).all()
    finally:
        db.close()
    assert len(events) == 1 and events[0].detail["change"] == "content_changed"
    assert events[0].detail["other_id"] == requirement_id and events[0].detail["link_id"] == live_link


def test_a_change_in_another_project_flags_the_verdict_but_the_notification_does_not_name_it(client, admin_token):
    org, parent, token = setup(client, admin_token, "Risk Rev Detect Cross Co")
    assert client.patch(f"/api/v1/projects/{parent['id']}", json={"can_be_parent": True}, headers=auth_headers(token)).status_code == 200
    child = create_project(client, token, org["id"], "Risk Rev Detect Cross Child", parent_project_id=parent["id"])
    owner_id, owner_token = _owner(client, token, org, child)
    risk = create_risk(client, token, child["id"], owner_id=owner_id)
    requirement_id = create_requirement(client, token, parent["id"], "Ancestor mitigation")
    resp = client.post(
        f"/api/v1/projects/{child['id']}/artefacts/risk/{risk['id']}/links",
        json={"link_type_id": link_type_id(client, token, org["id"], "Mitigates"), "direction": "incoming",
              "other_type": "requirement", "other_id": requirement_id, "other_project_id": parent["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    link_id = resp.json()["id"]
    assert assess(client, token, child["id"], risk["id"], link_id).status_code == 200

    _edit_requirement(client, token, parent["id"], requirement_id, description="Changed upstream.")

    assert _treatment_status(client, token, child["id"], risk["id"], link_id)["status"] == "needs_reassessment"
    rows = _notifications(client, owner_token, TREATMENT_REASSESSMENT_TYPE)
    assert len(rows) == 1 and rows[0]["project_id"] == child["id"]
    assert "another project" in rows[0]["body"] and "changed description" not in rows[0]["body"]


# --- Notification types and MCP ----------------------------------------------------


def test_module_notification_types_appear_in_preferences_and_can_be_set(client, admin_token):
    _org, _project, token = setup(client, admin_token, "Risk Rev Prefs Co")
    prefs = {p["type"]: p for p in client.get("/api/v1/notifications/preferences", headers=auth_headers(token)).json()}

    assert prefs[REVIEW_DUE_TYPE]["label"] == "Risk review due soon"
    assert prefs["project_joined"]["label"] is None
    assert {REVIEW_DUE_TYPE, REVIEW_OVERDUE_TYPE, TREATMENT_REASSESSMENT_TYPE} <= set(get_all_notification_types())

    off = client.put(f"/api/v1/notifications/preferences/{REVIEW_OVERDUE_TYPE}", json={"ui_enabled": False, "email_enabled": False},
                     headers=auth_headers(token))
    assert off.status_code == 200 and off.json()["label"] == "Risk review overdue" and off.json()["ui_enabled"] is False
    unknown = client.put("/api/v1/notifications/preferences/not_a_type", json={"ui_enabled": True, "email_enabled": True},
                         headers=auth_headers(token))
    assert unknown.status_code == 404


def test_an_opted_out_module_notification_is_hidden_in_the_list(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Rev Optout Co")
    owner_id, owner_token = _owner(client, token, org, project)
    create_risk(client, token, project["id"], owner_id=owner_id, review_date=_tomorrow_plus(-1))
    assert client.put(f"/api/v1/notifications/preferences/{REVIEW_OVERDUE_TYPE}", json={"ui_enabled": False, "email_enabled": True},
                      headers=auth_headers(owner_token)).status_code == 200

    _sweep()

    assert _notifications(client, owner_token, REVIEW_OVERDUE_TYPE) == []


def test_the_module_declares_its_mcp_tools():
    names = {tool.name for tool in build_mcp_tool_manifest() if tool.name.startswith("risk_management_")}
    assert {
        "risk_management_list_risks", "risk_management_get_risk", "risk_management_list_risk_treatments",
        "risk_management_list_risk_reviews", "risk_management_get_risk_scoring_scheme", "risk_management_create_risk",
        "risk_management_update_risk", "risk_management_transition_risk", "risk_management_assess_risk_treatment",
        "risk_management_record_risk_review", "risk_management_add_risk_comment",
    } <= names


def test_the_scoring_scheme_endpoint_mirrors_the_levels(client, admin_token):
    _org, project, token = setup(client, admin_token, "Risk Rev Scheme Co")
    mirrored = client.get(project_base(project["id"]) + "/scoring-scheme", headers=auth_headers(token))
    core = client.get(f"/api/v1/projects/{project['id']}/scoring-schemes/risk", headers=auth_headers(token))
    assert mirrored.status_code == 200 and mirrored.json() == core.json()
